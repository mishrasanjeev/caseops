"""20261031_0001 backfills default IP document classifications, and nothing else.

Each tenant below is shaped like a real pre-release production state: the
IP workspace rows, memberships and any firm-owned taxonomy exist before the
revision runs. The revision itself must create the default classifications.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import IpDocumentTaxonomyEntry, IpWorkspaceConfiguration
from caseops_api.db.session import clear_engine_cache
from caseops_api.services.ip_documents import (
    DEFAULT_TAXONOMY,
    TAXONOMY_VERSION,
    _normalize_alias,
    ensure_default_ip_document_taxonomy,
)
from tests.fixtures_postgres_client import temporary_http_database

PARENT = "20261026_0001"
REVISION = "20261031_0001"
ACTION = "ip_document_taxonomy.defaults_provisioned"
ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic" / "versions" / "20261031_0001_ip_document_taxonomy_defaults.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("taxonomy_defaults_20261031", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def fresh_engine(request, tmp_path):
    if request.param == "postgres":
        source = request.getfixturevalue("pg_engine")
        with temporary_http_database(source.url) as engine:
            yield engine
    else:
        engine = create_engine(
            "sqlite+pysqlite:///" + (tmp_path / "taxonomy-defaults.db").as_posix()
        )
        try:
            yield engine
        finally:
            engine.dispose()


def _alembic_config(engine, monkeypatch) -> Config:
    url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    monkeypatch.setenv("CASEOPS_ENV", "local")
    get_settings.cache_clear()
    clear_engine_cache()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def migration_config(fresh_engine, monkeypatch):
    try:
        yield _alembic_config(fresh_engine, monkeypatch)
    finally:
        clear_engine_cache()
        get_settings.cache_clear()


def _company(session: Session, slug: str) -> str:
    company_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO companies (id, name, slug, company_type, tenant_key, is_active, "
            "timezone, created_at) VALUES (:id, :name, :slug, 'law_firm', :tenant_key, "
            ":active, 'Asia/Kolkata', :created_at)"
        ),
        {
            "id": company_id,
            "name": slug.title(),
            "slug": slug,
            "tenant_key": company_id,
            "active": True,
            "created_at": datetime.now(UTC),
        },
    )
    return company_id


def _membership(
    session: Session,
    company_id: str,
    *,
    role: str,
    created_at: datetime,
    active: bool = True,
    user_active: bool = True,
) -> str:
    user_id, membership_id = str(uuid4()), str(uuid4())
    session.execute(
        text(
            "INSERT INTO users (id, email, full_name, password_hash, is_active, created_at) "
            "VALUES (:id, :email, 'Migration Member', 'not-used', :active, :created_at)"
        ),
        {
            "id": user_id,
            "email": f"{user_id}@taxonomy-migration.example",
            "active": user_active,
            "created_at": created_at,
        },
    )
    session.execute(
        text(
            "INSERT INTO company_memberships (id, company_id, user_id, role, is_active, "
            "created_at) VALUES (:id, :company_id, :user_id, :role, :active, :created_at)"
        ),
        {
            "id": membership_id,
            "company_id": company_id,
            "user_id": user_id,
            "role": role,
            "active": active,
            "created_at": created_at,
        },
    )
    return membership_id


def _workspace(session: Session, company_id: str, membership_id: str, *, enabled: bool) -> None:
    session.add(
        IpWorkspaceConfiguration(
            company_id=company_id,
            version=1,
            enabled_asset_types_json=["trademark"],
            jurisdictions_json=["IN"],
            offices_json=["IP India"],
            timezone="Asia/Kolkata",
            holiday_calendar_key="in-national",
            working_day_policy_json={"working_weekdays": [0, 1, 2, 3, 4]},
            # The legacy client label production tenants were configured with.
            document_taxonomy_version="ip-taxonomy-2026.1",
            event_catalog_version="ip-events-v1",
            deadline_rule_versions_json={"IN": "2026.1"},
            notification_channels_json=["in_app"],
            critical_event_policy_json={"escalation_after_minutes": 30},
            escalation_owner_membership_id=membership_id,
            provider_keys_json=[],
            enabled_automations_json=[],
            workspace_enabled=enabled,
            updated_by_membership_id=membership_id,
        )
    )


def _snapshot(engine, company_id: str) -> dict[str, object]:
    with engine.connect() as connection:
        entries = connection.execute(
            text(
                "SELECT id, key, label, description, sort_order, is_seeded, is_active, "
                "version, updated_by_membership_id FROM ip_document_taxonomy_entries "
                "WHERE company_id = :company_id ORDER BY key"
            ),
            {"company_id": company_id},
        ).all()
        aliases = connection.execute(
            text(
                "SELECT taxonomy_entry_id, alias, normalized_alias, source, "
                "created_by_membership_id FROM ip_document_taxonomy_aliases "
                "WHERE company_id = :company_id ORDER BY normalized_alias"
            ),
            {"company_id": company_id},
        ).all()
        audits = connection.execute(
            text(
                "SELECT actor_type, actor_membership_id, actor_label, target_type, target_id, "
                "result, metadata_json FROM audit_events "
                "WHERE company_id = :company_id AND action = :action"
            ),
            {"company_id": company_id, "action": ACTION},
        ).all()
    return {"entries": entries, "aliases": aliases, "audits": audits}


def test_frozen_migration_defaults_match_the_service_defaults() -> None:
    module = _migration_module()
    assert module.TAXONOMY_VERSION == TAXONOMY_VERSION
    assert [(key, label) for key, label, _normalized in module.DEFAULT_TAXONOMY] == list(
        DEFAULT_TAXONOMY
    )
    for _key, label, normalized in module.DEFAULT_TAXONOMY:
        assert normalized == _normalize_alias(label)


def test_backfill_seeds_only_enabled_zero_entry_tenants_and_is_idempotent(
    fresh_engine, migration_config
) -> None:
    engine = fresh_engine
    command.upgrade(migration_config, PARENT)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        # Tenant shaped like test-legal: enabled workspace, zero classifications.
        legacy = _company(session, "legacy-enabled")
        _membership(session, legacy, role="admin", created_at=base)
        _membership(
            session, legacy, role="owner", created_at=base + timedelta(days=1), active=False
        )
        _membership(
            session, legacy, role="owner", created_at=base + timedelta(days=2), user_active=False
        )
        attributed_owner = _membership(
            session, legacy, role="owner", created_at=base + timedelta(days=3)
        )
        later_owner = _membership(
            session, legacy, role="owner", created_at=base + timedelta(days=4)
        )
        # A firm that already owns a (deactivated, renamed) taxonomy.
        custom = _company(session, "custom-firm")
        custom_owner = _membership(session, custom, role="owner", created_at=base)
        # Configured but never enabled: not in scope of the backfill.
        configured = _company(session, "configured-only")
        configured_owner = _membership(session, configured, role="owner", created_at=base)
        # Enabled but no active owner to attribute the rows to: skipped.
        ownerless = _company(session, "ownerless-enabled")
        ownerless_admin = _membership(session, ownerless, role="admin", created_at=base)
        session.flush()
        _workspace(session, legacy, later_owner, enabled=True)
        _workspace(session, custom, custom_owner, enabled=True)
        _workspace(session, configured, configured_owner, enabled=False)
        _workspace(session, ownerless, ownerless_admin, enabled=True)
        session.add(
            IpDocumentTaxonomyEntry(
                company_id=custom,
                key="evidence",
                label="Evidence of use (firm)",
                description="Firm-renamed category.",
                sort_order=1,
                is_seeded=False,
                is_active=False,
                version=3,
                updated_by_membership_id=custom_owner,
            )
        )
        session.commit()
    custom_before = _snapshot(engine, custom)

    command.upgrade(migration_config, REVISION)

    legacy_after = _snapshot(engine, legacy)
    entries = legacy_after["entries"]
    assert sorted((row.key, row.label) for row in entries) == sorted(DEFAULT_TAXONOMY)
    assert {row.sort_order for row in entries} == set(range(10, 10 + len(DEFAULT_TAXONOMY)))
    assert all(row.is_seeded and row.is_active and row.version == 1 for row in entries)
    assert {row.updated_by_membership_id for row in entries} == {attributed_owner}
    aliases = legacy_after["aliases"]
    assert len(aliases) == len(DEFAULT_TAXONOMY)
    assert {row.taxonomy_entry_id for row in aliases} == {row.id for row in entries}
    assert {(row.alias, row.normalized_alias) for row in aliases} == {
        (label, _normalize_alias(label)) for _key, label in DEFAULT_TAXONOMY
    }
    assert {row.source for row in aliases} == {"seed"}
    assert {row.created_by_membership_id for row in aliases} == {attributed_owner}
    [audit] = legacy_after["audits"]
    assert audit.actor_type == "system"
    assert audit.actor_membership_id == attributed_owner
    assert audit.actor_label == f"CaseOps release migration {REVISION}"
    assert (audit.target_type, audit.target_id, audit.result) == (
        "ip_document_taxonomy",
        legacy,
        "success",
    )
    metadata = json.loads(audit.metadata_json)
    assert metadata == {
        "taxonomy_version": TAXONOMY_VERSION,
        "keys": [key for key, _label in DEFAULT_TAXONOMY],
        "trigger": "release_backfill",
        "migration_revision": REVISION,
    }

    assert _snapshot(engine, custom) == custom_before
    for untouched in (configured, ownerless):
        snapshot = _snapshot(engine, untouched)
        assert snapshot == {"entries": [], "aliases": [], "audits": []}

    # Downgrade is a deliberate no-op that keeps tenant data; a re-run of the
    # revision then finds every tenant provisioned and inserts nothing.
    command.downgrade(migration_config, PARENT)
    assert _snapshot(engine, legacy) == legacy_after
    command.upgrade(migration_config, REVISION)
    assert _snapshot(engine, legacy) == legacy_after
    assert _snapshot(engine, custom) == custom_before
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION


@pytest.mark.postgres
def test_concurrent_first_provisioning_keeps_exactly_one_winner(pg_engine, monkeypatch) -> None:
    """Two requests that both saw an empty taxonomy: one inserts, the other yields."""

    with temporary_http_database(pg_engine.url) as engine:
        try:
            command.upgrade(_alembic_config(engine, monkeypatch), REVISION)
            with Session(engine) as session:
                company_id = _company(session, "race-firm")
                first_actor = _membership(
                    session, company_id, role="owner", created_at=datetime.now(UTC)
                )
                second_actor = _membership(
                    session, company_id, role="admin", created_at=datetime.now(UTC)
                )
                session.commit()

            winner = Session(engine)
            try:
                winner_keys = ensure_default_ip_document_taxonomy(
                    winner,
                    company_id=company_id,
                    actor_membership_id=first_actor,
                    trigger="workspace_enable",
                )
                outcome: dict[str, object] = {}

                def loser() -> None:
                    try:
                        with Session(engine) as session:
                            outcome["keys"] = ensure_default_ip_document_taxonomy(
                                session,
                                company_id=company_id,
                                actor_membership_id=second_actor,
                                trigger="document_upload",
                            )
                            # The loser's own transaction is still usable.
                            outcome["visible"] = session.scalar(
                                text(
                                    "SELECT count(*) FROM ip_document_taxonomy_entries "
                                    "WHERE company_id = :company_id"
                                ),
                                {"company_id": company_id},
                            )
                            session.commit()
                    except Exception as exc:  # pragma: no cover - surfaced below
                        outcome["error"] = exc

                thread = threading.Thread(target=loser)
                thread.start()
                # Wait until the loser is blocked on the winner's uncommitted keys.
                deadline = time.monotonic() + 30
                with engine.connect() as probe:
                    while time.monotonic() < deadline:
                        waiting = probe.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                            )
                        )
                        if waiting:
                            break
                        probe.rollback()
                        time.sleep(0.05)
                    assert waiting, "the second provisioner never reached the unique index"
                winner.commit()
                thread.join(timeout=30)
                assert not thread.is_alive()
            finally:
                winner.close()

            assert "error" not in outcome, outcome.get("error")
            assert set(winner_keys) == {key for key, _label in DEFAULT_TAXONOMY}
            assert outcome["keys"] == []
            assert outcome["visible"] == len(DEFAULT_TAXONOMY)
            snapshot = _snapshot(engine, company_id)
            assert len(snapshot["entries"]) == len(DEFAULT_TAXONOMY)
            assert len(snapshot["aliases"]) == len(DEFAULT_TAXONOMY)
            assert {row.updated_by_membership_id for row in snapshot["entries"]} == {first_actor}
            [audit] = snapshot["audits"]
            assert audit.actor_membership_id == first_actor
        finally:
            clear_engine_cache()
            get_settings.cache_clear()
