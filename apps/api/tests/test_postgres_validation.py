"""AQ-005 (2026-04-25) — Postgres-backed validation suite.

Codex's no-manual-tester replacement standard requires that critical
DB behavior be proven on real Postgres + pgvector, not just the
SQLite shim the rest of the suite uses. Every test in this module
carries `@pytest.mark.postgres` and is auto-skipped unless
CASEOPS_TEST_POSTGRES_URL is set (see `tests/conftest.py`).

The CI job `postgres-validation` (.github/workflows/ci.yml) starts a
service container of `pgvector/pgvector:pg17`, runs alembic
`upgrade head` once via `_ensure_migrations`, then runs
`pytest -m postgres`.

Each test creates its own rows with uuid4 IDs to avoid colliding
with neighboring tests. We do NOT roll back per-test — the service
container is fresh per CI job, and a small amount of accumulated
test data is fine for the few minutes the suite runs.

Why these specific tests:

- `test_alembic_upgrade_to_head_runs_cleanly`: catches every batch-
  mode migration that secretly assumes SQLite (e.g. our C-3
  20260424_0002 that uses `op.batch_alter_table`).
- `test_lifecycle_migration_neutralizes_legacy_children_on_postgres`:
  proves the July 15 data repair against the production dialect, not
  merely the SQLite migration harness. A legacy closed Matter is
  upgraded with its old task/deadline/hearing permanently cancelled.
- `test_pgvector_extension_and_hnsw_index_work`: the entire RAG
  retrieval path depends on pgvector's `<=>` cosine operator + an
  HNSW index. SQLite has no equivalent; this is the only place we
  prove the corpus retrieval shape works.
- `test_portal_user_fk_set_null_on_delete_propagates`: the C-3 FKs
  on matter_attachments / matter_invoices / matter_time_entries use
  `ON DELETE SET NULL`. SQLite ignores ON DELETE constraints unless
  PRAGMA foreign_keys=ON is set explicitly per session, so this
  behavior is effectively unverified outside Postgres.
- `test_jsonb_column_roundtrip_preserves_nested_dict`: SQLAlchemy's
  JSON column maps to JSONB on PG and TEXT-with-JSON-serialization
  on SQLite. The two have different ordering + key-handling
  semantics; this proves the prod path works.
- `test_unique_constraint_on_invoice_line_item_time_entry`: every
  UniqueConstraint we declare needs a real PG check — SQLite
  enforces them too but with looser semantics (e.g. NULL handling
  in composite UNIQUE).
- `test_oc_cross_visibility_server_default_inserts_false`: proves
  the C-3 `server_default=false()` on `Matter.oc_cross_visibility_enabled`
  actually fires on Postgres (the migration uses `sa.false()`).
"""

from __future__ import annotations

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres


# ---------- module-scope migrations (run once per CI job) ----------


@pytest.fixture(scope="module", autouse=True)
def _ensure_migrations():
    """Run alembic upgrade head once before any pg test executes.
    Idempotent: alembic skips already-applied revisions.

    Module-scoped → cannot depend on `pg_engine` (function-scoped).
    Reads CASEOPS_TEST_POSTGRES_URL directly so alembic targets the
    same DB the per-test pg_engine fixture binds to.
    """
    url = os.environ.get("CASEOPS_TEST_POSTGRES_URL", "").strip()
    if not url:
        # Tests will be skipped at collection-time (see conftest); we
        # still let the fixture run so module-scope teardown works.
        yield
        return
    from alembic.config import Config

    from alembic import command

    project_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield


# ---------- helpers ----------


def _seed_company(session: Session) -> str:
    company_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO companies "
            "(id, name, slug, company_type, tenant_key, is_active, "
            "timezone, created_at) "
            "VALUES (:id, :n, :s, 'law_firm', :tk, true, :tz, :ts)"
        ),
        {
            "id": company_id,
            "n": f"PG Test Co {company_id[:8]}",
            "s": f"pgco-{company_id[:8]}",
            "tk": company_id,
            "tz": "Asia/Kolkata",
            "ts": datetime.now(UTC),
        },
    )
    return company_id


def _enqueue_shared_lifecycle_event(
    session: Session,
    *,
    company_id: str,
    event_key: str,
    aggregate_id: str,
    now: datetime,
):
    from caseops_api.services.domain_outbox import enqueue_domain_event

    correlation_id = f"correlation-{uuid4()}"
    return enqueue_domain_event(
        session,
        company_id=company_id,
        event_key=event_key,
        event_type="ip.legal_state.lifecycle_changed",
        schema_version=1,
        aggregate_type="ip_docket_record",
        aggregate_id=aggregate_id,
        aggregate_version=1,
        occurred_at=now,
        effective_at=now,
        source_command_id=f"command-{uuid4()}",
        source_event_id=None,
        producer="postgres-validation",
        confidentiality="privileged",
        correlation_id=correlation_id,
        payload={
            "target_type": "ip_docket_record",
            "target_id": aggregate_id,
            "from_state": "draft",
            "to_state": "active",
            "lifecycle_version": 1,
        },
        now=now,
    )


def _seed_matter(session: Session, company_id: str) -> str:
    """Raw-SQL seed: every NOT NULL column without a server_default
    must be supplied explicitly. Python-side `default=` on the
    SQLAlchemy model doesn't fire when we bypass the ORM."""
    matter_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO matters "
            "(id, company_id, title, matter_code, client_name, status, "
            "practice_area, forum_level, is_active, restricted_access, "
            "created_at, updated_at) "
            "VALUES (:id, :co, 'Test Matter', :code, 'Test Client', "
            "'active', 'commercial', 'high_court', true, false, :ts, :ts)"
        ),
        {
            "id": matter_id,
            "co": company_id,
            "code": f"PG-{matter_id[:6].upper()}",
            "ts": datetime.now(UTC),
        },
    )
    return matter_id


def _seed_membership(session: Session, company_id: str) -> str:
    user_id = str(uuid4())
    membership_id = str(uuid4())
    now = datetime.now(UTC)
    session.execute(
        text(
            "INSERT INTO users "
            "(id, email, full_name, password_hash, is_active, created_at) "
            "VALUES (:id, :email, 'Notice PG User', 'not-used', true, :ts)"
        ),
        {
            "id": user_id,
            "email": f"notice-pg-{user_id[:8]}@example.com",
            "ts": now,
        },
    )
    session.execute(
        text(
            "INSERT INTO company_memberships "
            "(id, company_id, user_id, role, is_active, created_at) "
            "VALUES (:id, :company, :user, 'member', true, :ts)"
        ),
        {
            "id": membership_id,
            "company": company_id,
            "user": user_id,
            "ts": now,
        },
    )
    return membership_id


def _seed_notice(
    session: Session,
    company_id: str,
    membership_id: str,
    **overrides: object,
) -> str:
    notice_id = str(uuid4())
    values: dict[str, object] = {
        "id": notice_id,
        "company": company_id,
        "owner": membership_id,
        "creator": membership_id,
        "direction": "received",
        "subject": f"PG notice {notice_id[:8]}",
        "status": "Open",
        "reply_required": False,
        "reply_sent": False,
        "currency": "INR",
        "ts": datetime.now(UTC),
    }
    values.update(overrides)
    session.execute(
        text(
            "INSERT INTO company_notices "
            "(id, company_id, owner_membership_id, created_by_membership_id, "
            "direction, subject, status, reply_required, reply_sent, currency, "
            "created_at, updated_at) VALUES "
            "(:id, :company, :owner, :creator, :direction, :subject, :status, "
            ":reply_required, :reply_sent, :currency, :ts, :ts)"
        ),
        values,
    )
    return notice_id


def _seed_portal_user(session: Session, company_id: str) -> str:
    pu_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO portal_users "
            "(id, company_id, email, full_name, role, is_active, created_at) "
            "VALUES (:id, :co, :em, 'Test PU', 'outside_counsel', true, :ts)"
        ),
        {
            "id": pu_id,
            "co": company_id,
            "em": f"pu-{pu_id[:8]}@example.com",
            "ts": datetime.now(UTC),
        },
    )
    return pu_id


def _fk_index_pairs() -> tuple[tuple[str, str], ...]:
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260625_0002_fk_leading_indexes.py"
    )
    spec = importlib.util.spec_from_file_location(migration.stem, migration)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    pairs = module.FK_INDEXES
    assert isinstance(pairs, tuple)
    return pairs


# ---------- tests ----------


