"""Real court imports with native claim, recovery and authority boundaries.

This is SQL/worker proof, not Cloud Run CPU allocation or rollout-drain proof.
"""

from datetime import UTC, date, datetime, timedelta
from threading import Event, get_ident, local
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import Matter, MatterCourtOrder, MatterCourtSyncJob, MatterCourtSyncRun
from caseops_api.schemas.matters import MatterCourtOrderSyncItem, MatterLifecycleStatusRequest
from caseops_api.services import court_sync_jobs, matters
from tests.test_document_finalizer_overlap_20261009_postgres import (
    _seed_finalizer,
)
from tests.test_document_finalizer_overlap_20261009_postgres import (
    finalizer_audit as _finalizer_audit_fixture,
)
from tests.test_postgres_validation import _ensure_migrations, _ip_race_context  # noqa: F401

pytestmark = pytest.mark.postgres
finalizer_audit = _finalizer_audit_fixture


@pytest.fixture
def court_audit(finalizer_audit, monkeypatch):
    audit = finalizer_audit
    audit.boundary = "court"
    fixture = _seed_finalizer(audit.engine, "matter")
    with Session(audit.engine) as session:
        job = MatterCourtSyncJob(
            company_id=fixture["company_id"],
            matter_id=fixture["matter_id"],
            requested_by_membership_id=fixture["actor_id"],
            source="local-emulator",
            source_reference="retained-source",
        )
        session.add(job)
        session.commit()
        fixture["court_job_id"] = job.id
    roles, sessions = local(), []

    def factory():
        session = audit.session(getattr(roles, "value", "worker"))
        session.info["court_thread"] = get_ident()
        sessions.append(session)
        return session

    def run(role="worker"):
        roles.value = role
        return court_sync_jobs.run_matter_court_sync_job(fixture["court_job_id"])

    monkeypatch.setattr(court_sync_jobs, "get_session_factory", lambda: factory)
    return audit, fixture, sessions, run


@pytest.fixture
def isolated_court_audit(http_pg_engine, request):
    # Resolve the audit only after the independently migrated template child is
    # selected. Global recovery must not consume another test's retained claim.
    result = request.getfixturevalue("court_audit")
    audit, fixture, _sessions, _run = result
    assert audit.engine.url == http_pg_engine.url
    assert audit.engine.url.database.startswith("caseops_http_")
    with Session(audit.engine) as session:
        jobs = list(session.scalars(select(MatterCourtSyncJob.id)))
    assert jobs == [fixture["court_job_id"]]
    audit.record("court_isolated_recovery_database", database=audit.engine.url.database,
                 initial_job_ids=jobs, template_child=True)
    return result


def _result(title):
    return SimpleNamespace(
        adapter_name="deterministic-court-emulator",
        summary="Retained local court result",
        cause_list_entries=[],
        orders=[
            MatterCourtOrderSyncItem(
                order_date=date(2026, 10, 10),
                title=title,
                summary="Native owned claim",
                order_text="The parties shall file their reply within two weeks.",
            )
        ],
    )


def _transactions(sessions):
    return [
        session.in_transaction()
        for session in sessions
        if session.info.get("court_thread") == get_ident()
    ]


def _readback(audit, fixture):
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        rows = {
            "job_status": job.status,
            "job_error": job.error_message,
            "started_at": str(job.started_at),
            "source_reference": job.source_reference,
            "runs": session.scalar(
                select(func.count())
                .select_from(MatterCourtSyncRun)
                .where(
                    MatterCourtSyncRun.matter_id == fixture["matter_id"],
                )
            ),
            "orders": list(
                session.scalars(
                    select(MatterCourtOrder.title)
                    .where(
                        MatterCourtOrder.matter_id == fixture["matter_id"],
                    )
                    .order_by(MatterCourtOrder.title)
                )
            ),
            "matter_status": session.get(Matter, fixture["matter_id"]).status,
        }
        audit.record("court_readback", **rows)
        return rows


