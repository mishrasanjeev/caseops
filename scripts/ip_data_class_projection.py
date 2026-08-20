#!/usr/bin/env python3
"""Render and verify the runtime data-class projection (IPLF-028A).

The dry-run service used to carry a hard-coded six-name frozenset. It was a
duplicate of ``IPLF_028A_DATA_GOVERNANCE_REGISTRY.yaml``, free to drift from it,
and it could not tell an unreviewed table from a nonexistent one.

The obvious fix - read the YAML at runtime - does not work, and the reason is
decisive: ``apps/api/Dockerfile`` copies ``pyproject.toml``, ``README.md``,
``alembic.ini``, ``src`` and ``alembic``. It does not copy ``docs/``. A runtime
that reads the reviewed registry from ``docs/`` reads nothing in production.

So the reviewed artifacts are compiled into a generated Python module under
``src/``, which ships. This script is the compiler, and - more importantly - the
gate that proves the shipped module still equals what the artifacts say. Byte
equality, both directions of set equality, per-field equality, and a live ORM
fingerprint. Regenerating is the only way to change the runtime's admitted set.

    render     rewrite the generated module from the reviewed artifacts
    validate   fail if the committed module is not exactly what render produces

`validate` is the CI gate. It is the whole control: without it the generated
module is just another copy that can drift, which is the defect being fixed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
CONTROL_ROOT = REPO_ROOT / "docs" / "ip-implementation"

MAP_PATH = CONTROL_ROOT / "DATA_GOVERNANCE_MAP.yaml"
REGISTRY_028A_PATH = CONTROL_ROOT / "IPLF_028A_DATA_GOVERNANCE_REGISTRY.yaml"
REGISTRY_027A_PATH = CONTROL_ROOT / "IPLF_027A_DATA_CLASS_REGISTRY.yaml"
GENERATED_PATH = (
    API_SRC / "caseops_api" / "governance" / "generated_data_class_projection.py"
)
HANDLER_PATH = API_SRC / "caseops_api" / "services" / "data_governance.py"

PROJECTION_SCHEMA_VERSION = 1

# The constant this projection replaces. If it ever reappears, the runtime has a
# second source of admitted classes and the gate below is decorative.
RETIRED_CONSTANT = "FOUNDATION_DATA_CLASS_IDS"

_CARRIED_FIELDS = (
    "company_scope",
    "company_key",
    "storage",
    "confidentiality",
    "legal_hold_disposition",
)


def _sha256_document(path: Path) -> str:
    """Fingerprint an artifact's CONTENT, not its bytes.

    Hashing raw bytes makes the fingerprint depend on line endings, and git
    rewrites these YAML files to CRLF on a Windows checkout. That produced a
    gate which passed in CI and failed locally on the identical commit - so the
    fingerprint identified content plus platform, and no developer could
    reproduce CI. Caught when a rebase re-checked-out the registry.

    Parsing and re-serialising canonically also means a whitespace or key-order
    change does not invalidate the projection, while any change to a value
    does. That is the property actually wanted: this fingerprint answers "was
    the projection rendered from these reviewed decisions?".
    """

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _orm_schema_fingerprint() -> str:
    if str(API_SRC) not in sys.path:
        sys.path.insert(0, str(API_SRC))
    from caseops_api.governance.schema_fingerprint import orm_schema_fingerprint

    return orm_schema_fingerprint()


def _reviewed_rows(document: dict[str, Any], slice_id: str) -> list[dict[str, Any]]:
    rows = []
    for row in document.get("data_classes", []):
        entry = {"id": str(row["id"]), "table_name": str(row["table_name"])}
        entry["source_slice"] = slice_id
        for field in _CARRIED_FIELDS:
            value = row.get(field)
            entry[field] = None if value is None else str(value)
        rows.append(entry)
    return sorted(rows, key=lambda item: item["id"])


def _collect() -> dict[str, Any]:
    map_document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    registry_028a = _load_yaml(REGISTRY_028A_PATH)
    registry_027a = _load_yaml(REGISTRY_027A_PATH)

    sql_tables = sorted(str(entry["table_name"]) for entry in map_document["sql_tables"])
    non_sql = sorted(str(entry["id"]) for entry in map_document["non_sql_data_classes"])

    admitted = _reviewed_rows(registry_028a, "IPLF-028A")
    elsewhere = _reviewed_rows(registry_027a, "IPLF-027A")

    fingerprints = {
        "MAP_DOCUMENT_FINGERPRINT": _sha256_document(MAP_PATH),
        "MAP_SCHEMA_FINGERPRINT": str(map_document["schema_fingerprint"]),
        "REGISTRY_028A_FINGERPRINT": _sha256_document(REGISTRY_028A_PATH),
        "REGISTRY_027A_FINGERPRINT": _sha256_document(REGISTRY_027A_PATH),
        "ORM_SCHEMA_FINGERPRINT": _orm_schema_fingerprint(),
    }
    projection_id = hashlib.sha256(
        json.dumps(
            {**fingerprints, "schema_version": PROJECTION_SCHEMA_VERSION},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "sql_tables": sql_tables,
        "non_sql": non_sql,
        "admitted": admitted,
        "elsewhere": elsewhere,
        "fingerprints": fingerprints,
        "projection_id": projection_id,
    }


def _render_field(field: str, value: str | None) -> list[str]:
    """One keyword argument, wrapped if the reviewed value is prose.

    Some registry dispositions are full sentences. Rendering them on one line
    puts the generated module over the line limit, and both alternatives -
    per-line noqa, or excluding this file from lint - amount to letting the
    generator emit code the project would reject if a human wrote it.
    """

    if value is None:
        return [f"        {field}=None,"]
    single = f'        {field}="{value}",'
    if len(single) <= 96:
        return [single]

    lines = [f"        {field}=("]
    current = ""
    for word in value.split(" "):
        candidate = f"{current} {word}" if current else word
        if len(candidate) > 74 and current:
            lines.append(f'            "{current} "')
            current = word
        else:
            current = candidate
    if current:
        lines.append(f'            "{current}"')
    lines.append("        ),")
    return lines


def _render_rows(rows: list[dict[str, Any]]) -> str:
    lines = []
    for row in rows:
        lines.append(f'    "{row["id"]}": ReviewedDataClass(')
        lines.append(f'        id="{row["id"]}",')
        lines.append(f'        table_name="{row["table_name"]}",')
        lines.append(f'        source_slice="{row["source_slice"]}",')
        for field in _CARRIED_FIELDS:
            lines.extend(_render_field(field, row[field]))
        lines.append("    ),")
    return "\n".join(lines)


def _render_names(names: list[str]) -> str:
    return "\n".join(f'        "{name}",' for name in names)


def render_module() -> str:
    data = _collect()
    fp = data["fingerprints"]
    return f'''"""Compiled runtime projection of the reviewed data-class registries.

