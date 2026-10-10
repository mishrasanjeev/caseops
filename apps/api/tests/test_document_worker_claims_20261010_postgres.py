from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Contract,
    ContractAttachment,
    DocumentProcessingJob,
    IpDocketRecord,
    IpDocumentVersion,
    Matter,
    MatterAccessGrant,
    MatterActivity,
    MatterAttachment,
    PrivateProjectionEvent,
    utcnow,
)
from caseops_api.services import document_jobs, document_processing
from tests.fixtures_document_jobs import (
    legacy_document_processing_receipt as _legacy_receipt_fixture,
)
from tests.test_matter_writer_admission_postgres import _fixture
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def _worker(monkeypatch, engine, parse):
    sessions = []
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def create():
        session = factory()
        sessions.append(session)
        return session

    monkeypatch.setattr(document_jobs, "get_session_factory", lambda: create)
    monkeypatch.setattr(document_processing, "parse_attachment", parse)
    monkeypatch.setattr(document_jobs, "embed_matter_attachment_chunks",
                        lambda session, attachment, **kwargs: 0)
    return sessions


def _parsed(value="Prepared content"):
    return document_processing.ParsedDocument("indexed", value, [value], None)


def _assert_success(engine, fixture, attempts, content="Prepared content"):
    with Session(engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        assert (job.status, job.attempt_count, job.processed_char_count) == (
            "completed", attempts, len(content),
        ), job.error_message
        assert check.get(MatterAttachment, fixture.attachment).extracted_text == content
        assert check.scalar(select(func.count()).select_from(MatterActivity).where(
            MatterActivity.matter_id == fixture.matter,
            MatterActivity.event_type == "attachment_processed",
        )) == 1


def _activity_source(engine, target, *, active=True):
    if target == "ip-targeted":
        from tests.test_ip_document_workflow_postgres import _seed_document_source

        fixture = _seed_document_source(engine)
        with Session(engine) as seed:
            job = DocumentProcessingJob(company_id=fixture["company_id"],
                requested_by_membership_id=fixture["actor_id"], target_type="ip_document_version",
                attachment_id=fixture["version_id"], action="initial_index")
            seed.add(job)
            seed.commit()
            return SimpleNamespace(company=fixture["company_id"], actor=fixture["actor_id"],
                job=job.id, source=fixture["version_id"], model=IpDocumentVersion,
                docket=str(fixture["family"].docket_id))
    fixture = _fixture(engine, "ip" if target == "ip-targetless" else "matter", active=active)
    if target == "contract":
        with Session(engine) as seed:
            seed.delete(seed.get(DocumentProcessingJob, fixture.job))
            contract = Contract(company_id=fixture.company, title="Company activity worker",
                contract_code=uuid4().hex, contract_type="commercial")
            seed.add(contract)
            seed.flush()
            attachment = ContractAttachment(contract_id=contract.id,
                uploaded_by_membership_id=fixture.actor, original_filename="activity.txt",
                storage_key=uuid4().hex + ".txt", content_type="text/plain",
                size_bytes=20, sha256_hex="a" * 64)
            seed.add(attachment)
            seed.flush()
            job = DocumentProcessingJob(company_id=fixture.company,
                requested_by_membership_id=fixture.actor, target_type="contract_attachment",
                attachment_id=attachment.id, action="initial_index")
            seed.add(job)
            seed.commit()
            return SimpleNamespace(company=fixture.company, actor=fixture.actor,
                job=job.id, source=attachment.id, model=ContractAttachment)
    return SimpleNamespace(company=fixture.company, actor=fixture.actor, job=fixture.job,
        source=fixture.target_id, model=(
            IpDocumentVersion if target == "ip-targetless" else MatterAttachment
        ))


def _assert_no_output(engine, fixture, events_before):
    with Session(engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        assert job.status == "failed", job.error_message
        assert job.processed_char_count == 0
        source = check.get(fixture.model, fixture.source)
        assert source.extracted_text is None
        assert source.processed_at is None
        assert source.extracted_char_count == 0
        if hasattr(source, "chunks"):
            assert source.chunks == []
        assert check.scalar(select(func.count()).select_from(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture.company,
        )) == events_before


@pytest.mark.parametrize("target", ["matter", "contract", "ip-targetless", "ip-targeted"])
@pytest.mark.parametrize("disable_before_parser", [False, True])
def test_company_disable_wins_without_parser_results_or_private_events(
    pg_engine, monkeypatch, target, disable_before_parser,
):
    fixture = _activity_source(pg_engine, target)
    with Session(pg_engine) as seed:
        events_before = seed.scalar(select(func.count()).select_from(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture.company,
        ))
        if disable_before_parser:
            seed.get(Company, fixture.company).is_active = False
            seed.commit()
    calls = []

    def parse(*_):
        calls.append("parse")
        assert all(not session.in_transaction() for session in sessions)
        with Session(pg_engine) as disable:
            assert disable.scalar(select(Company.id).where(Company.id == fixture.company)
                                  .with_for_update(nowait=True)) == fixture.company
            disable.get(Company, fixture.company).is_active = False
            disable.commit()
        return _parsed("Inactive company output must never persist")

    sessions = _worker(monkeypatch, pg_engine, parse)
    monkeypatch.setattr(document_jobs, "embed_matter_attachment_chunks", lambda *_a, **_kw: (
        calls.append("embed") or 0
    ))
    assert document_jobs.run_document_processing_job(fixture.job) is True
    assert calls == ([] if disable_before_parser else ["parse"])
    _assert_no_output(pg_engine, fixture, events_before)
    with Session(pg_engine) as check:
        assert check.get(Company, fixture.company).is_active is False
        assert "Company inactive" in check.get(DocumentProcessingJob, fixture.job).error_message


@pytest.mark.parametrize("revocation", ["membership", "user", "role", "acl", "permitted-role"])
def test_targeted_ip_current_access_is_rechecked_during_parse(
    pg_engine, monkeypatch, revocation,
):
    fixture = _activity_source(pg_engine, "ip-targeted")
    with Session(pg_engine) as seed:
        events_before = seed.scalar(select(func.count()).select_from(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture.company,
        ))

    def parse(*_):
        assert all(not session.in_transaction() for session in sessions)
        with Session(pg_engine) as revoke:
            actor = revoke.get(CompanyMembership, fixture.actor)
            if revocation == "membership":
                actor.is_active = False
            elif revocation == "user":
                actor.user.is_active = False
            elif revocation == "role":
                from caseops_api.services.capabilities import static_capabilities_for_role

                assert "documents:upload" not in static_capabilities_for_role("viewer")
                actor.role = "viewer"
            elif revocation == "permitted-role":
                from caseops_api.services.capabilities import static_capabilities_for_role

                assert "documents:upload" in static_capabilities_for_role("member")
                actor.role = "member"
            else:
                grant = revoke.scalars(select(MatterAccessGrant).where(
                    MatterAccessGrant.company_id == fixture.company,
                    MatterAccessGrant.ip_docket_id == fixture.docket,
                    MatterAccessGrant.membership_id == fixture.actor,
                )).one()
                grant.revoked_at = datetime.now(UTC)
            revoke.commit()
        return _parsed("Revoked IP writer output must never persist")

    sessions = _worker(monkeypatch, pg_engine, parse)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    if revocation == "permitted-role":
        with Session(pg_engine) as check:
            job = check.get(DocumentProcessingJob, fixture.job)
            assert job.status == "completed", job.error_message
            assert check.get(fixture.model, fixture.source).extracted_text == (
                "Revoked IP writer output must never persist"
            )
    else:
        _assert_no_output(pg_engine, fixture, events_before)


@pytest.mark.parametrize("target", ["matter", "contract", "ip-targetless"])
@pytest.mark.parametrize("retained", ["inactive", "null"])
def test_system_processing_preserves_retained_actor_not_live_user_authorization(
    pg_engine, monkeypatch, target, retained,
):
    # Null historical provenance is legal only without an active private event generation.
    fixture = _activity_source(pg_engine, target, active=retained != "null")
    with Session(pg_engine) as seed:
        job = seed.get(DocumentProcessingJob, fixture.job)
        source = seed.get(fixture.model, fixture.source)
        job.requested_by_membership_id = None
        if retained == "inactive":
            actor = seed.get(CompanyMembership, fixture.actor)
            actor.is_active = False
            actor.user.is_active = False
            actor.role = "viewer"
        else:
            # IP's uploader is required provenance; only its requester may be absent.
            if target != "ip-targetless":
                source.uploaded_by_membership_id = None
        seed.commit()
    calls = []

    def parse(*_):
        calls.append(True)
        assert all(not session.in_transaction() for session in sessions)
        return _parsed("Legitimate historical system processing")

    sessions = _worker(monkeypatch, pg_engine, parse)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    assert calls == [True]
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        assert job.status == "completed", job.error_message
        assert check.get(fixture.model, fixture.source).extracted_text == (
            "Legitimate historical system processing"
        )


def test_company_disable_during_embedding_wins_before_vector_or_chunk_flush(pg_engine, monkeypatch):
    fixture = _activity_source(pg_engine, "matter")
    with Session(pg_engine) as seed:
        events_before = seed.scalar(select(func.count()).select_from(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture.company,
        ))
    sessions = _worker(monkeypatch, pg_engine, lambda *_: _parsed())
    from caseops_api.services import embeddings

    calls = []

    def embed(texts):
        calls.append(True)
        assert all(not session.in_transaction() for session in sessions)
        with Session(pg_engine) as disable:
            assert disable.scalar(select(Company.id).where(Company.id == fixture.company)
                                  .with_for_update(nowait=True)) == fixture.company
            disable.get(Company, fixture.company).is_active = False
            disable.commit()
        return SimpleNamespace(vectors=[[0.001] * 1024 for _ in texts],
                               model="document-worker-local-proof", dimensions=1024)

    monkeypatch.setattr(embeddings, "build_provider", lambda: SimpleNamespace(embed=embed))
    monkeypatch.setattr(document_jobs, "embed_matter_attachment_chunks",
                        document_processing.embed_matter_attachment_chunks)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    assert calls == [True]
    _assert_no_output(pg_engine, fixture, events_before)


def test_two_workers_claim_once_and_parser_has_no_transaction(pg_engine, monkeypatch):
    fixture = _fixture(pg_engine)
    entered, release = Event(), Event()
    observations = []

    def parse(*_args):
        observations.append([session.in_transaction() for session in sessions])
        assert all(not value for value in observations[-1])
        with Session(pg_engine) as probe:
            probe.execute(text("SET LOCAL lock_timeout = '1s'"))
            for model, row_id in ((Matter, fixture.matter),
                                  (MatterAttachment, fixture.attachment)):
                assert probe.scalar(select(model.id).where(model.id == row_id)
                                    .with_for_update(nowait=True)) == row_id
            probe.rollback()
        entered.set()
        assert release.wait(10)
        return _parsed()

    sessions = _worker(monkeypatch, pg_engine, parse)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(document_jobs.run_document_processing_job, fixture.job)
        try:
            assert entered.wait(10)
            second = pool.submit(document_jobs.run_document_processing_job, fixture.job)
            assert second.result(3) is False
        finally:
            release.set()
        assert first.result(10) is True
    assert len(observations) == 1
    _assert_success(pg_engine, fixture, 1)
    assert all(not session.in_transaction() for session in sessions)


def test_paused_claim_commit_cannot_adopt_reclaimed_attempt(pg_engine, monkeypatch):
    fixture = _fixture(pg_engine)
    committed, release_old = Event(), Event()
    parsing_new, release_new = Event(), Event()
    clock = [datetime.now(UTC) - timedelta(minutes=16)]
    monkeypatch.setattr(document_jobs, "utcnow", lambda: clock[0])
    calls = []

    def parse(*_args):
        calls.append(paid_providers_blocked_for_request())
        if len(calls) == 1:
            parsing_new.set()
            assert release_new.wait(10)
            return _parsed("Recovered attempt")
        return _parsed("Stolen attempt must not persist")

    sessions = _worker(monkeypatch, pg_engine, parse)

    def after_commit(session):
        if session is sessions[0] and not committed.is_set():
            committed.set()
            assert release_old.wait(10)

    event.listen(Session, "after_commit", after_commit)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(document_jobs.run_document_processing_job, fixture.job)
            try:
                assert committed.wait(10)
                clock[0] += timedelta(minutes=16)
                assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 1
                new = pool.submit(document_jobs.run_document_processing_job, fixture.job)
                assert parsing_new.wait(10)
                release_old.set()
                assert old.result(3) is False
                with Session(pg_engine) as check:
                    job = check.get(DocumentProcessingJob, fixture.job)
                    assert (job.status, job.attempt_count, job.no_paid_providers) == (
                        "processing", 2, True,
                    )
                    assert check.get(MatterAttachment, fixture.attachment).extracted_text is None
            finally:
                release_old.set()
                release_new.set()
            assert new.result(10) is True
    finally:
        event.remove(Session, "after_commit", after_commit)
    assert calls == [True]
    _assert_success(pg_engine, fixture, 2, "Recovered attempt")


@pytest.mark.parametrize("old_fails", [False, True])
def test_reclaimed_attempt_cannot_flush_or_fail_new_attempt(pg_engine, monkeypatch, old_fails):
    fixture = _fixture(pg_engine)
    entered, release = Event(), Event()
    clock = [datetime.now(UTC) - timedelta(minutes=16)]
    calls = []
    monkeypatch.setattr(document_jobs, "utcnow", lambda: clock[0])

    def parse(*_args):
        assert all(not session.in_transaction() for session in sessions)
        calls.append(paid_providers_blocked_for_request())
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
            if old_fails:
                raise RuntimeError("Old crashed attempt")
            return _parsed("Stale result must not persist")
        return _parsed("Recovered attempt")

    sessions = _worker(monkeypatch, pg_engine, parse)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(document_jobs.run_document_processing_job, fixture.job)
        try:
            assert entered.wait(10)
            clock[0] += timedelta(minutes=16)
            assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 1
            with Session(pg_engine) as check:
                job = check.get(DocumentProcessingJob, fixture.job)
                assert (job.status, job.attempt_count, job.no_paid_providers) == (
                    "queued", 1, True,
                )
            assert document_jobs.run_document_processing_job(fixture.job) is True
        finally:
            release.set()
        assert old.result(10) is True
    assert calls == [True, True]
    _assert_success(pg_engine, fixture, 2, "Recovered attempt")
    with Session(pg_engine) as check:
        assert check.get(DocumentProcessingJob, fixture.job).error_message is None


def test_recovery_is_bounded_and_skips_locked_rows(pg_engine, monkeypatch):
    fixtures = [_fixture(pg_engine, active=False) for _ in range(4)]
    before = utcnow() - timedelta(minutes=16)
    with Session(pg_engine) as seed:
        for index, fixture in enumerate(fixtures):
            _legacy_receipt_fixture(seed, fixture.job, status="processing", attempt_count=1,
                                    started_at=before + timedelta(seconds=index))
        seed.commit()
    _worker(monkeypatch, pg_engine, lambda *_: _parsed())
    with Session(pg_engine) as holder:
        holder.scalar(select(DocumentProcessingJob.id).where(
            DocumentProcessingJob.id == fixtures[0].job,
        ).with_for_update())
        assert document_jobs.recover_stale_document_processing_jobs(limit=2) == 2
        with Session(pg_engine) as check:
            assert [check.get(DocumentProcessingJob, item.job).status for item in fixtures] == [
                "processing", "queued", "queued", "processing",
            ]
        holder.rollback()
    with Session(pg_engine) as cleanup:
        for fixture in fixtures:
            cleanup.delete(cleanup.get(DocumentProcessingJob, fixture.job))
        cleanup.commit()


def test_expired_claim_cannot_finish_even_before_recovery(pg_engine, monkeypatch):
    fixture = _fixture(pg_engine)
    clock = [datetime.now(UTC) - timedelta(minutes=15)]
    monkeypatch.setattr(document_jobs, "utcnow", lambda: clock[0])

    def parse(*_):
        assert all(not session.in_transaction() for session in sessions)
        clock[0] += timedelta(minutes=15)
        return _parsed("Expired output must not persist")

    sessions = _worker(monkeypatch, pg_engine, parse)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    with Session(pg_engine) as check:
        assert check.get(MatterAttachment, fixture.attachment).extracted_text is None
        job = check.get(DocumentProcessingJob, fixture.job)
        assert (job.status, job.attempt_count, job.no_paid_providers) == ("processing", 1, True)
    assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 1
    with Session(pg_engine) as cleanup:
        job = cleanup.get(DocumentProcessingJob, fixture.job)
        assert job.no_paid_providers is True
        cleanup.delete(job)
        cleanup.commit()


def test_legacy_missing_start_time_is_recovered_but_marker_is_retained(pg_engine, monkeypatch):
    fixture = _fixture(pg_engine, active=False)
    with Session(pg_engine) as seed:
        _legacy_receipt_fixture(seed, fixture.job, status="processing", started_at=None,
                                updated_at=utcnow() - timedelta(days=154))
        seed.commit()
    _worker(monkeypatch, pg_engine, lambda *_: _parsed())
    assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 1
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        assert (job.status, job.started_at, job.no_paid_providers) == ("queued", None, True)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    _assert_success(pg_engine, fixture, 1)


@pytest.mark.parametrize("marked", [False, True])
def test_enqueue_marker_and_worker_context_are_durable_for_real_tenant(
    pg_engine, monkeypatch, marked,
):
    fixture = _fixture(pg_engine, active=False)
    # Fixture names are random ordinary companies; isolation is not slug-derived.
    token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE if marked else None)
    try:
        with Session(pg_engine) as enqueue:
            old = enqueue.get(DocumentProcessingJob, fixture.job)
            enqueue.delete(old)
            enqueue.flush()
            new = document_jobs.enqueue_processing_job(
                enqueue, company_id=fixture.company,
                requested_by_membership_id=fixture.actor, target_type=old.target_type,
                attachment_id=old.attachment_id, action="initial_index",
            )
            enqueue.commit()
            fixture.job = new.id
            assert new.no_paid_providers is marked
    finally:
        reset_automated_test_request(token)
    observed = []
    clock = [datetime.now(UTC) - timedelta(minutes=15)]
    monkeypatch.setattr(document_jobs, "utcnow", lambda: clock[0])

    def parse(*_):
        assert all(not session.in_transaction() for session in sessions)
        observed.append(paid_providers_blocked_for_request())
        if len(observed) == 1:
            clock[0] += timedelta(minutes=15)
        return _parsed()

    sessions = _worker(monkeypatch, pg_engine, parse)
    assert paid_providers_blocked_for_request() is False
    assert document_jobs.run_document_processing_job(fixture.job) is True
    assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 1
    with Session(pg_engine) as check:
        assert check.get(DocumentProcessingJob, fixture.job).no_paid_providers is marked
    assert document_jobs.run_document_processing_job(fixture.job) is True
    assert observed == [marked, marked]
    assert paid_providers_blocked_for_request() is False
    _assert_success(pg_engine, fixture, 2)


def test_terminal_matter_wins_during_parser_without_result_persistence(pg_engine, monkeypatch):
    fixture = _fixture(pg_engine)

    def parse(*_):
        assert all(not session.in_transaction() for session in sessions)
        with Session(pg_engine) as disposer:
            from caseops_api.schemas.matters import MatterLifecycleStatusRequest
            from caseops_api.services.matters import transition_matter_lifecycle_status
            from tests.test_postgres_validation import _ip_race_context

            context = _ip_race_context(disposer, company_id=fixture.company,
                                       membership_id=fixture.actor)
            matter = disposer.get(Matter, fixture.matter)
            transition_matter_lifecycle_status(disposer, context=context, matter_id=matter.id,
                payload=MatterLifecycleStatusRequest(
                    expected_from_status=matter.status, expected_updated_at=matter.updated_at,
                    to_status="disposed", reason="Worker parser race regression",
                ))
        return _parsed("Rejected terminal output")

    sessions = _worker(monkeypatch, pg_engine, parse)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    with Session(pg_engine) as check:
        assert check.get(Matter, fixture.matter).status == "disposed"
        assert check.get(MatterAttachment, fixture.attachment).extracted_text is None
        assert check.get(DocumentProcessingJob, fixture.job).status == "failed"


def test_failed_jobs_are_not_implicitly_claimed(pg_engine, monkeypatch):
    fixture = _fixture(pg_engine, active=False)
    with Session(pg_engine) as seed:
        _legacy_receipt_fixture(seed, fixture.job, status="failed")
        seed.commit()
    calls = []
    _worker(monkeypatch, pg_engine, lambda *_: calls.append(True))
    assert document_jobs.run_document_processing_job(fixture.job) is False
    positive = _fixture(pg_engine, active=False)
    selected = []
    monkeypatch.setattr(document_jobs, "run_document_processing_job",
                        lambda job_id: selected.append(job_id) or False)
    assert document_jobs.drain_document_processing_jobs(limit=5) == 0
    assert fixture.job not in selected
    assert selected, "A positive queued receipt must also be selected"
    with Session(pg_engine) as check:
        assert check.get(DocumentProcessingJob, fixture.job).attempt_count == 0
        assert all(check.get(DocumentProcessingJob, job_id).status == "queued"
                   for job_id in selected)
        check.delete(check.get(DocumentProcessingJob, positive.job))
        check.commit()
    assert calls == []


def test_embedding_callback_has_no_transaction_and_persists_vectors(pg_engine, monkeypatch):
    fixture = _fixture(pg_engine)
    sessions = _worker(monkeypatch, pg_engine, lambda *_: _parsed())
    from caseops_api.services import embeddings

    observations = []

    def embed(texts):
        observations.append([session.in_transaction() for session in sessions])
        assert observations[-1] == [False]
        with Session(pg_engine) as probe:
            assert probe.scalar(select(Matter.id).where(Matter.id == fixture.matter)
                                .with_for_update(nowait=True)) == fixture.matter
        return SimpleNamespace(vectors=[[0.001] * 1024 for _ in texts],
                               model="document-worker-local-proof", dimensions=1024)

    monkeypatch.setattr(embeddings, "build_provider", lambda: SimpleNamespace(embed=embed))
    monkeypatch.setattr(document_jobs, "embed_matter_attachment_chunks",
                        document_processing.embed_matter_attachment_chunks)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    assert observations == [[False]]
    _assert_success(pg_engine, fixture, 1)
    with Session(pg_engine) as check:
        chunks = check.get(MatterAttachment, fixture.attachment).chunks
        assert len(chunks) == 1 and chunks[0].embedding_dimensions == 1024
        assert chunks[0].embedding_model == "document-worker-local-proof"
        assert chunks[0].embedding_json is not None


@pytest.mark.parametrize("terminal", [False, True])
def test_contract_parser_releases_transaction_and_rechecks_linked_matter(
    pg_engine, monkeypatch, terminal,
):
    fixture = _fixture(pg_engine, active=False)
    with Session(pg_engine) as seed:
        seed.delete(seed.get(DocumentProcessingJob, fixture.job))
        contract = Contract(company_id=fixture.company, linked_matter_id=fixture.matter,
                            title="Worker contract", contract_code=uuid4().hex,
                            contract_type="commercial")
        seed.add(contract)
        seed.flush()
        attachment = ContractAttachment(contract_id=contract.id,
            uploaded_by_membership_id=fixture.actor, original_filename="contract.txt",
            storage_key=uuid4().hex + ".txt", content_type="text/plain",
            size_bytes=20, sha256_hex="a" * 64)
        seed.add(attachment)
        seed.flush()
        job = DocumentProcessingJob(company_id=fixture.company,
            requested_by_membership_id=fixture.actor, target_type="contract_attachment",
            attachment_id=attachment.id, action="initial_index")
        seed.add(job)
        seed.commit()
        job_id, source_id, contract_id = job.id, attachment.id, contract.id
    observed = []

    def parse(*_):
        observed.append([session.in_transaction() for session in sessions])
        assert observed[-1] == [False]
        with Session(pg_engine) as writer:
            assert writer.scalar(select(Contract.id).where(Contract.id == contract_id)
                                 .with_for_update(nowait=True)) == contract_id
            writer.rollback()
            if terminal:
                from caseops_api.schemas.matters import MatterLifecycleStatusRequest
                from caseops_api.services.matters import transition_matter_lifecycle_status
                from tests.test_postgres_validation import _ip_race_context

                matter = writer.get(Matter, fixture.matter)
                transition_matter_lifecycle_status(writer,
                    context=_ip_race_context(writer, company_id=fixture.company,
                                             membership_id=fixture.actor),
                    matter_id=matter.id, payload=MatterLifecycleStatusRequest(
                        expected_from_status=matter.status, expected_updated_at=matter.updated_at,
                        to_status="disposed", reason="Contract processing lifecycle race",
                    ))
        return _parsed()

    sessions = _worker(monkeypatch, pg_engine, parse)
    assert document_jobs.run_document_processing_job(job_id) is True
    assert observed == [[False]]
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, job_id)
        assert job.status == ("failed" if terminal else "completed"), job.error_message
        assert check.get(ContractAttachment, source_id).extracted_text == (
            None if terminal else "Prepared content"
        )