def test_alembic_upgrade_to_head_runs_cleanly(pg_engine):
    """If `_ensure_migrations` got us here without raising, head is
    applied. Belt-and-suspenders: resolve Alembic's graph instead of
    guessing the head from lexicographic filenames.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()

    with pg_engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    assert len(rows) == 1, f"alembic_version should have one row, got {len(rows)}"
    assert heads == [rows[0][0]], (
        f"DB at {rows[0][0]} but Alembic graph heads are {heads}; "
        "alembic upgrade head did not advance the DB"
    )


def test_ip_delivery_holds_docket_lock_during_final_authorization(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
):
    """A concurrent access change cannot pass delivery's final policy check."""
    from threading import Event, Thread

    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError

    from caseops_api.db.models import (
        IpDocketRecord,
        NotificationDeliveryIntent,
        NotificationDeliveryStatus,
    )
    from caseops_api.services import notification_delivery

    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id)
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark_application",
            title="PostgreSQL delivery authorization lock",
            primary_identifier=f"PG-ACCESS-{str(uuid4())[:8]}",
            status="draft",
            is_active=True,
            restricted=False,
            created_by_membership_id=membership_id,
        )
        session.add(docket)
        session.flush()
        intent = NotificationDeliveryIntent(
            company_id=company_id,
            recipient_membership_id=membership_id,
            ip_docket_id=docket.id,
            channel="in_app",
            event_type="ip.access.postgres_lock",
            source_type="ip_docket_record",
            source_id=docket.id,
            idempotency_key=str(uuid4()),
            status=NotificationDeliveryStatus.QUEUED,
            title="Docket access changed",
            body="Review the docket in CaseOps.",
        )
        session.add(intent)
        session.commit()
        docket_id = docket.id
        intent_id = intent.id

    authorization_entered = Event()
    authorize_delivery = Event()
    worker_failures: list[Exception] = []

    def paused_authorization(_session: Session, _intent: NotificationDeliveryIntent) -> bool:
        authorization_entered.set()
        if not authorize_delivery.wait(timeout=10):
            raise TimeoutError("PostgreSQL delivery authorization test was not released.")
        return True

    monkeypatch.setattr(
        notification_delivery,
        "_recipient_still_permitted",
        paused_authorization,
    )

    def process_delivery() -> None:
        try:
            with Session(pg_engine) as session:
                notification_delivery.process_notification_delivery_intent(
                    session,
                    intent_id=intent_id,
                    company_id=company_id,
                )
                session.commit()
        except Exception as exc:  # pragma: no cover - surfaced in parent thread
            worker_failures.append(exc)

    worker = Thread(target=process_delivery, name="ip-delivery-lock-proof")
    worker.start()
    try:
        assert authorization_entered.wait(timeout=10), (
            "Delivery did not reach final authorization while holding the docket lock."
        )
        with Session(pg_engine) as access_change_session:
            access_change_session.execute(text("SET LOCAL lock_timeout = '250ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                access_change_session.scalar(
                    select(IpDocketRecord)
                    .where(IpDocketRecord.id == docket_id)
                    .with_for_update(of=IpDocketRecord)
                )
            access_change_session.rollback()
    finally:
        authorize_delivery.set()
        worker.join(timeout=10)

    assert not worker.is_alive(), "Delivery worker did not release the docket lock."
    assert worker_failures == []


def test_notification_convergence_backfills_boolean_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
):
    """A legacy reminder upgrades with a native PostgreSQL boolean value."""
    from alembic.config import Config

    from alembic import command
    from caseops_api.core.settings import get_settings

    url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    get_settings.cache_clear()
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)

    pg_engine.dispose()
    command.downgrade(config, "20260804_0003")

    reminder_id = str(uuid4())
    hearing_id = str(uuid4())
    scheduled_for = datetime(2099, 8, 5, 4, 30, tzinfo=UTC)
    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id)
        matter_id = _seed_matter(session, company_id)
        session.execute(
            text(
                "INSERT INTO matter_hearings "
                "(id, matter_id, hearing_on, forum_name, purpose, status, created_at) "
                "VALUES (:id, :matter_id, :hearing_on, 'Delhi High Court', "
                "'Legacy notification convergence proof', 'scheduled', :created_at)"
            ),
            {
                "id": hearing_id,
                "matter_id": matter_id,
                "hearing_on": scheduled_for.date(),
                "created_at": now,
            },
        )
        session.execute(
            text(
                "INSERT INTO hearing_reminders "
                "(id, company_id, matter_id, hearing_id, recipient_membership_id, "
                "recipient_email, channel, scheduled_for, status, attempts, "
                "created_at, updated_at) "
                "VALUES (:id, :company_id, :matter_id, :hearing_id, :membership_id, "
                "'notification-pg@example.com', 'email', :scheduled_for, 'queued', 0, "
                ":created_at, :updated_at)"
            ),
            {
                "id": reminder_id,
                "company_id": company_id,
                "matter_id": matter_id,
                "hearing_id": hearing_id,
                "membership_id": membership_id,
                "scheduled_for": scheduled_for,
                "created_at": now,
                "updated_at": now,
            },
        )
        session.commit()

    pg_engine.dispose()
    command.upgrade(config, "head")

    with pg_engine.connect() as connection:
        intent = connection.execute(
            text(
                "SELECT id, critical, destination_version, comparison_status "
                "FROM notification_delivery_intents "
                "WHERE source_type = 'hearing_reminder' AND source_id = :source_id"
            ),
            {"source_id": reminder_id},
        ).one()
        lineage_count = connection.execute(
            text(
                "SELECT count(*) FROM hearing_reminder_delivery_intents "
                "WHERE hearing_reminder_id = :reminder_id AND intent_id = :intent_id"
            ),
            {"reminder_id": reminder_id, "intent_id": intent.id},
        ).scalar_one()

    # The module contains another downgrade/re-upgrade regression. Remove this
    # isolated tenant so that a second upgrade cannot legitimately rediscover
    # the same legacy reminder and collide with its durable idempotency key.
    with pg_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM companies WHERE id = :company_id"),
            {"company_id": company_id},
        )

    assert intent.critical is True
    assert intent.destination_version == 1
    assert intent.comparison_status == "legacy_backfilled"
    assert lineage_count == 1


def test_lifecycle_migration_neutralizes_legacy_children_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
):
    """Upgrade a real legacy terminal row and prove children cannot revive."""
    from alembic.config import Config

    from alembic import command
    from caseops_api.core.settings import get_settings
    from caseops_api.db.models import (
        CalendarEventSync,
        Company,
        CompanyMembership,
        Matter,
        MatterDeadline,
        MatterHearing,
        MatterTask,
        User,
        UserCalendarConnection,
    )

    url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    get_settings.cache_clear()
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)

    company_id = str(uuid4())
    user_id = str(uuid4())
    membership_id = str(uuid4())
    matter_id = str(uuid4())
    task_id = str(uuid4())
    deadline_id = str(uuid4())
    hearing_id = str(uuid4())
    calendar_sync_id = str(uuid4())
    with Session(pg_engine) as session:
        session.add_all(
            [
                Company(
                    id=company_id,
                    name="Legacy PostgreSQL Lifecycle Firm",
                    slug=f"legacy-pg-lifecycle-{company_id[:8]}",
                    company_type="law_firm",
                    tenant_key=company_id,
                ),
                User(
                    id=user_id,
                    email=f"legacy-pg-lifecycle-{user_id[:8]}@example.com",
                    full_name="Legacy PostgreSQL Lifecycle Owner",
                    password_hash="not-used",
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                CompanyMembership(
                    id=membership_id,
                    company_id=company_id,
                    user_id=user_id,
                    role="owner",
                ),
                Matter(
                    id=matter_id,
                    company_id=company_id,
                    title="Legacy PostgreSQL closed matter",
                    matter_code=f"LEGACY-PG-{matter_id[:8].upper()}",
                    client_name="Legacy Client",
                    status="disposed",
                    practice_area="litigation",
                    forum_level="high_court",
                    is_active=False,
                    next_hearing_on=date(2099, 4, 10),
                    next_hearing_source="manual",
                    next_hearing_source_ref_type="matter_hearing",
                    next_hearing_source_ref_id=hearing_id,
                    next_hearing_manual_lock=True,
                ),
            ]
        )
        # These models are linked by scalar IDs, not in-memory relationships,
        # so SQLAlchemy has no unit-of-work edge from each child to the pending
        # Matter. Persist valid FK parents first; SQLite's permissive insert
        # ordering must not make an impossible production fixture look green.
        session.commit()
        session.add_all(
            [
                MatterTask(
                    id=task_id,
                    matter_id=matter_id,
                    title="Legacy PostgreSQL open task",
                    status="todo",
                ),
                MatterDeadline(
                    id=deadline_id,
                    matter_id=matter_id,
                    source="manual",
                    kind="filing",
                    title="Legacy PostgreSQL open deadline",
                    due_on=date(2099, 4, 9),
                    status="open",
                ),
                MatterHearing(
                    id=hearing_id,
                    matter_id=matter_id,
                    hearing_on=date(2099, 4, 10),
                    forum_name="Delhi High Court",
                    purpose="Legacy PostgreSQL open hearing",
                    status="scheduled",
                ),
            ]
        )
        session.commit()
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=membership_id,
            provider="outlook",
            status="connected",
        )
        session.add(connection)
        session.commit()
        session.add(
            CalendarEventSync(
                id=calendar_sync_id,
                company_id=company_id,
                calendar_connection_id=connection.id,
                source_type="matter_hearing",
                source_id=hearing_id,
                provider_event_id="legacy-pg-provider-event",
                sync_status="synced",
            )
        )
        session.commit()

    pg_engine.dispose()
    command.downgrade(config, "20260708_0001")
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE matters SET status = 'closed', is_active = true, "
                "next_hearing_on = '2099-04-10', next_hearing_source = 'manual', "
                "next_hearing_source_ref_type = 'matter_hearing', "
                "next_hearing_source_ref_id = :hearing_id, "
                "next_hearing_manual_lock = true WHERE id = :matter_id"
            ),
            {"hearing_id": hearing_id, "matter_id": matter_id},
        )
    pg_engine.dispose()
    command.upgrade(config, "head")

    with pg_engine.connect() as connection:
        matter_row = connection.execute(
            text(
                "SELECT status, is_active, next_hearing_on, next_hearing_source, "
                "next_hearing_source_ref_type, next_hearing_source_ref_id, "
                "next_hearing_manual_lock FROM matters WHERE id = :id"
            ),
            {"id": matter_id},
        ).one()
        task_row = connection.execute(
            text(
                "SELECT status, completed_at, cancelled_by_matter_disposal "
                "FROM matter_tasks WHERE id = :id"
            ),
            {"id": task_id},
        ).one()
        deadline_row = connection.execute(
            text(
                "SELECT status, completed_at, cancelled_by_matter_disposal "
                "FROM matter_deadlines WHERE id = :id"
            ),
            {"id": deadline_id},
        ).one()
        hearing_row = connection.execute(
            text(
                "SELECT status, cancelled_by_matter_disposal "
                "FROM matter_hearings WHERE id = :id"
            ),
            {"id": hearing_id},
        ).one()
        calendar_sync_row = connection.execute(
            text(
                "SELECT sync_status, next_attempt_at, dead_letter_reason "
                "FROM calendar_event_syncs WHERE id = :id"
            ),
            {"id": calendar_sync_id},
        ).one()

    assert tuple(matter_row) == ("disposed", False, None, "unknown", None, None, False)
    assert task_row.status == "cancelled"
    assert task_row.completed_at is not None
    assert task_row.cancelled_by_matter_disposal is True
    assert deadline_row.status == "cancelled"
    assert deadline_row.completed_at is not None
    assert deadline_row.cancelled_by_matter_disposal is True
    assert tuple(hearing_row) == ("cancelled", True)
    assert calendar_sync_row.sync_status == "delete_pending"
    assert calendar_sync_row.next_attempt_at is not None
    assert calendar_sync_row.dead_letter_reason == "matter_disposed_delete"