GENERATED FILE - DO NOT EDIT.

Regenerate with, in this order:

    python scripts/ip_data_governance_map.py generate
    python scripts/ip_data_class_projection.py render
    python scripts/ip_data_governance_map.py render

``scripts/ip_data_class_projection.py validate`` runs in CI and fails if this
file is not byte-identical to what ``render`` produces from the reviewed
artifacts, so hand-edits do not survive review.

This module exists because ``apps/api/Dockerfile`` ships ``src`` and not
``docs``: the reviewed YAML is unreadable in production, so it is compiled into
the package that does ship.
"""

from __future__ import annotations

from caseops_api.governance.types import ReviewedDataClass

PROJECTION_SCHEMA_VERSION = {PROJECTION_SCHEMA_VERSION}

# Fingerprints of the exact artifacts this projection was rendered from.
MAP_DOCUMENT_FINGERPRINT = "{fp["MAP_DOCUMENT_FINGERPRINT"]}"
MAP_SCHEMA_FINGERPRINT = "{fp["MAP_SCHEMA_FINGERPRINT"]}"
REGISTRY_028A_FINGERPRINT = "{fp["REGISTRY_028A_FINGERPRINT"]}"
REGISTRY_027A_FINGERPRINT = "{fp["REGISTRY_027A_FINGERPRINT"]}"
# The ORM schema at render time. Compared against the live models at runtime, so
# an image whose models moved after this file was rendered reports stale rather
# than answering from a projection that no longer describes it.
ORM_SCHEMA_FINGERPRINT = "{fp["ORM_SCHEMA_FINGERPRINT"]}"

PROJECTION_ID = "{data["projection_id"]}"

# Every SQL table the repository-wide map inventories. Membership here is what
# separates "inventoried but never reviewed" from "no such data class", which
# are different answers with different remedies.
INVENTORIED_SQL_TABLES = frozenset(
    {{
{_render_names(data["sql_tables"])}
    }}
)

# Object stores, indexes, caches, queues, logs, provider-held records. Kept in a
# SEPARATE set and never merged: they have no table, so a dependency plan cannot
# be computed for them, and folding them in would let one be requested as though
# it could be purged relationally.
INVENTORIED_NON_SQL_CLASSES = frozenset(
    {{
{_render_names(data["non_sql"])}
    }}
)

# Reviewed by IPLF-028A and admissible in a dry run.
ADMITTED_DATA_CLASSES: dict[str, ReviewedDataClass] = {{
{_render_rows(data["admitted"])}
}}

# Reviewed by IPLF-027A, which governs its own tables. Present so a caller
# naming one is told it is governed elsewhere rather than "never reviewed".
REVIEWED_ELSEWHERE_DATA_CLASSES: dict[str, ReviewedDataClass] = {{
{_render_rows(data["elsewhere"])}
}}
'''


def _display_path(path: Path) -> str:
    """Repo-relative where possible; absolute otherwise.

    ``relative_to`` raises on a path outside the repository, and a validator
    that crashes while formatting its own error message reports nothing.
    """

    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def validate() -> list[str]:
    errors: list[str] = []

    if not GENERATED_PATH.exists():
        return [f"missing generated projection {_display_path(GENERATED_PATH)}"]

    if GENERATED_PATH.read_text(encoding="utf-8") != render_module():
        errors.append(
            "generated data-class projection is stale or hand-edited; run "
            "`python scripts/ip_data_class_projection.py render`"
        )

    # Deliberately NOT an early return. Byte equality subsumes the checks below
    # whenever it passes - the file was rendered from the same _collect() - so
    # returning here would make every specific assertion unreachable and leave
    # "stale or hand-edited" as the only diagnosis the gate can ever give.
    #
    # They are also not redundant: byte equality compares the committed FILE
    # against freshly rendered text, while everything below compares the
    # IMPORTED module - what the runtime will actually load - against the
    # reviewed artifacts. Those can disagree, and the second is what matters.
    data = _collect()

    # Import the shipped module and compare against the artifacts through the
    # runtime path a request would take. A source-text check would pass on a
    # module that cannot be imported.
    if str(API_SRC) not in sys.path:
        sys.path.insert(0, str(API_SRC))
    from caseops_api.governance import generated_data_class_projection as projection

    admitted_expected = {row["id"] for row in data["admitted"]}
    admitted_actual = set(projection.ADMITTED_DATA_CLASSES)
    if admitted_actual != admitted_expected:
        errors.append(
            "admitted set disagrees with IPLF_028A registry: "
            f"only-in-runtime={sorted(admitted_actual - admitted_expected)} "
            f"only-in-registry={sorted(admitted_expected - admitted_actual)}"
        )

    elsewhere_expected = {row["id"] for row in data["elsewhere"]}
    if set(projection.REVIEWED_ELSEWHERE_DATA_CLASSES) != elsewhere_expected:
        errors.append("reviewed-elsewhere set disagrees with the IPLF_027A registry")

    for row in data["admitted"] + data["elsewhere"]:
        source = (
            projection.ADMITTED_DATA_CLASSES
            if row["source_slice"] == "IPLF-028A"
            else projection.REVIEWED_ELSEWHERE_DATA_CLASSES
        )
        entry = source.get(row["id"])
        if entry is None:
            continue
        for field in _CARRIED_FIELDS:
            if getattr(entry, field) != row[field]:
                errors.append(
                    f"{row['id']}.{field} is {getattr(entry, field)!r} in the runtime "
                    f"projection and {row[field]!r} in the reviewed registry"
                )

    if set(projection.INVENTORIED_SQL_TABLES) != set(data["sql_tables"]):
        errors.append("inventoried SQL table set disagrees with the data-governance map")
    if set(projection.INVENTORIED_NON_SQL_CLASSES) != set(data["non_sql"]):
        errors.append("inventoried non-SQL class set disagrees with the map")
    overlap = projection.INVENTORIED_SQL_TABLES & projection.INVENTORIED_NON_SQL_CLASSES
    if overlap:
        errors.append(f"SQL and non-SQL inventories overlap: {sorted(overlap)}")

    live_fingerprint = _orm_schema_fingerprint()
    if projection.ORM_SCHEMA_FINGERPRINT != live_fingerprint:
        errors.append(
            "projection was rendered from a different ORM schema than this tree "
            "carries; a migration landed without regenerating the projection"
        )

    missing_from_inventory = sorted(
        set(projection.ADMITTED_DATA_CLASSES) - set(projection.INVENTORIED_SQL_TABLES)
    )
    if missing_from_inventory:
        errors.append(
            f"admitted classes absent from the map inventory: {missing_from_inventory}"
        )

    handler_source = HANDLER_PATH.read_text(encoding="utf-8")
    if RETIRED_CONSTANT in handler_source:
        errors.append(
            f"{RETIRED_CONSTANT} has reappeared in {HANDLER_PATH.name}; the runtime "
            "would have a second, ungated source of admitted data classes"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("render")
    subparsers.add_parser("validate")
    args = parser.parse_args(argv)

    if args.command == "render":
        GENERATED_PATH.parent.mkdir(parents=True, exist_ok=True)
        GENERATED_PATH.write_text(render_module(), encoding="utf-8", newline="\n")
        print(f"rendered {GENERATED_PATH.relative_to(REPO_ROOT)}")
        return 0

    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("data-class projection valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