@pytest.mark.parametrize("target", ["matter", "contract"])
@pytest.mark.parametrize("boundary", [
    "replace", "parser_failure", "source_change", "finalize_failure",
])
def test_reindex_replaces_retained_chunks_only_after_fresh_authority(
    pg_engine, monkeypatch, target, boundary,
):
    fixture = _activity_source(pg_engine, target, active=False)
    old_text = "Retained first chunk. Retained second chunk."
    new_text = "Replacement first chunk. Replacement second chunk."
    chunk_model = fixture.model.chunks.property.mapper.class_
    with Session(pg_engine) as seed:
        source = seed.get(fixture.model, fixture.source)
        source.processing_status = "indexed"
        source.extracted_text = old_text
        source.extracted_char_count = len(old_text)
        source.processed_at = utcnow()
        source.chunks = [
            chunk_model(chunk_index=index, content=value, token_count=len(value.split()))
            for index, value in enumerate(["Retained first chunk.", "Retained second chunk."])
        ]
        original_job = seed.get(DocumentProcessingJob, fixture.job)
        target_type = original_job.target_type
        seed.delete(original_job)
        seed.flush()
        job = DocumentProcessingJob(company_id=fixture.company,
            requested_by_membership_id=fixture.actor, target_type=target_type,
            attachment_id=fixture.source, action="reindex", no_paid_providers=True)
        seed.add(job)
        seed.commit()
        job_id = job.id
        old_ids = [chunk.id for chunk in source.chunks]
        parent_model = Matter if target == "matter" else Contract
        parent_id = source.matter_id if target == "matter" else source.contract_id
    observations = []

    def parse(*_):
        assert all(not session.in_transaction() for session in sessions)
        with Session(pg_engine) as concurrent:
            assert concurrent.scalar(select(parent_model.id).where(parent_model.id == parent_id)
                                     .with_for_update(nowait=True)) == parent_id
            retained = concurrent.get(fixture.model, fixture.source)
            observations.append([chunk.content for chunk in retained.chunks])
            assert retained.extracted_text == old_text
            assert observations[-1] == ["Retained first chunk.", "Retained second chunk."]
            if boundary == "source_change":
                retained.chunks.append(chunk_model(chunk_index=2,
                    content="Concurrent writer wins.", token_count=4))
                concurrent.commit()
        if boundary == "parser_failure":
            raise RuntimeError("Deterministic parser failure before replacement")
        return document_processing.ParsedDocument("indexed", new_text,
            ["Replacement first chunk.", "Replacement second chunk."], None)

    sessions = _worker(monkeypatch, pg_engine, parse)
    if boundary == "finalize_failure":
        replace = document_jobs._attach_replacement_chunks

        def fail_after_delete(session, source):
            replace(session, source)
            assert session.scalar(select(func.count()).select_from(chunk_model).where(
                chunk_model.attachment_id == source.id)) == 0
            raise RuntimeError("Deterministic persistence failure after replacement delete")

        monkeypatch.setattr(document_jobs, "_attach_replacement_chunks", fail_after_delete)
    assert document_jobs.run_document_processing_job(job_id) is True
    assert len(observations) == 1
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, job_id)
        source = check.get(fixture.model, fixture.source)
        assert job.status == ("completed" if boundary == "replace" else "failed"), job.error_message
        assert source.extracted_text == (new_text if boundary == "replace" else old_text)
        chunks = list(source.chunks)
        assert [chunk.chunk_index for chunk in chunks] == (
            [0, 1, 2] if boundary == "source_change" else [0, 1])
        assert [chunk.content for chunk in chunks] == (
            ["Replacement first chunk.", "Replacement second chunk."] if boundary == "replace"
            else ["Retained first chunk.", "Retained second chunk."]
                 + (["Concurrent writer wins."] if boundary == "source_change" else []))
        if boundary == "replace":
            assert set(old_ids).isdisjoint(chunk.id for chunk in chunks)
        else:
            assert [chunk.id for chunk in chunks[:2]] == old_ids
        assert job.processed_char_count == (len(new_text) if boundary == "replace" else 0)
    if boundary == "replace":
        with Session(pg_engine) as seed:
            repeated = DocumentProcessingJob(company_id=fixture.company,
                requested_by_membership_id=fixture.actor, target_type=target_type,
                attachment_id=fixture.source, action="reindex", no_paid_providers=True)
            seed.add(repeated)
            seed.commit()
            repeated_id = repeated.id
        monkeypatch.setattr(document_processing, "parse_attachment", lambda *_:
            document_processing.ParsedDocument("indexed", "Second replacement.",
                                               ["Second replacement."], None))
        assert document_jobs.run_document_processing_job(repeated_id) is True
        with Session(pg_engine) as check:
            assert check.get(DocumentProcessingJob, repeated_id).status == "completed"
            source = check.get(fixture.model, fixture.source)
            assert source.extracted_text == "Second replacement."
            assert [(chunk.chunk_index, chunk.content) for chunk in source.chunks] == [
                (0, "Second replacement.")]


