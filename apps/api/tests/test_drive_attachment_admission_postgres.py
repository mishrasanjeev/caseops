"""Drive reviewed-file admission with real PostgreSQL and deterministic I/O."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
    DriveFileCandidate,
    DriveSyncControl,
    Matter,
    MatterActivity,
    MatterAttachment,
    TenantGoogleWorkspaceConfiguration,
    User,
    UserDriveConnection,
)
from caseops_api.schemas.drive import DriveCandidateReviewRequest
from caseops_api.schemas.matters import MatterLifecycleStatusRequest
from caseops_api.services import document_jobs, document_storage, drive_sync, matters, virus_scan
from caseops_api.services.calendar_sync import _decrypt_token_payload, _encrypt_secret
from tests.test_matter_writer_admission_postgres import _fixture, _mutate, race  # noqa: F401
from tests.test_postgres_validation import _ensure_migrations, _ip_race_context  # noqa: F401

pytestmark = pytest.mark.postgres
CONTENT = b"Reviewed Drive evidence bytes"


@pytest.fixture(autouse=True)
def _provider_isolation():
    drive_sync.set_google_drive_provider_for_tests(None)
    yield
    drive_sync.set_google_drive_provider_for_tests(None)


def _seed(engine):
    fixture = _fixture(engine)
    with Session(engine) as session:
        config = TenantGoogleWorkspaceConfiguration(
            company_id=fixture.company,
            client_id="tenant-drive-client",
            encrypted_client_secret_ref=_encrypt_secret("tenant-drive-secret"),
            drive_redirect_uri="https://api.example.test/api/drive/google/callback",
            enabled=True,
            drive_enabled=True,
            created_by_membership_id=fixture.actor,
        )
        control = DriveSyncControl(company_id=fixture.company, provider="google_drive")
        connection = UserDriveConnection(
            company_id=fixture.company,
            membership_id=fixture.actor,
            provider="google_drive",
            status="connected",
            provider_account_id="drive-owner",
            encrypted_token_ref=drive_sync._encrypt_token_payload(
                {
                    "access_token": "original-access",
                    "refresh_token": "original-refresh",
                }
            ),
            scopes_json=list(drive_sync.GOOGLE_DRIVE_SCOPES),
        )
        session.add_all([config, control, connection])
        session.flush()
        candidate = DriveFileCandidate(
            company_id=fixture.company,
            drive_connection_id=connection.id,
            provider="google_drive",
            provider_file_id=f"drive-{uuid4()}",
            provider_version="2026-10-08T00:00:00+00:00",
            name="review.txt",
            mime_type="text/plain",
            size_bytes=len(CONTENT),
            modified_time=datetime(2026, 10, 8, tzinfo=UTC),
            folder_path="/Reviewed",
            suggested_matter_id=fixture.matter,
            status="new",
        )
        session.add(candidate)
        session.commit()
        fixture.connection, fixture.candidate = connection.id, candidate.id
        fixture.config, fixture.control = config.id, control.id
        fixture.user = session.get(CompanyMembership, fixture.actor).user_id
    return fixture


def _storage(monkeypatch, root):
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: root)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(status="clean", signature=None),
    )


def _refresh_transport(monkeypatch, callback):
    class Body(httpx.SyncByteStream):
        def __init__(self, content):
            self.content = content

        def __iter__(self):
            yield self.content

    @contextmanager
    def stream(method, url, *, data, headers, timeout):
        assert method == "POST"
        assert headers == {"Accept-Encoding": "identity"}
        assert 0 < timeout.read <= 1 and 0 < timeout.connect <= 5
        response = callback(url, data=data, timeout=timeout.read)
        bounded = httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=Body(response.content),
            request=httpx.Request("POST", url),
        )
        try:
            yield bounded
        finally:
            bounded.close()

    monkeypatch.setattr(httpx, "stream", stream)


class _Provider:
    configured = True

    def __init__(self, callback=None):
        self.callback, self.calls = callback, []

    def fetch_file(self, **kwargs):
        self.calls.append(dict(kwargs))
        assert kwargs["expected_version"] == "2026-10-08T00:00:00+00:00"
        assert kwargs["expected"].name == "review.txt"
        return self.callback(**kwargs) if self.callback else CONTENT


def _context(session, fixture, actor=None):
    context = _ip_race_context(
        session, company_id=fixture.company, membership_id=actor or fixture.actor
    )
    context.token_issued_at = (datetime.now(UTC) - timedelta(minutes=1)).timestamp()
    return context


def _invoke(session, fixture, *, actor=None, action="import_file", matter_id=None):
    return drive_sync.review_drive_candidate(
        session,
        context=_context(session, fixture, actor),
        candidate_id=fixture.candidate,
        payload=DriveCandidateReviewRequest(action=action, matter_id=matter_id),
    )


def _files(root):
    return sorted(p for p in root.rglob("*") if p.is_file())


def _unpublished(engine, fixture):
    with Session(engine) as session:
        assert list(
            session.scalars(
                select(MatterAttachment.id).where(MatterAttachment.matter_id == fixture.matter)
            )
        ) == [fixture.attachment]
        assert list(
            session.scalars(
                select(DocumentProcessingJob.id).where(
                    DocumentProcessingJob.company_id == fixture.company
                )
            )
        ) == [fixture.job]
        assert not list(
            session.scalars(
                select(MatterActivity.id).where(
                    MatterActivity.matter_id == fixture.matter,
                    MatterActivity.event_type == "drive_file_attachment_added",
                )
            )
        )
        assert not list(
            session.scalars(
                select(AuditEvent.id).where(
                    AuditEvent.target_id == fixture.candidate,
                    AuditEvent.action == "drive.candidate.imported",
                )
            )
        )
        candidate = session.get(DriveFileCandidate, fixture.candidate)
        assert candidate.imported_attachment_id is None


def _published(engine, fixture, root, identity):
    with Session(engine) as session:
        candidate = session.get(DriveFileCandidate, fixture.candidate)
        assert candidate.status == "content_imported"
        assert candidate.imported_attachment_id == identity
        assert candidate.linked_matter_id == fixture.matter
        attachment = session.get(MatterAttachment, identity)
        assert attachment.matter_id == fixture.matter
        assert attachment.uploaded_by_membership_id == fixture.actor
        assert attachment.sha256_hex == sha256(CONTENT).hexdigest()
        assert (root / attachment.storage_key).read_bytes() == CONTENT
        jobs = list(
            session.scalars(
                select(DocumentProcessingJob).where(DocumentProcessingJob.attachment_id == identity)
            )
        )
        assert len(jobs) == 1
        assert jobs[0].action == "initial_index"
        assert jobs[0].target_type == "matter_attachment"
        assert (
            len(
                list(
                    session.scalars(
                        select(MatterActivity.id).where(
                            MatterActivity.matter_id == fixture.matter,
                            MatterActivity.event_type == "drive_file_attachment_added",
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
                            AuditEvent.action == "drive.candidate.imported",
                        )
                    )
                )
            )
            == 1
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("refresh", ["none", "preserve", "rotate"])
@pytest.mark.parametrize("controls", ["existing", "missing"])
def test_drive_transport_releases_all_transactions(
    pg_engine, monkeypatch, tmp_path, autoflush, refresh, controls
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    if controls == "missing":
        with Session(pg_engine) as session:
            session.delete(session.get(DriveSyncControl, fixture.control))
            session.commit()
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
                    ("user_drive_connections", fixture.connection),
                    ("drive_file_candidates", fixture.candidate),
                ):
                    observer.execute(
                        text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE NOWAIT"),
                        {"id": identity},
                    )
            _unpublished(pg_engine, fixture)
            observed.append(boundary)

        def fetch(**kwargs):
            released("fetch")
            if refresh != "none" and len(provider.calls) == 1:
                raise drive_sync.GoogleDriveProviderError("expired", status_code=401)
            assert kwargs["token_payload"]["access_token"] == (
                "original-access" if refresh == "none" else "refreshed-access"
            )
            return CONTENT

        provider = _Provider(fetch)
        drive_sync.set_google_drive_provider_for_tests(provider)

        def exchange(url, *, data, timeout):
            released("refresh")
            assert url == "https://oauth2.googleapis.com/token"
            assert data == {
                "client_id": "tenant-drive-client",
                "client_secret": "tenant-drive-secret",
                "grant_type": "refresh_token",
                "refresh_token": "original-refresh",
            }
            assert 0 < timeout <= 15
            returned = {"access_token": "refreshed-access"}
            if refresh == "rotate":
                returned["refresh_token"] = "rotated-refresh"
            return httpx.Response(200, json=returned)

        _refresh_transport(monkeypatch, exchange)
        monkeypatch.setattr(
            virus_scan,
            "scan_file_for_viruses",
            lambda _: (released("scan"), virus_scan.ScanResult(status="clean", signature=None))[1],
        )

        def store(source, target):
            released("store")
            return place(source, target)

        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        result = _invoke(session, fixture)
        assert not session.in_transaction()
        count = len(provider.calls)
        for _ in range(2):
            assert _invoke(session, fixture).imported_attachment_id == result.imported_attachment_id
            assert not session.in_transaction()
        assert len(provider.calls) == count
    _published(pg_engine, fixture, tmp_path, result.imported_attachment_id)
    assert "scan" in observed and "store" in observed
    with Session(pg_engine) as session:
        connection = session.get(UserDriveConnection, fixture.connection)
        tokens = _decrypt_token_payload(connection.encrypted_token_ref)
        assert tokens["refresh_token"] == (
            "rotated-refresh" if refresh == "rotate" else "original-refresh"
        )
        assert tokens["access_token"] not in connection.encrypted_token_ref
        assert (
            session.scalar(
                select(DriveSyncControl).where(DriveSyncControl.company_id == fixture.company)
            )
            is not None
        )


def _change(session, fixture, change):
    if change in {"dispose", "dispose_reopen"}:
        disposed = _mutate(session, fixture, "dispose")
        if change == "dispose_reopen":
            matters.transition_matter_lifecycle_status(
                session,
                context=_context(session, fixture),
                matter_id=fixture.matter,
                payload=MatterLifecycleStatusRequest(
                    to_status="intake",
                    expected_from_status="disposed",
                    expected_updated_at=disposed.updated_at,
                    reason="Drive race controlled reopen.",
                ),
            )
        return
    if change == "company":
        session.get(Company, fixture.company).is_active = False
    elif change == "quota":
        session.get(Company, fixture.company).storage_quota_bytes = 23
    elif change in {"actor", "cutoff", "capability"}:
        member = session.get(CompanyMembership, fixture.actor)
        if change == "actor":
            member.is_active = False
        elif change == "cutoff":
            member.sessions_valid_after = datetime.now(UTC)
        else:
            member.role = "viewer"
    elif change == "user":
        session.get(User, fixture.user).is_active = False
    elif change == "access":
        session.get(Matter, fixture.matter).restricted_access = True
    elif change in {"disconnect", "token", "scope"}:
        connection = session.get(UserDriveConnection, fixture.connection)
        if change == "disconnect":
            drive_sync.revoke_google_drive_connection(
                session, context=_context(session, fixture), connection_id=fixture.connection
            )
            return
        if change == "scope":
            connection.scopes_json = []
        else:
            connection.encrypted_token_ref = drive_sync._encrypt_token_payload(
                {"access_token": "newer-access", "refresh_token": "newer-refresh"}
            )
    elif change in {"config", "secret"}:
        config = session.get(TenantGoogleWorkspaceConfiguration, fixture.config)
        if change == "config":
            config.drive_enabled = False
        else:
            config.encrypted_client_secret_ref = _encrypt_secret("newer-secret")
    elif change in {"ignore", "name", "version", "unlink"}:
        candidate = session.get(DriveFileCandidate, fixture.candidate)
        if change == "ignore":
            candidate.status = "ignored"
        elif change == "name":
            candidate.name = "newer.txt"
        elif change == "version":
            candidate.provider_version = "newer-version"
        else:
            candidate.drive_connection_id = None
    elif change in {"folder", "mime", "max_size"}:
        control = session.get(DriveSyncControl, fixture.control)
        if change == "folder":
            control.blocked_folders_json = ["reviewed"]
        elif change == "mime":
            control.allowed_mime_types_json = ["application/pdf"]
        else:
            control.max_file_size_bytes = 1
    else:
        raise AssertionError(change)
    session.commit()


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("boundary", ["fetch", "store"])
@pytest.mark.parametrize(
    "change",
    [
        "company",
        "actor",
        "user",
        "cutoff",
        "capability",
        "access",
        "dispose",
        "dispose_reopen",
        "disconnect",
        "token",
        "scope",
        "config",
        "secret",
        "ignore",
        "name",
        "version",
        "unlink",
        "folder",
        "mime",
        "max_size",
        "quota",
    ],
)
def test_drive_fresh_admission_after_io(
    pg_engine, monkeypatch, tmp_path, autoflush, boundary, change
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    entered, resume = Event(), Event()
    place = document_storage._place_local_temp_file

    def pause():
        entered.set()
        assert resume.wait(15)

    def fetch(**kwargs):
        if boundary == "fetch":
            pause()
        return CONTENT

    def store(source, target):
        result = place(source, target)
        if boundary == "store":
            pause()
        return result

    drive_sync.set_google_drive_provider_for_tests(_Provider(fetch))
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
            with pytest.raises(HTTPException) as error:
                future.result(15)
            expected = (
                401
                if change == "cutoff"
                else 403
                if change in {"company", "actor", "user", "capability"}
                else 404
                if change == "access"
                else 413
                if change == "quota"
                else 409
            )
            assert error.value.status_code == expected
        finally:
            resume.set()
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)
    with Session(pg_engine) as session:
        assert session.get(DriveFileCandidate, fixture.candidate).status == (
            "ignored" if change == "ignore" else "new"
        )
        assert session.get(Matter, fixture.matter).status == (
            "disposed"
            if change == "dispose"
            else "intake"
            if change == "dispose_reopen"
            else "active"
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("work", ["new", "dirty", "deleted", "flushed", "core", "nested"])
def test_drive_preserves_caller_writes(pg_engine, monkeypatch, tmp_path, autoflush, work):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    provider = _Provider()
    drive_sync.set_google_drive_provider_for_tests(provider)
    with Session(pg_engine, autoflush=autoflush) as session:
        context = _context(session, fixture)
        candidate = session.get(DriveFileCandidate, fixture.candidate)
        if work == "new":
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
        elif work == "deleted":
            session.delete(candidate)
        elif work in {"dirty", "flushed"}:
            candidate.name = "caller-name.txt"
            if work == "flushed":
                session.flush()
        elif work == "core":
            session.execute(
                text("UPDATE drive_file_candidates SET name='caller-name.txt' WHERE id=:id"),
                {"id": fixture.candidate},
            )
        else:
            session.begin_nested()
        transaction = session.get_transaction()
        with pytest.raises(HTTPException, match="read-only session") as error:
            drive_sync.review_drive_candidate(
                session,
                context=context,
                candidate_id=fixture.candidate,
                payload=DriveCandidateReviewRequest(action="import_file"),
            )
        assert error.value.status_code == 409
        assert session.get_transaction() is transaction and transaction.is_active
        assert not provider.calls
        if work == "nested":
            assert session.in_nested_transaction()
        else:
            session.commit()
    with Session(pg_engine) as session:
        if work == "deleted":
            assert session.get(DriveFileCandidate, fixture.candidate) is None
        elif work in {"dirty", "flushed", "core"}:
            assert session.get(DriveFileCandidate, fixture.candidate).name == "caller-name.txt"
        elif work == "new":
            assert (
                session.scalar(
                    select(Communication.id).where(
                        Communication.company_id == fixture.company,
                        Communication.body == "Caller retained write",
                    )
                )
                is not None
            )
    assert not _files(tmp_path)


@pytest.mark.parametrize("autoflush", [False, True])
def test_drive_concurrent_duplicate_and_quota_one_winner(
    pg_engine, monkeypatch, tmp_path, autoflush
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    barrier = Barrier(2)
    place = document_storage._place_local_temp_file

    def store(source, target):
        result = place(source, target)
        barrier.wait(15)
        return result

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    drive_sync.set_google_drive_provider_for_tests(_Provider())

    def review():
        with Session(pg_engine, autoflush=autoflush) as session:
            return _invoke(session, fixture).imported_attachment_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(review), pool.submit(review)
        a, b = first.result(20), second.result(20)
    assert a == b
    assert len(_files(tmp_path)) == 1
    _published(pg_engine, fixture, tmp_path, a)


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("when", ["before", "after"])
def test_drive_unknown_commit_retains_bytes(pg_engine, monkeypatch, tmp_path, autoflush, when):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    drive_sync.set_google_drive_provider_for_tests(_Provider())
    with Session(pg_engine, autoflush=autoflush) as session:
        commit = session.commit

        def unknown():
            if when == "after":
                commit()
            raise RuntimeError("Commit acknowledgement unknown")

        monkeypatch.setattr(session, "commit", unknown)
        with pytest.raises(RuntimeError, match="acknowledgement unknown"):
            _invoke(session, fixture)
    assert len(_files(tmp_path)) == 1
    if when == "before":
        _unpublished(pg_engine, fixture)
    else:
        with Session(pg_engine) as session:
            result = _invoke(session, fixture)
        _published(pg_engine, fixture, tmp_path, result.imported_attachment_id)


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("failure", ["job", "audit"])
def test_drive_admission_failure_atomic_children(
    pg_engine, monkeypatch, tmp_path, autoflush, failure
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    drive_sync.set_google_drive_provider_for_tests(_Provider())
    if failure == "job":
        original = document_jobs.enqueue_processing_job

        def broken(session, **kwargs):
            original(session, **kwargs)
            session.flush()
            raise RuntimeError("Injected job admission failure")

        monkeypatch.setattr(document_jobs, "enqueue_processing_job", broken)
    else:
        original = drive_sync.record_from_context

        def broken(session, context, **kwargs):
            result = original(session, context, **kwargs)
            if kwargs["action"] == "drive.candidate.imported":
                session.flush()
                raise RuntimeError("Injected audit admission failure")
            return result

        monkeypatch.setattr(drive_sync, "record_from_context", broken)
    with Session(pg_engine, autoflush=autoflush) as session:
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture)
        assert error.value.status_code == 502
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)


@pytest.mark.parametrize(
    "case",
    [
        "timeout",
        "429",
        "503",
        "invalid_grant",
        "invalid_client",
        "refresh_timeout",
        "refresh_429",
        "refresh_503",
        "invalid_json",
        "missing_access",
        "whitespace",
        "bad_refresh",
        "token_type",
        "scope",
        "oversized",
        "nan",
        "retry_401",
        "retry_503",
    ],
)
def test_drive_refresh_failures_bounded_and_retryable(pg_engine, monkeypatch, tmp_path, case):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    refresh_calls = []

    def fetch(**kwargs):
        if case == "timeout":
            raise drive_sync.GoogleDriveProviderError("timeout secret")
        if case in {"429", "503"}:
            raise drive_sync.GoogleDriveProviderError("provider secret", status_code=int(case))
        if len(provider.calls) == 1:
            raise drive_sync.GoogleDriveProviderError("expired secret", status_code=401)
        raise drive_sync.GoogleDriveProviderError(
            "retry secret", status_code=401 if case == "retry_401" else 503
        )

    provider = _Provider(fetch)
    drive_sync.set_google_drive_provider_for_tests(provider)

    def exchange(url, **kwargs):
        refresh_calls.append(kwargs)
        if case == "refresh_timeout":
            raise httpx.ReadTimeout("secret timeout")
        if case in {"invalid_grant", "invalid_client"}:
            return httpx.Response(400, json={"error": case})
        if case in {"refresh_429", "refresh_503"}:
            return httpx.Response(int(case.split("_")[1]), content=b"secret html")
        if case == "invalid_json":
            return httpx.Response(200, content=b"invalid secret json")
        returned = {"access_token": "refreshed-access"}
        if case == "missing_access":
            returned = {}
        elif case == "whitespace":
            returned["access_token"] = "invalid access"
        elif case == "bad_refresh":
            returned["refresh_token"] = 123
        elif case == "token_type":
            returned["token_type"] = "Basic"
        elif case == "scope":
            returned["scope"] = "email"
        elif case == "oversized":
            returned["extra"] = "x" * 65536
        elif case == "nan":
            return httpx.Response(
                200, content=b'{"access_token":"refreshed-access","expires_in":NaN}'
            )
        return httpx.Response(200, json=returned)

    _refresh_transport(monkeypatch, exchange)
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture)
        expected = (
            409
            if case in {"invalid_grant", "retry_401"}
            else 502
            if case in {"timeout", "429", "503", "retry_503"}
            else 503
        )
        assert error.value.status_code == expected
        assert "secret" not in error.value.detail
    assert len(provider.calls) == (2 if case in {"retry_401", "retry_503"} else 1)
    assert len(refresh_calls) == (0 if case in {"timeout", "429", "503"} else 1)
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)
    with Session(pg_engine) as session:
        connection = session.get(UserDriveConnection, fixture.connection)
        assert connection.status == (
            "error" if case in {"invalid_grant", "retry_401"} else "connected"
        )
        tokens = _decrypt_token_payload(connection.encrypted_token_ref)
        assert tokens["refresh_token"] == "original-refresh"
        assert tokens["access_token"] == (
            "refreshed-access" if case in {"retry_401", "retry_503"} else "original-access"
        )
        assert session.get(DriveFileCandidate, fixture.candidate).status == "new"


@pytest.mark.parametrize("boundary", ["refresh", "scan", "failed_retry"])
def test_drive_disconnect_wins_over_rotated_credentials(pg_engine, monkeypatch, tmp_path, boundary):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)

    def disconnect():
        with Session(pg_engine) as writer:
            _change(writer, fixture, "disconnect")

    def fetch(**kwargs):
        if len(provider.calls) == 1:
            raise drive_sync.GoogleDriveProviderError("expired", status_code=401)
        if boundary == "failed_retry":
            disconnect()
            raise drive_sync.GoogleDriveProviderError("temporary", status_code=503)
        return CONTENT

    provider = _Provider(fetch)
    drive_sync.set_google_drive_provider_for_tests(provider)

    def exchange(*args, **kwargs):
        if boundary == "refresh":
            disconnect()
        return httpx.Response(
            200, json={"access_token": "rotated-access", "refresh_token": "rotated-refresh"}
        )

    _refresh_transport(monkeypatch, exchange)
    if boundary == "scan":
        monkeypatch.setattr(
            virus_scan,
            "scan_file_for_viruses",
            lambda _: (disconnect(), virus_scan.ScanResult(status="clean", signature=None))[1],
        )
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture)
        assert error.value.status_code == 409
    with Session(pg_engine) as session:
        connection = session.get(UserDriveConnection, fixture.connection)
        assert connection.status == "revoked"
        assert connection.encrypted_token_ref is None
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)


@pytest.mark.parametrize("action", ["retry", "link_metadata", "ignore"])
def test_drive_import_cannot_be_reset_by_other_review_actions(
    pg_engine, monkeypatch, tmp_path, action
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    provider = _Provider()
    drive_sync.set_google_drive_provider_for_tests(provider)
    with Session(pg_engine) as session:
        identity = _invoke(session, fixture).imported_attachment_id
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture, action=action)
        assert error.value.status_code == 409
    _published(pg_engine, fixture, tmp_path, identity)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("autoflush", [False, True])
def test_drive_waiting_admission_reloads_locked_authority(
    pg_engine, monkeypatch, tmp_path, request, autoflush
):
    harness = request.getfixturevalue("race")
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path / "objects")
    drive_sync.set_google_drive_provider_for_tests(_Provider())
    with harness.session("revoker") as revoker:
        revoker.execute(
            text("SELECT id FROM companies WHERE id=:id FOR NO KEY UPDATE"), {"id": fixture.company}
        )
        revoker.get(CompanyMembership, fixture.actor).is_active = False
        revoker.flush()

        def review():
            with harness.session("review") as session:
                session.autoflush = autoflush
                return _invoke(session, fixture)

        future = harness.submit("review", review)
        harness.blocked("review", "revoker", "FROM companies")
        revoker.commit()
    with pytest.raises(HTTPException) as error:
        future.result(15)
    assert error.value.status_code == 403
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path / "objects")


@pytest.mark.parametrize("autoflush", [False, True])
def test_drive_distinct_candidates_serialize_quota(pg_engine, monkeypatch, tmp_path, autoflush):
    fixture = _seed(pg_engine)
    sibling = SimpleNamespace(**vars(fixture))
    _storage(monkeypatch, tmp_path)
    with Session(pg_engine) as session:
        original = session.get(DriveFileCandidate, fixture.candidate)
        other = DriveFileCandidate(
            company_id=fixture.company,
            drive_connection_id=fixture.connection,
            provider="google_drive",
            provider_file_id=f"drive-{uuid4()}",
            provider_version=original.provider_version,
            modified_time=original.modified_time,
            name=original.name,
            mime_type=original.mime_type,
            size_bytes=original.size_bytes,
            suggested_matter_id=fixture.matter,
            status="new",
        )
        session.add(other)
        session.get(Company, fixture.company).storage_quota_bytes = 23 + len(CONTENT)
        session.commit()
        sibling.candidate = other.id
    barrier = Barrier(2)
    place = document_storage._place_local_temp_file

    def store(source, target):
        result = place(source, target)
        barrier.wait(15)
        return result

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    drive_sync.set_google_drive_provider_for_tests(_Provider())

    def review(target):
        with Session(pg_engine, autoflush=autoflush) as session:
            try:
                return target, _invoke(session, target).imported_attachment_id
            except HTTPException as exc:
                assert exc.status_code == 413
                return target, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(review, target) for target in (fixture, sibling)]
        results = [future.result(20) for future in futures]
    winners = [(target, identity) for target, identity in results if identity is not None]
    assert len(winners) == 1
    _published(pg_engine, winners[0][0], tmp_path, winners[0][1])
    assert len(_files(tmp_path)) == 1
    with Session(pg_engine) as session:
        attachments = list(
            session.scalars(
                select(MatterAttachment).where(MatterAttachment.matter_id == fixture.matter)
            )
        )
        assert len(attachments) == 2
        assert sum(row.size_bytes for row in attachments) == 23 + len(CONTENT)
        loser = next(target for target, identity in results if identity is None)
        assert session.get(DriveFileCandidate, loser.candidate).status == "new"


@pytest.mark.parametrize("change", ["actor", "user"])
def test_drive_shared_review_rechecks_connection_owner(pg_engine, monkeypatch, tmp_path, change):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)

    def fetch(**kwargs):
        with Session(pg_engine) as writer:
            _change(writer, fixture, change)
        return CONTENT

    drive_sync.set_google_drive_provider_for_tests(_Provider(fetch))
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture, actor=fixture.owner)
        assert error.value.status_code == 403
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)


def test_drive_cleanup_failure_preserves_rejection(pg_engine, monkeypatch, tmp_path, caplog):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    drive_sync.set_google_drive_provider_for_tests(_Provider())
    place = document_storage._place_local_temp_file

    def store(source, target):
        result = place(source, target)
        with Session(pg_engine) as writer:
            _change(writer, fixture, "disconnect")
        return result

    def cleanup(key):
        raise OSError("Synthetic cleanup failure")

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    monkeypatch.setattr(document_storage, "delete_stored_document", cleanup)
    monkeypatch.setattr(drive_sync.logger, "disabled", False)
    caplog.set_level("ERROR", logger=drive_sync.__name__)
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture)
        assert error.value.status_code == 409
    _unpublished(pg_engine, fixture)
    logs = [row for row in caplog.records if row.name == drive_sync.__name__]
    assert len(logs) == 1
    assert logs[0].msg == "drive_import.staged_cleanup_failed"
    assert logs[0].args == () and logs[0].exc_info is not None
    assert len(_files(tmp_path)) == 1
    assert _files(tmp_path)[0].read_bytes() == CONTENT


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("mode", ["rollback_only", "create_savepoint", "control_fully"])
@pytest.mark.parametrize("write", [False, True])
def test_drive_rejects_external_connection_transaction(
    pg_engine, monkeypatch, tmp_path, autoflush, mode, write
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    provider = _Provider()
    drive_sync.set_google_drive_provider_for_tests(provider)
    with Session(pg_engine) as observer:
        context = _context(observer, fixture)
    with pg_engine.connect() as connection:
        outer = connection.begin()
        if write:
            connection.execute(
                text("UPDATE drive_file_candidates SET name='external.txt' WHERE id=:id"),
                {"id": fixture.candidate},
            )
        with Session(bind=connection, autoflush=autoflush, join_transaction_mode=mode) as session:
            assert not session.in_transaction()
            with pytest.raises(HTTPException, match="read-only session") as error:
                drive_sync.review_drive_candidate(
                    session,
                    context=context,
                    candidate_id=fixture.candidate,
                    payload=DriveCandidateReviewRequest(action="import_file"),
                )
            assert error.value.status_code == 409
            assert connection.get_transaction() is outer and outer.is_active
            assert not session.in_transaction()
            outer.commit()
    with Session(pg_engine) as session:
        assert session.get(DriveFileCandidate, fixture.candidate).name == (
            "external.txt" if write else "review.txt"
        )
    assert not provider.calls and not _files(tmp_path)


@pytest.mark.parametrize("reported", [1, None])
def test_drive_actual_download_size_not_metadata_enforces_control(
    pg_engine, monkeypatch, tmp_path, reported
):
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    with Session(pg_engine) as session:
        session.get(DriveFileCandidate, fixture.candidate).size_bytes = reported
        session.get(DriveSyncControl, fixture.control).max_file_size_bytes = len(CONTENT) - 1
        session.commit()
    provider = _Provider()
    drive_sync.set_google_drive_provider_for_tests(provider)
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture)
        assert error.value.status_code == 413
    _unpublished(pg_engine, fixture)
    assert len(provider.calls) == 1 and not _files(tmp_path)


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("action", ["ignore", "retry", "link_metadata"])
@pytest.mark.parametrize("first", ["import", "metadata"])
def test_drive_metadata_actions_cannot_overwrite_concurrent_import(
    pg_engine,
    monkeypatch,
    tmp_path,
    request,
    autoflush,
    action,
    first,
):
    harness = request.getfixturevalue("race")
    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path / "objects")
    if action == "retry":
        with Session(pg_engine) as session:
            session.get(DriveFileCandidate, fixture.candidate).status = "failed"
            session.commit()
    downloaded, staged, resume_store = Event(), Event(), Event()
    place = document_storage._place_local_temp_file

    def fetch(**kwargs):
        downloaded.set()
        return CONTENT

    def store(source, target):
        result = place(source, target)
        staged.set()
        if first == "metadata":
            assert resume_store.wait(15)
        return result

    drive_sync.set_google_drive_provider_for_tests(_Provider(fetch))
    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    harness.pause_role = first
    harness.predicate = lambda sql: (
        "FROM drive_file_candidates" in sql
        and "FOR UPDATE" in sql
        and (first == "metadata" or downloaded.is_set())
    )

    def operation(role):
        with harness.session(role) as session:
            session.autoflush = autoflush
            # Retain the exact stale ORM row the former metadata path reused.
            initial = session.get(DriveFileCandidate, fixture.candidate)
            assert initial.status in {"new", "failed"}
            return _invoke(session, fixture, action="import_file" if role == "import" else action)

    imported = harness.submit("import", lambda: operation("import"))
    try:
        if first == "metadata":
            assert staged.wait(10)
        else:
            assert harness.paused.wait(10)
        metadata = harness.submit("metadata", lambda: operation("metadata"))
        if first == "metadata":
            assert harness.paused.wait(10)
            resume_store.set()
            harness.blocked("import", "metadata", "FROM companies")
        else:
            harness.blocked("metadata", "import", "FROM companies")
        harness.release.set()
        if first == "import":
            identity = imported.result(15).imported_attachment_id
            with pytest.raises(HTTPException) as error:
                metadata.result(15)
            assert error.value.status_code == 409
        else:
            result = metadata.result(15)
            assert (
                result.candidate.status
                == {"ignore": "ignored", "retry": "new", "link_metadata": "linked_metadata"}[action]
            )
            with pytest.raises(HTTPException) as error:
                imported.result(15)
            assert error.value.status_code == 409
            _unpublished(pg_engine, fixture)
            assert not _files(tmp_path / "objects")
            with Session(pg_engine) as session:
                identity = _invoke(session, fixture).imported_attachment_id
        _published(pg_engine, fixture, tmp_path / "objects", identity)
        with Session(pg_engine) as session:
            with pytest.raises(HTTPException) as error:
                _invoke(session, fixture, action=action)
            assert error.value.status_code == 409
        _published(pg_engine, fixture, tmp_path / "objects", identity)
        assert len(_files(tmp_path / "objects")) == 1
    finally:
        resume_store.set()
        harness.release.set()


@pytest.mark.parametrize("action", ["ignore", "retry"])
def test_drive_metadata_review_does_not_require_live_provider(pg_engine, monkeypatch, action):
    fixture = _seed(pg_engine)
    with Session(pg_engine) as session:
        _change(session, fixture, "disconnect")
    with Session(pg_engine) as session:
        _mutate(session, fixture, "dispose")
    monkeypatch.setattr(
        drive_sync,
        "_google_drive_runtime_config",
        lambda *a, **kw: pytest.fail("Metadata review must not inspect OAuth readiness"),
    )
    with Session(pg_engine) as session:
        result = _invoke(session, fixture, action=action)
        assert result.candidate.status == ("ignored" if action == "ignore" else "new")
    _unpublished(pg_engine, fixture)


@pytest.mark.parametrize("action", ["ignore", "retry", "link_metadata"])
def test_drive_metadata_review_preserves_dirty_caller(pg_engine, action):
    fixture = _seed(pg_engine)
    with Session(pg_engine) as session:
        context = _context(session, fixture)
        session.get(DriveFileCandidate, fixture.candidate).name = "caller-metadata.txt"
        transaction = session.get_transaction()
        with pytest.raises(HTTPException, match="read-only session"):
            drive_sync.review_drive_candidate(
                session,
                context=context,
                candidate_id=fixture.candidate,
                payload=DriveCandidateReviewRequest(action=action),
            )
        assert session.get_transaction() is transaction and transaction.is_active
        session.commit()
    with Session(pg_engine) as session:
        assert session.get(DriveFileCandidate, fixture.candidate).name == "caller-metadata.txt"


@pytest.mark.parametrize("action", ["ignore", "retry", "link_metadata"])
def test_drive_metadata_review_reauthorizes_stale_context(pg_engine, action):
    fixture = _seed(pg_engine)
    with Session(pg_engine) as session:
        context = _context(session, fixture)
        with Session(pg_engine) as writer:
            _change(writer, fixture, "actor")
        with pytest.raises(HTTPException) as error:
            drive_sync.review_drive_candidate(
                session,
                context=context,
                candidate_id=fixture.candidate,
                payload=DriveCandidateReviewRequest(action=action),
            )
        assert error.value.status_code == 403
    _unpublished(pg_engine, fixture)


@pytest.mark.parametrize("global_limit", ["application", "file_security"])
def test_drive_huge_tenant_cap_cannot_exceed_global_stream_limit(
    pg_engine, monkeypatch, tmp_path, global_limit
):
    import json

    from caseops_api.core.settings import get_settings
    from caseops_api.services import file_security

    fixture = _seed(pg_engine)
    _storage(monkeypatch, tmp_path)
    if global_limit == "application":
        monkeypatch.setattr(get_settings(), "max_attachment_size_bytes", 16)
    else:
        monkeypatch.setattr(file_security, "DEFAULT_MAX_BYTES", 16)
    with Session(pg_engine) as session:
        candidate = session.get(DriveFileCandidate, fixture.candidate)
        candidate.size_bytes = 10
        file_id = candidate.provider_file_id
        session.get(DriveSyncControl, fixture.control).max_file_size_bytes = 2_000_000_000
        session.commit()
    calls, pieces = [], []

    class Body(httpx.SyncByteStream):
        def __init__(self, chunks):
            self.chunks = chunks

        def __iter__(self):
            for chunk in self.chunks:
                pieces.append(len(chunk))
                yield chunk

    with Session(pg_engine) as session:

        @contextmanager
        def stream(method, url, *, params, **kwargs):
            assert not session.in_transaction()
            calls.append(params)
            if params.get("alt") == "media":
                chunks = [CONTENT, b"must not be consumed"]
            else:
                chunks = [
                    json.dumps(
                        {
                            "id": file_id,
                            "name": "review.txt",
                            "mimeType": "text/plain",
                            "size": "10",
                            "modifiedTime": "2026-10-08T00:00:00+00:00",
                            "version": "17",
                            "trashed": False,
                        }
                    ).encode()
                ]
            response = httpx.Response(200, request=httpx.Request(method, url), stream=Body(chunks))
            try:
                yield response
            finally:
                response.close()

        monkeypatch.setattr(httpx, "stream", stream)
        monkeypatch.setattr(
            virus_scan,
            "scan_file_for_viruses",
            lambda *a, **kw: pytest.fail("Over-limit content reached scanning"),
        )
        monkeypatch.setattr(
            document_storage,
            "_place_local_temp_file",
            lambda *a, **kw: pytest.fail("Over-limit content reached storage"),
        )
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture)
        assert error.value.status_code == 413
    assert len(calls) == 2 and pieces[-1] == len(CONTENT)
    _unpublished(pg_engine, fixture)
    assert not _files(tmp_path)


def test_drive_nonpositive_global_limit_fails_before_transport(pg_engine, monkeypatch):
    from caseops_api.core.settings import get_settings

    fixture = _seed(pg_engine)
    monkeypatch.setattr(get_settings(), "max_attachment_size_bytes", 0)
    provider = _Provider()
    drive_sync.set_google_drive_provider_for_tests(provider)
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture)
        assert error.value.status_code == 503
    assert not provider.calls
    _unpublished(pg_engine, fixture)
