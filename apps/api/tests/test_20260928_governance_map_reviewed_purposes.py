"""Reviewed table purposes survive data-governance map regeneration (2026-09-28).

`generate` rewrote every SQL table row with the generic purpose, so the reviewed
purpose of `matter_bulk_update_operations` (revision 20260925_0001) was lost
when the map was regenerated for revision 20260928_0001, and `validate` could
not tell. Reviewed purposes now live in `table_purpose_overrides`, like every
other policy decision in the map; rows are generated output.
"""

from __future__ import annotations

import copy
import importlib.util
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "ip_data_governance_map", REPO_ROOT / "scripts" / "ip_data_governance_map.py"
)
assert SPEC is not None and SPEC.loader is not None
governance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(governance)

BULK = "matter_bulk_update_operations"
SEEDED = "assistant_sessions"
SEEDED_PURPOSE = "Tenant-scoped assistant sessions, retained with their titles for review."
NEW_TABLE = "citation_probe_records"


def _rows(data: dict) -> dict[str, dict]:
    return {row["table_name"]: row for row in data["sql_tables"]}


@pytest.fixture
def map_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "DATA_GOVERNANCE_MAP.yaml"
    shutil.copyfile(governance.MAP_PATH, target)
    monkeypatch.setattr(governance, "MAP_PATH", target)
    return target


def _inventory(
    monkeypatch: pytest.MonkeyPatch, *, add_table: bool = False, drop: frozenset[str] = frozenset()
):
    schema = {
        name: columns
        for name, columns in governance.current_sql_schema().items()
        if name not in drop
    }
    orm_indexes = [
        index for index in governance.current_orm_indexes() if index["table_name"] not in drop
    ]
    migration_indexes = list(governance._migration_index_names())
    if add_table:
        schema[NEW_TABLE] = {
            "id": {"sql_type": "VARCHAR(36)", "nullable": False},
            "payload": {"sql_type": "TEXT", "nullable": True},
        }
        orm_indexes.append(
            {
                "table_name": NEW_TABLE,
                "index_name": f"ix_{NEW_TABLE}_payload",
                "columns": ["payload"],
                "unique": False,
            }
        )
        migration_indexes = sorted([*migration_indexes, f"ix_{NEW_TABLE}_payload"])
    monkeypatch.setattr(governance, "current_sql_schema", lambda: copy.deepcopy(schema))
    monkeypatch.setattr(governance, "current_orm_indexes", lambda: copy.deepcopy(orm_indexes))
    monkeypatch.setattr(governance, "_migration_index_names", lambda: list(migration_indexes))
    return schema, orm_indexes, migration_indexes


def test_committed_map_records_the_reviewed_bulk_update_purpose() -> None:
    data = governance._load(governance.MAP_PATH)
    reviewed = data["table_purpose_overrides"][BULK]
    assert reviewed.startswith("Tenant-scoped bulk-update operation history.")
    assert _rows(data)[BULK]["purpose"] == reviewed
    assert governance.validate(data) == []


def test_generate_keeps_reviewed_purposes_while_refreshing_the_inventory(
    map_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = governance._load(map_copy)
    reviewed = before["table_purpose_overrides"][BULK]
    before["table_purpose_overrides"][SEEDED] = SEEDED_PURPOSE
    governance._write(map_copy, before)
    schema, orm_indexes, migration_indexes = _inventory(monkeypatch, add_table=True)

    governance.generate()

    after = governance._load(map_copy)
    rows = _rows(after)
    assert rows[BULK]["purpose"] == reviewed
    assert rows[SEEDED]["purpose"] == SEEDED_PURPOSE
    assert rows[NEW_TABLE]["purpose"] == governance._generic_purpose(NEW_TABLE)
    assert after["table_purpose_overrides"] == {BULK: reviewed, SEEDED: SEEDED_PURPOSE}
    # The generated inventory still refreshed around the preserved purposes.
    assert after["schema_fingerprint"] == governance._fingerprint(
        governance._schema_fingerprint_payload(schema, orm_indexes, migration_indexes)
    )
    assert after["schema_fingerprint"] != before["schema_fingerprint"]
    inventory = after["index_inventory"]
    assert inventory["orm_index_count"] == before["index_inventory"]["orm_index_count"] + 1
    assert inventory["migration_index_count"] == (
        before["index_inventory"]["migration_index_count"] + 1
    )
    assert inventory["orm_index_fingerprint"] == governance._fingerprint(orm_indexes)
    assert inventory["migration_index_fingerprint"] == governance._fingerprint(migration_indexes)
    assert (
        governance.validate(
            after,
            sql_schema=schema,
            orm_indexes=orm_indexes,
            migration_indexes=migration_indexes,
            check_generated_view=False,
        )
        == []
    )


def test_generate_refuses_a_reviewed_purpose_written_only_into_a_row(
    map_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _inventory(monkeypatch)
    hand_edited = governance._load(map_copy)
    _rows(hand_edited)[SEEDED]["purpose"] = SEEDED_PURPOSE
    governance._write(map_copy, hand_edited)
    original = map_copy.read_bytes()

    with pytest.raises(ValueError, match=SEEDED):
        governance.generate()
    assert map_copy.read_bytes() == original
    errors = governance.validate(hand_edited, check_generated_view=False)
    assert any(f"sql-table/{SEEDED}: purpose must equal" in error for error in errors)

    # Dropping an override does not silently discard the reviewed text either.
    dropped = governance._load(map_copy)
    _rows(dropped)[SEEDED]["purpose"] = governance._generic_purpose(SEEDED)
    del dropped["table_purpose_overrides"][BULK]
    governance._write(map_copy, dropped)
    original = map_copy.read_bytes()
    with pytest.raises(ValueError, match=BULK):
        governance.generate()
    assert map_copy.read_bytes() == original


def test_a_removed_table_drops_its_row_and_its_stale_purpose_is_reported(
    map_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edited = governance._load(map_copy)
    # A removed table's row may hold any text: only tables that still exist are checked.
    _rows(edited)[SEEDED]["purpose"] = SEEDED_PURPOSE
    governance._write(map_copy, edited)
    schema, orm_indexes, migration_indexes = _inventory(monkeypatch, drop=frozenset({BULK, SEEDED}))

    governance.generate()

    after = governance._load(map_copy)
    assert BULK not in _rows(after) and SEEDED not in _rows(after)
    # The reviewed override is kept for a reviewer to remove, not deleted silently.
    assert BULK in after["table_purpose_overrides"]
    errors = governance.validate(
        after,
        sql_schema=schema,
        orm_indexes=orm_indexes,
        migration_indexes=migration_indexes,
        check_generated_view=False,
    )
    assert f"table purpose override references unknown table {BULK}" in errors


@pytest.mark.parametrize(
    ("purpose", "message"),
    [
        ("", "must be explicit"),
        (None, "must be explicit"),
        (governance._generic_purpose(SEEDED), "repeats the generated text"),
    ],
)
def test_validate_rejects_blank_or_redundant_purpose_overrides(purpose, message) -> None:
    data = copy.deepcopy(governance._load(governance.MAP_PATH))
    data["table_purpose_overrides"][SEEDED] = purpose
    errors = governance.validate(data, check_generated_view=False)
    assert f"table purpose override for {SEEDED} {message}" in errors
