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
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

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


def test_ip_filing_transactions_are_append_only_on_postgres(pg_engine) -> None:
    """The production dialect must reject update, delete, and truncate paths."""

    from caseops_api.db.models import (
        CompanyMembership,
        IpAsset,
        IpDocketRecord,
        IpFilingTransaction,
        TrademarkApplication,
        User,
    )

    now = datetime.now(UTC)
    suffix = uuid4().hex
    with pg_engine.connect() as connection:
        outer_transaction = connection.begin()
        try:
            # This test runs before destructive migration probes in the same
            # module. Keep its immutable legal-evidence fixture inside a
            # rollback-only savepoint so the later schema-reset helper never
            # needs to bypass the production TRUNCATE guard.
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                company_id = _seed_company(session)
                user = User(
                    email=f"ip-filing-append-only-{suffix}@example.test",
                    full_name="IP filing append-only test",
                    password_hash="not-used",
                )
                session.add(user)
                session.flush()
                membership = CompanyMembership(
                    company_id=company_id,
                    user_id=user.id,
                    role="owner",
                )
                session.add(membership)
                session.flush()
                docket = IpDocketRecord(
                    company_id=company_id,
                    record_type="trademark",
                    title="PostgreSQL append-only filing",
                    status="draft",
                    created_by_membership_id=membership.id,
                )
                session.add(docket)
                session.flush()
                asset = IpAsset(
                    company_id=company_id,
                    docket_id=docket.id,
                    asset_kind="trademark",
                    jurisdiction="IN",
                    title="Append-only mark",
                )
                session.add(asset)
                session.flush()
                application = TrademarkApplication(
                    company_id=company_id,
                    docket_id=docket.id,
                    asset_id=asset.id,
                    office="Trade Marks Registry",
                    jurisdiction="IN",
                    filing_phase="pre_filing",
                )
                session.add(application)
                session.flush()
                transaction = IpFilingTransaction(
                    company_id=company_id,
                    docket_id=docket.id,
                    application_id=application.id,
                    transaction_kind="submitted",
                    attempt_key=f"attempt-{suffix}",
                    idempotency_key=f"idempotency-{suffix}",
                    request_fingerprint="a" * 64,
                    external_reference=f"registry:{suffix}",
                    evidence_reference=f"document:{suffix}",
                    occurred_at=now,
                    details_json={},
                    recorded_by_membership_id=membership.id,
                )
                session.add(transaction)
                session.flush()
                transaction_id = transaction.id

                mutations = (
                    (
                        "UPDATE ip_filing_transactions "
                        "SET external_reference = 'tampered' WHERE id = :transaction_id",
                        {"transaction_id": transaction_id},
                    ),
                    (
                        "DELETE FROM ip_filing_transactions WHERE id = :transaction_id",
                        {"transaction_id": transaction_id},
                    ),
                    ("TRUNCATE TABLE ip_filing_transactions", {}),
                )
                for statement, parameters in mutations:
                    mutation_savepoint = connection.begin_nested()
                    try:
                        with pytest.raises(DBAPIError, match="append-only"):
                            connection.execute(text(statement), parameters)
                    finally:
                        if mutation_savepoint.is_active:
                            mutation_savepoint.rollback()

                assert session.get(IpFilingTransaction, transaction_id) is not None
        finally:
            if outer_transaction.is_active:
                outer_transaction.rollback()

    with Session(pg_engine) as verification_session:
        assert verification_session.get(IpFilingTransaction, transaction_id) is None


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


def _seed_membership(
    session: Session,
    company_id: str,
    *,
    role: str = "member",
) -> str:
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
            "VALUES (:id, :company, :user, :role, true, :ts)"
        ),
        {
            "id": membership_id,
            "company": company_id,
            "user": user_id,
            "role": role,
            "ts": now,
        },
    )
    return membership_id


def _seed_ip_coverage_lifecycle_fixture(session: Session) -> dict[str, str]:
    """Create the smallest linked Matter -> docket -> deadline -> coverage graph."""

    from caseops_api.db.models import (
        IpDeadlineCoverage,
        IpDocketRecord,
        MatterDeadline,
        MatterDeadlineStatus,
    )

    company_id = _seed_company(session)
    owner_id = _seed_membership(session, company_id, role="admin")
    replacement_id = _seed_membership(session, company_id)
    matter_id = _seed_matter(session, company_id)
    docket = IpDocketRecord(
        company_id=company_id,
        matter_id=matter_id,
        record_type="trademark_application",
        title="PostgreSQL lifecycle coverage race",
        primary_identifier=f"PG-IP-RACE-{str(uuid4())[:8]}",
        status="ready",
        is_active=True,
        restricted=False,
        created_by_membership_id=owner_id,
    )
    deadline = MatterDeadline(
        company_id=company_id,
        matter_id=matter_id,
        source="custom",
        kind="licence_royalty",
        title="PostgreSQL coverage race deadline",
        due_on=date.today() + timedelta(days=30),
        status=MatterDeadlineStatus.OPEN,
        assignee_membership_id=owner_id,
        created_by_membership_id=owner_id,
    )
    session.add_all([docket, deadline])
    session.flush()
    coverage = IpDeadlineCoverage(
        company_id=company_id,
        docket_id=docket.id,
        matter_deadline_id=deadline.id,
        responsible_membership_id=owner_id,
        coverage_status="accepted",
        calendar_projection_status="pending",
    )
    session.add(coverage)
    session.commit()
    return {
        "company_id": company_id,
        "owner_id": owner_id,
        "replacement_id": replacement_id,
        "matter_id": matter_id,
        "docket_id": docket.id,
        "deadline_id": deadline.id,
        "coverage_id": coverage.id,
    }


def _ip_race_context(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
):
    from caseops_api.db.models import Company, CompanyMembership, User
    from caseops_api.services.session_context import SessionContext

    company = session.get(Company, company_id)
    membership = session.get(CompanyMembership, membership_id)
    assert company is not None and membership is not None
    user = session.get(User, membership.user_id)
    assert user is not None
    return SessionContext(company=company, membership=membership, user=user)


def _wait_for_postgres_lock_wait(pg_engine, *, application_name: str) -> None:
    """Wait until the named worker is blocked on a real PostgreSQL lock."""

    deadline = datetime.now(UTC) + timedelta(seconds=5)
    last_state = None
    # pg_stat_activity is dynamic control-plane state, not application data.
    # Poll outside a long-lived transaction so a reused pooled connection
    # cannot retain a stale visibility snapshot while the worker begins and
    # enters its lock wait.
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        while datetime.now(UTC) < deadline:
            last_state = connection.execute(
                text(
                    "SELECT state, wait_event_type, wait_event "
                    "FROM pg_stat_activity WHERE application_name = :name"
                ),
                {"name": application_name},
            ).mappings().first()
            if last_state is not None and last_state["wait_event_type"] == "Lock":
                return
            Event().wait(0.02)
    pytest.fail(
        f"PostgreSQL worker {application_name!r} never waited on a lock; "
        f"last state was {last_state!r}"
    )


def _prepare_postgres_destructive_migration_probe(pg_engine, alembic_config) -> None:
    """Give destructive migration probes an isolated, schema-only database.

    The PostgreSQL validation module intentionally keeps ordinary test rows
    between cases.  A downgrade probe is different: rows created by a newer
    contract can make an older migration fail before the probe has installed
    its own legacy fixture, leaving every later test on a partially downgraded
    schema.  First use the filing-evidence migration's own fail-closed downgrade
    to prove no immutable filing rows exist and remove its TRUNCATE trigger.
    Only then clear application rows while retaining ``alembic_version`` so the
    three older downgrade/upgrade tests remain independent of collection order.
    """

    from alembic import command

    pg_engine.dispose()
    command.downgrade(alembic_config, "20260830_0002")

    with pg_engine.begin() as connection:
        # Tenant fixtures all descend from one of these roots.  Keep global
        # catalog/configuration rows intact: several later migrations assume
        # the canonical forum catalog populated by earlier revisions exists.
        connection.execute(
            text("TRUNCATE TABLE companies, users RESTART IDENTITY CASCADE")
        )
    pg_engine.dispose()


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


def test_billing_account_creation_is_idempotent_under_postgres_race(pg_engine) -> None:
    from caseops_api.db.models import BillingAccount, Company
    from caseops_api.services.saas_billing import ensure_billing_account

    with Session(pg_engine) as seed_session:
        company_id = _seed_company(seed_session)
        seed_session.commit()

    first_inserted = Event()
    release_first = Event()
    second_started = Event()

    def create_account(*, hold_transaction: bool) -> str:
        with Session(pg_engine) as session:
            company = session.get(Company, company_id)
            assert company is not None
            if not hold_transaction:
                second_started.set()
            account = ensure_billing_account(session, company)
            if hold_transaction:
                first_inserted.set()
                assert release_first.wait(timeout=5)

            # Prove conflict handling left the caller's transaction usable.
            assert session.execute(text("SELECT 1")).scalar_one() == 1
            session.commit()
            return account.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(create_account, hold_transaction=True)
        assert first_inserted.wait(timeout=5)
        second = executor.submit(create_account, hold_transaction=False)
        assert second_started.wait(timeout=5)
        try:
            with pytest.raises(FutureTimeoutError):
                second.result(timeout=0.25)
        finally:
            release_first.set()
        account_ids = {first.result(timeout=5), second.result(timeout=5)}

    with Session(pg_engine) as session:
        account_count = session.query(BillingAccount).filter_by(company_id=company_id).count()
    assert account_count == 1
    assert len(account_ids) == 1


@pytest.mark.parametrize(
    "writer_kind",
    [
        "deadline_create",
        "deadline_reopen",
        "coverage_add",
        "workflow_confirm",
        "workflow_override",
    ],
)
def test_offboarding_membership_fence_rejects_late_ip_assignment_writers(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    writer_kind: str,
) -> None:
    """Offboarding wins the shared membership fence before any IP parent lock."""

    from fastapi import HTTPException

    from caseops_api.db.models import (
        CompanyMembership,
        IpDeadlineCoverage,
        IpDocketRecord,
        MatterDeadline,
        MatterDeadlineStatus,
    )
    from caseops_api.schemas.employees import EmployeeOffboardingRequest
    from caseops_api.schemas.ip_deadlines import (
        IpDeadlineConfirmRequest,
        IpDeadlineOverrideRequest,
        IpResponsibilityInput,
    )
    from caseops_api.schemas.ip_operations import IpDeadlineCoverageCreateRequest
    from caseops_api.schemas.shared_work import (
        IpOperationalDeadlineCreateRequest,
        IpOperationalDeadlineUpdateRequest,
    )
    from caseops_api.services import employees as employee_service
    from caseops_api.services.ip_deadline_workflow import (
        confirm_deadline,
        override_deadline,
    )
    from caseops_api.services.ip_operations import add_ip_deadline_coverage
    from caseops_api.services.shared_work import (
        create_ip_operational_deadline,
        update_ip_operational_deadline,
    )

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        actor_id = _seed_membership(seed, company_id)
        target_id = _seed_membership(seed, company_id)
        replacement_id = _seed_membership(seed, company_id)
        actor = seed.get(CompanyMembership, actor_id)
        assert actor is not None
        actor.role = "owner"
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title=f"PostgreSQL offboarding fence {writer_kind}",
            primary_identifier=f"PG-OFFBOARD-{str(uuid4())[:8]}",
            status="active",
            is_active=True,
            restricted=False,
            created_by_membership_id=actor_id,
        )
        seed.add(docket)
        seed.flush()
        deadline = None
        if writer_kind in {"deadline_reopen", "coverage_add"}:
            deadline = MatterDeadline(
                company_id=company_id,
                ip_docket_id=docket.id,
                source="custom",
                kind="response",
                title=f"PostgreSQL offboarding fence {writer_kind}",
                due_on=date.today() + timedelta(days=30),
                status=(
                    MatterDeadlineStatus.DONE
                    if writer_kind == "deadline_reopen"
                    else MatterDeadlineStatus.OPEN
                ),
                assignee_membership_id=(
                    target_id if writer_kind == "deadline_reopen" else replacement_id
                ),
                created_by_membership_id=actor_id,
            )
            seed.add(deadline)
            seed.flush()
        seed.commit()
        docket_id = docket.id
        deadline_id = deadline.id if deadline is not None else None

    offboarding_holds_memberships = Event()
    release_offboarding = Event()
    original_preview = employee_service._build_offboarding_preview

    def paused_preview(session, *, context, target, reassign_to):
        offboarding_holds_memberships.set()
        if not release_offboarding.wait(timeout=10):
            raise TimeoutError("Offboarding membership-fence race did not release.")
        return original_preview(
            session,
            context=context,
            target=target,
            reassign_to=reassign_to,
        )

    monkeypatch.setattr(employee_service, "_build_offboarding_preview", paused_preview)
    application_name = f"caseops-offboarding-{writer_kind}-{str(uuid4())[:8]}"

    def offboard():
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=company_id,
                membership_id=actor_id,
            )
            return employee_service.commit_employee_offboarding(
                session,
                context=context,
                membership_id=target_id,
                payload=EmployeeOffboardingRequest(
                    reassign_to_membership_id=replacement_id,
                ),
            )

    def assign_ip_work():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=company_id,
                membership_id=actor_id,
            )
            try:
                if writer_kind == "deadline_create":
                    create_ip_operational_deadline(
                        session,
                        context=context,
                        payload=IpOperationalDeadlineCreateRequest(
                            docket_id=docket_id,
                            title="Late assignment must fail",
                            due_on=date.today() + timedelta(days=45),
                            assignee_membership_id=target_id,
                        ),
                    )
                elif writer_kind == "deadline_reopen":
                    assert deadline_id is not None
                    update_ip_operational_deadline(
                        session,
                        context=context,
                        deadline_id=deadline_id,
                        payload=IpOperationalDeadlineUpdateRequest(
                            docket_id=docket_id,
                            status="open",
                        ),
                    )
                elif writer_kind == "coverage_add":
                    assert deadline_id is not None
                    add_ip_deadline_coverage(
                        session,
                        context=context,
                        docket_id=docket_id,
                        payload=IpDeadlineCoverageCreateRequest(
                            matter_deadline_id=deadline_id,
                            responsible_membership_id=target_id,
                        ),
                    )
                elif writer_kind == "workflow_confirm":
                    confirm_deadline(
                        session,
                        context=context,
                        deadline_id=str(uuid4()),
                        payload=IpDeadlineConfirmRequest(
                            expected_version=1,
                            responsibilities=[
                                IpResponsibilityInput(
                                    membership_id=target_id,
                                    role="primary",
                                    accepted=True,
                                )
                            ],
                        ),
                    )
                else:
                    override_deadline(
                        session,
                        context=context,
                        deadline_id=str(uuid4()),
                        payload=IpDeadlineOverrideRequest(
                            expected_version=1,
                            new_result_on=date.today() + timedelta(days=60),
                            reason="PostgreSQL membership-fence race",
                            evidence_reference="pg-race-evidence",
                            impact_token="unused-after-membership-fence",
                            responsibilities=[
                                IpResponsibilityInput(
                                    membership_id=target_id,
                                    role="primary",
                                    accepted=True,
                                )
                            ],
                        ),
                    )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Inactive employee unexpectedly received operational IP work.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        offboarding = executor.submit(offboard)
        writer = None
        try:
            assert offboarding_holds_memberships.wait(timeout=10)
            writer = executor.submit(assign_ip_work)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            with pytest.raises(FutureTimeoutError):
                writer.result(timeout=0.05)
        finally:
            release_offboarding.set()
        result = offboarding.result(timeout=10)
        assert writer is not None
        writer_status, _writer_detail = writer.result(timeout=10)

    assert result.deactivated is True
    assert writer_status in {400, 404}
    with Session(pg_engine) as session:
        target = session.get(CompanyMembership, target_id)
        assert target is not None and target.is_active is False
        if writer_kind == "deadline_create":
            late_deadline = session.scalar(
                select(MatterDeadline).where(
                    MatterDeadline.company_id == company_id,
                    MatterDeadline.ip_docket_id == docket_id,
                    MatterDeadline.title == "Late assignment must fail",
                )
            )
            assert late_deadline is None
        elif writer_kind == "deadline_reopen":
            persisted = session.get(MatterDeadline, deadline_id)
            assert persisted is not None
            assert persisted.status == MatterDeadlineStatus.DONE
            assert persisted.assignee_membership_id == target_id
        elif writer_kind == "coverage_add":
            coverage = session.scalar(
                select(IpDeadlineCoverage).where(
                    IpDeadlineCoverage.company_id == company_id,
                    IpDeadlineCoverage.matter_deadline_id == deadline_id,
                )
            )
            assert coverage is None
        else:
            target_coverages = list(
                session.scalars(
                    select(IpDeadlineCoverage).where(
                        IpDeadlineCoverage.company_id == company_id,
                        IpDeadlineCoverage.responsible_membership_id == target_id,
                    )
                ).all()
            )
            assert target_coverages == []


