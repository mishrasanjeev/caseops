"""SQLite migration proof for the complete IPLF-039F cost boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260830_0002"
MIGRATION_HEAD = "20260830_0003"
COST_TRIGGERS = {
    "trg_ip_cost_items_evidence_immutable",
    "trg_ip_cost_items_evidence_retained",
    "trg_ip_cost_items_actor_tenant_insert",
    "trg_ip_cost_items_reconciler_tenant_insert",
    "trg_ip_cost_items_reconciler_tenant_update",
}
CORRECTION_TRIGGERS = {
    "trg_ip_cost_corrections_append_only",
    "trg_ip_cost_corrections_retained",
    "trg_ip_cost_corrections_actor_tenant_insert",
}


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Config]:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-cost-evidence.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return database_url, config


def _engine(database_url: str):  # type: ignore[no-untyped-def]
    engine = create_engine(database_url, future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _seed_scope(connection) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    for suffix in ("a", "b"):
        connection.execute(
            text(
                "INSERT INTO companies (id, name, slug, company_type, tenant_key, "
                "is_active, timezone, created_at) VALUES (:id, :name, :slug, "
                "'law_firm', :tenant, 1, 'Asia/Kolkata', :now)"
            ),
            {
                "id": f"company-{suffix}",
                "name": f"Company {suffix.upper()}",
                "slug": f"company-{suffix}",
                "tenant": f"company-{suffix}",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO users (id, email, full_name, password_hash, is_active, "
                "created_at) VALUES (:id, :email, :name, 'not-used', 1, :now)"
            ),
            {
                "id": f"user-{suffix}",
                "email": f"actor-{suffix}@example.com",
                "name": f"Actor {suffix.upper()}",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO company_memberships (id, company_id, user_id, role, "
                "is_active, created_at) VALUES (:id, :company, :user, 'owner', 1, :now)"
            ),
            {
                "id": f"membership-{suffix}",
                "company": f"company-{suffix}",
                "user": f"user-{suffix}",
                "now": now,
            },
        )
    connection.execute(
        text(
            "INSERT INTO ip_docket_records (id, company_id, record_type, title, status, "
            "is_active, lifecycle_version, restricted, access_policy_version, "
            "current_version, created_at, updated_at) VALUES ('docket-a', 'company-a', "
            "'trademark', 'SQLite matterless cost', 'draft', 1, 0, 0, 0, 1, :now, :now)"
        ),
        {"now": now},
    )


def _insert_cost_sql(*, cost_id: str, actor_id: str, status: str = "nonbillable"):
    return text(
        "INSERT INTO ip_cost_items (id, company_id, docket_id, matter_id, category, "
        "description, amount_minor, currency, billable, cost_nature, rate_confidential, "
        "evidence_reference, reconciliation_status, created_by_membership_id, created_at) "
        "VALUES (:cost, 'company-a', 'docket-a', NULL, 'official_fee', :description, "
        "900000, 'INR', 0, 'actual', 0, :evidence, :status, :actor, CURRENT_TIMESTAMP)"
    ).bindparams(
        cost=cost_id,
        actor=actor_id,
        status=status,
        description=f"Official filing fee {cost_id}",
        evidence=f"receipt:{cost_id}",
    )


def test_cost_guards_correction_lineage_and_parent_cascade_are_enforced_on_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch)
    command.upgrade(config, MIGRATION_HEAD)
    engine = _engine(database_url)
    try:
        with engine.begin() as connection:
            _seed_scope(connection)
            cost_triggers = set(
                connection.scalars(
                    text(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                        "AND tbl_name = 'ip_cost_items'"
                    )
                )
            )
            correction_triggers = set(
                connection.scalars(
                    text(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                        "AND tbl_name = 'ip_cost_item_corrections'"
                    )
                )
            )
            assert COST_TRIGGERS.issubset(cost_triggers)
            assert CORRECTION_TRIGGERS.issubset(correction_triggers)

        # Hostile direct writers cannot invent an unlinked matterless row or
        # attribute a cost to an actor from another tenant.
        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                _insert_cost_sql(
                    cost_id="invalid-status",
                    actor_id="membership-a",
                    status="unlinked",
                )
            )
        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="creator must be an active member of the cost tenant"
        ):
            connection.execute(
                _insert_cost_sql(
                    cost_id="invalid-actor",
                    actor_id="membership-b",
                )
            )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE company_memberships SET is_active = 0 "
                    "WHERE id = 'membership-b'"
                )
            )
        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="creator must be an active member of the cost tenant"
        ):
            connection.execute(
                _insert_cost_sql(
                    cost_id="inactive-actor",
                    actor_id="membership-b",
                )
            )

        with engine.begin() as connection:
            connection.execute(
                _insert_cost_sql(cost_id="cost-original", actor_id="membership-a")
            )
            connection.execute(
                _insert_cost_sql(cost_id="cost-replacement", actor_id="membership-a")
            )
            # The derived projection remains refreshable only inside the
            # terminal nonbillable constraint.
            connection.execute(
                text(
                    "UPDATE ip_cost_items SET reconciliation_status = 'nonbillable', "
                    "canonical_amount_minor = NULL, reconciliation_difference_minor = NULL, "
                    "reconciled_at = CURRENT_TIMESTAMP, "
                    "reconciled_by_membership_id = 'membership-a' "
                    "WHERE id = 'cost-original'"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ip_cost_item_corrections (id, company_id, docket_id, "
                    "source_cost_item_id, action, replacement_cost_item_id, reason, "
                    "evidence_reference, created_by_membership_id, created_at) VALUES "
                    "('correction-a', 'company-a', 'docket-a', 'cost-original', "
                    "'supersede', 'cost-replacement', 'Original receipt amount was wrong', "
                    "'correction:registry-confirmation', 'membership-a', CURRENT_TIMESTAMP)"
                )
            )

        for statement, message in (
            (
                "UPDATE ip_cost_items SET amount_minor = 1 WHERE id = 'cost-original'",
                "IP cost evidence is immutable",
            ),
            (
                "UPDATE ip_cost_items SET reconciliation_status = 'matched', "
                "canonical_amount_minor = 900000 WHERE id = 'cost-original'",
                "CHECK constraint failed",
            ),
            (
                "UPDATE ip_cost_items SET reconciled_by_membership_id = 'membership-b' "
                "WHERE id = 'cost-original'",
                "reconciler must be an active member of the cost tenant",
            ),
            (
                "UPDATE ip_cost_item_corrections SET reason = 'rewritten' "
                "WHERE id = 'correction-a'",
                "append-only",
            ),
            (
                "DELETE FROM ip_cost_item_corrections WHERE id = 'correction-a'",
                "corrections are retained",
            ),
            (
                "DELETE FROM ip_cost_items WHERE id = 'cost-original'",
                "IP cost evidence is retained",
            ),
        ):
            with engine.begin() as connection, pytest.raises(DBAPIError, match=message):
                connection.execute(text(statement))

        # The direct-delete fence must not invalidate the schema's declared
        # parent-owned CASCADE. During the parent deletion the docket no longer
        # exists, so both retained children may be dispositioned together.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM ip_docket_records WHERE id = 'docket-a'"))
            assert connection.scalar(text("SELECT count(*) FROM ip_cost_items")) == 0
            assert (
                connection.scalar(text("SELECT count(*) FROM ip_cost_item_corrections"))
                == 0
            )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = _engine(database_url)
    try:
        with engine.connect() as connection:
            triggers = set(
                connection.scalars(
                    text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                )
            )
            assert COST_TRIGGERS.isdisjoint(triggers)
            assert CORRECTION_TRIGGERS.isdisjoint(triggers)
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'ip_cost_item_corrections'"
                )
            ) == 0
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)


def test_downgrade_refuses_to_discard_append_only_correction_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore-forward is mandatory once governed correction rows exist."""

    database_url, config = _configure(tmp_path, monkeypatch)
    command.upgrade(config, MIGRATION_HEAD)
    engine = _engine(database_url)
    try:
        with engine.begin() as connection:
            _seed_scope(connection)
            connection.execute(
                _insert_cost_sql(cost_id="cost-original", actor_id="membership-a")
            )
            connection.execute(
                _insert_cost_sql(cost_id="cost-replacement", actor_id="membership-a")
            )
            connection.execute(
                text(
                    "INSERT INTO ip_cost_item_corrections (id, company_id, docket_id, "
                    "source_cost_item_id, action, replacement_cost_item_id, reason, "
                    "evidence_reference, created_by_membership_id, created_at) VALUES "
                    "('correction-a', 'company-a', 'docket-a', 'cost-original', "
                    "'supersede', 'cost-replacement', 'Registry corrected the fee', "
                    "'correction:official-register', 'membership-a', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "UPDATE company_memberships SET is_active = 0 "
                    "WHERE id = 'membership-a'"
                )
            )

        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="creator must be an active member of the cost tenant"
        ):
            connection.execute(
                _insert_cost_sql(cost_id="inactive-same-tenant", actor_id="membership-a")
            )
        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="reconciler must be an active member of the cost tenant"
        ):
            connection.execute(
                text(
                    "UPDATE ip_cost_items SET reconciled_by_membership_id = "
                    "'membership-a' WHERE id = 'cost-replacement'"
                )
            )
        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="correction actor must be an active member of the cost tenant"
        ):
            connection.execute(
                text(
                    "INSERT INTO ip_cost_item_corrections (id, company_id, docket_id, "
                    "source_cost_item_id, action, replacement_cost_item_id, reason, "
                    "evidence_reference, created_by_membership_id, created_at) VALUES "
                    "('correction-inactive', 'company-a', 'docket-a', "
                    "'cost-replacement', 'void', NULL, 'Inactive actor attempt', "
                    "'correction:inactive', 'membership-a', CURRENT_TIMESTAMP)"
                )
            )

        with pytest.raises(RuntimeError, match="restore or roll forward"):
            command.downgrade(config, PREVIOUS_HEAD)

        # The failed downgrade preserves the migration version, both immutable
        # costs, their parent docket, and the correction row. It does not delete
        # parent evidence as a way to make the destructive downgrade succeed.
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                MIGRATION_HEAD
            )
            assert connection.scalar(text("SELECT count(*) FROM ip_docket_records")) == 1
            assert connection.scalar(text("SELECT count(*) FROM ip_cost_items")) == 2
            assert (
                connection.scalar(text("SELECT count(*) FROM ip_cost_item_corrections"))
                == 1
            )
    finally:
        engine.dispose()
