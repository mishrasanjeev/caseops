"""Court executor marker and atomic import proof on PostgreSQL; no provider network."""

from datetime import UTC, date, datetime, timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
    provider_replay_requested,
    reset_automated_test_request,
    reset_provider_replay_request,
    set_automated_test_request,
    set_provider_replay_request,
)
from caseops_api.db.models import (
    Court,
    Matter,
    MatterCauseListEntry,
    MatterComplianceExtractionRun,
    MatterCourtSyncJob,
    MatterCourtSyncRun,
)
from caseops_api.schemas.matters import MatterCauseListSyncItem
from caseops_api.services import bench_resolver, court_sync_jobs, llm
from caseops_api.workers import court_sync
from tests.test_court_sync_execution_20261010_postgres import (
    _readback,
    _result,
    _transactions,
)
from tests.test_court_sync_execution_20261010_postgres import (
    court_audit as _court_audit_fixture,
)
from tests.test_court_sync_execution_20261010_postgres import (
    finalizer_audit as _finalizer_audit_fixture,
)
from tests.test_postgres_validation import _ensure_migrations, _ip_race_context  # noqa: F401

pytestmark = pytest.mark.postgres
court_audit = _court_audit_fixture
finalizer_audit = _finalizer_audit_fixture


@pytest.mark.parametrize("blocked", [False, True])
def test_native_new_court_admission_captures_actual_marker(court_audit, monkeypatch, blocked):
    audit, fixture, _sessions, _run = court_audit
    monkeypatch.setattr(court_sync_jobs, "get_court_sync_adapter", lambda _: object())
    token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE if blocked else None)
    try:
        with audit.session("auth") as session:
            context = _ip_race_context(
                session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
            )
            record = court_sync_jobs.create_matter_court_sync_job(
                session,
                context=context,
                matter_id=fixture["matter_id"],
                source="local-emulator",
                source_reference="new-admission",
            )
        with Session(audit.engine) as session:
            job = session.get(MatterCourtSyncJob, record.id)
            assert job.no_paid_providers is blocked
            assert job.requested_by_membership_id == fixture["actor_id"]
            audit.record(
                "court_admission_marker",
                blocked=job.no_paid_providers,
                actor=job.requested_by_membership_id,
                source=job.source_reference,
            )
    finally:
        reset_automated_test_request(token)


@pytest.mark.parametrize(
    "stored, ambient, failure",
    [
        (True, False, False),
        (False, False, False),
        (False, True, False),
        (True, False, True),
        (False, True, True),
    ],
)
def test_native_marker_is_restored_through_adapter_and_import_and_reset(
    court_audit,
    monkeypatch,
    stored,
    ambient,
    failure,
):
    audit, fixture, sessions, run = court_audit
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        job.no_paid_providers = stored
        session.commit()
    token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE if ambient else None)
    replay = set_provider_replay_request("verified-fresh")
    seen = []
    inner_calls = []
    original = court_sync_jobs._persist_court_sync_import

    def inner_provider(_settings, _purpose):
        inner_calls.append("deterministic construction")
        return llm.MockProvider(model="local")

    monkeypatch.setattr(llm, "_build_inner_provider", inner_provider)

    def persist(*args, **kwargs):
        seen.append(("import", paid_providers_blocked_for_request(), provider_replay_requested()))
        return original(*args, **kwargs)

    def fetch(**_):
        assert not any(_transactions(sessions))
        with Session(audit.engine) as session:
            job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
            assert job.status == "processing" and job.no_paid_providers is stored
        seen.append(
            (
                "transport",
                paid_providers_blocked_for_request(),
                provider_replay_requested(),
            )
        )
        audit.record(
            "court_transport",
            transactions=_transactions(sessions),
            marker=seen[-1][1],
            replay=seen[-1][2],
        )
        # The real provider factory must not construct a paid provider for a blocked job.
        provider = llm.build_provider(purpose="metadata_extract")
        assert isinstance(provider, llm.MockProvider)
        if failure:
            raise ValueError("Deterministic marker cleanup failure")
        return _result("Durable marker preserved")

    monkeypatch.setattr(court_sync_jobs, "_persist_court_sync_import", persist)
    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    try:
        assert run() is True
        assert seen == [("transport", stored or ambient, False)] + (
            [] if failure else [("import", stored or ambient, False)]
        )
        assert inner_calls == ([] if stored or ambient else ["deterministic construction"])
        assert paid_providers_blocked_for_request() is ambient
        assert provider_replay_requested() is ambient
        rows = _readback(audit, fixture)
        assert rows["job_status"] == ("failed" if failure else "completed")
        assert rows["runs"] == (0 if failure else 1)
    finally:
        reset_provider_replay_request(replay)
        reset_automated_test_request(token)