def test_hearing_resync_query_does_not_compare_json_columns_on_postgres(pg_engine):
    """The no-provider path must not apply DISTINCT to a JSON column."""
    from caseops_api.db.models import Company, CompanyMembership, User
    from caseops_api.services.calendar_sync import (
        resync_synced_hearing_events_for_context,
    )
    from caseops_api.services.session_context import SessionContext

    company_id = str(uuid4())
    user_id = str(uuid4())
    membership_id = str(uuid4())
    with Session(pg_engine) as session:
        company = Company(
            id=company_id,
            name="PostgreSQL Calendar Resync Firm",
            slug=f"pg-calendar-resync-{company_id[:8]}",
            company_type="law_firm",
            tenant_key=company_id,
        )
        user = User(
            id=user_id,
            email=f"pg-calendar-resync-{user_id[:8]}@example.com",
            full_name="PostgreSQL Calendar Resync Owner",
            password_hash="not-used",
        )
        membership = CompanyMembership(
            id=membership_id,
            company_id=company_id,
            user_id=user_id,
            role="owner",
        )
        session.add_all([company, user])
        session.commit()
        session.add(membership)
        session.commit()

        context = SessionContext(
            company=company,
            membership=membership,
            user=user,
        )
        assert (
            resync_synced_hearing_events_for_context(
                session,
                context=context,
                hearing_id=str(uuid4()),
            )
            == 0
        )


def test_foreign_key_indexes_exist_after_head(pg_engine):
    inspector = inspect(pg_engine)
    missing: list[tuple[str, str]] = []

    for table, column in _fk_index_pairs():
        indexes = inspector.get_indexes(table)
        if not any(index.get("column_names", [None])[0] == column for index in indexes):
            missing.append((table, column))

    assert not missing, f"Foreign-key columns missing leading indexes: {missing}"


def test_conflict_check_trigram_indexes_exist_after_head(pg_engine):
    expected = {
        "ix_clients_name_trgm",
        "ix_matters_client_name_trgm",
        "ix_matters_opposing_party_trgm",
    }
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname, indexdef "
                "FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND indexname = ANY(:names)"
            ),
            {"names": list(expected)},
        ).mappings()
        indexes = {str(row["indexname"]): str(row["indexdef"]) for row in rows}

    assert set(indexes) == expected
    for indexdef in indexes.values():
        assert "USING gin" in indexdef
        assert "gin_trgm_ops" in indexdef
        assert "lower(" in indexdef


def test_authority_structured_search_trigram_indexes_exist_after_head(pg_engine):
    expected = {
        "ix_authority_documents_citation_trgm",
        "ix_authority_documents_party_trgm",
        "ix_authority_documents_name_prefilter_trgm",
        "ix_authority_documents_court_name_trgm",
        "ix_authority_documents_judge_trgm",
        "ix_authority_documents_act_section_trgm",
    }
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname, indexdef "
                "FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND indexname = ANY(:names)"
            ),
            {"names": list(expected)},
        ).mappings()
        indexes = {str(row["indexname"]): str(row["indexdef"]) for row in rows}

    assert set(indexes) == expected
    for indexdef in indexes.values():
        assert "USING gin" in indexdef
        assert "gin_trgm_ops" in indexdef


def test_authority_exact_name_prefilter_matches_party_tokens_on_postgres(pg_engine):
    from caseops_api.services.authorities import _exact_name_match_document_ids

    doc_id = str(uuid4())
    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        session.execute(
            text(
                "INSERT INTO authority_documents "
                "(id, source, adapter_name, court_name, forum_level, document_type, "
                "title, canonical_key, summary, extracted_char_count, parties_json, "
                "bench_name, ingested_at, created_at, updated_at) "
                "VALUES (:id, 'pg-test', 'pg-test-adapter', 'Delhi High Court', "
                "'high_court', 'judgment', 'Acme Logistics v Kumar', :key, "
                "'Summary', 7, :parties, 'Commercial Bench', :ts, :ts, :ts)"
            ),
            {
                "id": doc_id,
                "key": f"pg-test::{doc_id}",
                "parties": '["Acme Logistics", "Kumar"]',
                "ts": now,
            },
        )
        session.commit()

        matches = _exact_name_match_document_ids(
            session,
            query="Acme Kumar",
            forum_level="high_court",
            court_name="Delhi High Court",
            document_type="judgment",
            limit=10,
        )
        court_misses = _exact_name_match_document_ids(
            session,
            query="Acme Kumar",
            forum_level="high_court",
            court_name="Bombay High Court",
            document_type="judgment",
            limit=10,
        )

    assert doc_id in matches
    assert doc_id not in court_misses


def test_pgvector_extension_and_hnsw_index_work(pg_engine):
    """Prove pgvector + HNSW + cosine distance round-trip on the same
    PG instance the corpus uses. No caseops table needed — we create
    a throwaway temp table so this test is hermetic.
    """
    with pg_engine.begin() as conn:
        ext = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        ).scalar()
        assert ext is not None, "pgvector extension must be installed"
        # Create a temp table — auto-dropped at session end.
        conn.execute(text("CREATE TEMP TABLE pg_aq005_vec_test (id int PRIMARY KEY, v vector(3))"))
        conn.execute(
            text(
                "INSERT INTO pg_aq005_vec_test (id, v) VALUES "
                "(1, '[1.0, 0.0, 0.0]'), "
                "(2, '[0.0, 1.0, 0.0]'), "
                "(3, '[0.95, 0.05, 0.0]')"
            )
        )
        # HNSW index — same shape as production
        conn.execute(text("CREATE INDEX ON pg_aq005_vec_test USING hnsw (v vector_cosine_ops)"))
        # Cosine-distance nearest-neighbour to [1,0,0]: id=1 first,
        # id=3 second, id=2 last.
        rows = conn.execute(
            text("SELECT id FROM pg_aq005_vec_test ORDER BY v <=> '[1.0, 0.0, 0.0]' LIMIT 3")
        ).fetchall()
        assert [r[0] for r in rows] == [1, 3, 2]


