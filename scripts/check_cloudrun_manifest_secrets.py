#!/usr/bin/env python3
"""Reject literal credentials in checked-in Cloud Run definitions.

YAML manifests are checked entry by entry: a secret-like container environment
name must use ``valueFrom.secretKeyRef`` or an exact deployment placeholder.
``infra/cloudrun/scheduler-inventory.json`` is the applied definition of every
recurring job, and ``scripts/scheduler_inventory.py`` passes its bootstrap
``environment`` to ``--set-env-vars`` verbatim, so a secret-like name there is
always a literal and every ``secrets`` entry must be a Secret Manager
``<secret>:<version>`` reference.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_LINE_KEY = "__caseops_yaml_line__"
_SECRET_ENV_NAME = re.compile(
    r"(?:^|_)(?:SECRET|KEY|TOKEN|PASSWORD|DATABASE_URL|CREDENTIAL|CREDENTIALS)$",
    re.IGNORECASE,
)
_EXPLICIT_PLACEHOLDER = re.compile(
    r"(?:__[A-Z][A-Z0-9_]*__|\$\{[A-Z][A-Z0-9_]*\})"
)
_SECRET_MANAGER_REFERENCE = re.compile(r"[A-Za-z0-9_-]{1,255}:(?:latest|[1-9][0-9]*)")
_YAML_SUFFIXES = {".yaml", ".yml"}
_INVENTORY_SUFFIXES = {".json"}
_DEFINITION_SUFFIXES = _YAML_SUFFIXES | _INVENTORY_SUFFIXES


class _MarkedSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that retains the source line of every mapping."""


def _construct_marked_mapping(
    loader: _MarkedSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=deep)
    mapping[_LINE_KEY] = node.start_mark.line + 1
    return mapping


_MarkedSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_marked_mapping,
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: error: {self.message}"


def _definition_paths(targets: list[Path]) -> list[Path]:
    definitions: set[Path] = set()
    for target in targets:
        if target.is_dir():
            definitions.update(
                path
                for path in target.rglob("*")
                if path.is_file() and path.suffix.lower() in _DEFINITION_SUFFIXES
            )
        elif target.is_file() and target.suffix.lower() in _DEFINITION_SUFFIXES:
            definitions.add(target)
        else:
            raise ValueError(
                f"definition target does not exist or is not YAML or JSON: {target}"
            )
    return sorted(definitions)