def test_native_marker_change_during_transport_fences_all_import(court_audit, monkeypatch):
    audit, fixture, sessions, run = court_audit

    def fetch(**_):
        assert not any(_transactions(sessions))
        with audit.session("mutation") as session:
            job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
            assert job.no_paid_providers is True
            job.no_paid_providers = False
            session.commit()
        audit.record("court_marker_winner_committed", activity=audit.snapshot())
        return _result("Changed provenance must not import")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    assert run() is True
    rows = _readback(audit, fixture)
    assert rows["runs"] == 0 and rows["orders"] == []


@pytest.mark.parametrize("blank_bench", [False, True])
def test_native_import_keeps_company_and_claim_lock_across_actual_bench_resolution(
    court_audit,
    monkeypatch,
    blank_bench,
):
    audit, fixture, sessions, run = court_audit
    resolved, release = Event(), Event()
    original = bench_resolver.resolve_listing_bench
    worker_commits = []
    with Session(audit.engine) as session:
        court = Court(
            name="Native atomic court " + fixture["matter_id"],
            short_name="native-" + fixture["matter_id"][:12],
            forum_level="high_court",
            jurisdiction="india",
            is_active=True,
        )
        session.add(court)
        session.flush()
        session.get(Matter, fixture["matter_id"]).court_id = court.id
        session.commit()

    def after_commit(session):
        if session.info.get("finalizer_role") == "worker" and not session.in_nested_transaction():
            worker_commits.append("commit")

    def contender():
        with audit.session("mutation") as session:
            session.execute(
                text("SELECT id FROM companies WHERE id = :id FOR NO KEY UPDATE"),
                {"id": fixture["company_id"]},
            )
            session.commit()

    def resolve(session, **kwargs):
        assert kwargs["commit"] is False
        original(session, **kwargs)
        audit.record(
            "court_bench_resolved_under_claim",
            activity=audit.snapshot(),
            transaction=session.in_transaction(),
        )
        resolved.set()
        assert release.wait(8), "Court bench boundary not released"
        return [], []

    def fetch(**_):
        assert not any(_transactions(sessions))
        result = _result("Atomic court import")
        result.cause_list_entries = [
            MatterCauseListSyncItem(
                listing_date=date(2026, 10, 11),
                forum_name="Bombay High Court",
                bench_name=None if blank_bench else "Justice Unknown Local Fixture",
            )
        ]
        return result

    monkeypatch.setattr(bench_resolver, "resolve_listing_bench", resolve)
    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    event.listen(Session, "after_commit", after_commit)
    try:
        with audit.pool() as (pool, futures):
            worker = pool.submit(run)
            futures.append(worker)
            assert resolved.wait(5)
            waiting = pool.submit(contender)
            futures.append(waiting)
            audit.await_blocker("mutation", "worker")
            audit.record("court_bench_company_writer_blocked", activity=audit.snapshot())
            with Session(audit.engine) as reader:
                job = reader.get(MatterCourtSyncJob, fixture["court_job_id"])
                assert job.status == "processing"
                assert not reader.scalars(
                    select(MatterCauseListEntry).where(
                        MatterCauseListEntry.matter_id == fixture["matter_id"],
                    )
                ).all()
            release.set()
            assert worker.result(timeout=8) is True
            waiting.result(timeout=6)
    finally:
        release.set()
        event.remove(Session, "after_commit", after_commit)
    rows = _readback(audit, fixture)
    audit.record("court_outer_commit_inventory", commits=worker_commits)
    assert worker_commits == ["commit", "commit"]
    assert rows["job_status"] == "completed" and rows["runs"] == 1
    assert rows["orders"] == ["Atomic court import"]


@pytest.mark.parametrize("failure", ["resolver", "expiry"])
def test_native_import_bench_failure_savepoint_and_postimport_expiry(
    court_audit,
    monkeypatch,
    failure,
):
    audit, fixture, sessions, run = court_audit
    original = bench_resolver.resolve_listing_bench

    def resolve(session, **kwargs):
        if failure == "resolver":
            # An actual SQL error must roll back only the resolver savepoint.
            session.execute(text("SELECT 1 / 0"))
        result = original(session, **kwargs)
        if failure == "expiry":
            future = datetime.now(UTC) + timedelta(minutes=30)
            monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: future)
        return result

    def fetch(**_):
        assert not any(_transactions(sessions))
        result = _result("Savepoint or expiry result")
        result.cause_list_entries = [
            MatterCauseListSyncItem(
                listing_date=date(2026, 10, 11),
                forum_name="Bombay High Court",
                bench_name=None,
            )
        ]
        return result

    monkeypatch.setattr(bench_resolver, "resolve_listing_bench", resolve)
    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    assert run() is True
    rows = _readback(audit, fixture)
    audit.record("court_atomic_import_boundary", failure=failure, **rows)
    assert rows["job_status"] == ("completed" if failure == "resolver" else "processing")
    assert rows["runs"] == (1 if failure == "resolver" else 0)
    assert bool(rows["orders"]) is (failure == "resolver")
    with Session(audit.engine) as session:
        listings = session.scalars(
            select(MatterCauseListEntry).where(
                MatterCauseListEntry.matter_id == fixture["matter_id"],
            )
        ).all()
        assert len(listings) == (1 if failure == "resolver" else 0)
        if listings:
            assert listings[0].judges_json is None