def test_portal_user_fk_set_null_on_delete_propagates(pg_engine):
    """C-3 schema: matter_attachments.submitted_by_portal_user_id is
    `ON DELETE SET NULL`. Insert a row with the FK set, delete the
    parent PortalUser, verify the FK is nulled (not cascaded).
    SQLite silently ignores ON DELETE without per-session PRAGMA;
    this is the only place we prove it on prod-shaped Postgres.
    """
    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))
        # Above call commits via transaction; reload session pattern
        # is awkward — use raw text for this small test.
        matter_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matters "
                "(id, company_id, title, matter_code, client_name, status, "
                "practice_area, forum_level, is_active, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', true, false, :ts, :ts)"
            ),
            {
                "id": matter_id,
                "co": company_id,
                "code": f"PG-{matter_id[:6]}",
                "ts": datetime.now(UTC),
            },
        )
        pu_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO portal_users "
                "(id, company_id, email, full_name, role, is_active, "
                "created_at) "
                "VALUES (:id, :co, :em, 'PU', 'outside_counsel', true, :ts)"
            ),
            {
                "id": pu_id,
                "co": company_id,
                "em": f"pu-{pu_id[:6]}@x.example",
                "ts": datetime.now(UTC),
            },
        )
        att_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matter_attachments "
                "(id, matter_id, submitted_by_portal_user_id, "
                "original_filename, storage_key, size_bytes, sha256_hex, "
                "processing_status, extracted_char_count, created_at) "
                "VALUES (:id, :m, :pu, 'a.pdf', :sk, 0, "
                "'0000000000000000000000000000000000000000000000000000000000000000', "
                "'pending', 0, :ts)"
            ),
            {
                "id": att_id,
                "m": matter_id,
                "pu": pu_id,
                "sk": f"k/{att_id}",
                "ts": datetime.now(UTC),
            },
        )

    # Verify FK is set BEFORE delete
    with pg_engine.connect() as conn:
        before = conn.execute(
            text("SELECT submitted_by_portal_user_id FROM matter_attachments WHERE id = :id"),
            {"id": att_id},
        ).scalar()
        assert before == pu_id

    # Delete the portal_user
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM portal_users WHERE id = :id"), {"id": pu_id})

    # FK should now be NULL (SET NULL behavior)
    with pg_engine.connect() as conn:
        after = conn.execute(
            text("SELECT submitted_by_portal_user_id FROM matter_attachments WHERE id = :id"),
            {"id": att_id},
        ).scalar()
    assert after is None, (
        f"Expected FK SET NULL after parent delete, got {after}. "
        "ON DELETE SET NULL is not enforced — schema bug."
    )


def test_jsonb_column_roundtrip_preserves_nested_dict(pg_engine):
    """SQLAlchemy `JSON` column maps to JSONB on PG. Verify a nested
    dict survives the roundtrip with the same structure (not stringified)."""
    import json as _json

    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))
        matter_id = str(uuid4())
        payload = {"facts": ["a", "b"], "score": 0.42, "nested": {"k": "v"}}
        conn.execute(
            text(
                "INSERT INTO matters "
                "(id, company_id, title, matter_code, client_name, status, "
                "practice_area, forum_level, is_active, restricted_access, "
                "executive_summary_json, created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', true, false, CAST(:j AS json), :ts, :ts)"
            ),
            {
                "id": matter_id,
                "co": company_id,
                "code": f"PGJ-{matter_id[:6]}",
                "j": _json.dumps(payload),
                "ts": datetime.now(UTC),
            },
        )

    with pg_engine.connect() as conn:
        got = conn.execute(
            text("SELECT executive_summary_json FROM matters WHERE id = :id"),
            {"id": matter_id},
        ).scalar()
    # psycopg returns a dict for JSON/JSONB columns
    assert got == payload, f"JSON roundtrip mismatch: {got!r}"


def test_unique_constraint_on_invoice_line_item_time_entry(pg_engine):
    """matter_invoice_line_items has UniqueConstraint(time_entry_id).
    Two rows with the same non-null time_entry_id must trigger
    IntegrityError on the second insert.
    """
    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))
        matter_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matters "
                "(id, company_id, title, matter_code, client_name, status, "
                "practice_area, forum_level, is_active, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', true, false, :ts, :ts)"
            ),
            {
                "id": matter_id,
                "co": company_id,
                "code": f"PGI-{matter_id[:6]}",
                "ts": datetime.now(UTC),
            },
        )
        invoice_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matter_invoices "
                "(id, company_id, matter_id, invoice_number, status, currency, "
                "subtotal_amount_minor, tax_amount_minor, total_amount_minor, "
                "amount_received_minor, balance_due_minor, issued_on, "
                "created_at, updated_at) "
                "VALUES (:id, :co, :m, :no, 'needs_review', 'INR', "
                "0, 0, 0, 0, 0, :d, :ts, :ts)"
            ),
            {
                "id": invoice_id,
                "co": company_id,
                "m": matter_id,
                "no": f"PG-{invoice_id[:6]}",
                "d": date.today(),
                "ts": datetime.now(UTC),
            },
        )
        time_entry_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matter_time_entries "
                "(id, matter_id, work_date, description, duration_minutes, "
                "billable, rate_currency, total_amount_minor, created_at) "
                "VALUES (:id, :m, :d, 'work', 60, true, 'INR', 0, :ts)"
            ),
            {
                "id": time_entry_id,
                "m": matter_id,
                "d": date.today(),
                "ts": datetime.now(UTC),
            },
        )
        conn.execute(
            text(
                "INSERT INTO matter_invoice_line_items "
                "(id, invoice_id, time_entry_id, description, "
                "line_total_amount_minor, created_at) "
                "VALUES (:id, :inv, :te, 'first', 1000, :ts)"
            ),
            {
                "id": str(uuid4()),
                "inv": invoice_id,
                "te": time_entry_id,
                "ts": datetime.now(UTC),
            },
        )

    # Second insert with the same time_entry_id must fail
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO matter_invoice_line_items "
                    "(id, invoice_id, time_entry_id, description, "
                    "line_total_amount_minor, created_at) "
                    "VALUES (:id, :inv, :te, 'second', 1000, :ts)"
                ),
                {
                    "id": str(uuid4()),
                    "inv": invoice_id,
                    "te": time_entry_id,
                    "ts": datetime.now(UTC),
                },
            )


def test_unique_tenant_key_blocks_cross_tenant_collisions(pg_engine):
    """AQ-005 expansion (2026-04-28) — `companies.tenant_key` is the
    cornerstone of tenant isolation. Inserting two companies with the
    same tenant_key must be rejected by Postgres at the unique-index
    layer, not just by application code. SQLite would also reject it,
    but with looser semantics (NULL/case handling); only Postgres
    proves the production guarantee.
    """
    shared_tenant_key = str(uuid4())
    with pg_engine.begin() as conn:
        # First insert succeeds.
        conn.execute(
            text(
                "INSERT INTO companies "
                "(id, name, slug, company_type, tenant_key, is_active, "
                "timezone, created_at) "
                "VALUES (:id, :n, :s, 'law_firm', :tk, true, :tz, :ts)"
            ),
            {
                "id": str(uuid4()),
                "n": "Tenant key uniqueness test A",
                "s": f"tk-test-a-{shared_tenant_key[:8]}",
                "tk": shared_tenant_key,
                "tz": "Asia/Kolkata",
                "ts": datetime.now(UTC),
            },
        )

    # Second insert with the same tenant_key MUST raise IntegrityError.
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO companies "
                    "(id, name, slug, company_type, tenant_key, is_active, "
                    "timezone, created_at) "
                    "VALUES (:id, :n, :s, 'law_firm', :tk, true, :tz, :ts)"
                ),
                {
                    "id": str(uuid4()),
                    "n": "Tenant key uniqueness test B",
                    "s": f"tk-test-b-{shared_tenant_key[:8]}",
                    "tk": shared_tenant_key,
                    "tz": "Asia/Kolkata",
                    "ts": datetime.now(UTC),
                },
            )


def test_oc_cross_visibility_server_default_inserts_false(pg_engine):
    """C-3c added oc_cross_visibility_enabled with
    server_default=false(). Insert a matter row WITHOUT supplying that
    column and verify it lands as False (not NULL, not True).
    """
    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))
        matter_id = str(uuid4())
        # Do NOT include oc_cross_visibility_enabled in the column list.
        conn.execute(
            text(
                "INSERT INTO matters "
                "(id, company_id, title, matter_code, client_name, status, "
                "practice_area, forum_level, is_active, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', true, false, :ts, :ts)"
            ),
            {
                "id": matter_id,
                "co": company_id,
                "code": f"PGD-{matter_id[:6]}",
                "ts": datetime.now(UTC),
            },
        )

    with pg_engine.connect() as conn:
        v = conn.execute(
            text("SELECT oc_cross_visibility_enabled FROM matters WHERE id = :id"),
            {"id": matter_id},
        ).scalar()
    assert v is False, (
        f"Expected server_default=false to land False, got {v!r}. "
        "Migration 20260424_0002 server_default may not have applied."
    )


def test_shared_outbox_skip_locked_claims_are_disjoint_on_postgres(pg_engine):
    """Concurrent drainers skip a locked event instead of double-claiming it."""
    from datetime import timedelta

    from caseops_api.services.domain_outbox import claim_outbox_events
    now = datetime(2026, 8, 12, 6, 30, tzinfo=UTC)
    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        for index in range(2):
            _enqueue_shared_lifecycle_event(
                seed,
                company_id=company_id,
                event_key=f"postgres-skip-locked-{uuid4()}",
                aggregate_id=f"fixture-{index}",
                now=now,
            )
        seed.commit()

    first_session = Session(pg_engine)
    second_session = Session(pg_engine)
    try:
        first = claim_outbox_events(
            first_session,
            company_id=company_id,
            lease_owner="postgres-worker-a",
            limit=1,
            lease_for=timedelta(minutes=5),
            now=now,
        )
        # Keep the first transaction open so its row lock remains live.
        second = claim_outbox_events(
            second_session,
            company_id=company_id,
            lease_owner="postgres-worker-b",
            limit=1,
            lease_for=timedelta(minutes=5),
            now=now,
        )
        assert len(first) == len(second) == 1
        assert first[0].event_id != second[0].event_id
        first_session.commit()
        second_session.commit()
    finally:
        first_session.close()
        second_session.close()


