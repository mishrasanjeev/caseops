"""IPLF-027B A1 ownership migration: backfill from evidence, never guess.

Each case starts from a fresh database migrated to the revision's parent, writes
legacy rows in the pre-A1 shape (no ``ip_rule_sets.company_id``), then upgrades.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from tests.fixtures_postgres_client import temporary_http_database
from tests.test_postgres_validation import _seed_company, _seed_membership

REVISION = "20261031_0001"


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def fresh_engine(request, tmp_path):
    if request.param == "postgres":
        source = request.getfixturevalue("pg_engine")
        with temporary_http_database(source.url) as engine:
            yield engine
    else:
        engine = create_engine(
            "sqlite+pysqlite:///" + (tmp_path / "rule-set-ownership.db").as_posix()
        )
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def at_parent(fresh_engine, monkeypatch):
    engine = fresh_engine
    url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    monkeypatch.setenv("CASEOPS_ENV", "local")
    get_settings.cache_clear()
    clear_engine_cache()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    # Read the parent from the revision itself so a later rechain of this
    # migration onto another head keeps exercising the true pre-A1 shape.
    parent = ScriptDirectory.from_config(config).get_revision(REVISION).down_revision
    try:
        command.upgrade(config, parent)
        assert "company_id" not in {
            column["name"] for column in inspect(engine).get_columns("ip_rule_sets")
        }
        yield engine, config, parent
    finally:
        clear_engine_cache()
        get_settings.cache_clear()


def _company_with_member(engine) -> tuple[str, str]:
    with Session(engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id, role="admin")
        session.commit()
    return company_id, membership_id


def _legacy_rule_set(engine, *, key: str) -> str:
    rule_set_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ip_rule_sets (id, key, rule_kind, jurisdiction, office, "
                "right_kind, proceeding_kind, role, stage, created_at) VALUES "
                "(:id, :key, 'deadline', 'IN', 'IP India', 'trademark', 'application', "
                "'applicant', 'examination', :ts)"
            ),
            {"id": rule_set_id, "key": key, "ts": datetime.now(UTC)},
        )
    return rule_set_id


def _legacy_version(
    engine,
    *,
    rule_set_id: str,
    version: int,
    proposer_id: str | None,
    status: str = "candidate",
) -> str:
    version_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ip_rule_versions (id, rule_set_id, version, status, "
                "source_record_id, source_hash, source_reference, effective_from, "
                "engine_compatibility, fixture_set_json, definition_json, "
                "proposed_by_membership_id, proposer_label_snapshot, created_at) VALUES "
                "(:id, :set, :version, :status, 'legacy-source', :hash, "
                "'https://official.example/rules', :effective, 'caseops-ip-deadline-v1', "
                ":fixtures, :definition, :proposer, 'Legacy proposer', :ts)"
            ),
            {
                "id": version_id,
                "set": rule_set_id,
                "version": version,
                "status": status,
                "hash": "b" * 64,
                "effective": date(2026, 1, 1),
                "fixtures": json.dumps([]),
                "definition": json.dumps({}),
                "proposer": proposer_id,
                "ts": datetime.now(UTC),
            },
        )
    return version_id


def _legacy_policy(
    engine,
    *,
    company_id: str,
    rule_set_id: str,
    version_id: str,
    updater_id: str,
) -> None:
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO company_ip_rule_policies (id, company_id, rule_set_id, "
                "active_rule_version_id, auto_confirm_eligible, "
                "internal_target_policy_json, version, updated_by_membership_id, "
                "updater_label_snapshot, created_at, updated_at) VALUES "
                "(:id, :company, :set, :version_id, false, :policy, 1, :updater, "
                "'Legacy updater', :ts, :ts)"
            ),
            {
                "id": str(uuid4()),
                "company": company_id,
                "set": rule_set_id,
                "version_id": version_id,
                "policy": json.dumps({}),
                "updater": updater_id,
                "ts": now,
            },
        )


def _current_revision(engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar())


def test_backfills_owner_from_evidence_and_scopes_keys_per_company(at_parent) -> None:
    engine, config, _parent = at_parent
    first_company, first_member = _company_with_member(engine)
    second_company, second_member = _company_with_member(engine)

    proposed = _legacy_rule_set(engine, key="in-tm-examination-response-v1")
    active = _legacy_version(
        engine, rule_set_id=proposed, version=1, proposer_id=first_member, status="active"
    )
    _legacy_policy(
        engine,
        company_id=first_company,
        rule_set_id=proposed,
        version_id=active,
        updater_id=first_member,
    )
    # The proposer membership was deleted (SET NULL); the policy still names
    # exactly one company, so ownership is evidenced rather than guessed.
    orphaned = _legacy_rule_set(engine, key="in-tm-hearing-v1")
    orphan_version = _legacy_version(
        engine, rule_set_id=orphaned, version=1, proposer_id=None, status="active"
    )
    _legacy_policy(
        engine,
        company_id=second_company,
        rule_set_id=orphaned,
        version_id=orphan_version,
        updater_id=second_member,
    )

    command.upgrade(config, REVISION)

    with engine.connect() as connection:
        owners = dict(connection.execute(text("SELECT id, company_id FROM ip_rule_sets")).all())
    assert owners == {proposed: first_company, orphaned: second_company}
    assert _current_revision(engine) == REVISION

    # The global key constraint is gone: another company may reuse the key ...
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ip_rule_sets (id, company_id, key, rule_kind, jurisdiction, "
                "right_kind, stage, created_at) VALUES (:id, :company, "
                "'in-tm-examination-response-v1', 'deadline', 'IN', 'trademark', "
                "'examination', :ts)"
            ),
            {"id": str(uuid4()), "company": second_company, "ts": datetime.now(UTC)},
        )
    # ... but one company still owns a key once.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ip_rule_sets (id, company_id, key, rule_kind, jurisdiction, "
                "right_kind, stage, created_at) VALUES (:id, :company, "
                "'in-tm-examination-response-v1', 'deadline', 'IN', 'trademark', "
                "'examination', :ts)"
            ),
            {"id": str(uuid4()), "company": first_company, "ts": datetime.now(UTC)},
        )

    # A company policy can no longer point at another company's rule set.
    with pytest.raises((IntegrityError, DBAPIError)), engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(
            text(
                "INSERT INTO company_ip_rule_policies (id, company_id, rule_set_id, "
                "active_rule_version_id, auto_confirm_eligible, "
                "internal_target_policy_json, version, updater_label_snapshot, "
                "created_at, updated_at) VALUES (:id, :company, :set, :version_id, "
                "false, '{}', 1, 'Cross-tenant probe', :ts, :ts)"
            ),
            {
                "id": str(uuid4()),
                "company": second_company,
                "set": proposed,
                "version_id": active,
                "ts": datetime.now(UTC),
            },
        )


def test_refuses_a_rule_set_whose_evidence_spans_companies(at_parent) -> None:
    engine, config, parent = at_parent
    _first_company, first_member = _company_with_member(engine)
    second_company, second_member = _company_with_member(engine)

    shared = _legacy_rule_set(engine, key="in-tm-shared-legacy-key")
    _legacy_version(engine, rule_set_id=shared, version=1, proposer_id=first_member)
    second_version = _legacy_version(
        engine, rule_set_id=shared, version=2, proposer_id=second_member, status="active"
    )
    _legacy_policy(
        engine,
        company_id=second_company,
        rule_set_id=shared,
        version_id=second_version,
        updater_id=second_member,
    )

    with pytest.raises(RuntimeError, match="ownership is ambiguous") as caught:
        command.upgrade(config, REVISION)
    message = str(caught.value)
    assert shared in message
    assert "2 companies" in message
    assert _current_revision(engine) == parent


def test_refuses_a_rule_set_without_any_ownership_evidence(at_parent) -> None:
    engine, config, parent = at_parent
    orphan = _legacy_rule_set(engine, key="in-tm-orphan-legacy-key")
    _legacy_version(engine, rule_set_id=orphan, version=1, proposer_id=None)

    with pytest.raises(RuntimeError, match="no ownership evidence") as caught:
        command.upgrade(config, REVISION)
    assert orphan in str(caught.value)
    assert _current_revision(engine) == parent