def test_ip_assignment_writer_wins_then_offboarding_reassigns_authoritative_row(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creator-first ordering is visible after offboarding waits on the member."""

    from caseops_api.db.models import CompanyMembership, IpDocketRecord, MatterDeadline
    from caseops_api.schemas.employees import EmployeeOffboardingRequest
    from caseops_api.schemas.shared_work import IpOperationalDeadlineCreateRequest
    from caseops_api.services import employees as employee_service
    from caseops_api.services import shared_work as shared_work_service

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        actor_id = _seed_membership(seed, company_id)
        target_id = _seed_membership(seed, company_id)
        replacement_id = _seed_membership(seed, company_id)
        actor = seed.get(CompanyMembership, actor_id)
        assert actor is not None
        actor.role = "owner"
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Writer-first offboarding race",
            primary_identifier=f"PG-WRITER-FIRST-{str(uuid4())[:8]}",
            status="active",
            is_active=True,
            restricted=False,
            created_by_membership_id=actor_id,
        )
        seed.add(docket)
        seed.commit()
        docket_id = docket.id

    writer_holds_fence = Event()
    release_writer = Event()
    original_record = shared_work_service.record_from_context

    def paused_record(session, context, **kwargs):
        result = original_record(session, context, **kwargs)
        if kwargs.get("action") == "shared_deadline.created":
            writer_holds_fence.set()
            if not release_writer.wait(timeout=10):
                raise TimeoutError("Writer-first offboarding race did not release.")
        return result

    monkeypatch.setattr(shared_work_service, "record_from_context", paused_record)
    application_name = f"caseops-offboarding-waits-writer-{str(uuid4())[:8]}"

    def create_deadline():
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=company_id,
                membership_id=actor_id,
            )
            return shared_work_service.create_ip_operational_deadline(
                session,
                context=context,
                payload=IpOperationalDeadlineCreateRequest(
                    docket_id=docket_id,
                    title="Writer-first deadline",
                    due_on=date.today() + timedelta(days=50),
                    assignee_membership_id=target_id,
                ),
            )

    def offboard():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=company_id,
                membership_id=actor_id,
            )
            return employee_service.commit_employee_offboarding(
                session,
                context=context,
                membership_id=target_id,
                payload=EmployeeOffboardingRequest(
                    reassign_to_membership_id=replacement_id,
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(create_deadline)
        offboarding = None
        try:
            assert writer_holds_fence.wait(timeout=10)
            offboarding = executor.submit(offboard)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
            with pytest.raises(FutureTimeoutError):
                offboarding.result(timeout=0.05)
        finally:
            release_writer.set()
        created = writer.result(timeout=10)
        assert offboarding is not None
        result = offboarding.result(timeout=10)

    assert result.deactivated is True
    assert result.preview.supported_counts["matter_deadlines"] == 1
    with Session(pg_engine) as session:
        target = session.get(CompanyMembership, target_id)
        deadline = session.get(MatterDeadline, created.id)
        assert target is not None and target.is_active is False
        assert deadline is not None
        assert deadline.assignee_membership_id == replacement_id


def test_pending_proposal_writer_wins_then_blocks_offboarding(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed auxiliary role is authoritative after offboarding waits."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, IpDeadlineCoverage
    from caseops_api.schemas.employees import EmployeeOffboardingRequest
    from caseops_api.schemas.ip_operations import (
        IpCoverageReassignPreviewRequest,
        IpCoverageReassignProposeRequest,
    )
    from caseops_api.services import employees as employee_service
    from caseops_api.services import ip_operations as ip_service

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)
        actor_id = _seed_membership(seed, fixture["company_id"])
        actor = seed.get(CompanyMembership, actor_id)
        assert actor is not None
        actor.role = "owner"
        seed.commit()

    with Session(pg_engine) as preview_session:
        context = _ip_race_context(
            preview_session,
            company_id=fixture["company_id"],
            membership_id=actor_id,
        )
        preview = ip_service.preview_ip_coverage_reassignment(
            preview_session,
            context=context,
            payload=IpCoverageReassignPreviewRequest(
                from_membership_id=fixture["owner_id"],
                to_membership_id=fixture["replacement_id"],
            ),
        )
        preview_token = preview.preview_token

    proposal_holds_fence = Event()
    release_proposal = Event()
    original_record = ip_service.record_from_context

    def paused_record(session, context, **kwargs):
        result = original_record(session, context, **kwargs)
        if kwargs.get("action") == "ip_deadline_coverage.transfer_proposed":
            proposal_holds_fence.set()
            if not release_proposal.wait(timeout=10):
                raise TimeoutError("Proposal-first offboarding race did not release.")
        return result

    monkeypatch.setattr(ip_service, "record_from_context", paused_record)
    application_name = f"caseops-offboarding-waits-proposal-{str(uuid4())[:8]}"

    def propose():
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=actor_id,
            )
            return ip_service.propose_ip_coverage_reassignment(
                session,
                context=context,
                payload=IpCoverageReassignProposeRequest(
                    from_membership_id=fixture["owner_id"],
                    to_membership_id=fixture["replacement_id"],
                    preview_token=preview_token,
                    reason="Proposal-first PostgreSQL race.",
                ),
            )

    def offboard():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=actor_id,
            )
            try:
                employee_service.commit_employee_offboarding(
                    session,
                    context=context,
                    membership_id=fixture["replacement_id"],
                    payload=EmployeeOffboardingRequest(
                        reassign_to_membership_id=actor_id,
                    ),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Pending replacement was offboarded without resolution.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        proposal = executor.submit(propose)
        offboarding = None
        try:
            assert proposal_holds_fence.wait(timeout=10)
            offboarding = executor.submit(offboard)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
            with pytest.raises(FutureTimeoutError):
                offboarding.result(timeout=0.05)
        finally:
            release_proposal.set()
        proposal.result(timeout=10)
        assert offboarding is not None
        offboarding_status, _detail = offboarding.result(timeout=10)

    assert offboarding_status == 400
    with Session(pg_engine) as session:
        target = session.get(CompanyMembership, fixture["replacement_id"])
        coverage = session.get(IpDeadlineCoverage, fixture["coverage_id"])
        assert target is not None and target.is_active is True
        assert coverage is not None
        assert coverage.pending_replacement_membership_id == fixture["replacement_id"]
        assert coverage.replacement_decision == "pending"


def test_assignment_membership_fence_sorts_reverse_id_inputs_without_deadlock(
    pg_engine,
) -> None:
    from caseops_api.services.assignment_memberships import (
        lock_company_memberships_for_assignment,
    )

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        first_id = _seed_membership(seed, company_id)
        second_id = _seed_membership(seed, company_id)
        seed.commit()
    low_id, high_id = sorted((first_id, second_id))
    first_holds_both = Event()
    release_first = Event()
    application_name = f"caseops-reverse-member-lock-{str(uuid4())[:8]}"

    def lock_pair(order: tuple[str, str], *, hold: bool, name: str | None = None):
        with Session(pg_engine) as session:
            if name is not None:
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": name},
                )
            locked = lock_company_memberships_for_assignment(
                session,
                company_id=company_id,
                membership_ids=order,
            )
            if hold:
                first_holds_both.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError("Reverse membership lock race did not release.")
            session.commit()
            return set(locked)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(lock_pair, (high_id, low_id), hold=True)
        second = None
        try:
            assert first_holds_both.wait(timeout=10)
            second = executor.submit(
                lock_pair,
                (low_id, high_id),
                hold=False,
                name=application_name,
            )
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_first.set()
        assert first.result(timeout=10) == {low_id, high_id}
        assert second is not None
        assert second.result(timeout=10) == {low_id, high_id}


def test_concurrent_cross_tenant_deactivation_serializes_shared_user_state(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last live tenant membership must deactivate the shared User."""

    from caseops_api.db.models import CompanyMembership, User
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        company_a = _seed_company(seed)
        company_b = _seed_company(seed)
        actor_a = _seed_membership(seed, company_a)
        actor_b = _seed_membership(seed, company_b)
        for actor_id in (actor_a, actor_b):
            actor = seed.get(CompanyMembership, actor_id)
            assert actor is not None
            actor.role = "owner"

        user_id = str(uuid4())
        target_a = str(uuid4())
        target_b = str(uuid4())
        now = datetime.now(UTC)
        seed.execute(
            text(
                "INSERT INTO users "
                "(id, email, full_name, password_hash, is_active, created_at) "
                "VALUES (:id, :email, 'Shared Tenant User', 'not-used', true, :ts)"
            ),
            {
                "id": user_id,
                "email": f"shared-deactivate-{user_id[:8]}@example.com",
                "ts": now,
            },
        )
        for membership_id, company_id in (
            (target_a, company_a),
            (target_b, company_b),
        ):
            seed.execute(
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
        seed.commit()

    first_holds_user = Event()
    release_first = Event()
    original_guard = identity_service.assert_no_operational_ip_work_before_deactivation

    def paused_guard(session, *, context, membership):
        original_guard(session, context=context, membership=membership)
        if membership.id == target_a:
            first_holds_user.set()
            if not release_first.wait(timeout=10):
                raise TimeoutError("Shared-User deactivation race did not release.")

    monkeypatch.setattr(
        identity_service,
        "assert_no_operational_ip_work_before_deactivation",
        paused_guard,
    )
    application_name = f"caseops-user-deactivate-{str(uuid4())[:8]}"

    def deactivate(
        *,
        company_id: str,
        actor_id: str,
        membership_id: str,
        application_name: str | None = None,
    ):
        with Session(pg_engine) as session:
            if application_name is not None:
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            context = _ip_race_context(
                session,
                company_id=company_id,
                membership_id=actor_id,
            )
            return identity_service.update_company_user(
                session,
                context=context,
                membership_id=membership_id,
                payload=CompanyUserUpdateRequest(is_active=False),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            deactivate,
            company_id=company_a,
            actor_id=actor_a,
            membership_id=target_a,
        )
        second = None
        try:
            assert first_holds_user.wait(timeout=10)
            second = executor.submit(
                deactivate,
                company_id=company_b,
                actor_id=actor_b,
                membership_id=target_b,
                application_name=application_name,
            )
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
            with pytest.raises(FutureTimeoutError):
                second.result(timeout=0.05)
        finally:
            release_first.set()
        first_result = first.result(timeout=10)
        assert second is not None
        second_result = second.result(timeout=10)

    assert first_result.membership_active is False
    assert second_result.membership_active is False
    assert second_result.user_active is False
    with Session(pg_engine) as session:
        persisted_user = session.get(User, user_id)
        persisted_a = session.get(CompanyMembership, target_a)
        persisted_b = session.get(CompanyMembership, target_b)
        assert persisted_user is not None and persisted_user.is_active is False
        assert persisted_a is not None and persisted_a.is_active is False
        assert persisted_b is not None and persisted_b.is_active is False


def test_matter_disposal_wins_bulk_ip_coverage_reassignment_race(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk reassignment sees cancelled Matter work without mutating IP cover."""

    from caseops_api.db.models import IpDeadlineCoverage, Matter, MatterDeadline
    from caseops_api.schemas.ip_operations import IpCoverageBulkReassignRequest
    from caseops_api.schemas.matters import MatterLifecycleStatusRequest
    from caseops_api.services import matters as matter_service
    from caseops_api.services.ip_operations import bulk_reassign_ip_deadline_coverages

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)

    disposal_has_parent_lock = Event()
    release_disposal = Event()
    original_neutralize = matter_service._neutralize_disposed_matter_operations

    def paused_neutralize(session, *, context, matter):
        disposal_has_parent_lock.set()
        if not release_disposal.wait(timeout=10):
            raise TimeoutError("Bulk coverage race did not release disposal.")
        return original_neutralize(session, context=context, matter=matter)

    monkeypatch.setattr(
        matter_service,
        "_neutralize_disposed_matter_operations",
        paused_neutralize,
    )
    application_name = f"caseops-ip-bulk-{str(uuid4())[:8]}"

    def dispose_matter():
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            matter = session.get(Matter, fixture["matter_id"])
            assert matter is not None
            return matter_service.transition_matter_lifecycle_status(
                session,
                context=context,
                matter_id=matter.id,
                payload=MatterLifecycleStatusRequest(
                    to_status="disposed",
                    expected_from_status="active",
                    expected_updated_at=matter.updated_at,
                    reason="PostgreSQL race proves parent lifecycle ownership.",
                ),
            )

    def bulk_reassign():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            return bulk_reassign_ip_deadline_coverages(
                session,
                context=context,
                payload=IpCoverageBulkReassignRequest(
                    from_membership_id=fixture["owner_id"],
                    to_membership_id=fixture["replacement_id"],
                    reason="Attempted handover while the matter is being disposed.",
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        disposal = executor.submit(dispose_matter)
        transfer = None
        try:
            assert disposal_has_parent_lock.wait(timeout=10)
            transfer = executor.submit(bulk_reassign)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            with pytest.raises(FutureTimeoutError):
                transfer.result(timeout=0.05)
        finally:
            release_disposal.set()
        disposed = disposal.result(timeout=10)
        assert transfer is not None
        transfer_result = transfer.result(timeout=10)

    assert disposed.status == "disposed"
    assert transfer_result.reassigned_count == 0
    assert transfer_result.coverage_ids == []
    with Session(pg_engine) as session:
        coverage = session.get(IpDeadlineCoverage, fixture["coverage_id"])
        deadline = session.get(MatterDeadline, fixture["deadline_id"])
        assert coverage is not None
        assert deadline is not None and deadline.status == "cancelled"
        assert coverage.coverage_status == "accepted"
        assert coverage.calendar_projection_status == "pending"
        assert coverage.responsible_membership_id == fixture["owner_id"]
        assert coverage.pending_replacement_membership_id is None
        assert coverage.replacement_decision == "none"
        assert coverage.reassignment_version == 1


def test_matter_disposal_wins_ip_coverage_proposal_race(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proposal rejects a stale preview while preserving independent IP cover."""

    from fastapi import HTTPException

    from caseops_api.db.models import IpDeadlineCoverage, Matter, MatterDeadline
    from caseops_api.schemas.ip_operations import (
        IpCoverageReassignPreviewRequest,
        IpCoverageReassignProposeRequest,
    )
    from caseops_api.schemas.matters import MatterLifecycleStatusRequest
    from caseops_api.services import matters as matter_service
    from caseops_api.services.ip_operations import (
        preview_ip_coverage_reassignment,
        propose_ip_coverage_reassignment,
    )

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)
    with Session(pg_engine) as preview_session:
        context = _ip_race_context(
            preview_session,
            company_id=fixture["company_id"],
            membership_id=fixture["owner_id"],
        )
        preview = preview_ip_coverage_reassignment(
            preview_session,
            context=context,
            payload=IpCoverageReassignPreviewRequest(
                from_membership_id=fixture["owner_id"],
                to_membership_id=fixture["replacement_id"],
            ),
        )
        assert preview.affected_coverage_ids == [fixture["coverage_id"]]
        preview_token = preview.preview_token

    disposal_has_parent_lock = Event()
    release_disposal = Event()
    original_neutralize = matter_service._neutralize_disposed_matter_operations

    def paused_neutralize(session, *, context, matter):
        disposal_has_parent_lock.set()
        if not release_disposal.wait(timeout=10):
            raise TimeoutError("Proposal coverage race did not release disposal.")
        return original_neutralize(session, context=context, matter=matter)

    monkeypatch.setattr(
        matter_service,
        "_neutralize_disposed_matter_operations",
        paused_neutralize,
    )
    application_name = f"caseops-ip-propose-{str(uuid4())[:8]}"

    def dispose_matter():
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            matter = session.get(Matter, fixture["matter_id"])
            assert matter is not None
            return matter_service.transition_matter_lifecycle_status(
                session,
                context=context,
                matter_id=matter.id,
                payload=MatterLifecycleStatusRequest(
                    to_status="disposed",
                    expected_from_status="active",
                    expected_updated_at=matter.updated_at,
                    reason="PostgreSQL race proves proposal lifecycle exclusion.",
                ),
            )

    def propose_reassignment():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                propose_ip_coverage_reassignment(
                    session,
                    context=context,
                    payload=IpCoverageReassignProposeRequest(
                        from_membership_id=fixture["owner_id"],
                        to_membership_id=fixture["replacement_id"],
                        preview_token=preview_token,
                        reason="Attempted proposal while the matter is being disposed.",
                    ),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Disposed coverage proposal unexpectedly succeeded.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        disposal = executor.submit(dispose_matter)
        proposal = None
        try:
            assert disposal_has_parent_lock.wait(timeout=10)
            proposal = executor.submit(propose_reassignment)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            with pytest.raises(FutureTimeoutError):
                proposal.result(timeout=0.05)
        finally:
            release_disposal.set()
        disposed = disposal.result(timeout=10)
        assert proposal is not None
        proposal_status, proposal_detail = proposal.result(timeout=10)

    assert disposed.status == "disposed"
    assert proposal_status == 409
    assert proposal_detail["code"] == "ip_coverage_preview_stale"
    with Session(pg_engine) as session:
        coverage = session.get(IpDeadlineCoverage, fixture["coverage_id"])
        deadline = session.get(MatterDeadline, fixture["deadline_id"])
        assert coverage is not None
        assert deadline is not None and deadline.status == "cancelled"
        assert coverage.coverage_status == "accepted"
        assert coverage.calendar_projection_status == "pending"
        assert coverage.responsible_membership_id == fixture["owner_id"]
        assert coverage.pending_replacement_membership_id is None
        assert coverage.replacement_decision == "none"
        assert coverage.reassignment_version == 1


def test_deadline_completion_wins_bulk_ip_coverage_reassignment_race(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk reassignment waits for the deadline lock and then skips DONE work."""

    from caseops_api.db.models import IpDeadlineCoverage, MatterDeadline
    from caseops_api.schemas.ip_operations import IpCoverageBulkReassignRequest
    from caseops_api.services import deadlines as deadline_service
    from caseops_api.services.ip_operations import bulk_reassign_ip_deadline_coverages

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)

    deadline_mutated = Event()
    release_deadline = Event()
    original_record = deadline_service.record_from_context

    def paused_record(*args, **kwargs):
        if kwargs.get("action") == "deadline.complete":
            deadline_mutated.set()
            if not release_deadline.wait(timeout=10):
                raise TimeoutError("Bulk race did not release deadline completion.")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(deadline_service, "record_from_context", paused_record)
    application_name = f"caseops-ip-bulk-deadline-{str(uuid4())[:8]}"

    def complete_deadline():
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            return deadline_service.transition_deadline(
                session,
                context=context,
                deadline_id=fixture["deadline_id"],
                action="complete",
            )

    def bulk_reassign():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            return bulk_reassign_ip_deadline_coverages(
                session,
                context=context,
                payload=IpCoverageBulkReassignRequest(
                    from_membership_id=fixture["owner_id"],
                    to_membership_id=fixture["replacement_id"],
                    reason="Attempted handover while its deadline completes.",
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        completion = executor.submit(complete_deadline)
        transfer = None
        try:
            assert deadline_mutated.wait(timeout=10)
            transfer = executor.submit(bulk_reassign)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            with pytest.raises(FutureTimeoutError):
                transfer.result(timeout=0.05)
        finally:
            release_deadline.set()
        completed = completion.result(timeout=10)
        assert transfer is not None
        transfer_result = transfer.result(timeout=10)

    assert completed.status == "done"
    assert transfer_result.reassigned_count == 0
    assert transfer_result.coverage_ids == []
    with Session(pg_engine) as session:
        deadline = session.get(MatterDeadline, fixture["deadline_id"])
        coverage = session.get(IpDeadlineCoverage, fixture["coverage_id"])
        assert deadline is not None and deadline.status == "done"
        assert coverage is not None
        assert coverage.coverage_status == "completed"
        assert coverage.calendar_projection_status == "completed"
        assert coverage.responsible_membership_id == fixture["owner_id"]
        assert coverage.pending_replacement_membership_id is None
        assert coverage.reassignment_version == 1


def test_deadline_cancellation_wins_ip_coverage_proposal_race(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proposal waits for the deadline lock and rejects its stale preview."""

    from fastapi import HTTPException

    from caseops_api.db.models import IpDeadlineCoverage, MatterDeadline
    from caseops_api.schemas.ip_operations import (
        IpCoverageReassignPreviewRequest,
        IpCoverageReassignProposeRequest,
    )
    from caseops_api.services import deadlines as deadline_service
    from caseops_api.services.ip_operations import (
        preview_ip_coverage_reassignment,
        propose_ip_coverage_reassignment,
    )

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)
    with Session(pg_engine) as preview_session:
        context = _ip_race_context(
            preview_session,
            company_id=fixture["company_id"],
            membership_id=fixture["owner_id"],
        )
        preview = preview_ip_coverage_reassignment(
            preview_session,
            context=context,
            payload=IpCoverageReassignPreviewRequest(
                from_membership_id=fixture["owner_id"],
                to_membership_id=fixture["replacement_id"],
            ),
        )
        assert preview.affected_coverage_ids == [fixture["coverage_id"]]
        preview_token = preview.preview_token

    deadline_mutated = Event()
    release_deadline = Event()
    original_record = deadline_service.record_from_context

    def paused_record(*args, **kwargs):
        if kwargs.get("action") == "deadline.cancel":
            deadline_mutated.set()
            if not release_deadline.wait(timeout=10):
                raise TimeoutError("Proposal race did not release deadline cancellation.")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(deadline_service, "record_from_context", paused_record)
    application_name = f"caseops-ip-propose-deadline-{str(uuid4())[:8]}"

    def cancel_deadline():
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            return deadline_service.transition_deadline(
                session,
                context=context,
                deadline_id=fixture["deadline_id"],
                action="cancel",
            )

    def propose_reassignment():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                propose_ip_coverage_reassignment(
                    session,
                    context=context,
                    payload=IpCoverageReassignProposeRequest(
                        from_membership_id=fixture["owner_id"],
                        to_membership_id=fixture["replacement_id"],
                        preview_token=preview_token,
                        reason="Attempted proposal while its deadline is cancelled.",
                    ),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Cancelled-deadline coverage proposal unexpectedly succeeded.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        cancellation = executor.submit(cancel_deadline)
        proposal = None
        try:
            assert deadline_mutated.wait(timeout=10)
            proposal = executor.submit(propose_reassignment)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            with pytest.raises(FutureTimeoutError):
                proposal.result(timeout=0.05)
        finally:
            release_deadline.set()
        cancelled = cancellation.result(timeout=10)
        assert proposal is not None
        proposal_status, proposal_detail = proposal.result(timeout=10)

    assert cancelled.status == "cancelled"
    assert proposal_status == 409
    assert proposal_detail["code"] == "ip_coverage_preview_stale"
    with Session(pg_engine) as session:
        deadline = session.get(MatterDeadline, fixture["deadline_id"])
        coverage = session.get(IpDeadlineCoverage, fixture["coverage_id"])
        assert deadline is not None and deadline.status == "cancelled"
        assert coverage is not None
        assert coverage.coverage_status == "completed"
        assert coverage.calendar_projection_status == "completed"
        assert coverage.responsible_membership_id == fixture["owner_id"]
        assert coverage.pending_replacement_membership_id is None
        assert coverage.reassignment_version == 1


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

    _prepare_postgres_destructive_migration_probe(pg_engine, config)
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

    _prepare_postgres_destructive_migration_probe(pg_engine, config)
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


def test_application_family_query_is_bounded_and_uses_tenant_asset_index(pg_engine):
    inspector = inspect(pg_engine)
    indexes = {
        str(index["name"]): tuple(index["column_names"])
        for index in inspector.get_indexes("trademark_applications")
    }
    assert indexes["ix_tm_applications_company_asset"] == ("company_id", "asset_id")

    company_id = str(uuid4())
    with pg_engine.connect() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan_rows = connection.execute(
            text(
                "EXPLAIN (COSTS OFF) "
                "SELECT asset_id, count(id) AS member_count "
                "FROM trademark_applications "
                "WHERE company_id = :company_id AND asset_id IS NOT NULL "
                "GROUP BY asset_id "
                "ORDER BY member_count DESC, asset_id "
                "LIMIT 26"
            ),
            {"company_id": company_id},
        ).scalars()
        plan = "\n".join(str(row) for row in plan_rows)

    assert "Limit" in plan
    assert "ix_tm_applications_company_asset" in plan


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
    """Alembic must not cross the revision that owns retained evidence."""

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from alembic import command

    url = os.environ["CASEOPS_TEST_POSTGRES_URL"]
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    _prepare_postgres_destructive_migration_probe(pg_engine, config)
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

    try:
        with pytest.raises(RuntimeError, match="roll application code forward"):
            command.downgrade(config, "20260811_0005")

        with pg_engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision is not None
            remaining_lineage = {
                candidate.revision
                for candidate in ScriptDirectory.from_config(config).walk_revisions(
                    base="base", head=revision
                )
            }
            assert "20260812_0001" in remaining_lineage
            assert connection.scalar(
                text("SELECT count(*) FROM api_idempotency_records WHERE id = :id"),
                {"id": record_id},
            ) == 1
    finally:
        command.upgrade(config, "head")


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


# ---------- final auth-session mint fence (2026-08-17) ----------


def _seed_auth_session_fence_identity(
    session: Session,
    *,
    invited: bool = False,
) -> dict[str, str]:
    from caseops_api.core.security import hash_password
    from caseops_api.db.models import Company, CompanyMembership, EmployeeProfile, User

    company_id = _seed_company(session)
    actor_id = _seed_membership(session, company_id)
    target_id = _seed_membership(session, company_id)
    company = session.get(Company, company_id)
    actor = session.get(CompanyMembership, actor_id)
    target = session.get(CompanyMembership, target_id)
    assert company is not None and actor is not None and target is not None
    actor.role = "owner"
    target.role = "member"
    user = session.get(User, target.user_id)
    assert user is not None
    user.email = f"auth-fence-{target.id[:8]}@example.com"
    user.full_name = "Auth Fence Target"
    user.password_hash = hash_password("BeforeFence123!")
    now = datetime.now(UTC)
    session.add(
        EmployeeProfile(
            company_id=company_id,
            membership_id=target_id,
            employment_status="invited" if invited else "active",
            force_password_change=invited,
            setup_completed_at=None if invited else now,
            created_at=now,
            updated_at=now,
        )
    )
    user_id = user.id
    email = user.email
    company_slug = company.slug
    session.commit()
    return {
        "company_id": company_id,
        "company_slug": company_slug,
        "actor_id": actor_id,
        "target_id": target_id,
        "user_id": user_id,
        "email": email,
    }


def _seed_auth_completion_token(
    session: Session,
    *,
    fixture: dict[str, str],
    purpose: str,
) -> str:
    import hashlib

    from caseops_api.db.models import AccountSetupToken

    plaintext = f"auth-fence-{purpose}-{uuid4()}"
    session.add(
        AccountSetupToken(
            company_id=fixture["company_id"],
            user_id=fixture["user_id"],
            membership_id=fixture["target_id"],
            token_hash=hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
            purpose=purpose,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    session.commit()
    return plaintext


def _deactivate_auth_session_fence_target(
    pg_engine,
    *,
    fixture: dict[str, str],
    application_name: str | None = None,
):
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as session:
        if application_name is not None:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
        context = _ip_race_context(
            session,
            company_id=fixture["company_id"],
            membership_id=fixture["actor_id"],
        )
        return identity_service.update_company_user(
            session,
            context=context,
            membership_id=fixture["target_id"],
            payload=CompanyUserUpdateRequest(is_active=False),
        )


def test_password_reset_wins_login_final_mint_fence_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A login that checked the old hash cannot mint after reset commits."""

    from fastapi import HTTPException

    from caseops_api.schemas.employees import AccountSetupCompleteRequest
    from caseops_api.services import employees as employee_service
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_auth_session_fence_identity(seed)
        reset_token = _seed_auth_completion_token(
            seed,
            fixture=fixture,
            purpose="password_reset",
        )

    reset_holds_identity_fence = Event()
    release_reset = Event()
    original_hash_password = employee_service.hash_password

    def paused_hash_password(password: str) -> str:
        reset_holds_identity_fence.set()
        if not release_reset.wait(timeout=10):
            raise TimeoutError("Password-reset/login race did not release reset.")
        return original_hash_password(password)

    monkeypatch.setattr(employee_service, "hash_password", paused_hash_password)
    original_issue = identity_service.issue_auth_session_under_fence
    application_name = f"caseops-login-after-reset-{str(uuid4())[:8]}"

    def named_final_issue(session, **kwargs):
        session.execute(
            text("SELECT set_config('application_name', :name, true)"),
            {"name": application_name},
        )
        return original_issue(session, **kwargs)

    monkeypatch.setattr(
        identity_service,
        "issue_auth_session_under_fence",
        named_final_issue,
    )

    def reset_password():
        with Session(pg_engine) as session:
            return employee_service.complete_password_reset(
                session,
                payload=AccountSetupCompleteRequest(
                    token=reset_token,
                    password="ResetWinner123!",
                ),
            )

    def login_with_losing_password():
        with Session(pg_engine) as session:
            try:
                auth = identity_service.authenticate_user(
                    session,
                    email=fixture["email"],
                    password="BeforeFence123!",
                    company_slug=fixture["company_slug"],
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, None
            session.commit()
            return 200, auth.access_token

    with ThreadPoolExecutor(max_workers=2) as executor:
        reset = executor.submit(reset_password)
        login = None
        try:
            assert reset_holds_identity_fence.wait(timeout=10)
            login = executor.submit(login_with_losing_password)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
            with pytest.raises(FutureTimeoutError):
                login.result(timeout=0.05)
        finally:
            release_reset.set()
        reset.result(timeout=10)
        assert login is not None
        login_status, login_token = login.result(timeout=10)

    assert login_status == 401
    assert login_token is None


def test_login_mint_wins_then_deactivation_revokes_token_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token minted first stays fenced until the later cutoff can commit."""

    from fastapi import HTTPException

    from caseops_api.core.security import decode_access_token
    from caseops_api.db.models import CompanyMembership
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_auth_session_fence_identity(seed)

    mint_holds_identity_fence = Event()
    release_mint = Event()
    original_create_access_token = identity_service.create_access_token

    def paused_create_access_token(**kwargs):
        token = original_create_access_token(**kwargs)
        mint_holds_identity_fence.set()
        if not release_mint.wait(timeout=10):
            raise TimeoutError("Login/deactivation race did not release login mint.")
        return token

    monkeypatch.setattr(
        identity_service,
        "create_access_token",
        paused_create_access_token,
    )
    application_name = f"caseops-deactivate-after-login-{str(uuid4())[:8]}"

    def login_first():
        with Session(pg_engine) as session:
            auth = identity_service.authenticate_user(
                session,
                email=fixture["email"],
                password="BeforeFence123!",
                company_slug=fixture["company_slug"],
            )
            token = auth.access_token
            session.commit()
            return token

    with ThreadPoolExecutor(max_workers=2) as executor:
        login = executor.submit(login_first)
        deactivate = None
        try:
            assert mint_holds_identity_fence.wait(timeout=10)
            deactivate = executor.submit(
                _deactivate_auth_session_fence_target,
                pg_engine,
                fixture=fixture,
                application_name=application_name,
            )
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
            with pytest.raises(FutureTimeoutError):
                deactivate.result(timeout=0.05)
        finally:
            release_mint.set()
        token = login.result(timeout=10)
        assert deactivate is not None
        deactivated = deactivate.result(timeout=10)

    assert deactivated.membership_active is False
    issued_at = float(decode_access_token(token)["issued_at_precise"])
    with Session(pg_engine) as session:
        membership = session.get(CompanyMembership, fixture["target_id"])
        assert membership is not None
        assert membership.sessions_valid_after is not None
        cutoff = membership.sessions_valid_after
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        assert issued_at < cutoff.timestamp()
        with pytest.raises(HTTPException) as exc_info:
            identity_service.get_session_context(
                session,
                fixture["target_id"],
                token_issued_at=issued_at,
            )
        assert exc_info.value.status_code in {401, 403}


def test_deactivation_wins_refresh_final_mint_fence_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh cannot turn a pre-cutoff JWT into a post-cutoff JWT."""

    from fastapi import HTTPException

    from caseops_api.core.security import create_access_token, decode_access_token
    from caseops_api.db.models import Company, CompanyMembership, User
    from caseops_api.services import identity as identity_service
    from caseops_api.services.session_context import SessionContext

    with Session(pg_engine) as seed:
        fixture = _seed_auth_session_fence_identity(seed)
        target = seed.get(CompanyMembership, fixture["target_id"])
        assert target is not None
        source_token = create_access_token(
            user_id=fixture["user_id"],
            company_id=fixture["company_id"],
            membership_id=fixture["target_id"],
            role=target.role,
        )
    source_issued_at = float(decode_access_token(source_token)["issued_at_precise"])

    deactivation_holds_identity_fence = Event()
    release_deactivation = Event()
    original_guard = identity_service.assert_no_operational_ip_work_before_deactivation

    def paused_guard(session, *, context, membership):
        original_guard(session, context=context, membership=membership)
        if membership.id == fixture["target_id"]:
            deactivation_holds_identity_fence.set()
            if not release_deactivation.wait(timeout=10):
                raise TimeoutError("Deactivation/refresh race did not release.")

    monkeypatch.setattr(
        identity_service,
        "assert_no_operational_ip_work_before_deactivation",
        paused_guard,
    )
    application_name = f"caseops-refresh-after-deactivate-{str(uuid4())[:8]}"

    def refresh_losing_session():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            company = session.get(Company, fixture["company_id"])
            membership = session.get(CompanyMembership, fixture["target_id"])
            user = session.get(User, fixture["user_id"])
            assert company is not None and membership is not None and user is not None
            stale_context = SessionContext(
                company=company,
                membership=membership,
                user=user,
                token_issued_at=source_issued_at,
            )
            try:
                refreshed = identity_service.refresh_auth_session(session, stale_context)
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, None
            session.commit()
            return 200, refreshed.access_token

    with ThreadPoolExecutor(max_workers=2) as executor:
        deactivate = executor.submit(
            _deactivate_auth_session_fence_target,
            pg_engine,
            fixture=fixture,
        )
        refresh = None
        try:
            assert deactivation_holds_identity_fence.wait(timeout=10)
            refresh = executor.submit(refresh_losing_session)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
            with pytest.raises(FutureTimeoutError):
                refresh.result(timeout=0.05)
        finally:
            release_deactivation.set()
        deactivated = deactivate.result(timeout=10)
        assert refresh is not None
        refresh_status, refresh_token = refresh.result(timeout=10)

    assert deactivated.membership_active is False
    assert refresh_status == 403
    assert refresh_token is None


@pytest.mark.parametrize(
    ("purpose", "invited"),
    [("account_setup", True), ("password_reset", False)],
    ids=["setup-completion", "reset-completion"],
)
def test_deactivation_wins_completion_response_final_mint_fence_on_postgres(
    pg_engine,
    purpose: str,
    invited: bool,
) -> None:
    """Completion may commit, but its response cannot mint after offboarding."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, EmployeeProfile
    from caseops_api.schemas.employees import AccountSetupCompleteRequest
    from caseops_api.services import employees as employee_service
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_auth_session_fence_identity(seed, invited=invited)
        plaintext = _seed_auth_completion_token(
            seed,
            fixture=fixture,
            purpose=purpose,
        )

    completion_committed = Event()
    allow_final_mint = Event()

    def complete_then_build_response():
        with Session(pg_engine) as session:
            payload = AccountSetupCompleteRequest(
                token=plaintext,
                password="CompletionWinner123!",
            )
            if purpose == "account_setup":
                context = employee_service.complete_account_setup(session, payload=payload)
            else:
                context = employee_service.complete_password_reset(session, payload=payload)
            completion_committed.set()
            if not allow_final_mint.wait(timeout=10):
                raise TimeoutError("Completion-response race did not release mint.")
            try:
                response = identity_service.issue_auth_session_under_fence(
                    session,
                    company_id=context.company.id,
                    membership_id=context.membership.id,
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, None
            session.commit()
            return 200, response.access_token

    with ThreadPoolExecutor(max_workers=1) as executor:
        completion = executor.submit(complete_then_build_response)
        try:
            assert completion_committed.wait(timeout=10)
            deactivated = _deactivate_auth_session_fence_target(
                pg_engine,
                fixture=fixture,
            )
        finally:
            allow_final_mint.set()
        completion_status, completion_token = completion.result(timeout=10)

    assert deactivated.membership_active is False
    assert completion_status == 403
    assert completion_token is None
    with Session(pg_engine) as session:
        membership = session.get(CompanyMembership, fixture["target_id"])
        profile = session.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.membership_id == fixture["target_id"]
            )
        )
        assert membership is not None and membership.is_active is False
        assert membership.sessions_valid_after is not None
        assert profile is not None and profile.employment_status == "inactive"


def test_ip_access_revocation_wins_coverage_assignment_race_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed wall is authoritative before a waiting owner cutover."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, EthicalWall, IpDeadlineCoverage
    from caseops_api.schemas.ip_access import IpAccessApplyRequest, IpAccessChangeRequest
    from caseops_api.schemas.ip_operations import IpCoverageBulkReassignRequest
    from caseops_api.services import matter_access
    from caseops_api.services.ip_operations import bulk_reassign_ip_deadline_coverages
    from caseops_api.services.matter_access import (
        apply_ip_access_change,
        preview_ip_access_change,
    )

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)
        owner = seed.get(CompanyMembership, fixture["owner_id"])
        assert owner is not None
        owner.role = "owner"
        seed.commit()

    access_payload = IpAccessChangeRequest(
        action="add_wall",
        expected_access_policy_version=0,
        reason="Concurrent conflict requires access removal before handoff.",
        subject_type="membership",
        subject_id=fixture["replacement_id"],
    )
    with Session(pg_engine) as preview_session:
        context = _ip_race_context(
            preview_session,
            company_id=fixture["company_id"],
            membership_id=fixture["owner_id"],
        )
        preview = preview_ip_access_change(
            preview_session,
            context=context,
            docket_id=fixture["docket_id"],
            payload=access_payload,
        )

    access_staged = Event()
    release_access = Event()
    original_record = matter_access.record_from_context

    def paused_record(*args, **kwargs):
        if kwargs.get("action") == "ip.access.add_wall":
            access_staged.set()
            if not release_access.wait(timeout=10):
                raise TimeoutError("Coverage transfer did not release IP access apply.")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(matter_access, "record_from_context", paused_record)
    application_name = f"caseops-ip-access-wins-{str(uuid4())[:8]}"

    def apply_wall():
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            return apply_ip_access_change(
                session,
                context=context,
                docket_id=fixture["docket_id"],
                payload=IpAccessApplyRequest(
                    **access_payload.model_dump(),
                    preview_token=preview.preview_token,
                ),
            )

    def transfer_coverage():
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                bulk_reassign_ip_deadline_coverages(
                    session,
                    context=context,
                    payload=IpCoverageBulkReassignRequest(
                        from_membership_id=fixture["owner_id"],
                        to_membership_id=fixture["replacement_id"],
                        reason="Concurrent owner handoff after access revocation.",
                        transfer_mode="immediate",
                        escalation_membership_id=fixture["owner_id"],
                    ),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Coverage transfer ignored the committed access wall.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        access = executor.submit(apply_wall)
        transfer = None
        try:
            assert access_staged.wait(timeout=10)
            transfer = executor.submit(transfer_coverage)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_access.set()
        applied = access.result(timeout=10)
        assert transfer is not None
        transfer_status, transfer_detail = transfer.result(timeout=10)

    assert applied.action == "add_wall"
    assert transfer_status == 409
    assert transfer_detail["code"] == "ip_coverage_replacement_lacks_access"
    with Session(pg_engine) as session:
        coverage = session.get(IpDeadlineCoverage, fixture["coverage_id"])
        walls = list(
            session.scalars(
                select(EthicalWall).where(
                    EthicalWall.ip_docket_id == fixture["docket_id"],
                    EthicalWall.excluded_membership_id == fixture["replacement_id"],
                    EthicalWall.revoked_at.is_(None),
                )
            ).all()
        )
        assert coverage is not None
        assert coverage.responsible_membership_id == fixture["owner_id"]
        assert coverage.pending_replacement_membership_id is None
        assert len(walls) == 1


def test_assignment_fence_waits_for_global_user_deactivation_on_postgres(
    pg_engine,
) -> None:
    """A membership writer must refresh User state after the global row lock."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, User
    from caseops_api.services.ip_operations import (
        _lock_assignment_memberships_or_404,
    )

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        actor_id = _seed_membership(seed, company_id)
        target_id = _seed_membership(seed, company_id)
        target = seed.get(CompanyMembership, target_id)
        assert target is not None
        target_user_id = target.user_id
        seed.commit()

    user_deactivation_staged = Event()
    release_user_deactivation = Event()
    application_name = f"caseops-user-fence-writer-{str(uuid4())[:8]}"

    def deactivate_global_user() -> None:
        with Session(pg_engine) as session:
            user = session.scalar(
                select(User)
                .where(User.id == target_user_id)
                .with_for_update(of=User)
                .execution_options(populate_existing=True)
            )
            assert user is not None
            user.is_active = False
            session.flush()
            user_deactivation_staged.set()
            if not release_user_deactivation.wait(timeout=10):
                raise TimeoutError("Global User fence race did not release.")
            session.commit()

    def assign_after_user_change() -> tuple[int, object]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=company_id,
                membership_id=actor_id,
            )
            try:
                    _lock_assignment_memberships_or_404(
                        session,
                        context,
                        membership_ids={target_id},
                        active_membership_ids={target_id},
                        required_capability="ip:write",
                    )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Inactive global User passed the assignment fence.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        deactivation = executor.submit(deactivate_global_user)
        writer = None
        try:
            assert user_deactivation_staged.wait(timeout=10)
            writer = executor.submit(assign_after_user_change)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
            with pytest.raises(FutureTimeoutError):
                writer.result(timeout=0.05)
        finally:
            release_user_deactivation.set()
        deactivation.result(timeout=10)
        assert writer is not None
        writer_status, _detail = writer.result(timeout=10)

    assert writer_status == 404
    with Session(pg_engine) as session:
        membership = session.get(CompanyMembership, target_id)
        user = session.get(User, target_user_id)
        assert membership is not None and membership.is_active is True
        assert user is not None and user.is_active is False


# ---------- Matter/team bounded-role lock-order races (2026-08-17) ----------


def _seed_matter_role_fence_fixture(session: Session) -> dict[str, str]:
    from caseops_api.db.models import (
        CompanyMembership,
        IpDocketRecord,
        Matter,
        MatterHearing,
        MatterTask,
    )

    company_id = _seed_company(session)
    actor_id = _seed_membership(session, company_id)
    target_id = _seed_membership(session, company_id)
    actor = session.get(CompanyMembership, actor_id)
    assert actor is not None
    actor.role = "owner"

    linked_matter_id = _seed_matter(session, company_id)
    linked_docket = IpDocketRecord(
        company_id=company_id,
        matter_id=linked_matter_id,
        record_type="trademark",
        title="Matter role fence linked docket",
        primary_identifier=f"PG-MATTER-ROLE-{str(uuid4())[:8]}",
        status="active",
        is_active=True,
        restricted=False,
        created_by_membership_id=actor_id,
    )
    existing_task = MatterTask(
        company_id=company_id,
        matter_id=linked_matter_id,
        created_by_membership_id=actor_id,
        owner_membership_id=actor_id,
        title="Existing task awaiting reassignment",
        status="todo",
        priority="medium",
    )
    session.add_all([linked_docket, existing_task])

    plain_matter_id = _seed_matter(session, company_id)
    plain_matter = session.get(Matter, plain_matter_id)
    assert plain_matter is not None
    plain_matter.assignee_membership_id = target_id
    follow_up_hearing = MatterHearing(
        company_id=company_id,
        matter_id=plain_matter_id,
        hearing_on=date.today() + timedelta(days=10),
        forum_name="PostgreSQL role-fence forum",
        purpose="Derived follow-up race",
        status="scheduled",
    )
    session.add(follow_up_hearing)
    session.commit()
    return {
        "company_id": company_id,
        "actor_id": actor_id,
        "target_id": target_id,
        "linked_matter_id": linked_matter_id,
        "linked_docket_id": linked_docket.id,
        "existing_task_id": existing_task.id,
        "plain_matter_id": plain_matter_id,
        "follow_up_hearing_id": follow_up_hearing.id,
    }


def _run_matter_role_writer(
    session: Session,
    *,
    fixture: dict[str, str],
    writer_kind: str,
) -> tuple[int, object | None]:
    from fastapi import HTTPException

    from caseops_api.schemas.matters import (
        MatterHearingCreateRequest,
        MatterHearingUpdateRequest,
        MatterTaskCreateRequest,
        MatterTaskUpdateRequest,
    )
    from caseops_api.services import deadlines as deadline_service
    from caseops_api.services import matters as matter_service

    context = _ip_race_context(
        session,
        company_id=fixture["company_id"],
        membership_id=fixture["actor_id"],
    )
    try:
        if writer_kind == "task_create":
            matter_service.create_matter_task(
                session,
                context=context,
                matter_id=fixture["linked_matter_id"],
                payload=MatterTaskCreateRequest(
                    title="Concurrent target task",
                    owner_membership_id=fixture["target_id"],
                    status="todo",
                    priority="high",
                ),
            )
        elif writer_kind == "task_reassign":
            matter_service.update_matter_task(
                session,
                context=context,
                matter_id=fixture["linked_matter_id"],
                task_id=fixture["existing_task_id"],
                payload=MatterTaskUpdateRequest(
                    owner_membership_id=fixture["target_id"],
                ),
            )
        elif writer_kind == "hearing_create":
            matter_service.create_matter_hearing(
                session,
                context=context,
                matter_id=fixture["linked_matter_id"],
                payload=MatterHearingCreateRequest(
                    hearing_on=date.today() + timedelta(days=30),
                    forum_name="PostgreSQL role-fence forum",
                    purpose="Concurrent escalation assignment",
                    reminder_recipient_membership_ids=[fixture["actor_id"]],
                    reminder_channels=["in_app"],
                    escalation_membership_id=fixture["target_id"],
                ),
            )
        elif writer_kind == "deadline_create":
            deadline_service.create_deadline(
                session,
                context=context,
                matter_id=fixture["linked_matter_id"],
                source="custom",
                kind="response",
                title="Concurrent generic linked-IP deadline",
                due_on=date.today() + timedelta(days=31),
                assignee_membership_id=fixture["target_id"],
            )
        elif writer_kind == "derived_follow_up":
            matter_service.update_matter_hearing(
                session,
                context=context,
                matter_id=fixture["plain_matter_id"],
                hearing_id=fixture["follow_up_hearing_id"],
                payload=MatterHearingUpdateRequest(
                    status="completed",
                    outcome_note="Generate the fenced follow-up.",
                    create_follow_up=True,
                ),
            )
        else:  # pragma: no cover - parametrization owns the values
            raise AssertionError(f"Unknown writer kind: {writer_kind}")
    except HTTPException as exc:
        session.rollback()
        return exc.status_code, exc.detail
    session.commit()
    return 200, None


@pytest.mark.parametrize(
    "writer_kind",
    (
        "task_create",
        "task_reassign",
        "hearing_create",
        "deadline_create",
        "derived_follow_up",
    ),
)
def test_generic_deactivation_wins_matter_role_writer_race_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    writer_kind: str,
) -> None:
    """Membership/User deactivation commits before every derived-role writer."""

    from fastapi import HTTPException

    from caseops_api.db.models import (
        CompanyMembership,
        MatterDeadline,
        MatterHearing,
        MatterTask,
    )
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_matter_role_fence_fixture(seed)

    deactivation_holds_fence = Event()
    release_deactivation = Event()
    original_guard = identity_service.assert_no_operational_ip_work_before_deactivation

    def paused_guard(*args, **kwargs):
        deactivation_holds_fence.set()
        if not release_deactivation.wait(timeout=10):
            raise TimeoutError("Matter writer did not release generic deactivation.")
        return original_guard(*args, **kwargs)

    monkeypatch.setattr(
        identity_service,
        "assert_no_operational_ip_work_before_deactivation",
        paused_guard,
    )
    application_name = f"caseops-matter-after-deactivate-{str(uuid4())[:8]}"

    def deactivate() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["actor_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["target_id"],
                    payload=CompanyUserUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    def write_role() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            return _run_matter_role_writer(
                session,
                fixture=fixture,
                writer_kind=writer_kind,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        deactivation = executor.submit(deactivate)
        writer = None
        try:
            assert deactivation_holds_fence.wait(timeout=10)
            writer = executor.submit(write_role)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_deactivation.set()
        deactivation_status, _detail = deactivation.result(timeout=10)
        assert writer is not None
        writer_status, _writer_detail = writer.result(timeout=10)

    assert deactivation_status == 200
    assert writer_status in {400, 404}
    with Session(pg_engine) as session:
        target = session.get(CompanyMembership, fixture["target_id"])
        assert target is not None and target.is_active is False
        if writer_kind == "task_create":
            assert session.scalar(
                select(MatterTask.id).where(
                    MatterTask.matter_id == fixture["linked_matter_id"],
                    MatterTask.title == "Concurrent target task",
                )
            ) is None
        elif writer_kind == "task_reassign":
            task = session.get(MatterTask, fixture["existing_task_id"])
            assert task is not None and task.owner_membership_id == fixture["actor_id"]
        elif writer_kind == "hearing_create":
            assert session.scalar(
                select(MatterHearing.id).where(
                    MatterHearing.matter_id == fixture["linked_matter_id"],
                    MatterHearing.purpose == "Concurrent escalation assignment",
                )
            ) is None
        elif writer_kind == "deadline_create":
            assert session.scalar(
                select(MatterDeadline.id).where(
                    MatterDeadline.matter_id == fixture["linked_matter_id"],
                    MatterDeadline.title
                    == "Concurrent generic linked-IP deadline",
                )
            ) is None
        else:
            hearing = session.get(MatterHearing, fixture["follow_up_hearing_id"])
            assert hearing is not None and hearing.status == "scheduled"
            assert session.scalar(
                select(MatterTask.id).where(
                    MatterTask.matter_id == fixture["plain_matter_id"],
                    MatterTask.owner_membership_id == fixture["target_id"],
                )
            ) is None


@pytest.mark.parametrize("writer_kind", ("task_create", "hearing_create"))
def test_matter_role_writer_wins_then_deactivation_fails_closed_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    writer_kind: str,
) -> None:
    """A committed linked-IP role is visible to the generic guard after waiting."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service
    from caseops_api.services import matters as matter_service

    with Session(pg_engine) as seed:
        fixture = _seed_matter_role_fence_fixture(seed)

    writer_holds_fence = Event()
    release_writer = Event()
    original_append = matter_service._append_activity

    def paused_append(*args, **kwargs):
        result = original_append(*args, **kwargs)
        event_type = kwargs.get("event_type")
        expected_event = "task_added" if writer_kind == "task_create" else "hearing_added"
        if event_type == expected_event:
            writer_holds_fence.set()
            if not release_writer.wait(timeout=10):
                raise TimeoutError("Generic deactivation did not release Matter writer.")
        return result

    monkeypatch.setattr(matter_service, "_append_activity", paused_append)
    application_name = f"caseops-deactivate-after-matter-{str(uuid4())[:8]}"

    def write_role() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            return _run_matter_role_writer(
                session,
                fixture=fixture,
                writer_kind=writer_kind,
            )

    def deactivate() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["actor_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["target_id"],
                    payload=CompanyUserUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Deactivation ignored a committed linked-IP role.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(write_role)
        deactivation = None
        try:
            assert writer_holds_fence.wait(timeout=10)
            deactivation = executor.submit(deactivate)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_writer.set()
        writer_status, _writer_detail = writer.result(timeout=10)
        assert deactivation is not None
        deactivation_status, _detail = deactivation.result(timeout=10)

    assert writer_status == 200
    assert deactivation_status == 409
    with Session(pg_engine) as session:
        target = session.get(CompanyMembership, fixture["target_id"])
        assert target is not None and target.is_active is True


def test_generic_deadline_writer_wins_then_deactivation_fails_closed_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late generic linked-IP deadline is visible after the member fence wait."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, MatterDeadline
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import deadlines as deadline_service
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_matter_role_fence_fixture(seed)

    writer_holds_fence = Event()
    release_writer = Event()
    original_record = deadline_service.record_from_context

    def paused_record(*args, **kwargs):
        result = original_record(*args, **kwargs)
        if kwargs.get("action") == "deadline.created":
            writer_holds_fence.set()
            if not release_writer.wait(timeout=10):
                raise TimeoutError("Generic deactivation did not release deadline writer.")
        return result

    monkeypatch.setattr(deadline_service, "record_from_context", paused_record)
    application_name = f"caseops-deactivate-after-deadline-{str(uuid4())[:8]}"

    def write_role() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            return _run_matter_role_writer(
                session,
                fixture=fixture,
                writer_kind="deadline_create",
            )

    def deactivate() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["actor_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["target_id"],
                    payload=CompanyUserUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Deactivation ignored a committed generic deadline role.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(write_role)
        deactivation = None
        try:
            assert writer_holds_fence.wait(timeout=10)
            deactivation = executor.submit(deactivate)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_writer.set()
        writer_status, _writer_detail = writer.result(timeout=10)
        assert deactivation is not None
        deactivation_status, _detail = deactivation.result(timeout=10)

    assert writer_status == 200
    assert deactivation_status == 409
    with Session(pg_engine) as session:
        target = session.get(CompanyMembership, fixture["target_id"])
        deadline = session.scalar(
            select(MatterDeadline).where(
                MatterDeadline.matter_id == fixture["linked_matter_id"],
                MatterDeadline.title == "Concurrent generic linked-IP deadline",
            )
        )
        assert target is not None and target.is_active is True
        assert deadline is not None
        assert deadline.assignee_membership_id == fixture["target_id"]


def _seed_team_role_race_fixture(
    session: Session,
    *,
    scoping_enabled: bool,
    target_on_team: bool,
) -> dict[str, str]:
    from caseops_api.db.models import (
        Company,
        CompanyMembership,
        IpDocketRecord,
        Matter,
        Team,
        TeamMembership,
    )

    company_id = _seed_company(session)
    actor_id = _seed_membership(session, company_id)
    target_id = _seed_membership(session, company_id)
    actor = session.get(CompanyMembership, actor_id)
    company = session.get(Company, company_id)
    assert actor is not None and company is not None
    actor.role = "owner"
    company.team_scoping_enabled = scoping_enabled
    team = Team(
        company_id=company_id,
        name="PostgreSQL role fence team",
        slug=f"pg-role-fence-{str(uuid4())[:8]}",
        kind="team",
        is_active=True,
    )
    session.add(team)
    session.flush()
    if target_on_team:
        session.add(TeamMembership(team_id=team.id, membership_id=target_id))

    matter_id = _seed_matter(session, company_id)
    matter = session.get(Matter, matter_id)
    assert matter is not None
    matter.team_id = team.id
    docket = IpDocketRecord(
        company_id=company_id,
        matter_id=matter_id,
        record_type="trademark",
        title="Team mutation race docket",
        primary_identifier=f"PG-TEAM-ROLE-{str(uuid4())[:8]}",
        status="active",
        is_active=True,
        restricted=False,
        created_by_membership_id=actor_id,
    )
    session.add(docket)
    session.commit()
    return {
        "company_id": company_id,
        "actor_id": actor_id,
        "target_id": target_id,
        "team_id": team.id,
        "matter_id": matter_id,
        "docket_id": docket.id,
    }


def test_team_removal_wins_concurrent_linked_role_assignment_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removal holds Membership first; the waiting assignment reauthorizes."""

    from caseops_api.db.models import MatterTask, TeamMembership
    from caseops_api.services import teams as team_service

    with Session(pg_engine) as seed:
        fixture = _seed_team_role_race_fixture(
            seed,
            scoping_enabled=True,
            target_on_team=True,
        )

    removal_holds_fence = Event()
    release_removal = Event()
    original_record = team_service.record_from_context

    def paused_record(*args, **kwargs):
        result = original_record(*args, **kwargs)
        if kwargs.get("action") == "team_membership.removed":
            removal_holds_fence.set()
            if not release_removal.wait(timeout=10):
                raise TimeoutError("Concurrent Matter assignment did not release team removal.")
        return result

    monkeypatch.setattr(team_service, "record_from_context", paused_record)
    application_name = f"caseops-task-after-team-removal-{str(uuid4())[:8]}"

    def remove_member() -> None:
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["actor_id"],
            )
            team_service.remove_team_member(
                session,
                context=context,
                team_id=fixture["team_id"],
                membership_id=fixture["target_id"],
            )
            session.commit()

    def assign_role() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            return _run_matter_role_writer(
                session,
                fixture={
                    **fixture,
                    "linked_matter_id": fixture["matter_id"],
                },
                writer_kind="task_create",
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        removal = executor.submit(remove_member)
        assignment = None
        try:
            assert removal_holds_fence.wait(timeout=10)
            assignment = executor.submit(assign_role)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_removal.set()
        removal.result(timeout=10)
        assert assignment is not None
        assignment_status, _detail = assignment.result(timeout=10)

    assert assignment_status == 400
    with Session(pg_engine) as session:
        assert session.scalar(
            select(TeamMembership.id).where(
                TeamMembership.team_id == fixture["team_id"],
                TeamMembership.membership_id == fixture["target_id"],
            )
        ) is None
        assert session.scalar(
            select(MatterTask.id).where(
                MatterTask.matter_id == fixture["matter_id"],
                MatterTask.owner_membership_id == fixture["target_id"],
            )
        ) is None


def test_linked_role_assignment_wins_concurrent_scoping_enable_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parent revalidation catches a role committed while scoping waited."""

    from fastapi import HTTPException

    from caseops_api.db.models import Company, MatterTask
    from caseops_api.services import matters as matter_service
    from caseops_api.services import teams as team_service

    with Session(pg_engine) as seed:
        fixture = _seed_team_role_race_fixture(
            seed,
            scoping_enabled=False,
            target_on_team=False,
        )

    writer_holds_fence = Event()
    release_writer = Event()
    original_append = matter_service._append_activity

    def paused_append(*args, **kwargs):
        result = original_append(*args, **kwargs)
        if kwargs.get("event_type") == "task_added":
            writer_holds_fence.set()
            if not release_writer.wait(timeout=10):
                raise TimeoutError("Team scoping did not release Matter assignment.")
        return result

    monkeypatch.setattr(matter_service, "_append_activity", paused_append)
    application_name = f"caseops-scope-after-task-{str(uuid4())[:8]}"

    def assign_role() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            return _run_matter_role_writer(
                session,
                fixture={
                    **fixture,
                    "linked_matter_id": fixture["matter_id"],
                },
                writer_kind="task_create",
            )

    def enable_scoping() -> tuple[int, object]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["actor_id"],
            )
            try:
                team_service.set_team_scoping(
                    session,
                    context=context,
                    enabled=True,
                )
                session.commit()
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Team scoping ignored the committed linked-IP role.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        assignment = executor.submit(assign_role)
        scoping = None
        try:
            assert writer_holds_fence.wait(timeout=10)
            scoping = executor.submit(enable_scoping)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_writer.set()
        assignment_status, _detail = assignment.result(timeout=10)
        assert scoping is not None
        scoping_status, scoping_detail = scoping.result(timeout=10)

    assert assignment_status == 200
    assert scoping_status == 409
    assert scoping_detail["code"] == "ip_team_access_responsibility_changed"
    with Session(pg_engine) as session:
        company = session.get(Company, fixture["company_id"])
        assert company is not None and company.team_scoping_enabled is False
        assert session.scalar(
            select(MatterTask.id).where(
                MatterTask.matter_id == fixture["matter_id"],
                MatterTask.owner_membership_id == fixture["target_id"],
            )
        ) is not None


def _seed_unrelated_actor_mutation_fixture(session: Session) -> dict[str, str]:
    from caseops_api.db.models import (
        CompanyMembership,
        IpDocketRecord,
        Matter,
        Team,
    )

    company_id = _seed_company(session)
    owner_id = _seed_membership(session, company_id)
    writer_id = _seed_membership(session, company_id)
    owner = session.get(CompanyMembership, owner_id)
    writer = session.get(CompanyMembership, writer_id)
    assert owner is not None and writer is not None
    owner.role = "owner"
    # Representative Matter and Team mutations below are route-authorized
    # writes, not a capability-bypass fixture.  Keep this unrelated actor an
    # OWNER so the locked teams:manage recheck exercises deactivation ordering
    # rather than correctly rejecting the stale MEMBER authorization.
    writer.role = "admin"
    matter_id = _seed_matter(session, company_id)
    matter = session.get(Matter, matter_id)
    assert matter is not None
    matter.assignee_membership_id = owner_id
    docket = IpDocketRecord(
        company_id=company_id,
        matter_id=matter_id,
        record_type="trademark",
        title="Unrelated actor fence docket",
        primary_identifier=f"PG-ACTOR-FENCE-{str(uuid4())[:8]}",
        status="active",
        is_active=True,
        restricted=False,
        created_by_membership_id=owner_id,
    )
    team = Team(
        company_id=company_id,
        name="Unrelated actor fence team",
        slug=f"pg-actor-fence-{str(uuid4())[:8]}",
        kind="team",
        is_active=True,
    )
    session.add_all([docket, team])
    session.commit()
    return {
        "company_id": company_id,
        "owner_id": owner_id,
        "writer_id": writer_id,
        "matter_id": matter_id,
        "docket_id": docket.id,
        "team_id": team.id,
    }


def _run_unrelated_actor_mutation(
    session: Session,
    *,
    fixture: dict[str, str],
    mutation_kind: str,
) -> tuple[int, object | None]:
    from fastapi import HTTPException

    from caseops_api.schemas.matters import MatterTaskCreateRequest
    from caseops_api.schemas.teams import TeamUpdateRequest
    from caseops_api.services import matters as matter_service
    from caseops_api.services import teams as team_service

    context = _ip_race_context(
        session,
        company_id=fixture["company_id"],
        membership_id=fixture["writer_id"],
    )
    try:
        if mutation_kind == "matter_task":
            matter_service.create_matter_task(
                session,
                context=context,
                matter_id=fixture["matter_id"],
                payload=MatterTaskCreateRequest(
                    title="Unrelated actor concurrent task",
                    owner_membership_id=fixture["owner_id"],
                    status="todo",
                    priority="high",
                ),
            )
        elif mutation_kind == "team_deactivate":
            team_service.update_team(
                session,
                context=context,
                team_id=fixture["team_id"],
                payload=TeamUpdateRequest(is_active=False),
            )
            session.commit()
        elif mutation_kind == "team_delete":
            team_service.delete_team(
                session,
                context=context,
                team_id=fixture["team_id"],
            )
            session.commit()
        else:  # pragma: no cover - parametrization owns the values
            raise AssertionError(f"Unknown mutation kind: {mutation_kind}")
    except HTTPException as exc:
        session.rollback()
        return exc.status_code, exc.detail
    return 200, None


@pytest.mark.parametrize("mutation_kind", ("matter_task", "team_delete"))
def test_unrelated_actor_deactivation_wins_mutation_without_deadlock_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    mutation_kind: str,
) -> None:
    """A deactivated caller cannot acquire a late audit/activity FK."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, MatterTask, Team
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_unrelated_actor_mutation_fixture(seed)

    deactivation_holds_actor = Event()
    release_deactivation = Event()
    original_guard = identity_service.assert_no_operational_ip_work_before_deactivation

    def paused_guard(*args, **kwargs):
        deactivation_holds_actor.set()
        if not release_deactivation.wait(timeout=10):
            raise TimeoutError("Unrelated actor mutation did not reach its lock wait.")
        return original_guard(*args, **kwargs)

    monkeypatch.setattr(
        identity_service,
        "assert_no_operational_ip_work_before_deactivation",
        paused_guard,
    )
    application_name = f"caseops-mutation-after-actor-off-{str(uuid4())[:8]}"

    def deactivate_actor() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["writer_id"],
                    payload=CompanyUserUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    def mutate() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            return _run_unrelated_actor_mutation(
                session,
                fixture=fixture,
                mutation_kind=mutation_kind,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        deactivation = executor.submit(deactivate_actor)
        mutation = None
        try:
            assert deactivation_holds_actor.wait(timeout=10)
            mutation = executor.submit(mutate)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_deactivation.set()
        deactivation_status, _deactivation_detail = deactivation.result(timeout=10)
        assert mutation is not None
        mutation_status, _mutation_detail = mutation.result(timeout=10)

    assert deactivation_status == 200
    assert mutation_status == 403
    with Session(pg_engine) as session:
        writer = session.get(CompanyMembership, fixture["writer_id"])
        team = session.get(Team, fixture["team_id"])
        assert writer is not None and writer.is_active is False
        assert team is not None and team.is_active is True
        assert session.scalar(
            select(MatterTask.id).where(
                MatterTask.matter_id == fixture["matter_id"],
                MatterTask.title == "Unrelated actor concurrent task",
            )
        ) is None


@pytest.mark.parametrize("mutation_kind", ("matter_task", "team_deactivate"))
def test_unrelated_actor_mutation_wins_then_deactivation_completes_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    mutation_kind: str,
) -> None:
    """Matter and Team writers fence the actor before parent/audit rows."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, MatterTask, Team
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service
    from caseops_api.services import matters as matter_service
    from caseops_api.services import teams as team_service

    with Session(pg_engine) as seed:
        fixture = _seed_unrelated_actor_mutation_fixture(seed)

    mutation_holds_actor = Event()
    release_mutation = Event()
    if mutation_kind == "matter_task":
        original_append = matter_service._append_activity

        def paused_append(*args, **kwargs):
            result = original_append(*args, **kwargs)
            if kwargs.get("event_type") == "task_added":
                mutation_holds_actor.set()
                if not release_mutation.wait(timeout=10):
                    raise TimeoutError("Actor deactivation did not wait on Matter writer.")
            return result

        monkeypatch.setattr(matter_service, "_append_activity", paused_append)
    else:
        original_record = team_service.record_from_context

        def paused_record(*args, **kwargs):
            result = original_record(*args, **kwargs)
            if kwargs.get("action") == "team.updated":
                mutation_holds_actor.set()
                if not release_mutation.wait(timeout=10):
                    raise TimeoutError("Actor deactivation did not wait on Team writer.")
            return result

        monkeypatch.setattr(team_service, "record_from_context", paused_record)

    application_name = f"caseops-actor-off-after-mutation-{str(uuid4())[:8]}"

    def mutate() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            return _run_unrelated_actor_mutation(
                session,
                fixture=fixture,
                mutation_kind=mutation_kind,
            )

    def deactivate_actor() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["writer_id"],
                    payload=CompanyUserUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    with ThreadPoolExecutor(max_workers=2) as executor:
        mutation = executor.submit(mutate)
        deactivation = None
        try:
            assert mutation_holds_actor.wait(timeout=10)
            deactivation = executor.submit(deactivate_actor)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_mutation.set()
        mutation_status, _mutation_detail = mutation.result(timeout=10)
        assert deactivation is not None
        deactivation_status, _deactivation_detail = deactivation.result(timeout=10)

    assert mutation_status == 200
    assert deactivation_status == 200
    with Session(pg_engine) as session:
        writer = session.get(CompanyMembership, fixture["writer_id"])
        team = session.get(Team, fixture["team_id"])
        assert writer is not None and writer.is_active is False
        assert team is not None
        assert team.is_active is (mutation_kind != "team_deactivate")
        task = session.scalar(
            select(MatterTask).where(
                MatterTask.matter_id == fixture["matter_id"],
                MatterTask.title == "Unrelated actor concurrent task",
            )
        )
        assert (task is not None) is (mutation_kind == "matter_task")


def _seed_core_ip_actor_fence_fixture(session: Session) -> dict[str, str]:
    from caseops_api.db.models import MatterDeadline

    fixture = _seed_unrelated_actor_mutation_fixture(session)
    deadline = MatterDeadline(
        company_id=fixture["company_id"],
        matter_id=fixture["matter_id"],
        source="custom",
        kind="response",
        title="Unrelated actor coverage projection",
        due_on=date.today() + timedelta(days=40),
        status="open",
        assignee_membership_id=fixture["owner_id"],
        created_by_membership_id=fixture["owner_id"],
    )
    session.add(deadline)
    session.commit()
    return {**fixture, "deadline_id": deadline.id}


def _run_core_ip_unrelated_actor_writer(
    session: Session,
    *,
    fixture: dict[str, str],
    writer_kind: str,
) -> tuple[int, object | None]:
    from fastapi import HTTPException

    from caseops_api.schemas.ip_operations import IpDeadlineCoverageCreateRequest
    from caseops_api.schemas.shared_work import IpSharedTaskCreateRequest
    from caseops_api.services import ip_operations, shared_work

    context = _ip_race_context(
        session,
        company_id=fixture["company_id"],
        membership_id=fixture["writer_id"],
    )
    try:
        if writer_kind == "shared_task":
            shared_work.create_ip_shared_task(
                session,
                context=context,
                payload=IpSharedTaskCreateRequest(
                    docket_id=fixture["docket_id"],
                    title="Unrelated actor shared task",
                    owner_membership_id=fixture["owner_id"],
                    status="todo",
                    priority="high",
                ),
            )
        elif writer_kind == "coverage_add":
            ip_operations.add_ip_deadline_coverage(
                session,
                context=context,
                docket_id=fixture["docket_id"],
                payload=IpDeadlineCoverageCreateRequest(
                    matter_deadline_id=fixture["deadline_id"],
                    responsible_membership_id=fixture["owner_id"],
                ),
            )
        else:  # pragma: no cover - parametrization owns the values
            raise AssertionError(f"Unknown core IP writer: {writer_kind}")
    except HTTPException as exc:
        session.rollback()
        return exc.status_code, exc.detail
    return 200, None


@pytest.mark.parametrize("writer_kind", ("shared_task", "coverage_add"))
def test_unrelated_actor_deactivation_wins_core_ip_writer_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    writer_kind: str,
) -> None:
    """Every core IP writer waits on and refreshes its unrelated actor."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, IpDeadlineCoverage, MatterTask
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_core_ip_actor_fence_fixture(seed)

    deactivation_holds_actor = Event()
    release_deactivation = Event()
    original_guard = identity_service.assert_no_operational_ip_work_before_deactivation

    def paused_guard(*args, **kwargs):
        deactivation_holds_actor.set()
        if not release_deactivation.wait(timeout=10):
            raise TimeoutError("Core IP writer did not reach the actor fence.")
        return original_guard(*args, **kwargs)

    monkeypatch.setattr(
        identity_service,
        "assert_no_operational_ip_work_before_deactivation",
        paused_guard,
    )
    application_name = f"caseops-core-ip-after-actor-off-{str(uuid4())[:8]}"

    def deactivate_actor() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["writer_id"],
                    payload=CompanyUserUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    def write_ip_work() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            return _run_core_ip_unrelated_actor_writer(
                session,
                fixture=fixture,
                writer_kind=writer_kind,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        deactivation = executor.submit(deactivate_actor)
        writer = None
        try:
            assert deactivation_holds_actor.wait(timeout=10)
            writer = executor.submit(write_ip_work)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
        finally:
            release_deactivation.set()
        deactivation_status, _detail = deactivation.result(timeout=10)
        assert writer is not None
        writer_status, _writer_detail = writer.result(timeout=10)

    assert deactivation_status == 200
    assert writer_status in {400, 403, 404}
    with Session(pg_engine) as session:
        actor = session.get(CompanyMembership, fixture["writer_id"])
        assert actor is not None and actor.is_active is False
        assert session.scalar(
            select(MatterTask.id).where(
                MatterTask.ip_docket_id == fixture["docket_id"],
                MatterTask.title == "Unrelated actor shared task",
            )
        ) is None
        assert session.scalar(
            select(IpDeadlineCoverage.id).where(
                IpDeadlineCoverage.matter_deadline_id == fixture["deadline_id"]
            )
        ) is None


def test_core_ip_writer_wins_then_unrelated_actor_deactivation_waits_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actor fence is acquired before the docket/task/audit transaction."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, MatterTask
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service
    from caseops_api.services import shared_work

    with Session(pg_engine) as seed:
        fixture = _seed_core_ip_actor_fence_fixture(seed)

    writer_holds_actor = Event()
    release_writer = Event()
    original_record = shared_work.record_from_context

    def paused_record(*args, **kwargs):
        result = original_record(*args, **kwargs)
        if kwargs.get("action") == "shared_task.created":
            writer_holds_actor.set()
            if not release_writer.wait(timeout=10):
                raise TimeoutError("Actor deactivation did not wait on the IP writer.")
        return result

    monkeypatch.setattr(shared_work, "record_from_context", paused_record)
    application_name = f"caseops-actor-off-after-core-ip-{str(uuid4())[:8]}"

    def write_ip_work() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            return _run_core_ip_unrelated_actor_writer(
                session,
                fixture=fixture,
                writer_kind="shared_task",
            )

    def deactivate_actor() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["writer_id"],
                    payload=CompanyUserUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(write_ip_work)
        deactivation = None
        try:
            assert writer_holds_actor.wait(timeout=10)
            deactivation = executor.submit(deactivate_actor)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
        finally:
            release_writer.set()
        writer_status, _detail = writer.result(timeout=10)
        assert deactivation is not None
        deactivation_status, _deactivation_detail = deactivation.result(timeout=10)

    assert writer_status == 200
    assert deactivation_status == 200
    with Session(pg_engine) as session:
        actor = session.get(CompanyMembership, fixture["writer_id"])
        task = session.scalar(
            select(MatterTask).where(
                MatterTask.ip_docket_id == fixture["docket_id"],
                MatterTask.title == "Unrelated actor shared task",
            )
        )
        assert actor is not None and actor.is_active is False
        assert task is not None and task.owner_membership_id == fixture["owner_id"]


def test_create_ip_docket_rejects_concurrent_linked_child_role_change_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-Matter snapshot rejects a child-role change that won first."""

    from fastapi import HTTPException

    from caseops_api.db.models import (
        CompanyMembership,
        IpDocketRecord,
        Matter,
        MatterTask,
    )
    from caseops_api.schemas.ip_operations import IpDocketCreateRequest
    from caseops_api.schemas.matters import MatterTaskUpdateRequest
    from caseops_api.services import ip_operations
    from caseops_api.services import matters as matter_service
    from tests.test_ip_record_workflow import _particulars

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        actor_id = _seed_membership(seed, company_id)
        old_owner_id = _seed_membership(seed, company_id)
        new_owner_id = _seed_membership(seed, company_id)
        actor = seed.get(CompanyMembership, actor_id)
        assert actor is not None
        actor.role = "owner"
        matter_id = _seed_matter(seed, company_id)
        matter = seed.get(Matter, matter_id)
        assert matter is not None
        matter.assignee_membership_id = actor_id
        task = MatterTask(
            company_id=company_id,
            matter_id=matter_id,
            created_by_membership_id=actor_id,
            owner_membership_id=old_owner_id,
            title="Role changes while docket linking waits",
            status="todo",
            priority="high",
        )
        seed.add(task)
        seed.commit()
        task_id = task.id

    mutation_staged = Event()
    release_mutation = Event()
    original_append = matter_service._append_activity
    observed_role_snapshots: list[object] = []
    original_role_snapshot = ip_operations._operational_matter_role_snapshot

    def observing_role_snapshot(*args, **kwargs):
        snapshot = original_role_snapshot(*args, **kwargs)
        observed_role_snapshots.append(snapshot)
        return snapshot

    def paused_append(*args, **kwargs):
        result = original_append(*args, **kwargs)
        if kwargs.get("event_type") == "task_updated":
            mutation_staged.set()
            if not release_mutation.wait(timeout=10):
                raise TimeoutError("IP docket creation did not wait on role mutation.")
        return result

    monkeypatch.setattr(matter_service, "_append_activity", paused_append)
    monkeypatch.setattr(
        ip_operations,
        "_operational_matter_role_snapshot",
        observing_role_snapshot,
    )
    application_name = f"caseops-ip-link-after-role-change-{str(uuid4())[:8]}"

    def mutate_child_role() -> None:
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=company_id,
                membership_id=actor_id,
            )
            matter_service.update_matter_task(
                session,
                context=context,
                matter_id=matter_id,
                task_id=task_id,
                payload=MatterTaskUpdateRequest(owner_membership_id=new_owner_id),
            )
            session.commit()

    def create_linked_docket() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=company_id,
                membership_id=actor_id,
            )
            try:
                result = ip_operations.create_ip_docket(
                    session,
                    context=context,
                    payload=IpDocketCreateRequest(
                        title="Must retry after linked child role changes",
                        matter_id=matter_id,
                        restricted=False,
                        particulars=_particulars("PG LINK ROLE CHANGE"),
                    ),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, result.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        mutation = executor.submit(mutate_child_role)
        creation = None
        try:
            assert mutation_staged.wait(timeout=10)
            creation = executor.submit(create_linked_docket)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
        finally:
            release_mutation.set()
        mutation.result(timeout=10)
        assert creation is not None
        creation_status, creation_detail = creation.result(timeout=10)

    assert len(observed_role_snapshots) == 2
    assert observed_role_snapshots[0] != observed_role_snapshots[1]
    assert creation_status == 409
    assert creation_detail["code"] == "ip_docket_linked_matter_roles_changed"
    with Session(pg_engine) as session:
        persisted_task = session.get(MatterTask, task_id)
        assert persisted_task is not None
        assert persisted_task.owner_membership_id == new_owner_id
        assert session.scalar(
            select(IpDocketRecord.id).where(IpDocketRecord.matter_id == matter_id)
        ) is None


def test_ip_access_change_wins_generic_linked_deadline_assignment_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A waiting generic assignment revalidates the whole docket ACL family."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, MatterDeadline
    from caseops_api.schemas.ip_access import IpAccessApplyRequest, IpAccessChangeRequest
    from caseops_api.services import deadlines as deadline_service
    from caseops_api.services import matter_access
    from caseops_api.services.matter_access import (
        apply_ip_access_change,
        preview_ip_access_change,
    )

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)
        owner = seed.get(CompanyMembership, fixture["owner_id"])
        assert owner is not None
        owner.role = "owner"
        seed.commit()

    access_payload = IpAccessChangeRequest(
        action="add_wall",
        expected_access_policy_version=0,
        reason="Concurrent wall must win before a generic deadline assignment.",
        subject_type="membership",
        subject_id=fixture["replacement_id"],
    )
    with Session(pg_engine) as preview_session:
        context = _ip_race_context(
            preview_session,
            company_id=fixture["company_id"],
            membership_id=fixture["owner_id"],
        )
        preview = preview_ip_access_change(
            preview_session,
            context=context,
            docket_id=fixture["docket_id"],
            payload=access_payload,
        )

    access_staged = Event()
    release_access = Event()
    original_record = matter_access.record_from_context

    def paused_record(*args, **kwargs):
        result = original_record(*args, **kwargs)
        if kwargs.get("action") == "ip.access.add_wall":
            access_staged.set()
            if not release_access.wait(timeout=10):
                raise TimeoutError("Generic deadline assignment did not reach its wait.")
        return result

    monkeypatch.setattr(matter_access, "record_from_context", paused_record)
    application_name = f"caseops-generic-deadline-after-wall-{str(uuid4())[:8]}"

    def apply_wall() -> None:
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            apply_ip_access_change(
                session,
                context=context,
                docket_id=fixture["docket_id"],
                payload=IpAccessApplyRequest(
                    **access_payload.model_dump(),
                    preview_token=preview.preview_token,
                ),
            )

    def assign_deadline() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                deadline_service.create_deadline(
                    session,
                    context=context,
                    matter_id=fixture["matter_id"],
                    source="custom",
                    kind="response",
                    title="Must not outlive a winning IP wall",
                    due_on=date.today() + timedelta(days=45),
                    assignee_membership_id=fixture["replacement_id"],
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Generic deadline ignored a committed IP wall.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        access = executor.submit(apply_wall)
        assignment = None
        try:
            assert access_staged.wait(timeout=10)
            assignment = executor.submit(assign_deadline)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
        finally:
            release_access.set()
        access.result(timeout=10)
        assert assignment is not None
        assignment_status, assignment_detail = assignment.result(timeout=10)

    assert assignment_status in {400, 409}
    if assignment_status == 409:
        assert assignment_detail["code"] == "ip_linked_docket_family_changed"
    with Session(pg_engine) as session:
        assert session.scalar(
            select(MatterDeadline.id).where(
                MatterDeadline.matter_id == fixture["matter_id"],
                MatterDeadline.title == "Must not outlive a winning IP wall",
            )
        ) is None


def test_ip_docket_lifecycle_wins_generic_linked_deadline_assignment_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal docket family cannot gain a late generic deadline owner."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, MatterDeadline
    from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
    from caseops_api.services import deadlines as deadline_service
    from caseops_api.services import ip_lifecycle

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)
        owner = seed.get(CompanyMembership, fixture["owner_id"])
        assert owner is not None
        owner.role = "owner"
        seed.commit()

    lifecycle_staged = Event()
    release_lifecycle = Event()
    original_record = ip_lifecycle.record_from_context

    def paused_record(*args, **kwargs):
        result = original_record(*args, **kwargs)
        if kwargs.get("action") == "ip_docket.lifecycle_transitioned":
            lifecycle_staged.set()
            if not release_lifecycle.wait(timeout=10):
                raise TimeoutError("Generic deadline assignment did not reach its wait.")
        return result

    monkeypatch.setattr(ip_lifecycle, "record_from_context", paused_record)
    application_name = f"caseops-generic-deadline-after-close-{str(uuid4())[:8]}"

    def close_docket() -> None:
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            ip_lifecycle.transition_ip_docket_lifecycle(
                session,
                context=context,
                docket_id=fixture["docket_id"],
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=0,
                    to_status="closed",
                    effective_at=datetime.now(UTC),
                    reason="Concurrent terminal disposition wins.",
                    outcome="closed",
                    source="lawyer_review",
                    evidence_ref="fixture:pg-generic-deadline-close",
                    linked_matter_handling="reviewed",
                ),
            )

    def assign_deadline() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                deadline_service.create_deadline(
                    session,
                    context=context,
                    matter_id=fixture["matter_id"],
                    source="custom",
                    kind="response",
                    title="Must not attach after docket closure",
                    due_on=date.today() + timedelta(days=50),
                    assignee_membership_id=fixture["replacement_id"],
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            raise AssertionError("Generic deadline ignored terminal linked IP work.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        lifecycle = executor.submit(close_docket)
        assignment = None
        try:
            assert lifecycle_staged.wait(timeout=10)
            assignment = executor.submit(assign_deadline)
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
        finally:
            release_lifecycle.set()
        lifecycle.result(timeout=10)
        assert assignment is not None
        assignment_status, assignment_detail = assignment.result(timeout=10)

    assert assignment_status == 409
    assert assignment_detail["code"] == "ip_linked_docket_family_changed"
    with Session(pg_engine) as session:
        assert session.scalar(
            select(MatterDeadline.id).where(
                MatterDeadline.matter_id == fixture["matter_id"],
                MatterDeadline.title == "Must not attach after docket closure",
            )
        ) is None


# ---------- final locked-capability / actor-fence races (2026-08-17) ----------


def _seed_locked_capability_employee_fixture(
    session: Session,
    *,
    custom_actor: bool,
) -> dict[str, str]:
    from caseops_api.db.models import CompanyMembership, CustomRole, User

    company_id = _seed_company(session)
    owner_id = _seed_membership(session, company_id)
    actor_id = _seed_membership(session, company_id)
    target_id = _seed_membership(session, company_id)
    owner = session.get(CompanyMembership, owner_id)
    actor = session.get(CompanyMembership, actor_id)
    target = session.get(CompanyMembership, target_id)
    assert owner is not None and actor is not None and target is not None
    owner.role = "owner"
    actor.role = "member" if custom_actor else "admin"
    role_id = ""
    if custom_actor:
        role = CustomRole(
            company_id=company_id,
            name=f"PG employee manager {str(uuid4())[:8]}",
            slug=f"pg-employee-manager-{str(uuid4())[:8]}",
            base_role="member",
            permissions_json=["company:manage_users"],
            is_system=False,
            is_active=True,
            created_by_membership_id=owner_id,
            updated_by_membership_id=owner_id,
        )
        session.add(role)
        session.flush()
        actor.custom_role_id = role.id
        role_id = role.id
    target_user = session.get(User, target.user_id)
    assert target_user is not None
    target_user.full_name = "Capability target before"
    session.commit()
    return {
        "company_id": company_id,
        "owner_id": owner_id,
        "actor_id": actor_id,
        "target_id": target_id,
        "target_user_id": target.user_id,
        "role_id": role_id,
    }


def _run_capability_employee_writer(
    session: Session,
    *,
    fixture: dict[str, str],
) -> tuple[int, object | None]:
    from fastapi import HTTPException

    from caseops_api.schemas.employees import EmployeeUpdateRequest
    from caseops_api.services import employees

    context = _ip_race_context(
        session,
        company_id=fixture["company_id"],
        membership_id=fixture["actor_id"],
    )
    try:
        employees.update_employee(
            session,
            context=context,
            membership_id=fixture["target_id"],
            payload=EmployeeUpdateRequest(full_name="Capability target after"),
        )
    except HTTPException as exc:
        session.rollback()
        return exc.status_code, exc.detail
    return 200, None


@pytest.mark.parametrize("ordering", ("writer_first", "role_update_first"))
def test_custom_role_update_serializes_with_locked_employee_capability_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    ordering: str,
) -> None:
    """The Membership row, not a reverse CustomRole lock, is the capability seam."""

    from fastapi import HTTPException

    from caseops_api.db.models import CustomRole, User
    from caseops_api.schemas.custom_roles import CustomRoleUpdateRequest
    from caseops_api.services import custom_roles, employees

    with Session(pg_engine) as seed:
        fixture = _seed_locked_capability_employee_fixture(seed, custom_actor=True)

    first_holds_actor = Event()
    release_first = Event()
    application_name = f"caseops-custom-role-cap-{ordering}-{str(uuid4())[:8]}"

    if ordering == "writer_first":
        original_capability = employees.require_locked_membership_capability

        def paused_capability(*args, **kwargs):
            first_holds_actor.set()
            if not release_first.wait(timeout=10):
                raise TimeoutError("Custom-role updater did not wait on the writer fence.")
            return original_capability(*args, **kwargs)

        monkeypatch.setattr(
            employees,
            "require_locked_membership_capability",
            paused_capability,
        )
    else:
        original_record = custom_roles.record_from_context

        def paused_role_record(*args, **kwargs):
            result = original_record(*args, **kwargs)
            args[0].flush()
            first_holds_actor.set()
            if not release_first.wait(timeout=10):
                raise TimeoutError("Employee writer did not wait on role invalidation.")
            return result

        monkeypatch.setattr(custom_roles, "record_from_context", paused_role_record)

    def update_role() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            if ordering == "writer_first":
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                custom_roles.update_custom_role(
                    session,
                    context=context,
                    role_id=fixture["role_id"],
                    payload=CustomRoleUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    def write_employee() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            if ordering == "role_update_first":
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            return _run_capability_employee_writer(session, fixture=fixture)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            write_employee if ordering == "writer_first" else update_role
        )
        second = None
        try:
            assert first_holds_actor.wait(timeout=10)
            second = executor.submit(
                update_role if ordering == "writer_first" else write_employee
            )
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_first.set()
        first_status, _first_detail = first.result(timeout=15)
        assert second is not None
        second_status, _second_detail = second.result(timeout=15)

    writer_status = first_status if ordering == "writer_first" else second_status
    role_status = second_status if ordering == "writer_first" else first_status
    assert role_status == 200
    assert writer_status == (200 if ordering == "writer_first" else 403)
    with Session(pg_engine) as session:
        role = session.get(CustomRole, fixture["role_id"])
        target = session.get(User, fixture["target_user_id"])
        assert role is not None and role.is_active is False
        assert target is not None
        assert target.full_name == (
            "Capability target after"
            if ordering == "writer_first"
            else "Capability target before"
        )


def test_custom_role_update_and_membership_invalidation_roll_back_atomically_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.db.models import CompanyMembership, CustomRole, User
    from caseops_api.schemas.custom_roles import CustomRoleUpdateRequest
    from caseops_api.services import custom_roles

    with Session(pg_engine) as seed:
        fixture = _seed_locked_capability_employee_fixture(seed, custom_actor=True)
        actor = seed.get(CompanyMembership, fixture["actor_id"])
        assert actor is not None
        initial_cutoff = actor.sessions_valid_after

    original_record = custom_roles.record_from_context

    def fail_after_invalidation(*args, **kwargs):
        original_record(*args, **kwargs)
        args[0].flush()
        raise RuntimeError("force atomic rollback after membership invalidation")

    monkeypatch.setattr(custom_roles, "record_from_context", fail_after_invalidation)
    with Session(pg_engine) as session:
        context = _ip_race_context(
            session,
            company_id=fixture["company_id"],
            membership_id=fixture["owner_id"],
        )
        with pytest.raises(RuntimeError, match="force atomic rollback"):
            custom_roles.update_custom_role(
                session,
                context=context,
                role_id=fixture["role_id"],
                payload=CustomRoleUpdateRequest(is_active=False),
            )
        session.rollback()

    with Session(pg_engine) as session:
        role = session.get(CustomRole, fixture["role_id"])
        actor = session.get(CompanyMembership, fixture["actor_id"])
        assert role is not None and role.is_active is True and role.revoked_at is None
        assert actor is not None and actor.sessions_valid_after == initial_cutoff
        assert _run_capability_employee_writer(session, fixture=fixture)[0] == 200
    with Session(pg_engine) as session:
        target = session.get(User, fixture["target_user_id"])
        assert target is not None and target.full_name == "Capability target after"


@pytest.mark.parametrize("ordering", ("deactivation_first", "acknowledgement_first"))
def test_bulk_acknowledge_serializes_with_actor_deactivation_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    ordering: str,
) -> None:
    """Both orders avoid a late audit FK and preserve the live-role blocker."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, IpDeadlineCoverage
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.schemas.ip_operations import IpCoverageBulkAcknowledgeRequest
    from caseops_api.services import identity as identity_service
    from caseops_api.services import ip_operations

    with Session(pg_engine) as seed:
        fixture = _seed_ip_coverage_lifecycle_fixture(seed)
        deactivator = seed.get(CompanyMembership, fixture["replacement_id"])
        assert deactivator is not None
        deactivator.role = "owner"
        seed.commit()

    first_holds_actor = Event()
    release_first = Event()
    application_name = f"caseops-bulk-ack-{ordering}-{str(uuid4())[:8]}"
    if ordering == "deactivation_first":
        original_guard = identity_service.assert_no_operational_ip_work_before_deactivation

        def paused_guard(*args, **kwargs):
            first_holds_actor.set()
            if not release_first.wait(timeout=10):
                raise TimeoutError("Bulk acknowledgement did not wait on deactivation.")
            return original_guard(*args, **kwargs)

        monkeypatch.setattr(
            identity_service,
            "assert_no_operational_ip_work_before_deactivation",
            paused_guard,
        )
    else:
        original_record = ip_operations.record_from_context

        def paused_ack_record(*args, **kwargs):
            result = original_record(*args, **kwargs)
            if kwargs.get("action") == "ip_deadline_coverage.bulk_acknowledged":
                first_holds_actor.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError("Deactivation did not wait on acknowledgement.")
            return result

        monkeypatch.setattr(ip_operations, "record_from_context", paused_ack_record)

    def deactivate() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            if ordering == "acknowledgement_first":
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["replacement_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["owner_id"],
                    payload=CompanyUserUpdateRequest(is_active=False),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    def acknowledge() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            if ordering == "deactivation_first":
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                response = ip_operations.bulk_acknowledge_ip_coverage(
                    session,
                    context=context,
                    payload=IpCoverageBulkAcknowledgeRequest(
                        coverage_ids=[fixture["coverage_id"]]
                    ),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, response.acknowledged_count

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            deactivate if ordering == "deactivation_first" else acknowledge
        )
        second = None
        try:
            assert first_holds_actor.wait(timeout=10)
            second = executor.submit(
                acknowledge if ordering == "deactivation_first" else deactivate
            )
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_first.set()
        first_status, first_detail = first.result(timeout=15)
        assert second is not None
        second_status, second_detail = second.result(timeout=15)

    acknowledge_result = (
        (second_status, second_detail)
        if ordering == "deactivation_first"
        else (first_status, first_detail)
    )
    deactivate_result = (
        (first_status, first_detail)
        if ordering == "deactivation_first"
        else (second_status, second_detail)
    )
    assert acknowledge_result == (200, 1)
    assert deactivate_result[0] == 409
    assert deactivate_result[1]["code"] == "employee_offboarding_required"
    assert deactivate_result[1]["live_reference_counts"]["ip_deadline_coverages"] == 1
    with Session(pg_engine) as session:
        actor = session.get(CompanyMembership, fixture["owner_id"])
        coverage = session.get(IpDeadlineCoverage, fixture["coverage_id"])
        assert actor is not None and actor.is_active is True and actor.user.is_active
        assert coverage is not None and coverage.accepted_at is not None


def _run_fixed_capability_writer(
    session: Session,
    *,
    fixture: dict[str, str],
    writer_kind: str,
) -> tuple[int, object | None]:
    from fastapi import HTTPException

    from caseops_api.schemas.employees import EmployeeUpdateRequest
    from caseops_api.schemas.ip_deadlines import LegalCalendarVersionProposalRequest
    from caseops_api.schemas.ip_records import IpWorkspaceConfigurationUpsertRequest
    from caseops_api.services import employees, ip_deadline_workflow, ip_workspace

    context = _ip_race_context(
        session,
        company_id=fixture["company_id"],
        membership_id=fixture["actor_id"],
    )
    try:
        if writer_kind == "workspace":
            ip_workspace.upsert_ip_workspace_configuration(
                session,
                context=context,
                payload=IpWorkspaceConfigurationUpsertRequest(
                    enabled_asset_types=["trademark"],
                    jurisdictions=["IN"],
                    offices=["IPO"],
                    timezone="Asia/Kolkata",
                    holiday_calendar_key="india-default",
                    working_day_policy={"working_weekdays": [0, 1, 2, 3, 4]},
                    document_taxonomy_version="v1",
                    event_catalog_version="v1",
                    deadline_rule_versions={},
                    notification_channels=["in_app"],
                    critical_event_policy={"escalation_after_minutes": 60},
                    escalation_owner_membership_id=fixture["owner_id"],
                ),
            )
        elif writer_kind == "governance":
            ip_deadline_workflow.propose_calendar_version(
                session,
                context=context,
                payload=LegalCalendarVersionProposalRequest(
                    key=f"pg-capability-{fixture['company_id'][:8]}",
                    name="PG capability calendar",
                    jurisdiction="IN",
                    timezone="Asia/Kolkata",
                    source_priority=["official"],
                    source_reference="https://example.test/pg-capability-calendar",
                    source_hash="a" * 64,
                    effective_from=date.today(),
                ),
            )
        elif writer_kind == "employee":
            employees.update_employee(
                session,
                context=context,
                membership_id=fixture["target_id"],
                payload=EmployeeUpdateRequest(full_name="Fixed role target after"),
            )
        else:  # pragma: no cover - parametrization owns values
            raise AssertionError(f"Unknown fixed-capability writer: {writer_kind}")
    except HTTPException as exc:
        session.rollback()
        return exc.status_code, exc.detail
    return 200, None


@pytest.mark.parametrize("writer_kind", ("workspace", "governance", "employee"))
def test_fixed_role_demotion_wins_core_capability_writer_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    writer_kind: str,
) -> None:
    """A committed ADMIN -> MEMBER change defeats every refreshed capability."""

    from fastapi import HTTPException

    from caseops_api.db.models import (
        CompanyMembership,
        IpWorkspaceConfiguration,
        LegalWorkingCalendar,
        User,
    )
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_locked_capability_employee_fixture(seed, custom_actor=False)

    demotion_holds_actor = Event()
    release_demotion = Event()
    original_lock = identity_service.lock_company_memberships_for_assignment

    def paused_identity_lock(*args, **kwargs):
        memberships = original_lock(*args, **kwargs)
        if fixture["actor_id"] in memberships:
            demotion_holds_actor.set()
            if not release_demotion.wait(timeout=10):
                raise TimeoutError("Capability writer did not wait on fixed-role demotion.")
        return memberships

    monkeypatch.setattr(
        identity_service,
        "lock_company_memberships_for_assignment",
        paused_identity_lock,
    )
    application_name = f"caseops-fixed-cap-{writer_kind}-{str(uuid4())[:8]}"

    def demote() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["actor_id"],
                    payload=CompanyUserUpdateRequest(role="member"),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    def write() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            return _run_fixed_capability_writer(
                session,
                fixture=fixture,
                writer_kind=writer_kind,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        demotion = executor.submit(demote)
        writer = None
        try:
            assert demotion_holds_actor.wait(timeout=10)
            writer = executor.submit(write)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_demotion.set()
        demotion_status, _demotion_detail = demotion.result(timeout=15)
        assert writer is not None
        writer_status, _writer_detail = writer.result(timeout=15)

    assert demotion_status == 200
    assert writer_status == 403
    with Session(pg_engine) as session:
        actor = session.get(CompanyMembership, fixture["actor_id"])
        target = session.get(User, fixture["target_user_id"])
        assert actor is not None and actor.role == "member"
        assert target is not None and target.full_name == "Capability target before"
        assert session.scalar(
            select(IpWorkspaceConfiguration.id).where(
                IpWorkspaceConfiguration.company_id == fixture["company_id"]
            )
        ) is None
        assert session.scalar(
            select(LegalWorkingCalendar.id).where(
                LegalWorkingCalendar.company_id == fixture["company_id"]
            )
        ) is None


# ---------- Matter / Team locked-capability races (2026-08-17) ----------


def _run_matter_team_capability_writer(
    session: Session,
    *,
    fixture: dict[str, str],
    writer_kind: str,
) -> tuple[int, object | None]:
    from fastapi import HTTPException

    from caseops_api.schemas.matters import MatterNoteCreateRequest
    from caseops_api.schemas.teams import TeamCreateRequest
    from caseops_api.services import matters as matter_service
    from caseops_api.services import teams as team_service

    context = _ip_race_context(
        session,
        company_id=fixture["company_id"],
        membership_id=fixture["writer_id"],
    )
    try:
        if writer_kind == "matter_note":
            matter_service.create_matter_note(
                session,
                context=context,
                matter_id=fixture["matter_id"],
                payload=MatterNoteCreateRequest(
                    body="Matter capability fence writer committed"
                ),
            )
        elif writer_kind == "team_create":
            team_service.create_team(
                session,
                context=context,
                payload=TeamCreateRequest(
                    name="Team capability fence writer",
                    slug=f"pg-team-cap-{fixture['company_id'][:8]}",
                ),
            )
            session.commit()
        else:  # pragma: no cover - parametrization owns values
            raise AssertionError(f"Unknown Matter/Team writer: {writer_kind}")
    except HTTPException as exc:
        session.rollback()
        return exc.status_code, exc.detail
    return 200, None


@pytest.mark.parametrize("writer_kind", ("matter_note", "team_create"))
@pytest.mark.parametrize("ordering", ("demotion_first", "writer_first"))
def test_fixed_role_change_serializes_with_matter_team_capability_writer_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    writer_kind: str,
    ordering: str,
) -> None:
    """Stale route authorization cannot outlive the Membership/User fence."""

    from fastapi import HTTPException

    from caseops_api.db.models import CompanyMembership, MatterNote, Team
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.services import identity as identity_service
    from caseops_api.services import matters as matter_service
    from caseops_api.services import teams as team_service

    with Session(pg_engine) as seed:
        fixture = _seed_unrelated_actor_mutation_fixture(seed)
        writer = seed.get(CompanyMembership, fixture["writer_id"])
        assert writer is not None
        writer.role = "admin"
        seed.commit()

    first_holds_actor = Event()
    release_first = Event()
    application_name = (
        f"caseops-matter-team-cap-{ordering}-{writer_kind}-{str(uuid4())[:8]}"
    )

    if ordering == "demotion_first":
        original_lock = identity_service.lock_company_memberships_for_assignment

        def paused_identity_lock(*args, **kwargs):
            memberships = original_lock(*args, **kwargs)
            if fixture["writer_id"] in memberships:
                first_holds_actor.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError(
                        "Matter/Team writer did not wait on fixed-role demotion."
                    )
            return memberships

        monkeypatch.setattr(
            identity_service,
            "lock_company_memberships_for_assignment",
            paused_identity_lock,
        )
    elif writer_kind == "matter_note":
        original_append = matter_service._append_activity

        def paused_append(*args, **kwargs):
            result = original_append(*args, **kwargs)
            if kwargs.get("event_type") == "note_added":
                first_holds_actor.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError("Role demotion did not wait on Matter writer.")
            return result

        monkeypatch.setattr(matter_service, "_append_activity", paused_append)
    else:
        original_record = team_service.record_from_context

        def paused_team_record(*args, **kwargs):
            result = original_record(*args, **kwargs)
            if kwargs.get("action") == "team.created":
                first_holds_actor.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError("Role demotion did not wait on Team writer.")
            return result

        monkeypatch.setattr(
            team_service,
            "record_from_context",
            paused_team_record,
        )

    def demote() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            if ordering == "writer_first":
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                identity_service.update_company_user(
                    session,
                    context=context,
                    membership_id=fixture["writer_id"],
                    payload=CompanyUserUpdateRequest(role="viewer"),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    def write() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            if ordering == "demotion_first":
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            return _run_matter_team_capability_writer(
                session,
                fixture=fixture,
                writer_kind=writer_kind,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(demote if ordering == "demotion_first" else write)
        second = None
        try:
            assert first_holds_actor.wait(timeout=10)
            second = executor.submit(write if ordering == "demotion_first" else demote)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_first.set()
        first_status, _first_detail = first.result(timeout=15)
        assert second is not None
        second_status, _second_detail = second.result(timeout=15)

    demotion_status = first_status if ordering == "demotion_first" else second_status
    writer_status = second_status if ordering == "demotion_first" else first_status
    assert demotion_status == 200
    assert writer_status == (403 if ordering == "demotion_first" else 200)
    with Session(pg_engine) as session:
        writer = session.get(CompanyMembership, fixture["writer_id"])
        assert writer is not None and writer.role == "viewer"
        note = session.scalar(
            select(MatterNote).where(
                MatterNote.matter_id == fixture["matter_id"],
                MatterNote.body == "Matter capability fence writer committed",
            )
        )
        team = session.scalar(
            select(Team).where(
                Team.company_id == fixture["company_id"],
                Team.slug == f"pg-team-cap-{fixture['company_id'][:8]}",
            )
        )
        assert (note is not None) is (
            writer_kind == "matter_note" and ordering == "writer_first"
        )
        assert (team is not None) is (
            writer_kind == "team_create" and ordering == "writer_first"
        )


# ---------- final IP-operation actor fence races (2026-08-17) ----------


def _run_saved_queue_capability_writer(
    session: Session,
    *,
    fixture: dict[str, str],
) -> tuple[int, object | None]:
    from fastapi import HTTPException

    from caseops_api.schemas.ip_operations import IpDocketQueueSaveRequest
    from caseops_api.services import ip_operations

    context = _ip_race_context(
        session,
        company_id=fixture["company_id"],
        membership_id=fixture["actor_id"],
    )
    try:
        row = ip_operations.save_ip_docket_queue(
            session,
            context=context,
            payload=IpDocketQueueSaveRequest(
                name=f"PG actor fence {fixture['company_id'][:8]}",
                filters={"critical_only": True},
            ),
        )
    except HTTPException as exc:
        session.rollback()
        return exc.status_code, exc.detail
    return 200, row.id


@pytest.mark.parametrize(
    "revocation_kind",
    ("fixed_role", "custom_role", "actor_deactivation"),
)
@pytest.mark.parametrize("ordering", ("writer_first", "revocation_first"))
def test_saved_queue_serializes_with_exact_actor_capability_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    revocation_kind: str,
    ordering: str,
) -> None:
    """The new IP writer seam admits only the transaction that wins the actor lock."""

    from fastapi import HTTPException

    from caseops_api.db.models import (
        AuditEvent,
        CompanyMembership,
        CustomRole,
        IpDocketQueue,
    )
    from caseops_api.schemas.companies import CompanyUserUpdateRequest
    from caseops_api.schemas.custom_roles import CustomRoleUpdateRequest
    from caseops_api.services import custom_roles, ip_operations
    from caseops_api.services import identity as identity_service

    with Session(pg_engine) as seed:
        fixture = _seed_locked_capability_employee_fixture(
            seed,
            custom_actor=revocation_kind == "custom_role",
        )
        if revocation_kind == "custom_role":
            role = seed.get(CustomRole, fixture["role_id"])
            assert role is not None
            role.permissions_json = ["company:manage_users", "ip:write"]
            seed.commit()

    first_holds_actor = Event()
    release_first = Event()
    application_name = (
        f"caseops-ip-writer-{revocation_kind}-{ordering}-{str(uuid4())[:8]}"
    )

    if ordering == "writer_first":
        original_record = ip_operations.record_from_context

        def paused_queue_record(*args, **kwargs):
            result = original_record(*args, **kwargs)
            if kwargs.get("action") == "ip_docket_queue.saved":
                args[0].flush()
                first_holds_actor.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError("Actor revocation did not wait on queue writer.")
            return result

        monkeypatch.setattr(
            ip_operations,
            "record_from_context",
            paused_queue_record,
        )
    elif revocation_kind == "custom_role":
        original_role_record = custom_roles.record_from_context

        def paused_role_record(*args, **kwargs):
            result = original_role_record(*args, **kwargs)
            args[0].flush()
            first_holds_actor.set()
            if not release_first.wait(timeout=10):
                raise TimeoutError("Queue writer did not wait on custom-role revocation.")
            return result

        monkeypatch.setattr(
            custom_roles,
            "record_from_context",
            paused_role_record,
        )
    else:
        original_identity_lock = identity_service.lock_company_memberships_for_assignment

        def paused_identity_lock(*args, **kwargs):
            memberships = original_identity_lock(*args, **kwargs)
            if fixture["actor_id"] in memberships:
                first_holds_actor.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError("Queue writer did not wait on actor revocation.")
            return memberships

        monkeypatch.setattr(
            identity_service,
            "lock_company_memberships_for_assignment",
            paused_identity_lock,
        )

    def revoke() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            if ordering == "writer_first":
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["owner_id"],
            )
            try:
                if revocation_kind == "custom_role":
                    custom_roles.update_custom_role(
                        session,
                        context=context,
                        role_id=fixture["role_id"],
                        payload=CustomRoleUpdateRequest(is_active=False),
                    )
                else:
                    identity_service.update_company_user(
                        session,
                        context=context,
                        membership_id=fixture["actor_id"],
                        payload=CompanyUserUpdateRequest(
                            role="viewer" if revocation_kind == "fixed_role" else None,
                            is_active=(
                                False
                                if revocation_kind == "actor_deactivation"
                                else None
                            ),
                        ),
                    )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
            return 200, None

    def write() -> tuple[int, object | None]:
        with Session(pg_engine) as session:
            if ordering == "revocation_first":
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
            return _run_saved_queue_capability_writer(session, fixture=fixture)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(write if ordering == "writer_first" else revoke)
        second = None
        try:
            assert first_holds_actor.wait(timeout=10)
            second = executor.submit(revoke if ordering == "writer_first" else write)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=application_name,
            )
        finally:
            release_first.set()
        first_status, first_detail = first.result(timeout=15)
        assert second is not None
        second_status, second_detail = second.result(timeout=15)

    writer_status, writer_detail = (
        (first_status, first_detail)
        if ordering == "writer_first"
        else (second_status, second_detail)
    )
    revocation_status = second_status if ordering == "writer_first" else first_status
    assert revocation_status == 200
    assert writer_status == (200 if ordering == "writer_first" else 403)
    if ordering == "revocation_first":
        if revocation_kind in {"fixed_role", "custom_role"}:
            assert writer_detail == "Capability 'ip:write' is required."
        else:
            assert "active company membership" in str(writer_detail)

    with Session(pg_engine) as session:
        actor = session.get(CompanyMembership, fixture["actor_id"])
        assert actor is not None
        if revocation_kind == "fixed_role":
            assert actor.role == "viewer" and actor.is_active
        elif revocation_kind == "custom_role":
            role = session.get(CustomRole, fixture["role_id"])
            assert role is not None and not role.is_active and role.revoked_at is not None
        else:
            assert actor.is_active is False and actor.user.is_active is False

        queues = list(
            session.scalars(
                select(IpDocketQueue).where(
                    IpDocketQueue.company_id == fixture["company_id"],
                    IpDocketQueue.name
                    == f"PG actor fence {fixture['company_id'][:8]}",
                )
            ).all()
        )
        saved_events = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.company_id == fixture["company_id"],
                    AuditEvent.action == "ip_docket_queue.saved",
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            ).all()
        )
        expected_writes = 1 if ordering == "writer_first" else 0
        assert len(queues) == expected_writes
        assert len(saved_events) == expected_writes
        if saved_events:
            revocation_action = (
                "custom_role.updated"
                if revocation_kind == "custom_role"
                else "company_user.updated"
            )
            revocation_event = session.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.company_id == fixture["company_id"],
                    AuditEvent.action == revocation_action,
                )
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            )
            assert revocation_event is not None
            assert saved_events[0].created_at <= revocation_event.created_at


# ---------- login request/background transaction boundary (2026-08-17) ----------


def test_login_releases_identity_fence_before_background_audit_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real FastAPI lifecycle must not self-deadlock on login audit.

    Starlette awaits BackgroundTasks before FastAPI closes the yielded request
    session. The background probe therefore asks PostgreSQL for KEY SHARE
    NOWAIT on the exact membership before running the real audit worker. It
    fails immediately on the regressed route, whose request still holds the
    Membership/User FOR UPDATE fence, and succeeds only when that completed
    fence transaction was committed before task registration.
    """

    from fastapi.testclient import TestClient

    from caseops_api.api.routes import auth as auth_routes
    from caseops_api.core.settings import get_settings
    from caseops_api.db.models import AuditEvent, EmployeeProfile
    from caseops_api.db.session import clear_engine_cache
    from caseops_api.main import create_application

    with Session(pg_engine) as seed:
        fixture = _seed_auth_session_fence_identity(seed)

    database_url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    monkeypatch.setenv("CASEOPS_ENV", "ci")
    monkeypatch.setenv(
        "CASEOPS_AUTH_SECRET",
        "pg-login-background-fence-secret-at-least-32-bytes",
    )
    get_settings.cache_clear()
    clear_engine_cache()

    original_worker = auth_routes.record_employee_login_async
    background_checked = Event()

    def checked_background_worker(membership_id: str) -> None:
        assert membership_id == fixture["target_id"]
        with Session(pg_engine) as probe:
            locked_id = probe.scalar(
                text(
                    "SELECT id FROM company_memberships "
                    "WHERE id = :membership_id FOR KEY SHARE NOWAIT"
                ),
                {"membership_id": membership_id},
            )
            assert locked_id == membership_id
            probe.rollback()
        background_checked.set()
        original_worker(membership_id)

    monkeypatch.setattr(
        auth_routes,
        "record_employee_login_async",
        checked_background_worker,
    )

    with TestClient(create_application()) as test_client:
        response = test_client.post(
            "/api/auth/login",
            json={
                "company_slug": fixture["company_slug"],
                "email": fixture["email"],
                "password": "BeforeFence123!",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["access_token"]
    assert background_checked.is_set()

    with Session(pg_engine) as verify:
        audit = verify.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "employee.login",
                AuditEvent.actor_membership_id == fixture["target_id"],
            )
        )
        profile = verify.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.membership_id == fixture["target_id"]
            )
        )
        assert audit is not None
        assert profile is not None and profile.last_login_at is not None