def _env_entries(node: Any) -> Iterator[dict[Any, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == _LINE_KEY:
                continue
            if key == "env" and isinstance(value, list):
                yield from (entry for entry in value if isinstance(entry, dict))
            yield from _env_entries(value)
    elif isinstance(node, list):
        for value in node:
            yield from _env_entries(value)


def _is_explicit_placeholder(value: Any) -> bool:
    return isinstance(value, str) and _EXPLICIT_PLACEHOLDER.fullmatch(value) is not None


def _valid_secret_key_ref(value_from: Any) -> bool:
    if not isinstance(value_from, dict):
        return False
    secret_key_ref = value_from.get("secretKeyRef")
    if not isinstance(secret_key_ref, dict):
        return False
    return all(
        isinstance(secret_key_ref.get(field), str) and bool(secret_key_ref[field].strip())
        for field in ("name", "key")
    )


def _entry_violations(path: Path, entry: dict[Any, Any]) -> list[Violation]:
    env_name = entry.get("name")
    if not isinstance(env_name, str) or _SECRET_ENV_NAME.search(env_name) is None:
        return []

    line = int(entry.get(_LINE_KEY, 1))
    if "value" in entry and "valueFrom" in entry:
        return [
            Violation(
                path,
                line,
                f"{env_name} defines both value and valueFrom",
            )
        ]
    if "value" in entry:
        if _is_explicit_placeholder(entry["value"]):
            return []
        return [
            Violation(
                path,
                line,
                (
                    f"{env_name} uses a literal value; use valueFrom.secretKeyRef "
                    "or an exact ${NAME}/__NAME__ deployment placeholder"
                ),
            )
        ]
    if not _valid_secret_key_ref(entry.get("valueFrom")):
        return [
            Violation(
                path,
                line,
                f"{env_name} must use valueFrom.secretKeyRef with non-empty name and key",
            )
        ]
    return []


def scan_manifest(path: Path) -> list[Violation]:
    with path.open(encoding="utf-8") as manifest:
        documents = list(yaml.load_all(manifest, Loader=_MarkedSafeLoader))
    return [
        violation
        for document in documents
        for entry in _env_entries(document)
        for violation in _entry_violations(path, entry)
    ]


def _job_line(lines: list[str], run_job_name: str) -> int:
    marker = f'"run_job_name": {json.dumps(run_job_name)}'
    return next(
        (number for number, line in enumerate(lines, start=1) if marker in line),
        1,
    )


def scan_inventory(path: Path) -> tuple[list[Violation], int]:
    """Check every bootstrap contract; return violations and the job count.

    Values are never echoed: a violation names the job and the variable only.
    """

    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list) or not jobs:
        raise ValueError(f"{path} is not a scheduler inventory with a non-empty jobs list")
    lines = text.splitlines()
    violations: list[Violation] = []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            violations.append(Violation(path, 1, f"jobs[{index}] is not an object"))
            continue
        label = str(job.get("run_job_name") or f"jobs[{index}]")
        line = _job_line(lines, label)
        bootstrap = job.get("bootstrap")
        environment = bootstrap.get("environment") if isinstance(bootstrap, dict) else None
        secrets = bootstrap.get("secrets") if isinstance(bootstrap, dict) else None
        if not isinstance(environment, dict) or not isinstance(secrets, dict):
            violations.append(
                Violation(
                    path,
                    line,
                    f"{label} has no bootstrap environment and secrets maps to check",
                )
            )
            continue
        for name in environment:
            if not isinstance(name, str):
                continue
            if name in secrets:
                violations.append(
                    Violation(
                        path,
                        line,
                        f"{label}: {name} is both a bootstrap environment value and a secret",
                    )
                )
            elif _SECRET_ENV_NAME.search(name):
                violations.append(
                    Violation(
                        path,
                        line,
                        (
                            f"{label}: {name} is a literal bootstrap environment value; "
                            "declare it in bootstrap.secrets as <secret>:<version>"
                        ),
                    )
                )
        for name, reference in secrets.items():
            if not (
                isinstance(reference, str)
                and _SECRET_MANAGER_REFERENCE.fullmatch(reference)
            ):
                violations.append(
                    Violation(
                        path,
                        line,
                        (
                            f"{label}: bootstrap.secrets.{name} must be a Secret "
                            "Manager <secret>:<version> reference"
                        ),
                    )
                )
    return violations, len(jobs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets", nargs="+", type=Path, help="YAML or JSON file, or directory"
    )
    args = parser.parse_args(argv)

    try:
        definitions = _definition_paths(args.targets)
        if not definitions:
            raise ValueError("no Cloud Run definitions found")
        violations: list[Violation] = []
        inventory_jobs = 0
        for definition in definitions:
            if definition.suffix.lower() in _INVENTORY_SUFFIXES:
                found, jobs = scan_inventory(definition)
                violations.extend(found)
                inventory_jobs += jobs
            else:
                violations.extend(scan_manifest(definition))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Cloud Run manifest secret check failed: {exc}", file=sys.stderr)
        return 2

    if violations:
        for violation in violations:
            print(violation.render())
        print(
            f"Cloud Run manifest secret check failed: {len(violations)} violation(s)."
        )
        return 1

    noun = "manifest" if len(definitions) == 1 else "manifests"
    detail = (
        f", including {inventory_jobs} scheduler-inventory job contracts"
        if inventory_jobs
        else ""
    )
    print(
        f"Cloud Run manifest secret check passed: checked {len(definitions)} {noun}{detail}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