def test_native_overlapping_claimers_dispatch_exactly_once(court_audit, monkeypatch):
    audit, fixture, sessions, run = court_audit
    entered, release = Event(), Event()
    calls = []

    def after(connection, _cursor, sql, _parameters, _context, _many):
        if (
            connection.info.get("finalizer_role") == "worker"
            and sql.startswith("SELECT ")
            and "FROM matter_court_sync_jobs" in sql
            and not entered.is_set()
        ):
            audit.record("court_claim_selection", pid=audit.pids["worker"], sql=sql)
            entered.set()
            assert release.wait(8), "Court claim selection was not released"

    def fetch(**_):
        active = _transactions(sessions)
        audit.record("court_transport", transactions=active, pids=audit.pids.copy())
        assert not any(active)
        calls.append("adapter")
        return _result("Single native claim")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    event.listen(audit.engine, "after_cursor_execute", after)
    try:
        with audit.pool() as (pool, futures):
            first = pool.submit(run)
            futures.append(first)
            assert entered.wait(5)
            second = pool.submit(run, "mutation")
            futures.append(second)
            try:
                duplicate = second.result(timeout=5)
                audit.record(
                    "court_duplicate_returned", result=duplicate, activity=audit.snapshot()
                )
            finally:
                release.set()
            assert first.result(timeout=8) is True
    finally:
        release.set()
        event.remove(audit.engine, "after_cursor_execute", after)
    rows = _readback(audit, fixture)
    audit.record("court_dispatch_count", calls=len(calls))
    assert calls == ["adapter"]
    assert duplicate is False
    assert rows["job_status"] == "completed" and rows["runs"] == 1
    assert rows["orders"] == ["Single native claim"]


@pytest.mark.parametrize("old_outcome", ["result", "error"])
def test_native_recovery_replacement_fences_stale_success_and_failure(
    isolated_court_audit,
    monkeypatch,
    old_outcome,
):
    audit, fixture, sessions, run = isolated_court_audit
    entered, release = Event(), Event()
    calls = []

    def fetch(**_):
        assert not any(_transactions(sessions))
        first = not calls
        calls.append("old" if first else "replacement")
        audit.record("court_transport", owner=calls[-1], transactions=_transactions(sessions))
        if first:
            entered.set()
            assert release.wait(8)
            if old_outcome == "error":
                raise ValueError("Stale deterministic court transport failed")
        return _result("Old result" if first else "Replacement result")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    try:
        with audit.pool() as (pool, futures):
            old = pool.submit(run)
            futures.append(old)
            assert entered.wait(5)
            with Session(audit.engine) as session:
                old_started = session.get(MatterCourtSyncJob, fixture["court_job_id"]).started_at
            future = datetime.now(UTC) + timedelta(minutes=30)
            monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: future)
            assert court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=15) == 1
            replacement = pool.submit(run, "mutation")
            futures.append(replacement)
            assert replacement.result(timeout=6) is True
            release.set()
            assert old.result(timeout=6) is True
    finally:
        release.set()
    rows = _readback(audit, fixture)
    audit.record("court_recovered_owner", old_started=str(old_started), calls=calls)
    assert calls == ["old", "replacement"]
    assert rows["job_status"] == "completed" and rows["job_error"] is None
    assert rows["runs"] == 1 and rows["orders"] == ["Replacement result"]
    assert rows["started_at"] != str(old_started)


