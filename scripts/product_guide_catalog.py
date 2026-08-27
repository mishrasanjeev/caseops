#!/usr/bin/env python3
"""Compile and verify the single maintained CaseOps Product Guide catalog.

The API and web images are built from different Docker contexts, so neither can
read ``docs/`` in production. This gate compiles the reviewed catalog into both
contexts and rejects drift, invented routes or capabilities, duplicate IDs, and
an index that no longer matches the existing ``/guide`` section owner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "docs" / "ip-implementation" / "PRODUCT_GUIDE_CATALOG.json"
API_PROJECTION_PATH = (
    REPO_ROOT
    / "apps"
    / "api"
    / "src"
    / "caseops_api"
    / "product_guide"
    / "catalog.generated.json"
)
WEB_PROJECTION_PATH = REPO_ROOT / "apps" / "web" / "lib" / "product-guide.generated.json"
GUIDE_PAGE_PATH = REPO_ROOT / "apps" / "web" / "app" / "guide" / "page.tsx"
SIDEBAR_PATH = REPO_ROOT / "apps" / "web" / "components" / "app" / "Sidebar.tsx"
CAPABILITY_CATALOG_PATH = (
    REPO_ROOT
    / "apps"
    / "api"
    / "src"
    / "caseops_api"
    / "services"
    / "capability_catalog.py"
)
PLATFORM_CAPABILITY_PATH = (
    REPO_ROOT
    / "apps"
    / "api"
    / "src"
    / "caseops_api"
    / "services"
    / "platform_admin.py"
)

MAX_SECTIONS = 64
MAX_COMMANDS = 96
_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^20\d{2}\.\d{2}\.\d{2}\.\d+$")
_CAPABILITY_RE = re.compile(r'"([a-z][a-z0-9_]*:[a-z][a-z0-9_]*)"')


def _load(path: Path | None = None) -> dict[str, Any]:
    path = path or SOURCE_PATH
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("catalog root must be an object")
    return document


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def catalog_fingerprint(document: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(_canonical_bytes(document or _load())).hexdigest()


def _known_capabilities() -> set[str]:
    text = CAPABILITY_CATALOG_PATH.read_text(encoding="utf-8")
    text += "\n" + PLATFORM_CAPABILITY_PATH.read_text(encoding="utf-8")
    return set(_CAPABILITY_RE.findall(text))


def _route_file(href: str) -> Path:
    relative = href.strip("/")
    return REPO_ROOT / "apps" / "web" / "app" / relative / "page.tsx"


def _duplicates(values: list[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _validate_terms(value: object, *, field: str, owner: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{owner}.{field} must be a non-empty list")
        return
    if any(not isinstance(term, str) or not term.strip() for term in value):
        errors.append(f"{owner}.{field} contains a blank or non-string term")
    normalized = [str(term).strip().casefold() for term in value]
    duplicates = _duplicates(normalized)
    if duplicates:
        errors.append(f"{owner}.{field} contains duplicates: {duplicates}")


def validate_document(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    version = document.get("content_version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        errors.append("content_version must use YYYY.MM.DD.revision")
    if document.get("canonical_path") != "/guide":
        errors.append("canonical_path must remain /guide")
    if document.get("language") != "en-IN":
        errors.append("the approved foundation corpus language must remain en-IN")

    groups = document.get("navigation_groups")
    if not isinstance(groups, dict) or not groups:
        errors.append("navigation_groups must be a non-empty object")
        groups = {}

    sections = document.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections must be a non-empty list")
        sections = []
    if len(sections) > MAX_SECTIONS:
        errors.append(f"sections exceed the bounded maximum of {MAX_SECTIONS}")

    section_ids: list[str] = []
    for index, section in enumerate(sections):
        owner = f"sections[{index}]"
        if not isinstance(section, dict):
            errors.append(f"{owner} must be an object")
            continue
        section_id = section.get("id")
        if not isinstance(section_id, str) or not _ID_RE.fullmatch(section_id):
            errors.append(f"{owner}.id must be a stable kebab-case identifier")
        else:
            section_ids.append(section_id)
        for field in ("title", "summary"):
            if not isinstance(section.get(field), str) or not section[field].strip():
                errors.append(f"{owner}.{field} must be non-empty")
        _validate_terms(section.get("keywords"), field="keywords", owner=owner, errors=errors)
        _validate_terms(section.get("aliases"), field="aliases", owner=owner, errors=errors)
    duplicate_sections = _duplicates(section_ids)
    if duplicate_sections:
        errors.append(f"duplicate section IDs: {duplicate_sections}")

    commands = document.get("commands")
    if not isinstance(commands, list) or not commands:
        errors.append("commands must be a non-empty list")
        commands = []
    if len(commands) > MAX_COMMANDS:
        errors.append(f"commands exceed the bounded maximum of {MAX_COMMANDS}")

    known_capabilities = _known_capabilities()
    command_ids: list[str] = []
    command_hrefs: list[str] = []
    for index, command in enumerate(commands):
        owner = f"commands[{index}]"
        if not isinstance(command, dict):
            errors.append(f"{owner} must be an object")
            continue
        command_id = command.get("id")
        if not isinstance(command_id, str) or not _ID_RE.fullmatch(command_id):
            errors.append(f"{owner}.id must be a stable kebab-case identifier")
        else:
            command_ids.append(command_id)
        for field in ("label", "summary", "icon"):
            if not isinstance(command.get(field), str) or not command[field].strip():
                errors.append(f"{owner}.{field} must be non-empty")
        href = command.get("href")
        if not isinstance(href, str) or not href.startswith("/") or "?" in href or "#" in href:
            errors.append(f"{owner}.href must be a stable internal page route")
        else:
            command_hrefs.append(href)
            if not _route_file(href).is_file():
                errors.append(f"{owner}.href has no page owner: {href}")
        group = command.get("group")
        if not isinstance(group, str) or group not in groups:
            errors.append(f"{owner}.group is not declared in navigation_groups")
        _validate_terms(command.get("keywords"), field="keywords", owner=owner, errors=errors)
        required = command.get("required_capabilities")
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            errors.append(f"{owner}.required_capabilities must be a string list")
        else:
            unknown = sorted(set(required) - known_capabilities)
            if unknown:
                errors.append(f"{owner} names unknown capabilities: {unknown}")

    duplicate_commands = _duplicates(command_ids)
    if duplicate_commands:
        errors.append(f"duplicate command IDs: {duplicate_commands}")
    duplicate_hrefs = _duplicates(command_hrefs)
    if duplicate_hrefs:
        errors.append(f"duplicate command hrefs: {duplicate_hrefs}")

    guide_source = GUIDE_PAGE_PATH.read_text(encoding="utf-8")
    rendered = re.findall(r'<Section\s+id="([a-z0-9-]+)"', guide_source)
    if rendered != section_ids:
        errors.append("catalog section order does not exactly match /guide rendered sections")
    if "const sections:" in guide_source:
        errors.append("/guide reintroduced a second manually maintained section index")

    sidebar_source = SIDEBAR_PATH.read_text(encoding="utf-8")
    if "const NAV:" in sidebar_source:
        errors.append("Sidebar reintroduced a second manually maintained command catalog")
    for icon in sorted({str(command.get("icon", "")) for command in commands}):
        if icon and f"{icon}," not in sidebar_source:
            errors.append(f"Sidebar has no icon mapping for catalog icon {icon}")
    return errors


def validate() -> list[str]:
    try:
        document = _load()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load Product Guide catalog: {exc}"]
    errors = validate_document(document)
    expected = _canonical_bytes(document)
    for path in (API_PROJECTION_PATH, WEB_PROJECTION_PATH):
        if not path.is_file():
            errors.append(f"missing generated projection: {_display_path(path)}")
        elif path.read_bytes().replace(b"\r\n", b"\n") != expected:
            errors.append(
                f"stale or hand-edited projection: {_display_path(path)}; "
                "run `python scripts/product_guide_catalog.py render`"
            )
    return errors


def render() -> None:
    document = _load()
    errors = validate_document(document)
    if errors:
        raise SystemExit("\n".join(f"ERROR: {error}" for error in errors))
    payload = _canonical_bytes(document)
    for path in (API_PROJECTION_PATH, WEB_PROJECTION_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        print(f"rendered {path.relative_to(REPO_ROOT)}")
    print(f"catalog fingerprint: {hashlib.sha256(payload).hexdigest()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("render", "validate"))
    args = parser.parse_args()
    if args.command == "render":
        render()
        return 0
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    document = _load()
    print(
        "Product Guide catalog valid: "
        f"{len(document['sections'])} sections, {len(document['commands'])} commands, "
        f"fingerprint {catalog_fingerprint(document)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