@pytest.mark.parametrize("terminal", [False, True])
def test_ip_parser_releases_transaction_and_rechecks_target_lifecycle(
    pg_engine, monkeypatch, terminal,
):
    from tests.test_ip_document_workflow_postgres import _seed_document_source

    fixture = _seed_document_source(pg_engine)
    with Session(pg_engine) as seed:
        job = DocumentProcessingJob(company_id=fixture["company_id"],
            requested_by_membership_id=fixture["actor_id"], target_type="ip_document_version",
            attachment_id=fixture["version_id"], action="initial_index")
        seed.add(job)
        seed.commit()
        job_id = job.id
    observed = []

    def parse(*_):
        observed.append([session.in_transaction() for session in sessions])
        assert observed[-1] == [False]
        with Session(pg_engine) as writer:
            assert writer.scalar(select(IpDocumentVersion.id).where(
                IpDocumentVersion.id == fixture["version_id"],
            ).with_for_update(nowait=True)) == fixture["version_id"]
            writer.rollback()
            if terminal:
                from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
                from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
                from tests.test_postgres_validation import _ip_race_context

                family = fixture["family"]
                transition_ip_docket_lifecycle(writer,
                    context=_ip_race_context(writer, company_id=fixture["company_id"],
                                             membership_id=fixture["actor_id"]),
                    docket_id=str(family.docket_id), payload=IpLifecycleTransitionRequest(
                        expected_lifecycle_version=family.lifecycle_version, to_status="closed",
                        effective_at=datetime.now(UTC), reason="Document worker terminal race",
                        outcome="closed", source="lawyer_review", evidence_ref="test:worker-race",
                        linked_matter_handling="reviewed",
                    ))
        return _parsed()

    sessions = _worker(monkeypatch, pg_engine, parse)
    assert document_jobs.run_document_processing_job(job_id) is True
    assert observed == [[False]]
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, job_id)
        assert job.status == ("failed" if terminal else "completed"), job.error_message
        assert check.get(IpDocumentVersion, fixture["version_id"]).extracted_text == (
            None if terminal else "Prepared content"
        )
        docket = check.get(IpDocketRecord, str(fixture["family"].docket_id))
        assert docket.is_active is (not terminal)