def test_native_global_recovery_counts_unrelated_retained_stale_claim(
    isolated_court_audit, monkeypatch,
):
    audit, fixture, _sessions, _run = isolated_court_audit
    unrelated = _seed_finalizer(audit.engine, "matter")
    now = datetime.now(UTC)
    stale = now - timedelta(minutes=30)
    with Session(audit.engine) as session:
        target = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        target.status, target.started_at = "processing", stale
        retained = MatterCourtSyncJob(
            company_id=unrelated["company_id"], matter_id=unrelated["matter_id"],
            requested_by_membership_id=unrelated["actor_id"],
            source="local-emulator", source_reference="unrelated-retained-source",
            status="processing", started_at=stale,
        )
        session.add(retained)
        session.commit()
        ids = sorted([target.id, retained.id])
        assert target.company_id != retained.company_id
    monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: now)
    recovered = court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=15)
    audit.record("court_shared_recovery_counterproof", job_ids=ids,
                 recovered=recovered, old_fixture_expected=1)
    assert recovered == 2
    with Session(audit.engine) as session:
        rows = list(session.execute(
            select(MatterCourtSyncJob.id, MatterCourtSyncJob.status)
            .where(MatterCourtSyncJob.id.in_(ids)).order_by(MatterCourtSyncJob.id)
        ))
    assert rows == [(job_id, "queued") for job_id in ids]


@pytest.mark.parametrize("winner", ["disposal", "source_change"])
def test_native_transport_winner_is_retained_without_import(court_audit, monkeypatch, winner):
    audit, fixture, sessions, run = court_audit

    def fetch(**_):
        assert not any(_transactions(sessions))
        with audit.session("mutation") as session:
            if winner == "disposal":
                context = _ip_race_context(
                    session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
                )
                matter = session.get(Matter, fixture["matter_id"])
                matters.transition_matter_lifecycle_status(
                    session,
                    context=context,
                    matter_id=matter.id,
                    payload=MatterLifecycleStatusRequest(
                        to_status="disposed",
                        expected_from_status="active",
                        expected_updated_at=matter.updated_at,
                        reason="Native court transport disposal winner.",
                    ),
                )
            else:
                job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
                job.source_reference = "changed-source"
                session.commit()
        audit.record("court_transport_winner_committed", winner=winner, activity=audit.snapshot())
        return _result("Must not survive winner")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    assert run() is True
    rows = _readback(audit, fixture)
    assert rows["runs"] == 0 and rows["orders"] == []
    if winner == "disposal":
        assert rows["matter_status"] == "disposed" and rows["job_status"] == "failed"
        assert "disposed" in rows["job_error"]
    else:
        assert rows["source_reference"] == "changed-source"


def test_native_recovery_skips_locked_claim_and_respects_batch(court_audit):
    audit, fixture, _sessions, _run = court_audit
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        job.status = "processing"
        job.started_at = datetime.now(UTC) - timedelta(minutes=30)
        session.commit()
    with audit.session("revocation") as holder:
        holder.scalar(
            select(MatterCourtSyncJob)
            .where(
                MatterCourtSyncJob.id == fixture["court_job_id"],
            )
            .with_for_update(of=MatterCourtSyncJob)
        )
        assert (
            court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=15, limit=1)
            == 0
        )
        audit.record("court_recovery_skipped_locked_claim", activity=audit.snapshot())
    assert (
        court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=15, limit=1) == 1
    )
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        assert job.status == "queued" and job.started_at is None
        assert job.requested_by_membership_id == fixture["actor_id"]
        assert job.source_reference == "retained-source"


def test_native_adapter_does_not_hold_company_authority_lock(court_audit, monkeypatch):
    audit, fixture, sessions, run = court_audit

    def fetch(**_):
        assert not any(_transactions(sessions))
        with audit.session("mutation") as session:
            session.execute(
                text("SELECT id FROM companies WHERE id = :id FOR NO KEY UPDATE"),
                {"id": fixture["company_id"]},
            )
            audit.record("court_transport_company_writer_admitted", activity=audit.snapshot())
            session.commit()
        return _result("Transaction-free court transport")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    assert run() is True
    rows = _readback(audit, fixture)
    assert rows["job_status"] == "completed" and rows["runs"] == 1


