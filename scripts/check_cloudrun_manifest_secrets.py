#!/usr/bin/env python3
"""Reject literal credentials in Cloud Run container environment entries."""

from __future__ import annotations

import argparse
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
_YAML_SUFFIXES = {".yaml", ".yml"}


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


def _manifest_paths(targets: list[Path]) -> list[Path]:
    manifests: set[Path] = set()
    for target in targets:
        if target.is_dir():
            manifests.update(
                path
                for path in target.rglob("*")
                if path.is_file() and path.suffix.lower() in _YAML_SUFFIXES
            )
        elif target.is_file() and target.suffix.lower() in _YAML_SUFFIXES:
            manifests.add(target)
        else:
            raise ValueError(f"manifest target does not exist or is not YAML: {target}")
    return sorted(manifests)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="+", type=Path, help="YAML file or directory")
    args = parser.parse_args(argv)

    try:
        manifests = _manifest_paths(args.targets)
        if not manifests:
            raise ValueError("no YAML manifests found")
        violations = [
            violation
            for manifest in manifests
            for violation in scan_manifest(manifest)
        ]
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

    noun = "manifest" if len(manifests) == 1 else "manifests"
    print(f"Cloud Run manifest secret check passed: checked {len(manifests)} {noun}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
