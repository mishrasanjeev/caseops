"""Gmail review stages bytes without transactions and admits one current write."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    Communication,
    Company,
    CompanyMembership,
    DocumentProcessingJob,
    MailboxAttachmentCandidate,
    MailboxMessageImport,
    Matter,
    MatterActivity,
    MatterAttachment,
    TenantGoogleWorkspaceConfiguration,
    User,
    UserMailboxConnection,
)
from caseops_api.schemas.mailbox import MailboxAttachmentCandidateReviewRequest
from caseops_api.services import document_jobs, document_storage, gmail_sync, matters, virus_scan
from caseops_api.services.calendar_sync import _decrypt_token_payload, _encrypt_secret
from caseops_api.services.gmail_sync import GmailProviderError
from tests.test_matter_writer_admission_postgres import _fixture, _mutate, race  # noqa: F401
from tests.test_postgres_validation import _ensure_migrations, _ip_race_context  # noqa: F401

pytestmark = pytest.mark.postgres
CONTENT = b"Reviewed Gmail evidence bytes"


@pytest.fixture(autouse=True)
def _gmail_provider_isolation():
    gmail_sync.set_gmail_provider_for_tests(None)
    yield
    gmail_sync.set_gmail_provider_for_tests(None)


def _seed(engine):
    fixture = _fixture(engine)
    with Session(engine) as session:
        configuration = TenantGoogleWorkspaceConfiguration(
            company_id=fixture.company,
            client_id="tenant-gmail-client",
            encrypted_client_secret_ref=_encrypt_secret("tenant-gmail-secret"),
            gmail_redirect_uri="https://api.example.test/api/mailbox/gmail/callback",
            enabled=True,
            gmail_enabled=True,
            created_by_membership_id=fixture.actor,
        )
        connection = UserMailboxConnection(
            company_id=fixture.company,
            membership_id=fixture.actor,
            provider="gmail",
            status="connected",
            provider_account_id="test@example.test",
            encrypted_token_ref=gmail_sync._encrypt_token_payload(
                {
                    "access_token": "original-access",
                    "refresh_token": "original-refresh",
                }
            ),
            scopes_json=list(gmail_sync.GMAIL_SCOPES),
        )
        session.add_all([configuration, connection])
        session.flush()
        message = MailboxMessageImport(
            company_id=fixture.company,
            mailbox_connection_id=connection.id,
            matter_id=fixture.matter,
            provider_message_id=f"gmail-{uuid4()}",
            status="linked_metadata",
            attachment_count=1,
        )
        session.add(message)
        session.flush()
        candidate = MailboxAttachmentCandidate(
            company_id=fixture.company,
            message_import_id=message.id,
            matter_id=fixture.matter,
            provider_attachment_ref_hash=sha256(b"attachment-id").hexdigest(),
            encrypted_provider_attachment_ref=_encrypt_secret("attachment-id"),
            filename="review.txt",
            content_type="text/plain",
            size_bytes=len(CONTENT),
            status="needs_review",
        )
        session.add(candidate)
        session.commit()
        fixture.connection, fixture.candidate = connection.id, candidate.id
        fixture.message, fixture.config = message.id, configuration.id
        fixture.user = session.get(CompanyMembership, fixture.actor).user_id
    return fixture


def _storage(monkeypatch, root):
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: root)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(
            status="clean",
            signature=None,
        ),
    )


class _Provider:
    configured = True

    def __init__(self, callback=None):
        self.callback, self.calls = callback, []

    def fetch_attachment(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.callback:
            return self.callback(**kwargs)
        return CONTENT


def _invoke(session, fixture, *, action="approve_import", actor=None):
    context = _ip_race_context(
        session,
        company_id=fixture.company,
        membership_id=actor or fixture.actor,
    )
    context.token_issued_at = (datetime.now(UTC) - timedelta(minutes=1)).timestamp()
    return gmail_sync.review_attachment_candidate(
        session,
        context=context,
        candidate_id=fixture.candidate,
        payload=MailboxAttachmentCandidateReviewRequest(action=action),
    )


def _files(root):
    return sorted(path for path in root.rglob("*") if path.is_file())


def _unpublished(engine, fixture):
    with Session(engine) as session:
        assert list(
            session.scalars(
                select(MatterAttachment.id).where(
                    MatterAttachment.matter_id == fixture.matter,
                )
            )
        ) == [fixture.attachment]
        assert list(
            session.scalars(
                select(DocumentProcessingJob.id).where(
                    DocumentProcessingJob.company_id == fixture.company,
                )
            )
        ) == [fixture.job]
        assert not list(
            session.scalars(
                select(MatterActivity.id).where(
                    MatterActivity.matter_id == fixture.matter,
                    MatterActivity.event_type == "inbound_email_attachment_added",
                )
            )
        )
        assert not list(
            session.scalars(
                select(AuditEvent.id).where(
                    AuditEvent.target_id == fixture.candidate,
                    AuditEvent.action == "mailbox.gmail_attachment.imported",
                )
            )
        )
        assert (
            session.get(MailboxAttachmentCandidate, fixture.candidate).imported_attachment_id
            is None
        )


def _published(engine, fixture, root, expected):
    with Session(engine) as session:
        candidate = session.get(MailboxAttachmentCandidate, fixture.candidate)
        assert candidate.status == "approved_imported"
        assert candidate.imported_attachment_id == expected
        attachment = session.get(MatterAttachment, expected)
        assert attachment.matter_id == fixture.matter
        assert attachment.uploaded_by_membership_id == fixture.actor
        assert attachment.sha256_hex == sha256(CONTENT).hexdigest()
        assert (root / attachment.storage_key).read_bytes() == CONTENT
        jobs = list(
            session.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.attachment_id == expected,
                )
            )
        )
        assert len(jobs) == 1
        assert jobs[0].action == "initial_index"
        assert jobs[0].target_type == "matter_attachment"
        assert jobs[0].requested_by_membership_id == fixture.actor
        assert (
            len(
                list(
                    session.scalars(
                        select(MatterActivity.id).where(
                            MatterActivity.matter_id == fixture.matter,
                            MatterActivity.event_type == "inbound_email_attachment_added",
                        )
                    )
                )
            )
            == 1
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(AuditEvent.id).where(
                            AuditEvent.target_id == fixture.candidate,
                            AuditEvent.action == "mailbox.gmail_attachment.imported",
                        )
                    )
                )
            )
            == 1
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("refresh_mode", ["none", "preserve", "rotate"])
def test_gmail_attachment_all_transport_releases_transaction(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    refresh_mode,
):
    refresh = refresh_mode != "none"
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    observed = []
    place = document_storage._place_local_temp_file
    with Session(pg_engine, autoflush=autoflush) as session:

        def released(boundary):
            assert not session.in_transaction(), boundary
            with Session(pg_engine) as observer:
                for table, identity in (
                    ("companies", fixture.company),
                    ("company_memberships", fixture.actor),
                    ("matters", fixture.matter),
                    ("user_mailbox_connections", fixture.connection),
                    ("mailbox_attachment_candidates", fixture.candidate),
                ):
                    observer.execute(
                        text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE NOWAIT"),
                        {"id": identity},
                    )
            _unpublished(pg_engine, fixture)
            observed.append(boundary)

        def fetch(**kwargs):
            released("fetch")
            if refresh and len(provider.calls) == 1:
                raise GmailProviderError("expired", status_code=401)
            assert kwargs["message_id"].startswith("gmail-")
            assert kwargs["attachment_id"] == "attachment-id"
            assert kwargs["token_payload"]["access_token"] == (
                "refreshed-access" if refresh else "original-access"
            )
            return CONTENT

        provider = _Provider(fetch)
        gmail_sync.set_gmail_provider_for_tests(provider)

        def token_refresh(url, *, data, timeout):
            released("refresh")
            assert url == "https://oauth2.googleapis.com/token"
            assert data == {
                "client_id": "tenant-gmail-client",
                "client_secret": "tenant-gmail-secret",
                "grant_type": "refresh_token",
                "refresh_token": "original-refresh",
            }
            assert timeout == 15
            refreshed = {"access_token": "refreshed-access"}
            if refresh_mode == "rotate":
                refreshed["refresh_token"] = "rotated-refresh"
            return httpx.Response(200, json=refreshed)

        def scan(_):
            released("scan")
            return virus_scan.ScanResult(status="clean", signature=None)

        def store(source, target):
            released("store")
            return place(source, target)

        monkeypatch.setattr(httpx, "post", token_refresh)
        monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        result = _invoke(session, fixture)
        _published(pg_engine, fixture, tmp_path, result.imported_attachment_id)
        for _ in range(2):
            assert _invoke(session, fixture).imported_attachment_id == result.imported_attachment_id
            assert not session.in_transaction()
    assert observed == (["fetch", "refresh", "fetch"] if refresh else ["fetch"]) + ["scan", "store"]
    assert len(_files(tmp_path)) == 1
    with Session(pg_engine) as session:
        connection = session.get(UserMailboxConnection, fixture.connection)
        token = _decrypt_token_payload(connection.encrypted_token_ref)
        assert token["refresh_token"] == (
            "rotated-refresh" if refresh_mode == "rotate" else "original-refresh"
        )
        assert token["access_token"] == ("refreshed-access" if refresh else "original-access")
        assert token["access_token"] not in connection.encrypted_token_ref


def _change(session, fixture, change):
    if change in {"dispose", "dispose_reopen"}:
        disposed = _mutate(session, fixture, "dispose")
        if change == "dispose_reopen":
            from caseops_api.schemas.matters import MatterLifecycleStatusRequest

            matters.transition_matter_lifecycle_status(
                session,
                context=_ip_race_context(
                    session,
                    company_id=fixture.company,
                    membership_id=fixture.actor,
                ),
                matter_id=fixture.matter,
                payload=MatterLifecycleStatusRequest(
                    to_status="intake",
                    expected_from_status="disposed",
                    expected_updated_at=disposed.updated_at,
                    reason="Controlled Gmail race reopen.",
                ),
            )
        return
    if change in {"company_disabled", "quota"}:
        company = session.get(Company, fixture.company)
        if change == "quota":
            company.storage_quota_bytes = 23
        else:
            company.is_active = False
    elif change in {"membership_disabled", "session_cutoff", "capability"}:
        member = session.get(CompanyMembership, fixture.actor)
        if change == "membership_disabled":
            member.is_active = False
        elif change == "session_cutoff":
            member.sessions_valid_after = datetime.now(UTC)
        else:
            member.role = "viewer"
    elif change == "user_disabled":
        session.get(User, fixture.user).is_active = False
    elif change == "access":
        session.get(Matter, fixture.matter).restricted_access = True
    elif change in {"connection_revoked", "token_rotated", "connection_scope"}:
        connection = session.get(UserMailboxConnection, fixture.connection)
        if change == "connection_revoked":
            gmail_sync.revoke_gmail_connection(
                session,
                context=_ip_race_context(
                    session,
                    company_id=fixture.company,
                    membership_id=fixture.actor,
                ),
                connection_id=fixture.connection,
            )
            return
        if change == "connection_scope":
            connection.scopes_json = []
        else:
            connection.encrypted_token_ref = gmail_sync._encrypt_token_payload(
                {"access_token": "newer-access", "refresh_token": "newer-refresh"}
            )
    elif change in {"config_disabled", "config_rotated"}:
        config = session.get(TenantGoogleWorkspaceConfiguration, fixture.config)
        if change == "config_disabled":
            config.gmail_enabled = False
        else:
            config.encrypted_client_secret_ref = _encrypt_secret("newer-tenant-secret")
    elif change in {"candidate_rejected", "candidate_changed", "candidate_unlinked"}:
        candidate = session.get(MailboxAttachmentCandidate, fixture.candidate)
        if change == "candidate_rejected":
            candidate.status = "rejected"
        elif change == "candidate_unlinked":
            candidate.matter_id = None
        else:
            candidate.filename = "newer-name.txt"
    elif change in {"message_changed", "message_unlinked"}:
        message = session.get(MailboxMessageImport, fixture.message)
        if change == "message_unlinked":
            message.matter_id = None
        else:
            message.provider_message_id = "newer-provider-id"
    else:
        raise AssertionError(change)
    session.commit()


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("boundary", ["fetch", "store"])
@pytest.mark.parametrize(
    "change",
    [
        "company_disabled",
        "membership_disabled",
        "user_disabled",
        "session_cutoff",
        "capability",
        "access",
        "dispose",
        "dispose_reopen",
        "connection_revoked",
        "token_rotated",
        "config_disabled",
        "config_rotated",
        "candidate_rejected",
        "candidate_changed",
        "message_changed",
        "candidate_unlinked",
        "message_unlinked",
        "connection_scope",
        "quota",
    ],
)
def test_gmail_attachment_rechecks_current_authority_after_io(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    boundary,
    change,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    entered, resume = Event(), Event()
    place = document_storage._place_local_temp_file

    def pause():
        entered.set()
        assert resume.wait(15), "Gmail review I/O was not released"

    def fetch(**kwargs):
        if boundary == "fetch":
            pause()
        return CONTENT

    def store(source, target):
        result = place(source, target)
        if boundary == "store":
            pause()
        return result

    gmail_sync.set_gmail_provider_for_tests(_Provider(fetch))
    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)

    def review():
        with Session(pg_engine, autoflush=autoflush) as session:
            return _invoke(session, fixture)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(review)
        try:
            assert entered.wait(10)
            with Session(pg_engine) as writer:
                writer.execute(text("SET LOCAL lock_timeout = '2s'"))
                _change(writer, fixture, change)
            resume.set()
            with pytest.raises(HTTPException) as failure:
                future.result(15)
            expected = (
                401
                if change == "session_cutoff"
                else 403
                if change
                in {"company_disabled", "membership_disabled", "user_disabled", "capability"}
                else 404
                if change == "access"
                else 409
            )
            if change == "quota":
                expected = 413
            assert failure.value.status_code == expected
        finally:
            resume.set()
    _unpublished(pg_engine, fixture)
    assert _files(tmp_path) == []
    with Session(pg_engine) as session:
        candidate = session.get(MailboxAttachmentCandidate, fixture.candidate)
        assert candidate.status == (
            "rejected" if change == "candidate_rejected" else "needs_review"
        )
        assert session.get(Matter, fixture.matter).status == (
            "disposed"
            if change == "dispose"
            else "intake"
            if change == "dispose_reopen"
            else "active"
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("outer_work", ["new", "dirty", "deleted", "flushed", "core_dml", "nested"])
def test_gmail_review_preserves_caller_owned_writes(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    outer_work,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    provider = _Provider()
    gmail_sync.set_gmail_provider_for_tests(provider)
    with Session(pg_engine, autoflush=autoflush) as session:
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.actor)
        candidate = session.get(MailboxAttachmentCandidate, fixture.candidate)
        if outer_work == "new":
            session.add(
                Communication(
                    company_id=fixture.company,
                    matter_id=fixture.matter,
                    direction="inbound",
                    channel="note",
                    body="Caller retained write",
                    created_by_membership_id=fixture.actor,
                )
            )
        elif outer_work == "deleted":
            session.delete(candidate)
        elif outer_work in {"dirty", "flushed"}:
            candidate.filename = "caller-name.txt"
            if outer_work == "flushed":
                session.flush()
        elif outer_work == "core_dml":
            session.execute(
                text("UPDATE mailbox_attachment_candidates SET filename=:name WHERE id=:id"),
                {"name": "caller-name.txt", "id": fixture.candidate},
            )
        else:
            session.begin_nested()
        transaction = session.get_transaction()
        with pytest.raises(HTTPException) as failure:
            gmail_sync.review_attachment_candidate(
                session,
                context=context,
                candidate_id=fixture.candidate,
                payload=MailboxAttachmentCandidateReviewRequest(action="approve_import"),
            )
        assert failure.value.status_code == 409
        assert session.get_transaction() is transaction
        assert transaction.is_active
        assert not provider.calls
        if outer_work == "nested":
            assert session.in_nested_transaction()
        else:
            session.commit()
    assert not _files(tmp_path)
    with Session(pg_engine) as session:
        if outer_work == "deleted":
            assert session.get(MailboxAttachmentCandidate, fixture.candidate) is None
        elif outer_work in {"dirty", "flushed", "core_dml"}:
            assert (
                session.get(MailboxAttachmentCandidate, fixture.candidate).filename
                == "caller-name.txt"
            )
        elif outer_work == "new":
            assert (
                session.scalar(
                    select(Communication.id).where(
                        Communication.company_id == fixture.company,
                        Communication.body == "Caller retained write",
                    )
                )
                is not None
            )


@pytest.mark.parametrize("autoflush", [False, True])
def test_gmail_concurrent_review_is_atomic_and_idempotent(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    gmail_sync.set_gmail_provider_for_tests(_Provider())
    barrier = Barrier(2)
    place = document_storage._place_local_temp_file

    def store(source, target):
        result = place(source, target)
        barrier.wait(12)
        return result

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)

    def review():
        with Session(pg_engine, autoflush=autoflush) as session:
            return _invoke(session, fixture)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(review) for _ in range(2)]
        results = [future.result(20) for future in futures]
    assert results[0].imported_attachment_id == results[1].imported_attachment_id
    _published(pg_engine, fixture, tmp_path, results[0].imported_attachment_id)
    assert len(_files(tmp_path)) == 1


@pytest.mark.parametrize("autoflush", [False, True])
def test_gmail_concurrent_candidates_have_one_quota_winner(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
):
    fixture = _seed(pg_engine)
    sibling = SimpleNamespace(**vars(fixture))
    with Session(pg_engine) as session:
        original = session.get(MailboxAttachmentCandidate, fixture.candidate)
        candidate = MailboxAttachmentCandidate(
            company_id=fixture.company,
            message_import_id=fixture.message,
            matter_id=fixture.matter,
            filename="sibling.txt",
            content_type="text/plain",
            provider_attachment_ref_hash=sha256(b"sibling-attachment").hexdigest(),
            encrypted_provider_attachment_ref=_encrypt_secret("sibling-attachment"),
            size_bytes=len(CONTENT),
            status=original.status,
        )
        session.add(candidate)
        session.get(Company, fixture.company).storage_quota_bytes = 23 + len(CONTENT)
        session.commit()
        sibling.candidate = candidate.id
    _storage(monkeypatch, tmp_path)
    gmail_sync.set_gmail_provider_for_tests(_Provider())
    barrier = Barrier(2)
    place = document_storage._place_local_temp_file

    def store(source, target):
        result = place(source, target)
        barrier.wait(12)
        return result

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)

    def review(target):
        with Session(pg_engine, autoflush=autoflush) as session:
            try:
                return target, _invoke(session, target)
            except HTTPException as exc:
                assert exc.status_code == 413
                return target, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(review, target) for target in (fixture, sibling)]
        results = [future.result(20) for future in futures]
    winners = [(target, result) for target, result in results if result is not None]
    assert len(winners) == 1
    target, result = winners[0]
    _published(pg_engine, target, tmp_path, result.imported_attachment_id)
    assert len(_files(tmp_path)) == 1
    with Session(pg_engine) as session:
        attachments = list(
            session.scalars(
                select(MatterAttachment).where(
                    MatterAttachment.matter_id == fixture.matter,
                )
            )
        )
        assert len(attachments) == 2
        assert sum(row.size_bytes for row in attachments) == 23 + len(CONTENT)
        loser = next(target for target, result in results if result is None)
        assert session.get(MailboxAttachmentCandidate, loser.candidate).status == "needs_review"


@pytest.mark.parametrize("owner_change", ["membership_disabled", "user_disabled"])
def test_gmail_shared_matter_review_rechecks_mailbox_owner(
    pg_engine,
    monkeypatch,
    tmp_path,
    owner_change,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)

    def fetch(**kwargs):
        with Session(pg_engine) as session:
            _change(session, fixture, owner_change)
        return CONTENT

    gmail_sync.set_gmail_provider_for_tests(_Provider(fetch))
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as failure:
            _invoke(session, fixture, actor=fixture.owner)
        assert failure.value.status_code == 403
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)


def test_gmail_cleanup_failure_does_not_mask_revocation(
    pg_engine,
    monkeypatch,
    tmp_path,
    caplog,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    gmail_sync.set_gmail_provider_for_tests(_Provider())
    place = document_storage._place_local_temp_file

    def store(source, target):
        result = place(source, target)
        with Session(pg_engine) as session:
            _change(session, fixture, "connection_revoked")
        return result

    def failed_cleanup(key):
        raise OSError("Synthetic storage cleanup failure")

    monkeypatch.setattr(gmail_sync.logger, "disabled", False)
    caplog.set_level("ERROR", logger=gmail_sync.__name__)
    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    monkeypatch.setattr(document_storage, "delete_stored_document", failed_cleanup)
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as failure:
            _invoke(session, fixture)
        assert failure.value.status_code == 409
    _unpublished(pg_engine, fixture)
    logs = [row for row in caplog.records if row.name == gmail_sync.__name__]
    assert len(logs) == 1
    assert logs[0].msg == "gmail_attachment.staged_cleanup_failed"
    assert logs[0].args == ()
    assert logs[0].exc_info is not None
    assert len(_files(tmp_path)) == 1
    assert _files(tmp_path)[0].read_bytes() == CONTENT


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("outcome", ["before_commit", "after_commit"])
def test_gmail_unknown_commit_retains_unique_object_bytes(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    outcome,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    gmail_sync.set_gmail_provider_for_tests(_Provider())
    with Session(pg_engine, autoflush=autoflush) as session:
        commit = session.commit

        def uncertain_commit():
            if outcome == "after_commit":
                commit()
            raise RuntimeError("Synthetic unknown commit response")

        monkeypatch.setattr(session, "commit", uncertain_commit)
        with pytest.raises(RuntimeError, match="unknown commit"):
            _invoke(session, fixture)
    assert len(_files(tmp_path)) == 1
    assert _files(tmp_path)[0].read_bytes() == CONTENT
    if outcome == "before_commit":
        _unpublished(pg_engine, fixture)
    else:
        with Session(pg_engine) as session:
            imported_id = session.get(
                MailboxAttachmentCandidate, fixture.candidate
            ).imported_attachment_id
        _published(pg_engine, fixture, tmp_path, imported_id)
        with Session(pg_engine) as session:
            assert _invoke(session, fixture).imported_attachment_id == imported_id


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("stage", ["job", "audit"])
def test_gmail_admission_failure_rolls_back_all_children(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    stage,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    gmail_sync.set_gmail_provider_for_tests(_Provider())
    enqueue, audit = document_jobs.enqueue_processing_job, gmail_sync.record_from_context

    def fail_job(session, **kwargs):
        enqueue(session, **kwargs)
        raise RuntimeError("Synthetic job-stage failure")

    def fail_audit(session, context, **kwargs):
        result = audit(session, context, **kwargs)
        if kwargs["action"] == "mailbox.gmail_attachment.imported":
            session.flush()
            raise RuntimeError("Synthetic audit-stage failure")
        return result

    monkeypatch.setattr(
        document_jobs, "enqueue_processing_job", fail_job if stage == "job" else enqueue
    )
    monkeypatch.setattr(
        gmail_sync, "record_from_context", fail_audit if stage == "audit" else audit
    )
    with Session(pg_engine, autoflush=autoflush) as session:
        with pytest.raises(HTTPException) as failure:
            _invoke(session, fixture)
        assert failure.value.status_code == 502
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)


@pytest.mark.parametrize("boundary", ["refresh", "scan"])
def test_gmail_disconnect_during_refresh_or_scanner_cannot_restore_credentials(
    pg_engine,
    monkeypatch,
    tmp_path,
    boundary,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    provider = _Provider()

    def disconnect():
        with Session(pg_engine) as session:
            _change(session, fixture, "connection_revoked")

    def fetch(**kwargs):
        if len(provider.calls) == 1:
            raise GmailProviderError("expired", status_code=401)
        return CONTENT

    provider.callback = fetch
    gmail_sync.set_gmail_provider_for_tests(provider)

    def refresh(*args, **kwargs):
        if boundary == "refresh":
            disconnect()
        return httpx.Response(
            200,
            json={
                "access_token": "stale-refreshed-access",
                "refresh_token": "stale-rotated-refresh",
            },
        )

    def scan(_):
        if boundary == "scan":
            disconnect()
        return virus_scan.ScanResult(status="clean", signature=None)

    monkeypatch.setattr(httpx, "post", refresh)
    monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as failure:
            _invoke(session, fixture)
        assert failure.value.status_code == 409
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)
    with Session(pg_engine) as session:
        connection = session.get(UserMailboxConnection, fixture.connection)
        assert connection.status == "revoked"
        assert connection.encrypted_token_ref is None


@pytest.mark.parametrize("autoflush", [False, True])
def test_gmail_provider_failure_after_refresh_cannot_overwrite_disconnect(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    provider = _Provider()

    def fetch(**kwargs):
        raise GmailProviderError(
            "expired" if len(provider.calls) == 1 else "unavailable",
            status_code=401 if len(provider.calls) == 1 else 503,
        )

    def refresh(*args, **kwargs):
        with Session(pg_engine) as session:
            _change(session, fixture, "connection_revoked")
        return httpx.Response(
            200, json={"access_token": "stale-refreshed", "refresh_token": "stale-rotation"}
        )

    provider.callback = fetch
    gmail_sync.set_gmail_provider_for_tests(provider)
    monkeypatch.setattr(httpx, "post", refresh)
    with Session(pg_engine, autoflush=autoflush) as session:
        with pytest.raises(HTTPException) as failure:
            _invoke(session, fixture)
        assert failure.value.status_code == 409
    assert len(provider.calls) == 2
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)
    with Session(pg_engine) as session:
        connection = session.get(UserMailboxConnection, fixture.connection)
        assert connection.status == "revoked"
        assert connection.encrypted_token_ref is None
        assert not list(
            session.scalars(
                select(AuditEvent.id).where(
                    AuditEvent.target_id == fixture.candidate,
                    AuditEvent.action == "mailbox.gmail_attachment.import_failed",
                )
            )
        )


@pytest.mark.parametrize("condition", ["config", "scope", "connection", "reference"])
def test_gmail_unusable_review_fails_before_provider_transport(
    pg_engine,
    monkeypatch,
    tmp_path,
    condition,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    provider = _Provider()
    gmail_sync.set_gmail_provider_for_tests(provider)
    with Session(pg_engine) as session:
        if condition == "config":
            session.get(TenantGoogleWorkspaceConfiguration, fixture.config).gmail_enabled = False
        elif condition == "scope":
            session.get(UserMailboxConnection, fixture.connection).scopes_json = []
        elif condition == "connection":
            session.get(UserMailboxConnection, fixture.connection).status = "error"
        else:
            session.get(
                MailboxAttachmentCandidate, fixture.candidate
            ).encrypted_provider_attachment_ref = None
        session.commit()
        with pytest.raises(HTTPException) as failure:
            _invoke(session, fixture)
        assert failure.value.status_code == (503 if condition == "config" else 409)
    assert not provider.calls
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)


@pytest.mark.parametrize(
    "failure",
    [
        "429",
        "503",
        "timeout",
        "invalid_grant",
        "refresh_503",
        "invalid_json",
        "missing_access",
        "repeated_401",
        "retry_503",
        "refresh_timeout",
        "refresh_429_html",
        "invalid_client",
        "unexpected_403",
        "whitespace_access",
        "wrong_token_type",
        "insufficient_scope",
        "invalid_refresh",
        "oversized",
        "nan_token",
    ],
)
def test_gmail_provider_failures_are_bounded_and_keep_transient_review_retryable(
    pg_engine,
    monkeypatch,
    tmp_path,
    failure,
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    provider = _Provider()
    refresh_calls = []

    def fetch(**kwargs):
        if failure in {"429", "503"}:
            raise GmailProviderError(
                "Provider token or private payload must not leak", status_code=int(failure)
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("Private provider URL must not leak")
        if failure == "retry_503" and len(provider.calls) == 2:
            raise GmailProviderError("temporarily unavailable after refresh", status_code=503)
        raise GmailProviderError("expired", status_code=401)

    def refresh(*args, **kwargs):
        refresh_calls.append(True)
        if failure == "invalid_grant":
            return httpx.Response(400, json={"error": "invalid_grant"})
        if failure == "invalid_client":
            return httpx.Response(400, json={"error": "invalid_client"})
        if failure == "unexpected_403":
            return httpx.Response(403, text="Private provider response must not leak")
        if failure == "refresh_503":
            return httpx.Response(503, json={"error": "unavailable"})
        if failure == "refresh_429_html":
            return httpx.Response(429, text="Private provider response must not leak")
        if failure == "refresh_timeout":
            raise httpx.ReadTimeout("Private token URL must not leak")
        if failure == "invalid_json":
            return httpx.Response(200, text="not-json")
        if failure == "missing_access":
            return httpx.Response(200, json={"refresh_token": "rotated"})
        if failure == "whitespace_access":
            return httpx.Response(200, json={"access_token": "invalid token"})
        if failure == "wrong_token_type":
            return httpx.Response(200, json={"access_token": "refreshed", "token_type": "mac"})
        if failure == "insufficient_scope":
            return httpx.Response(200, json={"access_token": "refreshed", "scope": "openid"})
        if failure == "invalid_refresh":
            return httpx.Response(200, json={"access_token": "refreshed", "refresh_token": ["bad"]})
        if failure == "oversized":
            return httpx.Response(200, json={"access_token": "x" * 65537})
        if failure == "nan_token":
            return httpx.Response(200, text='{"access_token":"refreshed","expires_in":NaN}')
        return httpx.Response(200, json={"access_token": "refreshed"})

    provider.callback = fetch
    gmail_sync.set_gmail_provider_for_tests(provider)
    monkeypatch.setattr(httpx, "post", refresh)
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture)
    reconnect = failure in {"invalid_grant", "repeated_401"}
    assert error.value.status_code == (
        409 if reconnect else 502 if failure in {"429", "503", "timeout", "retry_503"} else 503
    )
    assert "Private" not in str(error.value.detail)
    assert len(provider.calls) == (2 if failure in {"repeated_401", "retry_503"} else 1)
    assert len(refresh_calls) == int(failure not in {"429", "503", "timeout"})
    _unpublished(pg_engine, fixture)
    with Session(pg_engine) as session:
        connection = session.get(UserMailboxConnection, fixture.connection)
        assert connection.status == ("error" if reconnect else "connected")
        token = _decrypt_token_payload(connection.encrypted_token_ref)
        assert token["access_token"] == (
            "refreshed" if failure in {"repeated_401", "retry_503"} else "original-access"
        )
        assert token["refresh_token"] == "original-refresh"
        assert token["access_token"] not in connection.encrypted_token_ref
        assert session.get(MailboxAttachmentCandidate, fixture.candidate).status == "needs_review"
    assert not _files(tmp_path)


@pytest.mark.parametrize("autoflush", [False, True])
def test_gmail_waiting_admission_reloads_authority_after_company_lock(
    pg_engine,
    monkeypatch,
    tmp_path,
    request,
    autoflush,
):
    harness = request.getfixturevalue("race")
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    gmail_sync.set_gmail_provider_for_tests(_Provider())
    entered, resume = Event(), Event()
    place = document_storage._place_local_temp_file

    def store(source, target):
        result = place(source, target)
        entered.set()
        assert resume.wait(15)
        return result

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    harness.pause_role = "revoke"
    harness.predicate = lambda sql: sql.startswith("UPDATE company_memberships")
    harness.after = True

    def review():
        with harness.session("review") as session:
            return _invoke(session, fixture)

    def revoke():
        with harness.session("revoke") as session:
            from caseops_api.services.matter_write_fence import lock_matter_private_authority

            lock_matter_private_authority(session, company_id=fixture.company)
            session.get(CompanyMembership, fixture.actor).is_active = False
            session.commit()

    review_future = harness.submit("review", review)
    try:
        assert entered.wait(10)
        revoke_future = harness.submit("revoke", revoke)
        assert harness.paused.wait(10)
        resume.set()
        harness.blocked("review", "revoke", "SELECT companies.id")
        harness.release.set()
        revoke_future.result(15)
        with pytest.raises(HTTPException) as failure:
            review_future.result(15)
        assert failure.value.status_code == 403
    finally:
        resume.set()
        harness.release.set()
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)