def test_workflow_definition_identity_is_immutable_on_postgres(pg_engine):
    """Published-version semantics cannot be rewritten through the definition row."""
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        session.commit()

    definition_id = str(uuid4())
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ip_workflow_definitions "
                "(id, company_id, key, name, initial_state) VALUES "
                "(:id, :company_id, 'postgres-retained', 'Postgres retained', 'draft')"
            ),
            {"id": definition_id, "company_id": company_id},
        )
        connection.execute(
            text(
                "UPDATE ip_workflow_definitions SET name = 'Renamed retained' "
                "WHERE id = :id"
            ),
            {"id": definition_id},
        )

    with pytest.raises(DBAPIError, match="definition identity is immutable"):
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ip_workflow_definitions SET initial_state = 'rewritten' "
                    "WHERE id = :id"
                ),
                {"id": definition_id},
            )


def test_shared_reliability_downgrade_lock_excludes_postgres_writer(pg_engine):
    """The fail-closed empty check owns exclusive locks before inspecting rows."""

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260812_0001_shared_reliability_foundation.py"
    )
    spec = importlib.util.spec_from_file_location(migration_path.stem, migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    now = datetime(2026, 8, 12, 6, 45, tzinfo=UTC)
    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        seed.commit()

    writer_started = Event()
    record_id = str(uuid4())

    def insert_evidence() -> None:
        writer_started.set()
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO api_idempotency_records "
                    "(id, company_id, actor_scope, http_method, operation, "
                    "idempotency_key, request_hash, state, claim_token, "
                    "claim_generation, claim_expires_at, expires_at, created_at, "
                    "updated_at) VALUES "
                    "(:id, :company_id, 'system:downgrade-lock', 'POST', "
                    "'fixture.downgrade-lock', :key, :request_hash, 'processing', "
                    "'fixture-claim', 1, :claim_expires_at, :expires_at, "
                    ":created_at, :created_at)"
                ),
                {
                    "id": record_id,
                    "company_id": company_id,
                    "key": f"downgrade-lock-{record_id}",
                    "request_hash": "d" * 64,
                    "claim_expires_at": now.replace(minute=50),
                    "expires_at": now.replace(day=19),
                    "created_at": now,
                },
            )

    with pg_engine.connect() as lock_connection:
        transaction = lock_connection.begin()
        migration._lock_tables_for_populated_downgrade_check(lock_connection)
        with ThreadPoolExecutor(max_workers=1) as executor:
            writer = executor.submit(insert_evidence)
            assert writer_started.wait(timeout=5)
            with pytest.raises(FutureTimeoutError):
                writer.result(timeout=0.25)
            transaction.rollback()
            writer.result(timeout=5)

    with Session(pg_engine) as session:
        assert session.scalar(
            text("SELECT count(*) FROM api_idempotency_records WHERE id = :id"),
            {"id": record_id},
        ) == 1


def test_shared_reliability_actual_postgres_downgrade_refuses_evidence(pg_engine):
    """Alembic itself must leave revision 0001 installed once evidence exists."""

    from alembic.config import Config

    from alembic import command

    url = os.environ["CASEOPS_TEST_POSTGRES_URL"]
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    with pg_engine.connect() as connection:
        installed_revision = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    now = datetime(2026, 8, 12, 6, 55, tzinfo=UTC)
    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        record_id = str(uuid4())
        seed.execute(
            text(
                "INSERT INTO api_idempotency_records "
                "(id, company_id, actor_scope, http_method, operation, "
                "idempotency_key, request_hash, state, claim_token, "
                "claim_generation, claim_expires_at, expires_at, created_at, "
                "updated_at) VALUES "
                "(:id, :company_id, 'system:actual-downgrade', 'POST', "
                "'fixture.actual-downgrade', :key, :request_hash, 'processing', "
                "'fixture-claim', 1, :claim_expires_at, :expires_at, "
                ":created_at, :created_at)"
            ),
            {
                "id": record_id,
                "company_id": company_id,
                "key": f"actual-downgrade-{record_id}",
                "request_hash": "e" * 64,
                "claim_expires_at": now + timedelta(minutes=5),
                "expires_at": now + timedelta(days=7),
                "created_at": now,
            },
        )
        seed.commit()

    with pytest.raises(RuntimeError, match="roll application code forward"):
        command.downgrade(config, "20260811_0005")

    with pg_engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == installed_revision
        assert connection.scalar(
            text("SELECT count(*) FROM api_idempotency_records WHERE id = :id"),
            {"id": record_id},
        ) == 1


def test_shared_outbox_fence_rejects_stale_worker_on_postgres(pg_engine):
    from datetime import timedelta

    from caseops_api.db.models import DomainOutboxEvent, DomainOutboxState
    from caseops_api.services.domain_outbox import (
        StaleOutboxLeaseError,
        claim_consumer_effect,
        claim_outbox_events,
        complete_consumer_effect,
        complete_outbox_event,
    )

    now = datetime(2026, 8, 12, 7, 0, tzinfo=UTC)
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        event = _enqueue_shared_lifecycle_event(
            session,
            company_id=company_id,
            event_key=f"postgres-fence-{uuid4()}",
            aggregate_id="fenced-fixture",
            now=now,
        ).event
        session.commit()
        event_id = event.id

    with Session(pg_engine) as session:
        old_claim = claim_outbox_events(
            session,
            company_id=company_id,
            lease_owner="postgres-old-worker",
            limit=1,
            lease_for=timedelta(seconds=1),
            now=now,
        )[0]
        session.commit()

    with Session(pg_engine) as session:
        new_claim = claim_outbox_events(
            session,
            company_id=company_id,
            lease_owner="postgres-new-worker",
            limit=1,
            lease_for=timedelta(minutes=5),
            now=now + timedelta(seconds=2),
        )[0]
        assert new_claim.event_id == event_id
        assert new_claim.fence_version == old_claim.fence_version + 1
        session.commit()

    with Session(pg_engine) as session:
        with pytest.raises(StaleOutboxLeaseError):
            complete_outbox_event(
                session,
                claim=old_claim,
                now=now + timedelta(seconds=3),
            )
        session.rollback()

    with Session(pg_engine) as session:
        for consumer_name in (
            "ip-portfolio-projection",
            "notification-intent-adapter",
            "operational-deadline-projection",
        ):
            effect_claim = claim_consumer_effect(
                session,
                outbox_claim=new_claim,
                consumer_name=consumer_name,
                consumer_version="v1",
                effect_key=f"postgres-fence:{consumer_name}",
                lease_owner="postgres-new-worker",
                now=now + timedelta(seconds=3),
            )
            complete_consumer_effect(
                session,
                outbox_claim=new_claim,
                effect_id=effect_claim.effect.id,
                effect_lease_token=str(effect_claim.lease_token),
                effect_fence_version=int(effect_claim.fence_version or 0),
                now=now + timedelta(seconds=3),
            )
        completed = complete_outbox_event(
            session,
            claim=new_claim,
            now=now + timedelta(seconds=3),
        )
        assert completed.state == DomainOutboxState.SUCCEEDED
        session.commit()
        stored = session.get(DomainOutboxEvent, event_id)
        assert stored is not None
        assert stored.fence_version == new_claim.fence_version

    with pytest.raises(DBAPIError, match="envelope is immutable"):
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE domain_outbox_events SET aggregate_version = "
                    "aggregate_version + 1 WHERE id = :event_id"
                ),
                {"event_id": event_id},
            )