def test_native_court_cli_bounded_real_queue_and_exact_outcomes(court_audit, monkeypatch, capsys):
    audit, fixture, sessions, _run = court_audit
    with Session(audit.engine) as session:
        # Exclude retained neighbors from this run's deterministic selection window.
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        job.queued_at = datetime(2000, 1, 1, tzinfo=UTC)
        session.commit()
    monkeypatch.setattr(
        court_sync,
        "get_settings",
        lambda: SimpleNamespace(
            court_sync_worker_admission_protocol_version=1,
            court_sync_worker_admission_enabled=True,
            court_sync_worker_batch_size=1,
            court_sync_stale_after_minutes=1440,
        ),
    )

    def fetch(**_):
        assert not any(_transactions(sessions))
        audit.record(
            "court_transport",
            transactions=_transactions(sessions),
            marker=paid_providers_blocked_for_request(),
        )
        return _result("Court-only CLI imported")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    assert court_sync.main(["--once", "--batch-size=1", "--skip-migrations"]) == 0
    receipt = capsys.readouterr().out
    audit.record("court_cli_receipt", receipt=receipt)
    assert "recovered=0 attempted=1 completed=1 failed=0 unfinalized=0" in receipt
    rows = _readback(audit, fixture)
    assert rows["job_status"] == "completed" and rows["runs"] == 1


def test_native_retained_null_creator_is_not_replaced_by_worker_identity(court_audit, monkeypatch):
    audit, fixture, sessions, run = court_audit
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        job.requested_by_membership_id = None
        session.commit()

    def fetch(**_):
        assert not any(_transactions(sessions))
        assert paid_providers_blocked_for_request()
        audit.record("court_transport", transactions=_transactions(sessions), marker=True)
        return _result("Historical null creator")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    assert run() is True
    rows = _readback(audit, fixture)
    assert rows["job_status"] == "completed" and rows["runs"] == 1
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        sync_run = session.get(MatterCourtSyncRun, job.sync_run_id)
        extraction = session.scalars(
            select(MatterComplianceExtractionRun).where(
                MatterComplianceExtractionRun.matter_id == fixture["matter_id"],
            )
        ).one()
        assert job.requested_by_membership_id is None
        assert sync_run.triggered_by_membership_id is None
        assert extraction.created_by_membership_id is None
        audit.record(
            "court_null_creator_retained",
            job_creator=None,
            import_creator=None,
            extraction_creator=None,
            real_extraction_status=extraction.status,
        )


def test_native_interrupt_resets_marker_and_retains_recoverable_claim(court_audit, monkeypatch):
    audit, fixture, sessions, run = court_audit
    clock = datetime.now(UTC) - timedelta(days=1)
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        job.updated_at = clock - timedelta(seconds=1)
        session.commit()
    monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: clock)

    def interrupted(**_):
        assert not any(_transactions(sessions))
        assert paid_providers_blocked_for_request()
        audit.record(
            "court_transport",
            transactions=_transactions(sessions),
            marker=True,
            outcome="interrupted",
        )
        raise KeyboardInterrupt("Deterministic worker interruption")

    token = set_automated_test_request(None)
    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=interrupted)
    )
    try:
        with pytest.raises(KeyboardInterrupt, match="Deterministic worker interruption"):
            run()
        assert not paid_providers_blocked_for_request()
        assert not any(_transactions(sessions))
        rows = _readback(audit, fixture)
        assert rows["job_status"] == "processing" and rows["runs"] == 0
        clock += timedelta(minutes=16)
        with Session(audit.engine) as session:
            eligible = session.scalars(
                select(MatterCourtSyncJob.id).where(
                    MatterCourtSyncJob.status == "processing",
                    MatterCourtSyncJob.started_at <= clock - timedelta(minutes=15),
                )
            ).all()
            assert eligible == [fixture["court_job_id"]]
        assert (
            court_sync_jobs.recover_stale_matter_court_sync_jobs(
                stale_after_minutes=15,
                limit=1,
            )
            == 1
        )
        with Session(audit.engine) as session:
            job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
            assert job.status == "queued" and job.started_at is None
            assert job.no_paid_providers is True
            assert job.requested_by_membership_id == fixture["actor_id"]
        monkeypatch.setattr(
            court_sync_jobs,
            "get_court_sync_adapter",
            lambda _: SimpleNamespace(
                fetch=lambda **_: _result("Recovered after local interruption"),
            ),
        )
        assert run() is True
        assert not paid_providers_blocked_for_request()
        rows = _readback(audit, fixture)
        assert rows["job_status"] == "completed" and rows["runs"] == 1
        audit.record(
            "court_interruption_recovery",
            exact_eligible_ids=eligible,
            marker_after_execution=False,
            **rows,
        )
    finally:
        reset_automated_test_request(token)