# ---------- document worker / Notice upload lock order (2026-08-26) ----------


def test_notice_reply_upload_shares_worker_lifecycle_fence_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An immediate reply must not time out behind initial Notice processing.

    Both transactions are operational child writers, so their shared parent
    fences are compatible. Disposal remains an exclusive parent update and
    must wait until the worker commits before it neutralizes child work.
    """

    from hashlib import sha256
    from io import BytesIO

    from caseops_api.db.models import (
        DocumentProcessingAction,
        DocumentProcessingJob,
        DocumentProcessingJobStatus,
        DocumentProcessingStatus,
        DocumentProcessingTargetType,
        Matter,
        MatterAttachment,
    )
    from caseops_api.schemas.matters import MatterLifecycleStatusRequest
    from caseops_api.services import document_jobs
    from caseops_api.services import matters as matter_service
    from caseops_api.services.document_storage import StoredDocument

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        membership_id = _seed_membership(seed, company_id, role="admin")
        matter_id = _seed_matter(seed, company_id)
        primary = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=membership_id,
            original_filename="received-notice.txt",
            storage_key=f"postgres-validation/{uuid4()}/received-notice.txt",
            content_type="text/plain",
            size_bytes=27,
            sha256_hex="a" * 64,
            document_type="notice",
            notice_direction="received",
            notice_document_role="notice",
            notice_reply_required=True,
            notice_reply_due_on=date.today() + timedelta(days=7),
        )
        seed.add(primary)
        seed.flush()
        job = DocumentProcessingJob(
            company_id=company_id,
            requested_by_membership_id=membership_id,
            target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
            attachment_id=primary.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
            status=DocumentProcessingJobStatus.QUEUED,
        )
        seed.add(job)
        seed.commit()
        job_id = job.id
        primary_id = primary.id

    worker_session_factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    monkeypatch.setattr(document_jobs, "get_session_factory", lambda: worker_session_factory)

    def index_without_storage(target: MatterAttachment) -> None:
        target.processing_status = DocumentProcessingStatus.INDEXED
        target.extracted_text = "Received Notice processing"
        target.extracted_char_count = len(target.extracted_text)
        target.extraction_error = None

    worker_fence_held = Event()
    release_worker = Event()

    def hold_worker_lifecycle_fence(_session, _attachment, *, before_flush=None) -> int:
        assert before_flush is not None
        before_flush()
        worker_fence_held.set()
        assert release_worker.wait(timeout=15)
        return 0

    monkeypatch.setattr(document_jobs, "index_matter_attachment", index_without_storage)
    monkeypatch.setattr(
        document_jobs,
        "embed_matter_attachment_chunks",
        hold_worker_lifecycle_fence,
    )

    def persist_without_external_storage(**kwargs) -> StoredDocument:
        content = kwargs["stream"].read()
        before_store = kwargs.get("before_store")
        if before_store is not None:
            before_store(len(content))
        return StoredDocument(
            storage_key=f"postgres-validation/{uuid4()}/reply.txt",
            size_bytes=len(content),
            sha256_hex=sha256(content).hexdigest(),
        )

    monkeypatch.setattr(
        matter_service,
        "persist_matter_attachment",
        persist_without_external_storage,
    )

    disposal_application_name = f"pg-notice-disposal-{uuid4()}"

    def dispose_after_reply():
        with Session(pg_engine) as disposal_session:
            disposal_session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": disposal_application_name},
            )
            context = _ip_race_context(
                disposal_session,
                company_id=company_id,
                membership_id=membership_id,
            )
            matter = disposal_session.get(Matter, matter_id)
            assert matter is not None
            return matter_service.transition_matter_lifecycle_status(
                disposal_session,
                context=context,
                matter_id=matter_id,
                payload=MatterLifecycleStatusRequest(
                    to_status="disposed",
                    expected_from_status="active",
                    expected_updated_at=matter.updated_at,
                    reason="Prove the shared Notice fence remains fail closed.",
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        worker = executor.submit(document_jobs.run_document_processing_job, job_id)
        disposal = None
        try:
            assert worker_fence_held.wait(timeout=15)
            with Session(pg_engine) as reply_session:
                reply_session.execute(text("SET LOCAL lock_timeout = '1000ms'"))
                context = _ip_race_context(
                    reply_session,
                    company_id=company_id,
                    membership_id=membership_id,
                )
                reply, _reply_job_id = matter_service.create_matter_attachment(
                    reply_session,
                    context=context,
                    matter_id=matter_id,
                    filename="reply.txt",
                    content_type="text/plain",
                    stream=BytesIO(b"Immediate reply to received Notice"),
                    document_type="notice",
                    notice_direction="sent",
                    notice_document_role="reply",
                    notice_parent_attachment_id=primary_id,
                    notice_reply_sent=True,
                    notice_reply_sent_on=date.today(),
                )
                reply_id = reply.id

            disposal = executor.submit(dispose_after_reply)
            _wait_for_postgres_lock_wait(
                pg_engine,
                application_name=disposal_application_name,
            )
        finally:
            release_worker.set()
        worker.result(timeout=15)
        assert disposal is not None
        disposed = disposal.result(timeout=15)
        assert disposed.status == "disposed"

    with Session(pg_engine) as verify:
        matter = verify.get(Matter, matter_id)
        processed_primary = verify.get(MatterAttachment, primary_id)
        persisted_reply = verify.get(MatterAttachment, reply_id)
        completed_job = verify.get(DocumentProcessingJob, job_id)
        assert matter is not None
        assert matter.status == "disposed"
        assert matter.is_active is False
        assert processed_primary is not None
        assert processed_primary.processing_status == DocumentProcessingStatus.INDEXED
        assert processed_primary.notice_reply_sent is True
        assert persisted_reply is not None
        assert persisted_reply.notice_parent_attachment_id == primary_id
        assert completed_job is not None
        assert completed_job.status == DocumentProcessingJobStatus.COMPLETED


def test_document_worker_does_not_contend_with_interactive_actor_fence_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document worker must not block the next interactive matter write.

    Interactive attachment writes fence Membership/User for role-revocation
    safety. Processing is system work and its activity has a nullable actor FK,
    so it must not acquire that global interactive fence. The parent lifecycle
    lock must also be released after indexing and before downstream compliance
    work, which can be provider-bound.
    """

    from caseops_api.db.models import (
        DocumentProcessingAction,
        DocumentProcessingJob,
        DocumentProcessingJobStatus,
        DocumentProcessingStatus,
        DocumentProcessingTargetType,
        Matter,
        MatterActivity,
        MatterAttachment,
    )
    from caseops_api.services import document_jobs
    from caseops_api.services.assignment_memberships import (
        lock_company_memberships_for_assignment,
    )

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        membership_id = _seed_membership(seed, company_id, role="admin")
        matter_id = _seed_matter(seed, company_id)
        attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=membership_id,
            original_filename="notice-lock-order.txt",
            storage_key=f"postgres-validation/{uuid4()}/notice-lock-order.txt",
            content_type="text/plain",
            size_bytes=23,
            sha256_hex="a" * 64,
            document_type="order_judgment",
        )
        seed.add(attachment)
        seed.flush()
        job = DocumentProcessingJob(
            company_id=company_id,
            requested_by_membership_id=membership_id,
            target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
            attachment_id=attachment.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
            status=DocumentProcessingJobStatus.QUEUED,
        )
        seed.add(job)
        seed.commit()
        job_id = job.id
        attachment_id = attachment.id

    worker_session_factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    monkeypatch.setattr(document_jobs, "get_session_factory", lambda: worker_session_factory)

    def index_without_storage(target: MatterAttachment) -> None:
        target.processing_status = DocumentProcessingStatus.INDEXED
        target.extracted_text = "Notice lock-order regression"
        target.extracted_char_count = len(target.extracted_text)
        target.extraction_error = None

    def embed_without_provider(_session, _attachment, *, before_flush=None) -> int:
        assert before_flush is not None
        before_flush()
        return 0

    monkeypatch.setattr(document_jobs, "index_matter_attachment", index_without_storage)
    monkeypatch.setattr(
        document_jobs,
        "embed_matter_attachment_chunks",
        embed_without_provider,
    )

    compliance_started = Event()
    release_compliance = Event()

    def blocking_compliance_extraction(*_args, **_kwargs):
        compliance_started.set()
        assert release_compliance.wait(timeout=15)
        return None, []

    from caseops_api.services import compliance_extraction

    monkeypatch.setattr(
        compliance_extraction,
        "run_compliance_extraction_for_attachment",
        blocking_compliance_extraction,
    )

    with Session(pg_engine) as upload_session:
        lock_company_memberships_for_assignment(
            upload_session,
            company_id=company_id,
            membership_ids={membership_id},
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker = executor.submit(document_jobs.run_document_processing_job, job_id)
            try:
                assert compliance_started.wait(timeout=15)
                upload_session.execute(text("SET LOCAL lock_timeout = '1000ms'"))
                locked_matter_id = upload_session.scalar(
                    select(Matter.id)
                    .where(Matter.id == matter_id)
                    .with_for_update()
                )
                assert locked_matter_id == matter_id
                release_compliance.set()
                worker.result(timeout=15)
            finally:
                release_compliance.set()
                if upload_session.in_transaction():
                    upload_session.rollback()

    with Session(pg_engine) as verify:
        completed_job = verify.get(DocumentProcessingJob, job_id)
        processed_attachment = verify.get(MatterAttachment, attachment_id)
        assert completed_job is not None
        assert completed_job.status == DocumentProcessingJobStatus.COMPLETED
        assert processed_attachment is not None
        assert processed_attachment.processing_status == DocumentProcessingStatus.INDEXED
        assert verify.scalar(select(Matter.id).where(Matter.id == matter_id)) == matter_id
        processing_activity = verify.scalar(
            select(MatterActivity).where(
                MatterActivity.matter_id == matter_id,
                MatterActivity.event_type == "attachment_processed",
            )
        )
        assert processing_activity is not None
        assert processing_activity.actor_membership_id is None


def test_matter_disposal_wins_attachment_compliance_preparation_race_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider preparation cannot resurrect compliance children after disposal."""

    from caseops_api.db.models import (
        DocumentProcessingAction,
        DocumentProcessingJob,
        DocumentProcessingJobStatus,
        DocumentProcessingStatus,
        DocumentProcessingTargetType,
        Matter,
        MatterAttachment,
        MatterComplianceExtractionRun,
        MatterComplianceItem,
    )
    from caseops_api.schemas.matters import MatterLifecycleStatusRequest
    from caseops_api.services import compliance_extraction, document_jobs
    from caseops_api.services import matters as matter_service

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        membership_id = _seed_membership(seed, company_id, role="admin")
        matter_id = _seed_matter(seed, company_id)
        attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=membership_id,
            original_filename="disposal-compliance-race.txt",
            storage_key=f"postgres-validation/{uuid4()}/disposal-compliance-race.txt",
            content_type="text/plain",
            size_bytes=128,
            sha256_hex="b" * 64,
            document_type="order_judgment",
        )
        seed.add(attachment)
        seed.flush()
        job = DocumentProcessingJob(
            company_id=company_id,
            requested_by_membership_id=membership_id,
            target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
            attachment_id=attachment.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
            status=DocumentProcessingJobStatus.QUEUED,
        )
        seed.add(job)
        seed.commit()
        job_id = job.id

    worker_session_factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    monkeypatch.setattr(document_jobs, "get_session_factory", lambda: worker_session_factory)

    def index_without_storage(target: MatterAttachment) -> None:
        target.processing_status = DocumentProcessingStatus.INDEXED
        target.extracted_text = (
            "The respondent shall file a compliance affidavit within fourteen days "
            "from the date of this order."
        )
        target.extracted_char_count = len(target.extracted_text)
        target.extraction_error = None

    def embed_without_provider(_session, _attachment, *, before_flush=None) -> int:
        assert before_flush is not None
        before_flush()
        return 0

    monkeypatch.setattr(document_jobs, "index_matter_attachment", index_without_storage)
    monkeypatch.setattr(
        document_jobs,
        "embed_matter_attachment_chunks",
        embed_without_provider,
    )

    preparation_started = Event()
    release_preparation = Event()

    def blocking_preparation(*_args, **_kwargs):
        preparation_started.set()
        assert release_preparation.wait(timeout=15)
        return compliance_extraction._PreparedAICompliance()

    monkeypatch.setattr(compliance_extraction, "_prepare_ai_items", blocking_preparation)

    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = executor.submit(document_jobs.run_document_processing_job, job_id)
        try:
            assert preparation_started.wait(timeout=15)
            with Session(pg_engine) as disposal_session:
                context = _ip_race_context(
                    disposal_session,
                    company_id=company_id,
                    membership_id=membership_id,
                )
                matter = disposal_session.get(Matter, matter_id)
                assert matter is not None
                disposed = matter_service.transition_matter_lifecycle_status(
                    disposal_session,
                    context=context,
                    matter_id=matter_id,
                    payload=MatterLifecycleStatusRequest(
                        to_status="disposed",
                        expected_from_status="active",
                        expected_updated_at=matter.updated_at,
                        reason="Regression proof for compliance child resurrection.",
                    ),
                )
                assert disposed.status == "disposed"
        finally:
            release_preparation.set()
        worker.result(timeout=15)

    with Session(pg_engine) as verify:
        matter = verify.get(Matter, matter_id)
        assert matter is not None
        assert matter.status == "disposed"
        assert matter.is_active is False
        assert (
            verify.scalar(
                select(MatterComplianceExtractionRun.id).where(
                    MatterComplianceExtractionRun.matter_id == matter_id
                )
            )
            is None
        )
        assert (
            verify.scalar(
                select(MatterComplianceItem.id).where(
                    MatterComplianceItem.matter_id == matter_id
                )
            )
            is None
        )


# ---------------------------------------------------------------------------
# EH-SGR-04 - invoice number immutability (migration 20260820_0002)
#
# These live here rather than beside the rest of the EH-SGR-04 regression
# because the postgres-validation CI job runs exactly one file:
#
#     uv run pytest -q -m postgres tests/test_postgres_validation.py
#
# A @pytest.mark.postgres test in any other module is skipped on the default
# shards AND never selected here, so it runs nowhere while still reading as
# coverage. That is the "committed spec omitted by a manual allowlist is not
# regression coverage" trap.
#
# Placing them here also buys better evidence: `_ensure_migrations` has run
# `alembic upgrade head`, so these assert against the real migrated
# `matter_invoices` table rather than a hand-built copy of the DDL. That
# proves the migration applied the trigger, not merely that the SQL is valid.
# ---------------------------------------------------------------------------


def _seed_invoice(session: Session, company_id: str, matter_id: str, number: str) -> str:
    invoice_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO matter_invoices "
            "(id, company_id, matter_id, invoice_number, status, currency, "
            " subtotal_amount_minor, tax_amount_minor, total_amount_minor, "
            " amount_received_minor, balance_due_minor, issued_on, "
            " created_at, updated_at) "
            "VALUES (:id, :co, :mt, :num, 'draft', 'INR', "
            " 1000, 0, 1000, 0, 1000, :d, :ts, :ts)"
        ),
        {
            "id": invoice_id,
            "co": company_id,
            "mt": matter_id,
            "num": number,
            "d": date(2026, 8, 20),
            "ts": datetime.now(UTC),
        },
    )
    return invoice_id


@pytest.mark.postgres
def test_invoice_number_cannot_be_rewritten_on_postgres(pg_engine):
    """The control EH-SGR-04 was missing: an issued number is immutable.

    Under Indian GST a tax invoice number is fixed at issue; corrections go
    through a credit or debit note. Before 20260820_0002 nothing enforced that
    - immutability existed only because no edit endpoint had been written.
    """
    from sqlalchemy.exc import DBAPIError

    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        matter_id = _seed_matter(session, company_id)
        invoice_id = _seed_invoice(session, company_id, matter_id, "GBA-0001")
        session.commit()

    with Session(pg_engine) as session:
        with pytest.raises(DBAPIError) as exc:
            session.execute(
                text(
                    "UPDATE matter_invoices SET invoice_number = :n WHERE id = :i"
                ),
                {"n": "GBA-9999", "i": invoice_id},
            )
            session.commit()
        assert "immutable" in str(exc.value).lower()
        session.rollback()

    with Session(pg_engine) as verify:
        got = verify.execute(
            text("SELECT invoice_number FROM matter_invoices WHERE id = :i"),
            {"i": invoice_id},
        ).scalar_one()
        assert got == "GBA-0001", "the rejected UPDATE must not have applied"


@pytest.mark.postgres
def test_invoice_amounts_remain_updatable_on_postgres(pg_engine):
    """An immutability control that freezes the whole row is a bug, not a
    control: recording a payment legitimately rewrites amounts on an issued
    invoice. Only the number is frozen."""
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        matter_id = _seed_matter(session, company_id)
        invoice_id = _seed_invoice(session, company_id, matter_id, "GBA-0002")
        session.commit()

    with Session(pg_engine) as session:
        session.execute(
            text(
                "UPDATE matter_invoices SET amount_received_minor = 400, "
                "balance_due_minor = 600 WHERE id = :i"
            ),
            {"i": invoice_id},
        )
        session.commit()

    with Session(pg_engine) as verify:
        received = verify.execute(
            text("SELECT amount_received_minor FROM matter_invoices WHERE id = :i"),
            {"i": invoice_id},
        ).scalar_one()
        assert received == 400


@pytest.mark.postgres
def test_rewriting_the_same_invoice_number_is_not_an_error_on_postgres(pg_engine):
    """A no-op rewrite is what an ORM flush of an unchanged row looks like.
    The trigger's WHEN clause must let it through, or every ordinary save of
    an invoice fails."""
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        matter_id = _seed_matter(session, company_id)
        invoice_id = _seed_invoice(session, company_id, matter_id, "GBA-0003")
        session.commit()

    with Session(pg_engine) as session:
        session.execute(
            text("UPDATE matter_invoices SET invoice_number = :n WHERE id = :i"),
            {"n": "GBA-0003", "i": invoice_id},
        )
        session.commit()


@pytest.mark.postgres
def test_blank_invoice_number_is_rejected_on_postgres(pg_engine):
    """ck_matter_invoice_number_not_blank, on the real migrated table."""
    from sqlalchemy.exc import DBAPIError

    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        matter_id = _seed_matter(session, company_id)
        session.commit()

    for blank in ("", "   "):
        with Session(pg_engine) as session:
            with pytest.raises(DBAPIError):
                _seed_invoice(session, company_id, matter_id, blank)
                session.commit()
            session.rollback()


@pytest.mark.postgres
def test_iplf039c_reconciliation_candidate_evidence_constraints_on_postgres(pg_engine):
    """The drift-review row must have one exact, accountable observation.

    SQLite exercises the authorization flow; this real-Postgres check proves
    the migration's composite fingerprint uniqueness and evidence-state check
    survive the production dialect.  A duplicate observation cannot create a
    second review task, and a terminal decision cannot omit its human evidence.
    """

    from caseops_api.db.models import (
        CalendarEventSync,
        CalendarProjectionReconciliationCandidate,
        UserCalendarConnection,
    )

    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id, role="admin")
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=membership_id,
            provider="google_calendar",
            status="connected",
        )
        session.add(connection)
        session.flush()
        sync = CalendarEventSync(
            company_id=company_id,
            calendar_connection_id=connection.id,
            source_type="matter_deadline",
            source_id=str(uuid4()),
            provider_event_id="pg-reconciliation-event",
            sync_status="synced",
        )
        session.add(sync)
        session.flush()
        connection_id = connection.id
        sync_id = sync.id
        source_id = sync.source_id
        candidate = CalendarProjectionReconciliationCandidate(
            company_id=company_id,
            calendar_event_sync_id=sync_id,
            calendar_connection_id=connection_id,
            source_type=sync.source_type,
            source_id=source_id,
            drift_status="moved",
            snapshot_schema_version=1,
            expected_snapshot_json={"occurs_on": "2099-01-10"},
            observed_snapshot_json={"start_date": "2099-01-11"},
            snapshot_sha256="a" * 64,
            status="pending",
            detected_by_membership_id=membership_id,
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    with Session(pg_engine) as session:
        duplicate = CalendarProjectionReconciliationCandidate(
            company_id=company_id,
            calendar_event_sync_id=sync_id,
            calendar_connection_id=connection_id,
            source_type="matter_deadline",
            source_id=source_id,
            drift_status="moved",
            snapshot_schema_version=1,
            expected_snapshot_json={"occurs_on": "2099-01-10"},
            observed_snapshot_json={"start_date": "2099-01-11"},
            snapshot_sha256="a" * 64,
            status="pending",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError) as duplicate_error:
            session.commit()
        assert "uq_calendar_projection_reconciliation_snapshot" in str(
            duplicate_error.value
        )
        session.rollback()

        incomplete_decision = CalendarProjectionReconciliationCandidate(
            company_id=company_id,
            calendar_event_sync_id=sync_id,
            calendar_connection_id=connection_id,
            source_type="matter_deadline",
            source_id=source_id,
            drift_status="missing",
            snapshot_schema_version=1,
            expected_snapshot_json={"occurs_on": "2099-01-10"},
            observed_snapshot_json={"event_present": False},
            snapshot_sha256="b" * 64,
            status="accepted",
        )
        session.add(incomplete_decision)
        with pytest.raises(IntegrityError) as evidence_error:
            session.commit()
        assert "ck_calendar_projection_reconciliation_decision_evidence" in str(
            evidence_error.value
        )
        session.rollback()

    with Session(pg_engine) as session:
        with pytest.raises(IntegrityError) as incomplete_claim_error:
            session.execute(
                text(
                    "UPDATE calendar_event_syncs "
                    "SET reconciliation_candidate_id = :candidate_id WHERE id = :sync_id"
                ),
                {"candidate_id": candidate_id, "sync_id": sync_id},
            )
            session.commit()
        assert "ck_calendar_event_sync_reconciliation_claim_complete" in str(
            incomplete_claim_error.value
        )
        session.rollback()

    with Session(pg_engine) as session:
        with pytest.raises(DBAPIError, match="snapshot evidence is immutable"):
            session.execute(
                text(
                    "UPDATE calendar_projection_reconciliation_candidates "
                    "SET observed_snapshot_json = CAST(:payload AS json) WHERE id = :id"
                ),
                {"payload": '{"tampered": true}', "id": candidate_id},
            )
            session.commit()
        session.rollback()

    with Session(pg_engine) as session:
        session.execute(
            text(
                "UPDATE calendar_projection_reconciliation_candidates "
                "SET status = 'accepted', decided_by_membership_id = :actor, "
                "decision_evidence_reference = :evidence, decided_at = :decided "
                "WHERE id = :id"
            ),
            {
                "actor": membership_id,
                "evidence": "postgres:calendar-review",
                "decided": datetime.now(UTC),
                "id": candidate_id,
            },
        )
        session.commit()

    with Session(pg_engine) as session:
        with pytest.raises(DBAPIError, match="decision is terminal"):
            session.execute(
                text(
                    "UPDATE calendar_projection_reconciliation_candidates "
                    "SET status = 'rejected' WHERE id = :id"
                ),
                {"id": candidate_id},
            )
            session.commit()
        session.rollback()

    with Session(pg_engine) as session:
        with pytest.raises(DBAPIError):
            session.execute(
                text("DELETE FROM calendar_event_syncs WHERE id = :id"),
                {"id": sync_id},
            )
            session.commit()
        session.rollback()


@pytest.mark.postgres
def test_uj59_control_review_evidence_is_immutable_and_tenant_correlated_on_postgres(
    pg_engine,
):
    """UJ-59 evidence survives direct SQL and cross-tenant mutation attempts."""

    from caseops_api.db.models import (
        IpControlReviewExceptionDecision,
        IpControlReviewSampleEvidence,
        IpControlReviewSignature,
        IpDocketControlReview,
    )

    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        preparer_id = _seed_membership(session, company_id, role="admin")
        reviewer_id = _seed_membership(session, company_id, role="admin")
        other_company_id = _seed_company(session)
        other_membership_id = _seed_membership(session, other_company_id, role="admin")
        review = IpDocketControlReview(
            company_id=company_id,
            generated_at=now,
            filters_json={},
            freshness_json={"stale_sources": [], "failed_queries": []},
            completeness_status="complete",
            incompleteness_reasons_json=[],
            mandatory_exception_ids_json=[],
            query_version="ip-docket-control-v1",
            snapshot_schema_version=2,
            report_snapshot_json={"schema_version": 2},
            manifest_sha256="a" * 64,
            review_policy_json={"policy_version": "daily-docket-review-v1"},
            required_signature_count=2,
            required_sample_size=1,
            delta_json={},
            version=1,
            created_by_membership_id=preparer_id,
        )
        session.add(review)
        session.flush()
        review_id = review.id

        decision = IpControlReviewExceptionDecision(
            company_id=company_id,
            review_id=review_id,
            docket_id=str(uuid4()),
            exception_kind="uncovered",
            disposition="annotated",
            annotation="Controlled follow-up recorded.",
            evidence_reference="postgres:decision-evidence",
            decided_by_membership_id=preparer_id,
            decided_at=now,
        )
        sample = IpControlReviewSampleEvidence(
            company_id=company_id,
            review_id=review_id,
            docket_id=str(uuid4()),
            reviewer_membership_id=reviewer_id,
            source_evidence_reference="postgres:source",
            calculation_evidence_reference="postgres:calculation",
            coverage_evidence_reference="postgres:coverage",
            sampled_at=now,
        )
        signature = IpControlReviewSignature(
            company_id=company_id,
            review_id=review_id,
            signer_membership_id=preparer_id,
            signer_role="preparer",
            signer_label_snapshot="Postgres Preparer",
            attestation="Prepared and checked the daily docket.",
            manifest_sha256=review.manifest_sha256,
            sequence=1,
            signed_at=now,
        )
        session.add_all([decision, sample, signature])
        session.commit()
        decision_id = decision.id
        sample_id = sample.id
        signature_id = signature.id

    mutation_attempts = [
        (
            "UPDATE ip_docket_control_reviews SET manifest_sha256 = :value WHERE id = :id",
            {"value": "b" * 64, "id": review_id},
        ),
        (
            "UPDATE ip_control_review_exception_decisions SET annotation = :value WHERE id = :id",
            {"value": "rewritten", "id": decision_id},
        ),
        (
            "DELETE FROM ip_control_review_sample_evidence WHERE id = :id",
            {"id": sample_id},
        ),
        (
            "UPDATE ip_control_review_signatures SET attestation = :value WHERE id = :id",
            {"value": "rewritten", "id": signature_id},
        ),
    ]
    for statement, parameters in mutation_attempts:
        with Session(pg_engine) as session:
            with pytest.raises(DBAPIError, match="append-only"):
                session.execute(text(statement), parameters)
                session.commit()
            session.rollback()

    with Session(pg_engine) as session:
        with pytest.raises(IntegrityError):
            session.add(
                IpControlReviewSignature(
                    company_id=company_id,
                    review_id=review_id,
                    signer_membership_id=other_membership_id,
                    signer_role="reviewer",
                    signer_label_snapshot="Wrong Tenant Reviewer",
                    attestation="This actor belongs to another tenant.",
                    manifest_sha256="a" * 64,
                    sequence=2,
                    signed_at=now,
                )
            )
            session.commit()
        session.rollback()

    with Session(pg_engine) as session:
        with pytest.raises(IntegrityError) as manifest_mismatch:
            session.add(
                IpControlReviewSignature(
                    company_id=company_id,
                    review_id=review_id,
                    signer_membership_id=reviewer_id,
                    signer_role="reviewer",
                    signer_label_snapshot="Postgres Reviewer",
                    attestation="The signature must bind to the frozen manifest.",
                    manifest_sha256="f" * 64,
                    sequence=2,
                    signed_at=now,
                )
            )
            session.commit()
        assert "fk_ip_control_signature_manifest" in str(manifest_mismatch.value)
        session.rollback()

    with Session(pg_engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "UPDATE ip_docket_control_reviews "
                    "SET required_signature_count = 3 WHERE id = :id"
                ),
                {"id": review_id},
            )
            session.commit()
        session.rollback()

    with Session(pg_engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text("DELETE FROM ip_docket_control_reviews WHERE id = :id"),
                {"id": review_id},
            )
            session.commit()
        session.rollback()

    with Session(pg_engine) as session:
        assert session.get(IpDocketControlReview, review_id) is not None
        assert session.get(IpControlReviewExceptionDecision, decision_id) is not None
        assert session.get(IpControlReviewSampleEvidence, sample_id) is not None
        assert session.get(IpControlReviewSignature, signature_id) is not None


@pytest.mark.postgres
def test_uj58_incident_evidence_is_append_only_retained_and_tenant_correlated_on_postgres(
    pg_engine,
):
    from caseops_api.db.models import (
        IpDeadlineIncident,
        IpDeadlineIncidentImpact,
    )

    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        fixture = _seed_ip_coverage_lifecycle_fixture(session)
        other_company_id = _seed_company(session)
        other_actor_id = _seed_membership(session, other_company_id)
        incident = IpDeadlineIncident(
            company_id=fixture["company_id"],
            docket_id=fixture["docket_id"],
            matter_deadline_id=fixture["deadline_id"],
            severity="critical",
            summary="PostgreSQL immutable incident evidence",
            impact_json={"affected_rights": ["opaque-right"]},
            evidence_snapshot_json={"rule_version_refs": ["rule:v7"]},
            preservation_manifest_sha256="a" * 64,
            defect_scope="shared_rule",
            defect_fingerprint_sha256="b" * 64,
            status="open",
            created_by_membership_id=fixture["owner_id"],
            created_at=now,
        )
        session.add(incident)
        session.flush()
        impact = IpDeadlineIncidentImpact(
            company_id=fixture["company_id"],
            incident_id=incident.id,
            record_type="trademark_application",
            record_reference_sha256="c" * 64,
            relationship="same defective rule",
            assessment="affected",
            scan_method="fingerprint scan",
            evidence_reference="postgres:impact:1",
            assessed_by_membership_id=fixture["owner_id"],
            assessed_at=now,
        )
        session.add(impact)
        session.commit()
        incident_id = incident.id
        impact_id = impact.id

    attempts = [
        (
            "UPDATE ip_deadline_incidents SET summary = 'rewritten' WHERE id = :id",
            {"id": incident_id},
            "discovery evidence is immutable",
        ),
        (
            "DELETE FROM ip_deadline_incidents WHERE id = :id",
            {"id": incident_id},
            "evidence is retained",
        ),
        (
            "UPDATE ip_deadline_incident_impacts SET assessment = 'not_affected' "
            "WHERE id = :id",
            {"id": impact_id},
            "append-only",
        ),
    ]
    for statement, parameters, message in attempts:
        with Session(pg_engine) as session:
            with pytest.raises(DBAPIError, match=message):
                session.execute(text(statement), parameters)
                session.commit()
            session.rollback()

    with Session(pg_engine) as session:
        with pytest.raises(IntegrityError):
            session.add(
                IpDeadlineIncidentImpact(
                    company_id=fixture["company_id"],
                    incident_id=incident_id,
                    record_type="trademark_application",
                    record_reference_sha256="d" * 64,
                    relationship="cross-tenant actor attempt",
                    assessment="pending",
                    scan_method="invalid actor test",
                    evidence_reference="postgres:impact:cross-tenant",
                    assessed_by_membership_id=other_actor_id,
                    assessed_at=now,
                )
            )
            session.commit()
        session.rollback()

    with Session(pg_engine) as session:
        assert session.get(IpDeadlineIncident, incident_id) is not None
        assert session.get(IpDeadlineIncidentImpact, impact_id) is not None


@pytest.mark.postgres
def test_iplf040_opposition_stage_and_profile_events_are_append_only_on_postgres(
    pg_engine,
):
    from caseops_api.db.models import IpDocketEvent, IpProceeding

    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        fixture = _seed_ip_coverage_lifecycle_fixture(session)
        proceeding = IpProceeding(
            company_id=fixture["company_id"],
            docket_id=fixture["docket_id"],
            proceeding_kind="opposition",
            side="applicant",
            office="Trade Marks Registry Delhi",
            jurisdiction="IN",
            stage="draft",
            origin_kind="manual_intake",
            stage_template_version="opposition-applicant-v1",
        )
        session.add(proceeding)
        session.flush()
        event = IpDocketEvent(
            company_id=fixture["company_id"],
            docket_id=fixture["docket_id"],
            sequence=1,
            proceeding_id=proceeding.id,
            event_kind="lifecycle_transition",
            source="manual",
            effective_at=now,
            responsible_membership_id=fixture["owner_id"],
            entered_by_membership_id=fixture["owner_id"],
            reason="PostgreSQL opposition transition evidence.",
            evidence_refs_json=["postgres:opposition:evidence"],
            document_refs_json=[],
            resulting_stage="notice_filed",
            resulting_deadline_refs_json=[],
            before_phase="draft",
            after_phase="notice_filed",
            candidate_status="confirmed",
            payload_json={
                "opposition_stage_transition": True,
                "expected_proceeding_version": 1,
            },
        )
        session.add(event)
        profile_event = IpDocketEvent(
            company_id=fixture["company_id"],
            docket_id=fixture["docket_id"],
            sequence=2,
            proceeding_id=proceeding.id,
            event_kind="opposition_profile",
            source="manual",
            effective_at=now,
            responsible_membership_id=fixture["owner_id"],
            entered_by_membership_id=fixture["owner_id"],
            reason="PostgreSQL opposition profile evidence.",
            evidence_refs_json=["postgres:opposition:profile"],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            before_phase="draft",
            candidate_status="confirmed",
            payload_json={"opposition_profile_revision": True},
        )
        session.add(profile_event)
        session.commit()
        event_ids = (event.id, profile_event.id)

    for event_id in event_ids:
        for statement in (
            "UPDATE ip_docket_events SET reason = 'rewritten' WHERE id = :id",
            "DELETE FROM ip_docket_events WHERE id = :id",
        ):
            with Session(pg_engine) as session:
                with pytest.raises(DBAPIError, match="append-only"):
                    session.execute(text(statement), {"id": event_id})
                    session.commit()
                session.rollback()


@pytest.mark.postgres
def test_iplf051_registry_snapshot_is_append_only_and_tenant_fks_exist_on_postgres(
    pg_engine,
):
    from caseops_api.db.models import (
        IpProceeding,
        IpRegistryLink,
        IpRegistrySnapshot,
        IpRegistrySyncAttempt,
    )

    inspector = inspect(pg_engine)
    snapshot_fk_names = {
        row["name"] for row in inspector.get_foreign_keys("ip_registry_snapshots")
    }
    attempt_fk_names = {
        row["name"] for row in inspector.get_foreign_keys("ip_registry_sync_attempts")
    }
    diff_fk_names = {
        row["name"] for row in inspector.get_foreign_keys("ip_registry_diffs")
    }
    tracked_reference_fk_names = {
        row["name"] for row in inspector.get_foreign_keys("ip_tracked_case_links")
    }
    assert "fk_ip_registry_snapshot_link_company" in snapshot_fk_names
    assert "fk_ip_registry_snapshot_attempt_company" in snapshot_fk_names
    assert "fk_ip_registry_snapshot_supersedes_company" in snapshot_fk_names
    assert "fk_ip_registry_attempt_replay_company" in attempt_fk_names
    assert "fk_ip_registry_diff_event_company" in diff_fk_names
    assert "fk_ip_tracked_case_link_case_company" in tracked_reference_fk_names

    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        fixture = _seed_ip_coverage_lifecycle_fixture(session)
        proceeding = IpProceeding(
            company_id=fixture["company_id"],
            docket_id=fixture["docket_id"],
            proceeding_kind="opposition",
            side="applicant",
            office="Trade Marks Registry Delhi",
            jurisdiction="IN",
            stage="draft",
            origin_kind="registry_event",
            stage_template_version="opposition-applicant-v1",
        )
        session.add(proceeding)
        session.flush()
        link = IpRegistryLink(
            company_id=fixture["company_id"],
            docket_id=fixture["docket_id"],
            proceeding_id=proceeding.id,
            provider_key="ipindia-registry",
            office="Trade Marks Registry Delhi",
            jurisdiction="IN",
            identifier_kind="opposition",
            raw_identifier=f"OPP-{uuid4()}",
            normalized_identifier=f"opp{uuid4().hex}",
            source_url="https://ipindia.gov.in/registry/postgres-fixture",
            match_status="confirmed",
            match_confidence="1.0000",
            match_evidence_json={"fixture": True},
            accepted_state_json={"status": "draft"},
            capability_version="manual-evidence-v1",
            created_by_membership_id=fixture["owner_id"],
        )
        session.add(link)
        session.flush()
        attempt = IpRegistrySyncAttempt(
            company_id=fixture["company_id"],
            link_id=link.id,
            provider_key="ipindia-registry",
            operation_kind="manual_snapshot",
            idempotency_key=f"postgres-{uuid4()}",
            correlation_id=uuid4().hex + uuid4().hex,
            status="succeeded",
            response_class="success",
            external_call=False,
            requested_by_membership_id=fixture["owner_id"],
            started_at=now,
            completed_at=now,
            metadata_json={"request_fingerprint": "a" * 64},
        )
        session.add(attempt)
        session.flush()
        snapshot = IpRegistrySnapshot(
            company_id=fixture["company_id"],
            link_id=link.id,
            attempt_id=attempt.id,
            source_url=link.source_url,
            source_retrieved_at=now,
            parser_version="postgres-fixture-v1",
            schema_version=1,
            attribution_json={"fixture": True},
            raw_sha256="b" * 64,
            normalized_sha256="c" * 64,
            raw_json={"status": "pending"},
            normalized_json={"status": "pending"},
        )
        session.add(snapshot)
        session.commit()
        snapshot_id = snapshot.id

    for statement in (
        "UPDATE ip_registry_snapshots SET parser_version = 'rewritten' WHERE id = :id",
        "DELETE FROM ip_registry_snapshots WHERE id = :id",
    ):
        with Session(pg_engine) as session:
            with pytest.raises(DBAPIError, match="append-only"):
                session.execute(text(statement), {"id": snapshot_id})
                session.commit()
            session.rollback()


@pytest.mark.postgres
def test_iplf057a_madrid_tenant_fks_and_designation_identity_on_postgres(pg_engine):
    from caseops_api.db.models import (
        IpDocketRecord,
        TrademarkInternationalRegistration,
    )

    inspector = inspect(pg_engine)
    foreign_keys = {
        row["name"]
        for row in inspector.get_foreign_keys("trademark_international_registrations")
    }
    assert {
        "fk_tm_international_docket_company",
        "fk_tm_international_parent_company",
        "fk_tm_international_basic_application_company",
        "fk_tm_international_creator_company",
        "fk_tm_international_updater_company",
    } <= foreign_keys
    indexes = {
        row["name"]: row
        for row in inspector.get_indexes("trademark_international_registrations")
    }
    assert indexes["uq_tm_international_company_ir_number"]["unique"] is True
    assert indexes["uq_tm_international_designation_member"]["unique"] is True

    now = datetime.now(UTC)
    registration_id = str(uuid4())
    designation_date = date(2026, 8, 25)
    with Session(pg_engine) as session:
        fixture = _seed_ip_coverage_lifecycle_fixture(session)
        registration_docket = IpDocketRecord(
            company_id=fixture["company_id"],
            record_type="international_registration",
            title="PostgreSQL Madrid registration",
            status="ready",
            created_by_membership_id=fixture["owner_id"],
        )
        first_designation_docket = IpDocketRecord(
            company_id=fixture["company_id"],
            record_type="international_designation",
            title="PostgreSQL Madrid IN designation",
            status="ready",
            created_by_membership_id=fixture["owner_id"],
        )
        duplicate_designation_docket = IpDocketRecord(
            company_id=fixture["company_id"],
            record_type="international_designation",
            title="PostgreSQL duplicate designation",
            status="ready",
            created_by_membership_id=fixture["owner_id"],
        )
        session.add_all(
            [
                registration_docket,
                first_designation_docket,
                duplicate_designation_docket,
            ]
        )
        session.flush()
        registration = TrademarkInternationalRegistration(
            id=registration_id,
            company_id=fixture["company_id"],
            docket_id=registration_docket.id,
            record_kind="international_registration",
            direction="inbound",
            ir_number=f"PG-{uuid4()}",
            wipo_reference=f"WIPO-{uuid4()}",
            holder_name="PostgreSQL holder",
            mark_name="ASTER",
            classes_json=[9],
            goods_services_json={"9": "Software"},
            priority_claims_json=[],
            wipo_status="recorded",
            source_url="https://www.wipo.int/madrid/postgres",
            source_reference="postgres:wipo:registration",
            source_retrieved_at=now,
            created_by_membership_id=fixture["owner_id"],
            updated_by_membership_id=fixture["owner_id"],
        )
        designation = TrademarkInternationalRegistration(
            company_id=fixture["company_id"],
            docket_id=first_designation_docket.id,
            record_kind="international_designation",
            direction="inbound",
            parent_registration_id=registration_id,
            wipo_reference=f"WIPO-DES-{uuid4()}",
            holder_name="PostgreSQL holder",
            mark_name="ASTER",
            designated_member_code="IN",
            designated_office="IP India",
            jurisdiction="IN",
            designation_kind="original",
            classes_json=[9],
            goods_services_json={"9": "Software"},
            priority_claims_json=[],
            wipo_status="notified",
            national_status="examined",
            source_url="https://www.wipo.int/madrid/postgres/in",
            source_reference="postgres:wipo:designation",
            source_retrieved_at=now,
            designation_effective_date=designation_date,
            created_by_membership_id=fixture["owner_id"],
            updated_by_membership_id=fixture["owner_id"],
        )
        session.add_all([registration, designation])
        session.commit()
        company_id = fixture["company_id"]
        owner_id = fixture["owner_id"]
        duplicate_docket_id = duplicate_designation_docket.id

    with Session(pg_engine) as session:
        session.add(
            TrademarkInternationalRegistration(
                company_id=company_id,
                docket_id=duplicate_docket_id,
                record_kind="international_designation",
                direction="inbound",
                parent_registration_id=registration_id,
                wipo_reference=f"WIPO-DES-{uuid4()}",
                holder_name="PostgreSQL holder",
                mark_name="ASTER",
                designated_member_code="IN",
                designated_office="IP India",
                jurisdiction="IN",
                designation_kind="original",
                classes_json=[9],
                goods_services_json={"9": "Software"},
                priority_claims_json=[],
                wipo_status="notified",
                national_status="protected",
                source_url="https://www.wipo.int/madrid/postgres/in-duplicate",
                source_reference="postgres:wipo:designation:duplicate",
                source_retrieved_at=now,
                designation_effective_date=designation_date,
                created_by_membership_id=owner_id,
                updated_by_membership_id=owner_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with Session(pg_engine) as session:
        other_company_id = _seed_company(session)
        other_owner_id = _seed_membership(session, other_company_id)
        other_docket = IpDocketRecord(
            company_id=other_company_id,
            record_type="international_registration",
            title="Cross-tenant Madrid docket",
            status="ready",
            created_by_membership_id=other_owner_id,
        )
        session.add(other_docket)
        session.commit()
        other_docket_id = other_docket.id

    with Session(pg_engine) as session:
        session.add(
            TrademarkInternationalRegistration(
                company_id=company_id,
                docket_id=other_docket_id,
                record_kind="international_registration",
                direction="inbound",
                ir_number=f"PG-{uuid4()}",
                wipo_reference=f"WIPO-{uuid4()}",
                holder_name="Cross-tenant holder",
                mark_name="ASTER",
                classes_json=[],
                goods_services_json={},
                priority_claims_json=[],
                source_url="https://www.wipo.int/madrid/postgres/cross-tenant",
                source_reference="postgres:wipo:cross-tenant",
                source_retrieved_at=now,
                created_by_membership_id=owner_id,
                updated_by_membership_id=owner_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.postgres
def test_iplf057b_madrid_projection_and_source_reconciliation_on_postgres(pg_engine):
    from fastapi import HTTPException

    from caseops_api.db.models import (
        IpDocketRecord,
        IpTrademarkParticularVersion,
        TrademarkInternationalRegistration,
    )
    from caseops_api.schemas.ip_international import (
        TrademarkInternationalActionRequest,
        TrademarkInternationalRecordCreateRequest,
    )
    from caseops_api.services.ip_international import (
        create_international_record,
        international_workspace,
        record_international_action,
    )

    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        fixture = _seed_ip_coverage_lifecycle_fixture(session)
        context = _ip_race_context(
            session,
            company_id=fixture["company_id"],
            membership_id=fixture["owner_id"],
        )

        def create_record(**overrides):
            data = {
                "docket_title": f"PostgreSQL Madrid {uuid4()}",
                "record_kind": "international_registration",
                "direction": "inbound",
                "parent_registration_id": None,
                "wipo_reference": f"WIPO-PG-057B-{uuid4()}",
                "holder_name": "PostgreSQL Madrid holder",
                "mark_name": "ASTER",
                "classes": [9],
                "goods_services": {"9": "Legal software"},
                "source_url": "https://www.wipo.int/madrid/monitor/pg-057b",
                "source_reference": f"postgres:057b:{uuid4()}",
                "source_retrieved_at": now,
            }
            data.update(overrides)
            return create_international_record(
                session,
                context=context,
                payload=TrademarkInternationalRecordCreateRequest(**data),
            )

        registration = create_record()
        first = create_record(
            record_kind="international_designation",
            parent_registration_id=registration.id,
            designated_member_code="IN",
            designated_office="Trade Marks Registry India",
            jurisdiction="IN",
            designation_kind="original",
            designation_effective_date=date(2026, 8, 25),
        )
        sibling = create_record(
            record_kind="international_designation",
            parent_registration_id=registration.id,
            designated_member_code="EM",
            designated_office="EUIPO",
            jurisdiction="EM",
            designation_kind="subsequent",
            designation_effective_date=date(2026, 8, 26),
        )

        projection = session.scalar(
            select(IpTrademarkParticularVersion).where(
                IpTrademarkParticularVersion.docket_id == first.docket_id,
                IpTrademarkParticularVersion.version == 1,
            )
        )
        assert projection is not None
        assert projection.classes_json == [
            {"class_number": 9, "specification": "Legal software"}
        ]

        first_docket = session.get(IpDocketRecord, first.docket_id)
        assert first_docket is not None
        candidate = record_international_action(
            session,
            context=context,
            record_id=first.id,
            payload=TrademarkInternationalActionRequest(
                expected_version=first.version,
                expected_lifecycle_version=first_docket.lifecycle_version,
                action_kind="source_snapshot",
                authority="national_office",
                effective_at=now,
                responsible_membership_id=context.membership.id,
                reason="PostgreSQL national-office source snapshot.",
                source_url="https://ipindia.gov.in/trademark/pg-057b",
                source_reference=f"postgres:057b:snapshot:{uuid4()}",
                source_retrieved_at=now,
                national_status="provisional_refusal",
            ),
        )
        assert candidate.status_applied is False
        assert candidate.record.national_status is None

        reconciled = record_international_action(
            session,
            context=context,
            record_id=first.id,
            payload=TrademarkInternationalActionRequest(
                expected_version=candidate.record.version,
                expected_lifecycle_version=first_docket.lifecycle_version,
                action_kind="source_reconciliation",
                authority="internal",
                effective_at=now,
                responsible_membership_id=context.membership.id,
                reason="PostgreSQL counsel accepted the source candidate.",
                source_reference=f"postgres:057b:reconcile:{uuid4()}",
                source_retrieved_at=now,
                reconciles_event_id=candidate.event.id,
                reconciliation_decision="same_fact",
            ),
        )
        assert reconciled.status_applied is True
        assert reconciled.record.national_status == "provisional_refusal"

        sibling_row = session.get(TrademarkInternationalRegistration, sibling.id)
        registration_row = session.get(
            TrademarkInternationalRegistration,
            registration.id,
        )
        assert sibling_row is not None and sibling_row.national_status is None
        assert registration_row is not None and registration_row.wipo_status is None
        workspace = international_workspace(session, context=context, record_id=first.id)
        assert workspace.unresolved_source_candidates == []
        assert workspace.provider_mode == "manual_sourced_only"
        assert "provider_contract_not_approved" in workspace.provider_activation_blockers

        with pytest.raises(HTTPException) as stale:
            record_international_action(
                session,
                context=context,
                record_id=first.id,
                payload=TrademarkInternationalActionRequest(
                    expected_version=1,
                    expected_lifecycle_version=first_docket.lifecycle_version,
                    action_kind="change_recorded",
                    authority="internal",
                    effective_at=now,
                    responsible_membership_id=context.membership.id,
                    reason="PostgreSQL stale Madrid writer must fail.",
                    source_reference=f"postgres:057b:stale:{uuid4()}",
                    source_retrieved_at=now,
                ),
            )
        assert stale.value.status_code == 409


def test_bounded_renewal_report_reader_runs_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IPLF-038B exercises its bounded canonical renewal join on PostgreSQL."""

    from fastapi.testclient import TestClient

    from caseops_api.core.settings import get_settings
    from caseops_api.db.session import clear_engine_cache
    from caseops_api.main import create_application
    from tests.test_ip_report_workflow import (
        test_iplf_req_report_01_renewal_report_returns_canonical_evidence,
    )

    monkeypatch.setenv(
        "CASEOPS_DATABASE_URL",
        os.environ["CASEOPS_TEST_POSTGRES_URL"].strip(),
    )
    monkeypatch.setenv("CASEOPS_ENV", "ci")
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    monkeypatch.setenv(
        "CASEOPS_AUTH_SECRET",
        "pg-report-reader-secret-at-least-32-bytes",
    )
    monkeypatch.setenv("CASEOPS_AUTH_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    clear_engine_cache()

    with TestClient(create_application()) as test_client:
        test_iplf_req_report_01_renewal_report_returns_canonical_evidence(test_client)


def test_ip_document_link_projection_event_key_is_bounded_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real POST flow must fit PostgreSQL VARCHAR(120) and stay idempotent."""

    import hashlib

    from fastapi.testclient import TestClient

    from caseops_api.core.settings import get_settings
    from caseops_api.db.models import (
        IpDocketRecord,
        IpDocument,
        IpDocumentTaxonomyEntry,
        IpDocumentVersion,
        PrivateProjectionEvent,
    )
    from caseops_api.db.session import clear_engine_cache
    from caseops_api.main import create_application
    from caseops_api.services.private_retrieval import (
        build_private_projection_event_key,
    )

    postgres_url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    monkeypatch.setenv("CASEOPS_DATABASE_URL", postgres_url)
    monkeypatch.setenv("CASEOPS_ENV", "ci")
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    monkeypatch.setenv(
        "CASEOPS_AUTH_SECRET",
        "pg-private-event-key-secret-at-least-32-bytes",
    )
    monkeypatch.setenv("CASEOPS_AUTH_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    clear_engine_cache()

    fixture_id = uuid4().hex
    try:
        with TestClient(create_application()) as test_client:
            bootstrap = test_client.post(
                "/api/bootstrap/company",
                json={
                    "company_name": f"Private event key {fixture_id[:8]}",
                    "company_slug": f"private-event-key-{fixture_id[:12]}",
                    "company_type": "law_firm",
                    "owner_full_name": "PostgreSQL Event Owner",
                    "owner_email": f"private-event-{fixture_id[:12]}@example.in",
                    "owner_password": "PostgresEventKey123!",
                },
            )
            assert bootstrap.status_code == 200, bootstrap.text
            company_id = str(bootstrap.json()["company"]["id"])
            membership_id = str(bootstrap.json()["membership"]["id"])
            headers = {
                "Authorization": f"Bearer {bootstrap.json()['access_token']}"
            }

            with Session(pg_engine) as seed:
                taxonomy = IpDocumentTaxonomyEntry(
                    company_id=company_id,
                    key=f"event-key-{fixture_id[:8]}",
                    label="PostgreSQL event key evidence",
                    is_seeded=False,
                    is_active=True,
                    version=1,
                    updated_by_membership_id=membership_id,
                )
                target_docket = IpDocketRecord(
                    company_id=company_id,
                    record_type="trademark",
                    title="PostgreSQL private event target",
                    status="draft",
                    is_active=True,
                    restricted=False,
                    created_by_membership_id=membership_id,
                )
                seed.add_all([taxonomy, target_docket])
                seed.flush()
                document = IpDocument(
                    company_id=company_id,
                    taxonomy_entry_id=taxonomy.id,
                    title="PostgreSQL event key document",
                    confidentiality="internal",
                    is_privileged=False,
                    current_version=1,
                    created_by_membership_id=membership_id,
                )
                seed.add(document)
                seed.flush()
                version = IpDocumentVersion(
                    company_id=company_id,
                    document_id=document.id,
                    version=1,
                    original_filename="postgres-event-key.txt",
                    display_name="postgres-event-key.txt",
                    storage_key=f"postgres-event-key/{fixture_id}",
                    content_type="text/plain",
                    size_bytes=32,
                    sha256_hex=hashlib.sha256(fixture_id.encode("ascii")).hexdigest(),
                    processing_status="indexed",
                    extracted_char_count=32,
                    state="draft",
                    uploaded_by_membership_id=membership_id,
                )
                seed.add(version)
                seed.commit()
                document_id = document.id
                target_docket_id = target_docket.id

            request = {
                "expected_current_version": 1,
                "links": [{"target_type": "docket", "target_id": target_docket_id}],
            }
            linked = test_client.post(
                f"/api/ip/documents/{document_id}/links",
                headers=headers,
                json=request,
            )
            assert linked.status_code == 200, linked.text
            assert len(linked.json()["links"]) == 1
            created_link_id = str(linked.json()["links"][0]["id"])

            # A retry resolves the same operation identity and must not create
            # another event or advance the private security generation again.
            retried = test_client.post(
                f"/api/ip/documents/{document_id}/links",
                headers=headers,
                json=request,
            )
            assert retried.status_code == 200, retried.text

        raw_key = (
            f"ip-document-links:{document_id}:1:"
            f"{hashlib.sha256(created_link_id.encode('utf-8')).hexdigest()}"
        )
        assert len(raw_key) == 121
        with Session(pg_engine) as verify:
            events = list(
                verify.scalars(
                    select(PrivateProjectionEvent).where(
                        PrivateProjectionEvent.company_id == company_id,
                        PrivateProjectionEvent.target_type == "ip_document",
                        PrivateProjectionEvent.target_id == document_id,
                        PrivateProjectionEvent.reason_code
                        == "ip_document_links_changed",
                    )
                ).all()
            )
            assert len(events) == 1
            assert events[0].status == "applied"
            assert events[0].idempotency_key == build_private_projection_event_key(
                raw_key
            )
            assert len(events[0].idempotency_key) == 120
    finally:
        clear_engine_cache()
        get_settings.cache_clear()