def test_shared_reliability_company_fk_and_transaction_rollback_on_postgres(
    pg_engine,
):
    from datetime import timedelta

    from sqlalchemy import func, select

    from caseops_api.db.models import DomainConsumerEffect, DomainOutboxEvent
    from caseops_api.services.domain_outbox import claim_outbox_events
    from caseops_api.services.idempotency import canonical_request_hash, claim_idempotency

    now = datetime(2026, 8, 12, 7, 30, tzinfo=UTC)
    rolled_back_key = f"postgres-rollback-{uuid4()}"
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        _enqueue_shared_lifecycle_event(
            session,
            company_id=company_id,
            event_key=rolled_back_key,
            aggregate_id="rollback-fixture",
            now=now,
        )
        claim_idempotency(
            session,
            company_id=company_id,
            actor_scope="system:postgres-rollback",
            http_method="POST",
            operation="fixture.rollback",
            idempotency_key=rolled_back_key,
            request_hash=canonical_request_hash({"rolled_back": True}),
            now=now,
        )
        session.rollback()

    with Session(pg_engine) as session:
        assert session.scalar(
            select(func.count()).select_from(DomainOutboxEvent).where(
                DomainOutboxEvent.event_key == rolled_back_key
            )
        ) == 0
        from caseops_api.db.models import ApiIdempotencyRecord

        assert session.scalar(
            select(func.count()).select_from(ApiIdempotencyRecord).where(
                ApiIdempotencyRecord.idempotency_key == rolled_back_key
            )
        ) == 0
        company_a = _seed_company(session)
        company_b = _seed_company(session)
        membership_a = _seed_membership(session, company_a)
        event = _enqueue_shared_lifecycle_event(
            session,
            company_id=company_a,
            event_key=f"postgres-company-fk-{uuid4()}",
            aggregate_id="company-fk-fixture",
            now=now,
        ).event
        session.commit()
        event_id = event.id

    with Session(pg_engine) as session:
        claim = claim_outbox_events(
            session,
            company_id=company_a,
            lease_owner="postgres-company-worker",
            limit=1,
            lease_for=timedelta(minutes=5),
            now=now,
        )[0]
        assert claim.event_id == event_id
        session.commit()

    with pytest.raises(IntegrityError):
        with Session(pg_engine) as session:
            session.add(
                DomainConsumerEffect(
                    company_id=company_b,
                    outbox_event_id=event_id,
                    consumer_name="cross-company-fixture",
                    consumer_version="v1",
                    effect_key=f"cross-company-{uuid4()}",
                    state="processing",
                    attempts=1,
                    outbox_fence_version=1,
                    lease_owner="postgres-company-worker",
                    lease_token=uuid4().hex,
                    lease_expires_at=now + timedelta(minutes=5),
                    fence_version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

    with pytest.raises(IntegrityError):
        with pg_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM companies WHERE id = :company_id"),
                {"company_id": company_a},
            )

    with pytest.raises(IntegrityError):
        with Session(pg_engine) as session:
            claim_idempotency(
                session,
                company_id=company_b,
                actor_scope=f"membership:{membership_a}",
                actor_membership_id=membership_a,
                http_method="POST",
                operation="fixture.cross-company",
                idempotency_key=f"cross-company-{uuid4()}",
                request_hash=canonical_request_hash({"company": "b"}),
                now=now,
            )
            session.commit()


def test_records_governance_guards_reject_real_postgres_mutations(pg_engine):
    """IPLF-028A's fail-closed constraints must hold on the production dialect."""
    from caseops_api.db.models import (
        DataRetentionPolicy,
        DataRetentionPolicyVersion,
        LegalHold,
        LegalHoldItem,
        TenantDataOperation,
        TenantDataOperationItem,
    )

    now = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        requester_membership_id = _seed_membership(session, company_id)
        approver_membership_id = _seed_membership(session, company_id)
        policy = DataRetentionPolicy(
            company_id=company_id,
            key=f"pg-foundation-{uuid4()}",
            name="Postgres foundation policy",
        )
        session.add(policy)
        session.flush()
        policy_version = DataRetentionPolicyVersion(
            company_id=company_id,
            policy_id=policy.id,
            version=1,
            status="candidate",
            data_class_selector_json=["legal_holds"],
            purpose="Postgres regression fixture",
            legal_policy_basis="fixture-only",
            sensitivity="confidential",
            retention_days=365,
            disposition="hold_aware",
            hold_behavior="preserve",
            policy_hash="a" * 64,
            proposed_by_membership_id=requester_membership_id,
            proposed_by_membership_company_id=company_id,
            proposer_label_snapshot="Postgres requester",
            created_at=now,
        )
        hold = LegalHold(
            company_id=company_id,
            key=f"pg-hold-{uuid4()}",
            title="Postgres hold fixture",
            authority_reference="fixture://postgres-hold",
            status="draft",
            created_by_membership_id=requester_membership_id,
            created_by_membership_company_id=company_id,
            creator_label_snapshot="Postgres requester",
            created_at=now,
            updated_at=now,
        )
        session.add_all([policy_version, hold])
        session.flush()
        hold_item = LegalHoldItem(
            company_id=company_id,
            legal_hold_id=hold.id,
            data_class_id="legal_holds",
            target_type="tenant",
            target_reference_hash="b" * 64,
            created_at=now,
        )
        operation = TenantDataOperation(
            company_id=company_id,
            operation_type="tenant_export",
            execution_mode="dry_run",
            status="dry_run_complete",
            approval_status="not_requested",
            request_scope_json={"schema_version": 1, "fixture": "postgres"},
            request_scope_hash="c" * 64,
            request_evidence_ref="fixture://postgres-dry-run",
            retention_policy_version_id=policy_version.id,
            manifest_json={"schema_version": 1, "safe_to_execute": False},
            manifest_hash="d" * 64,
            requested_by_membership_id=requester_membership_id,
            requested_by_membership_company_id=company_id,
            requester_label_snapshot="Postgres requester",
            dry_run_completed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(operation)
        session.flush()
        operation_item = TenantDataOperationItem(
            company_id=company_id,
            operation_id=operation.id,
            data_class_id="legal_holds",
            target_type="tenant",
            target_reference_hash="e" * 64,
            item_status="eligible",
            candidate_record_count=0,
            estimated_bytes=0,
            safe_to_execute=False,
            created_at=now,
        )
        session.add_all([hold_item, operation_item])
        session.flush()
        policy_version_id = policy_version.id
        hold_id = hold.id
        hold_item_id = hold_item.id
        operation_id = operation.id
        operation_item_id = operation_item.id
        session.commit()

    with pytest.raises(DBAPIError, match="manifest is immutable"):
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tenant_data_operations SET execution_mode = 'execute' "
                    "WHERE id = :operation_id"
                ),
                {"operation_id": operation_id},
            )
    with pytest.raises(DBAPIError, match="manifest is immutable"):
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tenant_data_operations SET manifest_hash = :manifest_hash "
                    "WHERE id = :operation_id"
                ),
                {"operation_id": operation_id, "manifest_hash": "f" * 64},
            )
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE legal_holds SET status = 'active' "
                    "WHERE id = :hold_id"
                ),
                {"hold_id": hold_id},
            )

    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE legal_holds SET status = 'active', "
                "approved_by_membership_id = :approver_membership_id, "
                "approved_by_membership_company_id = :company_id, "
                "approver_label_snapshot = 'Postgres approver', activated_at = :activated_at "
                "WHERE id = :hold_id"
            ),
            {
                "approver_membership_id": approver_membership_id,
                "company_id": company_id,
                "activated_at": now,
                "hold_id": hold_id,
            },
        )
        connection.execute(
            text(
                "UPDATE data_retention_versions SET status = 'approved' "
                "WHERE id = :policy_version_id"
            ),
            {"policy_version_id": policy_version_id},
        )

    with pytest.raises(DBAPIError, match="Legal hold state cannot reopen"):
        with pg_engine.begin() as connection:
            connection.execute(
                text("UPDATE legal_holds SET status = 'draft' WHERE id = :hold_id"),
                {"hold_id": hold_id},
            )
    with pytest.raises(DBAPIError, match="Legal hold scope is immutable"):
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE legal_hold_items SET target_type = 'matter' "
                    "WHERE id = :hold_item_id"
                ),
                {"hold_item_id": hold_item_id},
            )
    with pytest.raises(DBAPIError, match="Published retention policy terms are immutable"):
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE data_retention_versions SET purpose = 'rewritten' "
                    "WHERE id = :policy_version_id"
                ),
                {"policy_version_id": policy_version_id},
            )
    with pytest.raises(DBAPIError, match="Tenant data-operation items are immutable"):
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tenant_data_operation_items SET item_status = 'blocked' "
                    "WHERE id = :operation_item_id"
                ),
                {"operation_item_id": operation_item_id},
            )


def test_notice_tenant_constraints_and_delete_policy_on_postgres(pg_engine):
    """Production DB must reject tenant drift and notice globalization."""
    with Session(pg_engine) as session:
        company_a = _seed_company(session)
        company_b = _seed_company(session)
        membership_a = _seed_membership(session, company_a)
        membership_b = _seed_membership(session, company_b)
        matter_a = _seed_matter(session, company_a)
        matter_b = _seed_matter(session, company_b)
        notice_a = _seed_notice(session, company_a, membership_a)
        session.execute(
            text(
                "INSERT INTO company_notice_matter_links "
                "(id, company_id, notice_id, matter_id, created_at) "
                "VALUES (:id, :company, :notice, :matter, :ts)"
            ),
            {
                "id": str(uuid4()),
                "company": company_a,
                "notice": notice_a,
                "matter": matter_a,
                "ts": datetime.now(UTC),
            },
        )
        session.commit()

    for overrides in (
        {"owner": membership_b},
        {"creator": membership_b},
        {"creator": None},
    ):
        with pytest.raises(IntegrityError):
            with Session(pg_engine) as session:
                _seed_notice(session, company_a, membership_a, **overrides)
                session.commit()

    invalid_links = (
        (company_a, notice_a, matter_b),
        (company_b, notice_a, matter_b),
    )
    for company_id, notice_id, matter_id in invalid_links:
        with pytest.raises(IntegrityError):
            with pg_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO company_notice_matter_links "
                        "(id, company_id, notice_id, matter_id, created_at) "
                        "VALUES (:id, :company, :notice, :matter, :ts)"
                    ),
                    {
                        "id": str(uuid4()),
                        "company": company_id,
                        "notice": notice_id,
                        "matter": matter_id,
                        "ts": datetime.now(UTC),
                    },
                )

    with pytest.raises(IntegrityError):
        with pg_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM matters WHERE id = :id"),
                {"id": matter_a},
            )
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM company_memberships WHERE id = :id"),
                {"id": membership_a},
            )