def test_native_production_dispatch_preserves_queue_without_postresponse_work(
    court_audit, monkeypatch
):
    audit, fixture, sessions, run = court_audit
    background_tasks = BackgroundTasks()
    calls = []

    def fetch(**_):
        assert not any(_transactions(sessions))
        calls.append("adapter")
        return _result("Admitted independent court job")

    monkeypatch.setattr(court_sync_jobs, "get_settings", lambda: SimpleNamespace(env="cloud"))
    with audit.session("auth") as request_session:
        request_session.get(MatterCourtSyncJob, fixture["court_job_id"])
        court_sync_jobs.dispatch_matter_court_sync_job(
            session=request_session,
            background_tasks=background_tasks,
            job_id=fixture["court_job_id"],
        )
        assert not request_session.in_transaction()
        with audit.session("mutation") as writer:
            writer.execute(
                text("SELECT id FROM companies WHERE id = :id FOR NO KEY UPDATE"),
                {"id": fixture["company_id"]},
            )
            writer.commit()
        audit.record(
            "court_production_admission",
            background_tasks=len(background_tasks.tasks),
            request_transaction=request_session.in_transaction(),
            provider_calls=len(calls),
            activity=audit.snapshot(),
        )
    rows = _readback(audit, fixture)
    assert not background_tasks.tasks and not calls
    assert rows["job_status"] == "queued" and rows["runs"] == 0
    monkeypatch.setattr(
        court_sync_jobs,
        "get_settings",
        lambda: SimpleNamespace(env="cloud", court_sync_stale_after_minutes=15),
    )
    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    assert run() is True
    rows = _readback(audit, fixture)
    assert calls == ["adapter"]
    assert rows["job_status"] == "completed" and rows["runs"] == 1
    assert rows["orders"] == ["Admitted independent court job"]


def test_native_expired_claim_cannot_import_before_recovery(court_audit, monkeypatch):
    audit, fixture, sessions, run = court_audit
    claim_time = datetime.now(UTC) - timedelta(days=1)
    with Session(audit.engine) as session:
        job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
        job.updated_at = claim_time - timedelta(seconds=1)
        session.commit()
        existing_stale = list(
            session.scalars(
                select(MatterCourtSyncJob.id)
                .where(
                    MatterCourtSyncJob.status == "processing",
                    MatterCourtSyncJob.started_at <= claim_time + timedelta(minutes=1),
                )
                .limit(26)
            )
        )
    # The owned gate retains preceding tenants. Isolate the recovery window,
    # rather than assuming a global LIMIT 1 will select this fixture's claim.
    assert not existing_stale
    audit.record(
        "court_expiry_fixture_window",
        claim_time=claim_time.isoformat(),
        preexisting_eligible_job_ids=existing_stale,
    )
    monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: claim_time)

    def fetch(**_):
        assert not any(_transactions(sessions))
        with Session(audit.engine) as reader:
            started = reader.get(MatterCourtSyncJob, fixture["court_job_id"]).started_at
        expired = started + timedelta(minutes=16)
        monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: expired)
        audit.record(
            "court_transport_expired",
            started_at=started.isoformat(),
            observed_now=expired.isoformat(),
            transactions=_transactions(sessions),
        )
        return _result("Expired result must not survive")

    monkeypatch.setattr(
        court_sync_jobs, "get_court_sync_adapter", lambda _: SimpleNamespace(fetch=fetch)
    )
    assert run() is True
    rows = _readback(audit, fixture)
    assert rows["job_status"] == "processing" and rows["job_error"] is None
    assert rows["runs"] == 0 and rows["orders"] == []
    with Session(audit.engine) as session:
        eligible = list(
            session.scalars(
                select(MatterCourtSyncJob.id)
                .where(
                    MatterCourtSyncJob.status == "processing",
                    MatterCourtSyncJob.started_at
                    <= court_sync_jobs.utcnow() - timedelta(minutes=15),
                )
                .limit(26)
            )
        )
    audit.record("court_expiry_recovery_inventory", eligible_job_ids=eligible)
    assert eligible == [fixture["court_job_id"]]
    assert (
        court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=15, limit=1) == 1
    )
    rows = _readback(audit, fixture)
    assert rows["job_status"] == "queued" and rows["started_at"] == "None"
    assert rows["source_reference"] == "retained-source" and rows["runs"] == 0
