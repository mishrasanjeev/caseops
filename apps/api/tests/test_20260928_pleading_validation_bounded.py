"""Bounded IP pleading validation (2026-09-28).

``GET .../drafts/{id}/validate`` took a near-constant 4.6 s in production. Each
revision's citations are rechecked against the public authority corpus (more
than 800K documents) with ``id IN ... OR neutral_citation IN ... OR
case_reference IN ...``. ``neutral_citation`` had no equality index, so that OR
read the whole corpus on every validate, approve, finalize and file, and on each
generation and edit through the citation verifier.

These journeys validate a real grounded pleading twice. The second revision
cites thirty authorities, including two the corpus no longer holds. The request
must keep one constant statement set, still block approval on exactly the lost
citations, and look those citations up through indexes.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, insert, select, text
from sqlalchemy.engine import Engine

from caseops_api.db.models import AuthorityDocument, DraftVersion
from caseops_api.db.session import get_engine, get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_ip_opposition_opponent_workflow import _fixture
from tests.test_ip_pleading_drafting import _base, _generate_grounded_notice

LOST_CITATIONS = ("1999 LOST INSC 1", "LOST/APPEAL/1999")
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260928_0001_authority_neutral_citation_index.py"
)
GOVERNANCE_MAP_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "ip_data_governance_map.py"
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_unrelated_authorities(rows: int, *, run: str) -> list[AuthorityDocument]:
    """Insert unrelated corpus rows; return a sample the revision will cite."""

    now = datetime.now(UTC)
    payload = [
        {
            "id": str(uuid4()),
            "source": "seed-tests",
            "adapter_name": "validation-bound",
            "court_name": "Delhi High Court",
            "forum_level": "high_court",
            "document_type": "judgment",
            "title": f"Validation bound authority {run} {index}",
            "case_reference": f"CS(COMM) {index}/{run}",
            "neutral_citation": None if index % 4 == 0 else f"{run} DHC {index}",
            "canonical_key": f"validation-bound::{run}::{index}",
            "summary": f"Unrelated retained authority {index} for bounded validation.",
            "extracted_char_count": 60,
            "ingested_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for index in range(rows)
    ]
    with get_session_factory()() as session:
        for start in range(0, len(payload), 1_000):
            session.execute(insert(AuthorityDocument.__table__), payload[start : start + 1_000])
        session.commit()
        return list(
            session.scalars(
                select(AuthorityDocument)
                .where(AuthorityDocument.canonical_key.like(f"validation-bound::{run}::%"))
                .order_by(AuthorityDocument.canonical_key)
                .limit(40)
            )
        )


def captured_validate(
    client: TestClient, url: str, headers: dict[str, str]
) -> tuple[dict, list[tuple[str, object]]]:
    statements: list[tuple[str, object]] = []

    def capture(_conn, _cursor, statement, parameters, _context, _many) -> None:
        statements.append((statement, parameters))

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(url, headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    return response.json(), statements


def citation_lookup(statements: list[tuple[str, object]]) -> tuple[str, object]:
    matches = [
        (statement, parameters)
        for statement, parameters in statements
        if "FROM authority_documents" in statement and "neutral_citation IN" in statement
    ]
    assert len(matches) == 1, [statement for statement, _ in statements]
    return matches[0]


def assert_sqlite_lookup_uses_indexes(engine: Engine, statement: str, parameters) -> None:
    with engine.connect() as connection:
        plan = connection.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement}", parameters).fetchall()
    details = [str(row[-1]) for row in plan]
    assert not any(detail.startswith("SCAN authority_documents") for detail in details), details
    assert any("ix_authority_documents_neutral_citation" in detail for detail in details), details


def validate_twice(
    client: TestClient,
    *,
    corpus_rows: int,
    plan_check: Callable[[Engine, str, object], None] | None,
) -> dict:
    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    generated = _generate_grounded_notice(
        client, bootstrap=bootstrap, docket=docket, proceeding=proceeding
    )
    draft_id = generated["id"]
    version_id = generated["versions"][0]["id"]
    run = uuid4().hex[:8]
    cited = seed_unrelated_authorities(corpus_rows, run=run)
    url = f"{_base(docket, proceeding)}/drafts/{draft_id}/validate"

    grounded, grounded_statements = captured_validate(client, url, headers)
    grounded_codes = {row["code"] for row in grounded["findings"]}
    assert "citation.source_lost" not in grounded_codes
    assert "citation.none_verified" not in grounded_codes

    with get_session_factory()() as session:
        version = session.get(DraftVersion, version_id)
        assert version is not None
        original = json.loads(version.citations_json or "[]")
        assert original, "The grounded notice must cite its verified authority."
        widened = [
            *original,
            *[row.neutral_citation for row in cited if row.neutral_citation][:20],
            *[row.case_reference for row in cited[20:26]],
            *[row.id for row in cited[26:28]],
            *LOST_CITATIONS,
        ]
        assert len(widened) == len(original) + 30
        version.citations_json = json.dumps(widened)
        session.commit()

    widened_report, widened_statements = captured_validate(client, url, headers)
    lost = [row for row in widened_report["findings"] if row["code"] == "citation.source_lost"]
    assert len(lost) == 1 and lost[0]["severity"] == "blocker", widened_report["findings"]
    assert sorted(lost[0]["references"]) == sorted(LOST_CITATIONS)
    assert widened_report["can_approve"] is False
    assert len(widened_statements) == len(grounded_statements), (
        f"{len(grounded_statements)} statements for one citation but "
        f"{len(widened_statements)} for thirty-one"
    )
    statement, parameters = citation_lookup(widened_statements)
    if plan_check is not None:
        plan_check(get_engine(), statement, parameters)
    return {
        "statements": len(widened_statements),
        "lookup": (statement, parameters),
    }


def test_pleading_validation_is_one_bounded_index_driven_statement_set(
    client: TestClient,
) -> None:
    validate_twice(client, corpus_rows=400, plan_check=assert_sqlite_lookup_uses_indexes)


def test_citation_index_migration_is_concurrent_and_recovers_invalid_build() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'down_revision = "20260925_0001"' in source
    upgrade_source, downgrade_source = source.split("def downgrade()", 1)
    assert "autocommit_block" in upgrade_source
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in upgrade_source
    assert "ON authority_documents (neutral_citation)" in upgrade_source
    assert "indisvalid" in upgrade_source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in upgrade_source
    # IF NOT EXISTS keeps a same-named index of any shape, so the upgrade
    # checks the shape of whatever index it ends with.
    upgrade_body = upgrade_source.split("def upgrade()", 1)[1]
    assert upgrade_body.index("_require_expected_shape(bind)") > upgrade_body.index(
        "op.execute(_INDEX_DDL)"
    )
    assert "DROP INDEX IF EXISTS" in downgrade_source
    assert "autocommit_block" not in downgrade_source
    assert "CONCURRENTLY" not in downgrade_source
    # The ORM declaration names the same index, so create_all and Alembic agree.
    declared = {index.name for index in AuthorityDocument.__table__.indexes}
    assert "ix_authority_documents_neutral_citation" in declared


def test_citation_index_is_in_the_governance_migration_inventory() -> None:
    migration = _load_module(MIGRATION_PATH, "authority_neutral_citation_index")
    # The DDL spells the name out so the governance scanner can read it.
    assert migration._INDEX_DDL.startswith(
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {migration._INDEX_NAME} "
    )
    assert migration._SQLITE_INDEX_DDL.startswith(
        f"CREATE INDEX IF NOT EXISTS {migration._INDEX_NAME} "
    )
    governance = _load_module(GOVERNANCE_MAP_SCRIPT, "ip_data_governance_map")
    assert migration._INDEX_NAME in governance._migration_index_names()


def test_neutral_citation_index_exists_on_the_migrated_sqlite_schema(
    client: TestClient,
) -> None:
    del client
    with get_engine().connect() as connection:
        indexes = {
            row[1]: row
            for row in connection.execute(text("PRAGMA index_list('authority_documents')"))
        }
        assert "ix_authority_documents_neutral_citation" in indexes
        columns = [
            row[2]
            for row in connection.execute(
                text("PRAGMA index_info('ix_authority_documents_neutral_citation')")
            )
        ]
    assert columns == ["neutral_citation"]