def test_notice_direction_and_reply_checks_on_postgres(pg_engine):
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id)
        session.commit()

    invalid_states = (
        {
            "direction": "received",
            "received_on": None,
            "received_from": None,
            "sent_on": date(2026, 7, 15),
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "sent",
            "received_on": date(2026, 7, 15),
            "received_from": None,
            "sent_on": None,
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "sent",
            "received_on": None,
            "received_from": "Invalid sender",
            "sent_on": None,
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "sent",
            "received_on": None,
            "received_from": None,
            "sent_on": date(2026, 7, 15),
            "reply_due_on": None,
            "reply_required": True,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "received",
            "received_on": date(2026, 7, 15),
            "received_from": None,
            "sent_on": None,
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": True,
            "reply_sent_on": None,
        },
        {
            "direction": "received",
            "received_on": date(2026, 7, 15),
            "received_from": None,
            "sent_on": None,
            "reply_due_on": date(2026, 7, 20),
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "received",
            "received_on": date(2026, 7, 15),
            "received_from": None,
            "sent_on": None,
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": date(2026, 7, 19),
        },
    )
    statement = text(
        "INSERT INTO company_notices "
        "(id, company_id, owner_membership_id, created_by_membership_id, "
        "direction, subject, status, received_on, received_from, sent_on, "
        "reply_due_on, reply_required, reply_sent, reply_sent_on, currency, "
        "created_at, updated_at) VALUES "
        "(:id, :company, :membership, :membership, :direction, :subject, "
        "'Open', :received_on, :received_from, :sent_on, :reply_due_on, "
        ":reply_required, :reply_sent, :reply_sent_on, 'INR', :ts, :ts)"
    )
    for index, invalid_state in enumerate(invalid_states):
        with pytest.raises(IntegrityError):
            with pg_engine.begin() as connection:
                connection.execute(
                    statement,
                    {
                        "id": str(uuid4()),
                        "company": company_id,
                        "membership": membership_id,
                        "subject": f"Invalid PG notice state {index}",
                        "ts": datetime.now(UTC),
                        **invalid_state,
                    },
                )


@pytest.mark.postgres
def test_iplf039c_batch_altered_constraints_enforce_on_postgres(pg_engine):
    """IPLF-039C — the two `batch_alter_table` migrations behave on the real dialect.

    `20260815_0002` (coverage replacement decision) and `20260815_0004`
    (calendar drift) both use `op.batch_alter_table`, which exists as a SQLite
    workaround: it rebuilds the table by copy-and-move. On Postgres alembic
    takes a different path entirely, so a constraint proven under SQLite is not
    proven here.

    This asserts the constraints exist **and fire**. A constraint that exists
    but does not refuse is worse than none, because it reads as protection.
    """

    expected = {
        "ip_deadline_coverages": {
            "ck_ip_coverage_replacement_decision",
            "ck_ip_coverage_pending_has_subject",
            "ck_ip_coverage_emergency_is_time_boxed",
        },
        "calendar_event_syncs": {"ck_calendar_event_sync_drift_status"},
        "ip_docket_queues": {"ck_ip_docket_queue_has_scope"},
    }
    with pg_engine.connect() as conn:
        for table, names in expected.items():
            found = {
                row[0]
                for row in conn.execute(
                    text(
                        # cast(...) rather than `:t::regclass`: the `::` cast
                        # collides with SQLAlchemy's `:param` binding syntax.
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = cast(:t AS regclass) AND contype = 'c'"
                    ),
                    {"t": table},
                )
            }
            missing = names - found
            assert not missing, f"{table} lost check constraints on Postgres: {missing}"

        queue_owner_delete_action = conn.scalar(
            text(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conrelid = cast('ip_docket_queues' AS regclass) "
                "AND contype = 'f' "
                "AND pg_get_constraintdef(oid) LIKE "
                "'FOREIGN KEY (owner_membership_id)%'"
            )
        )
        # PostgreSQL encodes ON DELETE CASCADE as `c`. SET NULL (`n`) would
        # collide with ck_ip_docket_queue_has_scope for a personal queue.
        assert queue_owner_delete_action == "c"

    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))

    # A queue belonging to neither a team nor a member is refused.
    with pytest.raises(IntegrityError) as scope_error:
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ip_docket_queues "
                    "(id, company_id, name, filters_json, team_id, "
                    " owner_membership_id, created_by_membership_id, "
                    " created_at, updated_at) "
                    "VALUES (:id, :co, 'Orphan', '{}', NULL, NULL, NULL, :ts, :ts)"
                ),
                {"id": str(uuid4()), "co": company_id, "ts": datetime.now(UTC)},
            )
    # Name the rule, so this cannot pass on an unrelated integrity error.
    assert "ck_ip_docket_queue_has_scope" in str(scope_error.value)

    # An out-of-vocabulary drift status is refused.
    with pytest.raises(IntegrityError) as drift_error:
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO calendar_event_syncs "
                    "(id, company_id, calendar_connection_id, source_type, "
                    " source_id, sync_status, drift_status, attempts, "
                    " max_attempts, created_at, updated_at) "
                    "VALUES (:id, :co, :conn, 'matter_deadline', :src, "
                    " 'pending', 'definitely_fine', 0, 3, :ts, :ts)"
                ),
                {
                    "id": str(uuid4()),
                    "co": company_id,
                    "conn": str(uuid4()),
                    "src": str(uuid4()),
                    "ts": datetime.now(UTC),
                },
            )
    assert "ck_calendar_event_sync_drift_status" in str(drift_error.value)


@pytest.mark.postgres
def test_iplf039c_drift_status_server_default_lands_on_postgres(pg_engine):
    """`drift_status` must default to `unchecked`, never NULL.

    The column was added with `server_default="unchecked"` so pre-existing rows
    read truthfully as *not yet checked*. If the default failed to apply they
    would be NULL, and the honesty rule this slice is built on — unverified is
    never reported as verified — would be silently broken for every projection
    that existed before the migration.
    """

    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT column_default, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'calendar_event_syncs' "
                "AND column_name = 'drift_status'"
            )
        ).one()

    default, nullable = row
    assert default is not None and "unchecked" in default, (
        f"drift_status server_default did not apply on Postgres: {default!r}. "
        "Migration 20260815_0004 would leave existing projections unlabelled."
    )
    assert nullable == "NO"


@pytest.mark.postgres
def test_iplf039c_queue_name_is_unique_per_company_on_postgres(pg_engine):
    """A saved queue name cannot be shadowed inside one workspace.

    Composite UNIQUE has looser NULL semantics on SQLite, so per-tenant
    uniqueness is only meaningfully proven here. The second half matters as
    much as the first: the name must stay free in a *different* workspace, so
    one firm cannot deny another a queue name.
    """

    def _insert_queue(company_id: str, name: str, owner_id: str) -> None:
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ip_docket_queues "
                    "(id, company_id, name, filters_json, team_id, "
                    " owner_membership_id, created_by_membership_id, "
                    " created_at, updated_at) "
                    "VALUES (:id, :co, :name, '{}', NULL, :owner, NULL, :ts, :ts)"
                ),
                {
                    "id": str(uuid4()),
                    "co": company_id,
                    "name": name,
                    "owner": owner_id,
                    "ts": datetime.now(UTC),
                },
            )

    with pg_engine.begin() as conn:
        session = Session(bind=conn)
        company_id = _seed_company(session)
        other_company_id = _seed_company(session)
        owner_id = _seed_membership(session, company_id)
        other_owner_id = _seed_membership(session, other_company_id)

    _insert_queue(company_id, "Critical this week", owner_id)
    with pytest.raises(IntegrityError) as excinfo:
        _insert_queue(company_id, "Critical this week", owner_id)
    assert "uq_ip_docket_queue_company_name" in str(excinfo.value)

    # Per-tenant, not global.
    _insert_queue(other_company_id, "Critical this week", other_owner_id)


@pytest.mark.postgres
def test_new_ip_foreign_keys_are_tenant_matched_and_preserve_delete_actions(pg_engine):
    expected = {
        "bulk_import_jobs": {
            "fk_bulk_import_job_creator_company": (
                ["created_by_membership_id", "company_id"],
                "company_memberships",
                ["id", "company_id"],
            )
        },
        "ip_import_rows": {
            "fk_ip_import_row_created_docket_company": (
                ["created_docket_id", "company_id"],
                "ip_docket_records",
                ["id", "company_id"],
            )
        },
        "ip_docket_control_reviews": {
            "fk_ip_control_review_signer_company": (
                ["signed_off_by_membership_id", "company_id"],
                "company_memberships",
                ["id", "company_id"],
            ),
            "fk_ip_control_review_creator_company": (
                ["created_by_membership_id", "company_id"],
                "company_memberships",
                ["id", "company_id"],
            ),
        },
        "ip_deadline_coverages": {
            "fk_ip_coverage_pending_replacement_company": (
                ["pending_replacement_membership_id", "company_id"],
                "company_memberships",
                ["id", "company_id"],
            ),
            "fk_ip_coverage_emergency_escalation_company": (
                ["emergency_escalation_membership_id", "company_id"],
                "company_memberships",
                ["id", "company_id"],
            ),
        },
        "ip_docket_queues": {
            "fk_ip_docket_queue_team_company": (
                ["team_id", "company_id"],
                "teams",
                ["id", "company_id"],
            ),
            "fk_ip_docket_queue_owner_company": (
                ["owner_membership_id", "company_id"],
                "company_memberships",
                ["id", "company_id"],
            ),
            "fk_ip_docket_queue_creator_company": (
                ["created_by_membership_id", "company_id"],
                "company_memberships",
                ["id", "company_id"],
            ),
        },
        "ip_identifiers": {
            "fk_ip_identifier_supersedes_company": (
                ["supersedes_identifier_id", "company_id"],
                "ip_identifiers",
                ["id", "company_id"],
            ),
            "fk_ip_identifier_superseded_by_company": (
                ["superseded_by_identifier_id", "company_id"],
                "ip_identifiers",
                ["id", "company_id"],
            ),
        },
    }
    # pg_constraint action codes: a=NO ACTION, c=CASCADE, r=RESTRICT;
    # confmatchtype s=MATCH SIMPLE. Deferred NO ACTION companions allow the
    # original single-column SET NULL FK to null only its nullable ID.
    deferred_set_null_companions = {
        "fk_bulk_import_job_creator_company",
        "fk_ip_import_row_created_docket_company",
        "fk_ip_control_review_signer_company",
        "fk_ip_control_review_creator_company",
        "fk_ip_coverage_pending_replacement_company",
        "fk_ip_coverage_emergency_escalation_company",
        "fk_ip_docket_queue_creator_company",
    }
    cascade_companions = {
        "fk_ip_docket_queue_team_company",
        "fk_ip_docket_queue_owner_company",
    }
    restrict_constraints = {
        "fk_ip_identifier_supersedes_company",
        "fk_ip_identifier_superseded_by_company",
    }
    schema = inspect(pg_engine)
    for table, expected_by_name in expected.items():
        actual_by_name = {
            foreign_key["name"]: (
                foreign_key["constrained_columns"],
                foreign_key["referred_table"],
                foreign_key["referred_columns"],
            )
            for foreign_key in schema.get_foreign_keys(table)
            if foreign_key.get("name")
        }
        for name, shape in expected_by_name.items():
            assert actual_by_name[name] == shape

    with pg_engine.connect() as connection:
        for name in deferred_set_null_companions:
            assert connection.execute(
                text(
                    "SELECT confdeltype, condeferrable, condeferred, confmatchtype "
                    "FROM pg_constraint WHERE conname = :name"
                ),
                {"name": name},
            ).one() == ("a", True, True, "s")
        for name in cascade_companions:
            assert connection.execute(
                text(
                    "SELECT confdeltype, condeferrable, condeferred, confmatchtype "
                    "FROM pg_constraint WHERE conname = :name"
                ),
                {"name": name},
            ).one() == ("c", False, False, "s")
        for name in restrict_constraints:
            assert connection.execute(
                text(
                    "SELECT confdeltype, condeferrable, condeferred, confmatchtype "
                    "FROM pg_constraint WHERE conname = :name"
                ),
                {"name": name},
            ).one() == ("r", False, False, "s")

    with pg_engine.begin() as connection:
        session = Session(bind=connection)
        company_a = _seed_company(session)
        company_b = _seed_company(session)
        membership_a = _seed_membership(session, company_a)
        membership_b = _seed_membership(session, company_b)
        team_b = str(uuid4())
        now = datetime.now(UTC)
        connection.execute(
            text(
                "INSERT INTO teams "
                "(id, company_id, name, slug, kind, is_active, created_at, updated_at) "
                "VALUES (:id, :company, 'Foreign Team', :slug, 'team', true, :now, :now)"
            ),
            {
                "id": team_b,
                "company": company_b,
                "slug": f"foreign-team-{team_b[:8]}",
                "now": now,
            },
        )

    invalid_writes = [
        (
            "fk_bulk_import_job_creator_company",
            "INSERT INTO bulk_import_jobs "
            "(id, company_id, domain, filename, source_sha256, "
            " created_by_membership_id, creator_label_snapshot, created_at, updated_at) "
            "VALUES (:id, :company, 'ip_trademark', 'tenant.csv', :sha, "
            " :membership, 'Wrong tenant', :now, :now)",
            {
                "id": str(uuid4()),
                "company": company_a,
                "sha": "a" * 64,
                "membership": membership_b,
                "now": now,
            },
        ),
        (
            "fk_ip_control_review_signer_company",
            "INSERT INTO ip_docket_control_reviews "
            "(id, company_id, generated_at, filters_json, freshness_json, "
            " incompleteness_reasons_json, mandatory_exception_ids_json, "
            " query_version, report_snapshot_json, manifest_sha256, "
            " signed_off_by_membership_id, created_at, updated_at) "
            "VALUES (:id, :company, :now, '{}', '{}', '[]', '[]', "
            " 'daily-docket-v1', '{}', :sha, :membership, :now, :now)",
            {
                "id": str(uuid4()),
                "company": company_a,
                "membership": membership_b,
                "sha": "b" * 64,
                "now": now,
            },
        ),
        (
            "fk_ip_docket_queue_owner_company",
            "INSERT INTO ip_docket_queues "
            "(id, company_id, name, filters_json, owner_membership_id, "
            " created_at, updated_at) "
            "VALUES (:id, :company, :name, '{}', :membership, :now, :now)",
            {
                "id": str(uuid4()),
                "company": company_a,
                "name": f"Foreign owner {uuid4()}",
                "membership": membership_b,
                "now": now,
            },
        ),
        (
            "fk_ip_docket_queue_team_company",
            "INSERT INTO ip_docket_queues "
            "(id, company_id, name, filters_json, team_id, created_at, updated_at) "
            "VALUES (:id, :company, :name, '{}', :team, :now, :now)",
            {
                "id": str(uuid4()),
                "company": company_a,
                "name": f"Foreign team {uuid4()}",
                "team": team_b,
                "now": now,
            },
        ),
    ]
    for constraint_name, statement, parameters in invalid_writes:
        with pytest.raises(IntegrityError) as excinfo:
            with pg_engine.begin() as connection:
                connection.execute(text(statement), parameters)
        assert constraint_name in str(excinfo.value)

    import_id = str(uuid4())
    queue_id = str(uuid4())
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO bulk_import_jobs "
                "(id, company_id, domain, filename, source_sha256, "
                " created_by_membership_id, creator_label_snapshot, created_at, updated_at) "
                "VALUES (:id, :company, 'ip_trademark', 'valid.csv', :sha, "
                " :membership, 'Ephemeral Member', :now, :now)"
            ),
            {
                "id": import_id,
                "company": company_a,
                "sha": "c" * 64,
                "membership": membership_a,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ip_docket_queues "
                "(id, company_id, name, filters_json, owner_membership_id, "
                " created_at, updated_at) "
                "VALUES (:id, :company, :name, '{}', :membership, :now, :now)"
            ),
            {
                "id": queue_id,
                "company": company_a,
                "name": f"Ephemeral queue {queue_id[:8]}",
                "membership": membership_a,
                "now": now,
            },
        )
        connection.execute(
            text("DELETE FROM company_memberships WHERE id = :id"),
            {"id": membership_a},
        )
        assert connection.execute(
            text(
                "SELECT company_id, created_by_membership_id "
                "FROM bulk_import_jobs WHERE id = :id"
            ),
            {"id": import_id},
        ).one() == (company_a, None)
        assert connection.scalar(
            text("SELECT count(*) FROM ip_docket_queues WHERE id = :id"),
            {"id": queue_id},
        ) == 0


def test_ip_rule_governance_fingerprint_uses_real_postgres_read_only_snapshot(
    pg_engine,
) -> None:
    from caseops_api.scripts.ip_rule_governance_fingerprint import fingerprint_database

    snapshot = fingerprint_database(pg_engine)

    assert snapshot["database_context"]["dialect"] == "postgresql"
    assert snapshot["database_context"]["alembic_heads"]
    digest = snapshot["overall_sha256"]
    assert isinstance(digest, str)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")

    # The fingerprint transaction rolled back and did not leave a pooled
    # connection read-only. A fresh transaction must still permit a temp write.
    with pg_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TEMP TABLE caseops_a0_fingerprint_write_probe "
            "(value integer NOT NULL) ON COMMIT DROP"
        )
        connection.exec_driver_sql(
            "INSERT INTO caseops_a0_fingerprint_write_probe (value) VALUES (1)"
        )
        assert (
            connection.exec_driver_sql(
                "SELECT value FROM caseops_a0_fingerprint_write_probe"
            ).scalar_one()
            == 1
        )
