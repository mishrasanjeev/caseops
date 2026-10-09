"""Transaction-free inbound/OC storage with atomic, freshly authorized publication."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from threading import Barrier, Event, local
from uuid import uuid4

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
    Matter,
    MatterAttachment,
    MatterPortalGrant,
    PortalUser,
    User,
)
from caseops_api.schemas.communications import CommunicationCreateRequest, InboundEmailImportRequest
from caseops_api.schemas.matters import MatterLifecycleStatusRequest
from caseops_api.services import (
    communications,
    document_storage,
    matters,
    portal_outside_counsel,
    virus_scan,
)
from tests.test_matter_writer_admission_postgres import _fixture, _mutate, race  # noqa: F401
from tests.test_postgres_validation import _ensure_migrations, _ip_race_context  # noqa: F401

pytestmark = pytest.mark.postgres


def _seed(engine):
    fixture = _fixture(engine)
    with Session(engine) as session:
        user = PortalUser(
            company_id=fixture.company,
            email=f"{uuid4()}@example.test",
            full_name="Outside Counsel",
            role="outside_counsel",
            is_active=True,
            invited_by_membership_id=fixture.actor,
        )
        session.add(user)
        session.flush()
        grant = MatterPortalGrant(
            company_id=fixture.company,
            matter_id=fixture.matter,
            portal_user_id=user.id,
            role="outside_counsel",
            scope_json={"can_upload": True},
            granted_by_membership_id=fixture.actor,
            granted_by_label_snapshot="Audit owner",
            granted_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add(grant)
        session.commit()
        fixture.portal, fixture.grant = user.id, grant.id
        fixture.user = session.get(CompanyMembership, fixture.actor).user_id
    return fixture


def _payload(message_id=None):
    return InboundEmailImportRequest(
        provider="manual",
        provider_message_id=message_id or str(uuid4()),
        sender_email="sender@example.com",
        subject="Atomic imported email",
        body_preview="Retained preview",
        body_text="Retained full email body",
        attachments=[
            dict(
                filename="evidence.txt",
                content_type="text/plain",
                content_base64=base64.b64encode(b"Retained attachment").decode(),
            )
        ],
    )


def _invoke(session, fixture, surface, payload=None):
    if surface == "inbound":
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.actor)
        context.token_issued_at = (datetime.now(UTC) - timedelta(minutes=1)).timestamp()
        return communications.import_inbound_email(
            session,
            context=context,
            matter_id=fixture.matter,
            payload=payload or _payload(),
        )
    return portal_outside_counsel.upload_oc_work_product(
        session,
        portal_user=session.get(PortalUser, fixture.portal),
        matter_id=fixture.matter,
        filename="work-product.txt",
        content_type="text/plain",
        stream=BytesIO(b"Work product"),
    )


def _local_storage(monkeypatch, root):
    monkeypatch.setenv("CASEOPS_CLAMAV_REQUIRED", "true")
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: root)


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("surface", ["inbound", "oc"])
def test_upload_transport_has_no_transaction_or_partial_rows(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    surface,
):
    fixture = _seed(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    place = document_storage._place_local_temp_file
    observed = []
    with Session(pg_engine, autoflush=autoflush) as session:

        def assert_released():
            assert not session.in_transaction()
            with Session(pg_engine) as observer:
                for table, identity in (
                    ("companies", fixture.company),
                    ("matters", fixture.matter),
                    ("company_memberships", fixture.actor),
                    ("portal_users", fixture.portal),
                    ("matter_portal_grants", fixture.grant),
                ):
                    observer.execute(
                        text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE NOWAIT"),
                        {"id": identity},
                    )
                assert (
                    observer.scalar(
                        select(Communication.id).where(Communication.matter_id == fixture.matter)
                    )
                    is None
                )
                assert list(
                    observer.scalars(
                        select(MatterAttachment.id).where(
                            MatterAttachment.matter_id == fixture.matter
                        )
                    )
                ) == [fixture.attachment]

        def scan(path):
            assert_released()
            observed.append("scan")
            return virus_scan.ScanResult(status="clean", signature=None)

        def store(temp, target):
            assert_released()
            observed.append("store")
            return place(temp, target)

        monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        result = _invoke(session, fixture, surface)
        if surface == "inbound":
            assert len(result.attachment_ids) == len(result.processing_job_ids) == 2
            assert result.body_attachment_id in result.attachment_ids
            assert not result.duplicate
        else:
            assert result.submitted_by_portal_user_id == fixture.portal
    assert observed == ["scan", "store"] * (2 if surface == "inbound" else 1)
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == (
        2 if surface == "inbound" else 1
    )


def _change_authority(session, fixture, change):
    if change in {"dispose", "dispose_reopen"}:
        disposed = _mutate(session, fixture, "dispose")
        if change == "dispose_reopen":
            matters.transition_matter_lifecycle_status(
                session,
                context=_ip_race_context(
                    session, company_id=fixture.company, membership_id=fixture.actor
                ),
                matter_id=fixture.matter,
                payload=MatterLifecycleStatusRequest(
                    to_status="intake",
                    expected_from_status="disposed",
                    expected_updated_at=disposed.updated_at,
                    reason="Controlled reopen during upload.",
                ),
            )
        return
    if change in {"company_disabled", "quota"}:
        row = session.get(Company, fixture.company)
        if change == "quota":
            row.storage_quota_bytes = 23
        else:
            row.is_active = False
    elif change in {"membership_disabled", "capability", "user_disabled", "session_cutoff"}:
        row = session.get(CompanyMembership, fixture.actor)
        if change == "membership_disabled":
            row.is_active = False
        elif change == "capability":
            row.role = "viewer"
        elif change == "user_disabled":
            session.get(User, row.user_id).is_active = False
        else:
            row.sessions_valid_after = datetime.now(UTC)
    elif change in {"portal_disabled", "portal_cutoff"}:
        row = session.get(PortalUser, fixture.portal)
        if change == "portal_disabled":
            row.is_active = False
        else:
            row.sessions_valid_after = datetime.now(UTC)
    else:
        row = session.get(MatterPortalGrant, fixture.grant)
        if change == "grant_revoked":
            row.revoked_at = datetime.now(UTC)
        elif change == "grant_permission":
            row.scope_json = {"can_upload": False}
        elif change == "grant_expired":
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            raise AssertionError(change)
    session.commit()


def _assert_unpublished(engine, fixture):
    with Session(engine) as verify:
        assert (
            list(
                verify.scalars(
                    select(Communication.id).where(Communication.matter_id == fixture.matter)
                )
            )
            == []
        )
        assert list(
            verify.scalars(
                select(MatterAttachment.id).where(MatterAttachment.matter_id == fixture.matter)
            )
        ) == [fixture.attachment]
        assert list(
            verify.scalars(
                select(DocumentProcessingJob.id).where(
                    DocumentProcessingJob.company_id == fixture.company
                )
            )
        ) == [fixture.job]
        assert (
            list(
                verify.scalars(
                    select(AuditEvent.id).where(
                        AuditEvent.company_id == fixture.company,
                        AuditEvent.action.in_(
                            ["inbound_email.imported", "portal_oc.upload_work_product"]
                        ),
                    )
                )
            )
            == []
        )


@pytest.mark.parametrize("autoflush", [False, True])
def test_preview_only_import_does_not_consume_upload_quota(
    pg_engine,
    monkeypatch,
    autoflush,
):
    fixture = _seed(pg_engine)
    with Session(pg_engine) as seed:
        seed.get(Company, fixture.company).storage_quota_bytes = 1
        seed.commit()
    payload = _payload().model_copy(update={"body_text": None, "attachments": []})

    def unexpected_transport(*args, **kwargs):
        raise AssertionError("Preview-only import must not scan/store bytes")

    monkeypatch.setattr(communications, "persist_matter_attachment", unexpected_transport)
    with Session(pg_engine, autoflush=autoflush) as session:
        result = _invoke(session, fixture, "inbound", payload)
        assert not result.duplicate
        assert result.attachment_ids == result.processing_job_ids == []
        assert result.body_attachment_id is None
        assert result.communication.body == payload.body_preview
        assert _invoke(session, fixture, "inbound", payload).duplicate


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("surface", ["inbound", "oc"])
@pytest.mark.parametrize("outer_work", ["new", "dirty", "deleted", "flushed", "core_dml"])
def test_upload_rejects_caller_owned_writes_without_discarding_them(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    surface,
    outer_work,
):
    fixture = _seed(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="clean", signature=None),
    )

    def caller_row():
        return Communication(
            company_id=fixture.company,
            matter_id=fixture.matter,
            direction="inbound",
            channel="note",
            body="Original caller row",
            status="logged",
            created_by_membership_id=fixture.actor,
        )

    with Session(pg_engine) as seed:
        existing = caller_row()
        seed.add(existing)
        seed.commit()
        existing_id = existing.id
    with Session(pg_engine, autoflush=autoflush) as session:
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.actor)
        portal_user = session.get(PortalUser, fixture.portal)
        row = session.get(Communication, existing_id)
        if outer_work == "new":
            row = caller_row()
            session.add(row)
        elif outer_work == "deleted":
            session.delete(row)
        elif outer_work == "core_dml":
            session.connection().execute(
                text("UPDATE communications SET body='Preserved caller change' WHERE id=:id"),
                {"id": existing_id},
            )
        else:
            row.body = "Preserved caller change"
            if outer_work == "flushed":
                session.flush()
        transaction = session.get_transaction()
        with pytest.raises(HTTPException) as error:
            if surface == "inbound":
                communications.import_inbound_email(
                    session, context=context, matter_id=fixture.matter, payload=_payload()
                )
            else:
                portal_outside_counsel.upload_oc_work_product(
                    session,
                    portal_user=portal_user,
                    matter_id=fixture.matter,
                    filename="outer.txt",
                    content_type="text/plain",
                    stream=BytesIO(b"Outer upload"),
                )
        assert error.value.status_code == 409
        assert "read-only" in str(error.value.detail)
        assert session.get_transaction() is transaction
        if outer_work == "new":
            assert row in session.new
        elif outer_work == "dirty":
            assert row in session.dirty and row.body == "Preserved caller change"
        elif outer_work == "deleted":
            assert row in session.deleted
        session.commit()
        row_id = row.id
    with Session(pg_engine) as verify:
        if outer_work == "deleted":
            assert verify.get(Communication, existing_id) is None
        else:
            retained = verify.get(Communication, row_id)
            assert retained.body == (
                "Original caller row" if outer_work == "new" else "Preserved caller change"
            )
        assert list(
            verify.scalars(
                select(MatterAttachment.id).where(MatterAttachment.matter_id == fixture.matter)
            )
        ) == [fixture.attachment]
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


_CUTOFFS = (
    [
        (surface, change)
        for surface in ("inbound", "oc")
        for change in (
            "dispose",
            "dispose_reopen",
            "company_disabled",
            "quota",
        )
    ]
    + [
        ("inbound", change)
        for change in (
            "membership_disabled",
            "capability",
            "user_disabled",
            "session_cutoff",
        )
    ]
    + [
        ("oc", change)
        for change in (
            "portal_disabled",
            "portal_cutoff",
            "grant_revoked",
            "grant_permission",
            "grant_expired",
        )
    ]
)


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("surface,change", _CUTOFFS)
def test_upload_rechecks_authority_after_real_storage(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    surface,
    change,
):
    fixture = _seed(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    place, delete = document_storage._place_local_temp_file, document_storage.delete_stored_document
    observed, deleted = [], []
    module = communications if surface == "inbound" else portal_outside_counsel
    with Session(pg_engine, autoflush=autoflush) as session:

        def store(temp, target):
            assert not session.in_transaction()
            result = place(temp, target)
            observed.append(target)
            if len(observed) == (2 if surface == "inbound" else 1):
                with Session(pg_engine) as contender:
                    contender.execute(text("SET LOCAL lock_timeout = '2s'"))
                    _change_authority(contender, fixture, change)
            return result

        def cleanup(key):
            assert not session.in_transaction()
            _assert_unpublished(pg_engine, fixture)
            deleted.append(key)
            delete(key)

        monkeypatch.setattr(
            virus_scan,
            "scan_file_for_viruses",
            lambda path: virus_scan.ScanResult(status="clean", signature=None),
        )
        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        monkeypatch.setattr(module, "delete_stored_document", cleanup)
        with pytest.raises(HTTPException) as error:
            _invoke(session, fixture, surface)
        expected = (
            413 if change == "quota" else 409 if change in {"dispose", "dispose_reopen"} else None
        )
        assert (
            error.value.status_code == expected
            if expected
            else error.value.status_code in {401, 403, 404}
        )
    _assert_unpublished(pg_engine, fixture)
    assert len(deleted) == len(observed) == (2 if surface == "inbound" else 1)
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("failure", ["second_scan", "metadata"])
def test_inbound_import_is_atomic_and_retryable(
    pg_engine, monkeypatch, tmp_path, autoflush, failure
):
    fixture = _seed(pg_engine)
    payload = _payload()
    _local_storage(monkeypatch, tmp_path)
    count = 0
    original_audit = communications.record_from_context
    with Session(pg_engine, autoflush=autoflush) as session:

        def scan(path):
            nonlocal count
            assert not session.in_transaction()
            count += 1
            if failure == "second_scan" and count == 2:
                raise RuntimeError("injected scanner outage")
            return virus_scan.ScanResult(status="clean", signature=None)

        def audit(*args, **kwargs):
            _assert_unpublished(pg_engine, fixture)
            raise RuntimeError("injected atomic metadata failure")

        monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
        if failure == "metadata":
            monkeypatch.setattr(communications, "record_from_context", audit)
        with pytest.raises((RuntimeError, HTTPException)):
            _invoke(session, fixture, "inbound", payload)
        _assert_unpublished(pg_engine, fixture)
        assert not any(path.is_file() for path in tmp_path.rglob("*"))
        monkeypatch.setattr(communications, "record_from_context", original_audit)
        result = _invoke(session, fixture, "inbound", payload)
        assert not result.duplicate
        before = count
        duplicate = _invoke(session, fixture, "inbound", payload)
        assert duplicate.duplicate
        assert duplicate.communication.id == result.communication.id
        assert duplicate.attachment_ids == result.attachment_ids
        assert duplicate.processing_job_ids == result.processing_job_ids
        assert count == before
    with Session(pg_engine) as verify:
        row = verify.get(Communication, result.communication.id)
        assert row.metadata_json["provider_message_id"] == payload.provider_message_id
        assert row.metadata_json["attachment_ids"] == result.attachment_ids
        assert row.metadata_json["processing_job_ids"] == result.processing_job_ids
        assert row.metadata_json["body_attachment_id"] == result.body_attachment_id
        assert row.created_by_membership_id == fixture.actor
        assert row.body == payload.body_preview


@pytest.mark.parametrize("autoflush", [False, True])
def test_simultaneous_inbound_import_preserves_idempotency(
    pg_engine, monkeypatch, tmp_path, autoflush
):
    fixture, payload = _seed(pg_engine), _payload()
    _local_storage(monkeypatch, tmp_path)
    gate, state = Barrier(2), local()
    place = document_storage._place_local_temp_file

    def store(temp, target):
        assert not state.session.in_transaction()
        result = place(temp, target)
        state.stored += 1
        if state.stored == 2:
            gate.wait(timeout=8)
        return result

    def invoke():
        with Session(pg_engine, autoflush=autoflush) as session:
            state.session, state.stored = session, 0
            return _invoke(session, fixture, "inbound", payload)

    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="clean", signature=None),
    )
    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(result.duplicate for result in results) == [False, True]
    assert results[0].communication.id == results[1].communication.id
    assert results[0].attachment_ids == results[1].attachment_ids
    assert results[0].processing_job_ids == results[1].processing_job_ids
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 2
    with Session(pg_engine) as verify:
        assert (
            len(
                list(
                    verify.scalars(
                        select(Communication.id).where(Communication.matter_id == fixture.matter)
                    )
                )
            )
            == 1
        )
        assert (
            len(
                list(
                    verify.scalars(
                        select(MatterAttachment.id).where(
                            MatterAttachment.matter_id == fixture.matter
                        )
                    )
                )
            )
            == 3
        )
        assert (
            len(
                list(
                    verify.scalars(
                        select(DocumentProcessingJob.id).where(
                            DocumentProcessingJob.company_id == fixture.company
                        )
                    )
                )
            )
            == 3
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("surface", ["inbound", "oc"])
def test_commit_acknowledgement_failure_retains_committed_bytes(
    pg_engine, monkeypatch, tmp_path, autoflush, surface
):
    fixture = _seed(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="clean", signature=None),
    )
    with Session(pg_engine, autoflush=autoflush) as session:
        commit = session.commit

        def committed_then_disconnected():
            commit()
            raise ConnectionError("injected lost commit acknowledgement")

        monkeypatch.setattr(session, "commit", committed_then_disconnected)
        with pytest.raises(ConnectionError, match="commit acknowledgement"):
            _invoke(session, fixture, surface)
    with Session(pg_engine) as verify:
        attachments = list(
            verify.scalars(
                select(MatterAttachment).where(
                    MatterAttachment.matter_id == fixture.matter,
                    MatterAttachment.id != fixture.attachment,
                )
            )
        )
        assert len(attachments) == (2 if surface == "inbound" else 1)
        for attachment in attachments:
            assert (tmp_path / attachment.storage_key).is_file()


@pytest.mark.parametrize("autoflush", [False, True])
def test_oc_audit_failure_rolls_back_attachment_before_cleanup(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
):
    fixture = _seed(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="clean", signature=None),
    )
    delete = document_storage.delete_stored_document
    deleted = []
    with Session(pg_engine, autoflush=autoflush) as session:

        def fail_audit(*args, **kwargs):
            _assert_unpublished(pg_engine, fixture)
            raise RuntimeError("injected OC audit failure")

        def cleanup(key):
            assert not session.in_transaction()
            _assert_unpublished(pg_engine, fixture)
            deleted.append(key)
            delete(key)

        monkeypatch.setattr(portal_outside_counsel, "record_audit", fail_audit)
        monkeypatch.setattr(portal_outside_counsel, "delete_stored_document", cleanup)
        with pytest.raises(RuntimeError, match="OC audit"):
            _invoke(session, fixture, "oc")
    _assert_unpublished(pg_engine, fixture)
    assert len(deleted) == 1
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("surface", ["inbound", "oc"])
def test_concurrent_uploads_cannot_oversubscribe_aggregate_quota(
    pg_engine,
    monkeypatch,
    tmp_path,
    autoflush,
    surface,
):
    fixture = _seed(pg_engine)
    with Session(pg_engine) as seed:
        seed.get(Company, fixture.company).storage_quota_bytes = 23 + (
            len(_payload().body_text.encode()) + len(b"Retained attachment")
            if surface == "inbound"
            else len(b"Work product")
        )
        seed.commit()
    _local_storage(monkeypatch, tmp_path)
    gate, state = Barrier(2), local()
    place = document_storage._place_local_temp_file

    def store(temp, target):
        assert not state.session.in_transaction()
        result = place(temp, target)
        state.stored += 1
        if state.stored == (2 if surface == "inbound" else 1):
            gate.wait(timeout=8)
        return result

    def invoke():
        with Session(pg_engine, autoflush=autoflush) as session:
            state.session, state.stored = session, 0
            try:
                _invoke(session, fixture, surface)
                return "published"
            except HTTPException as exc:
                assert exc.status_code == 413
                return "quota_rejected"

    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="clean", signature=None),
    )
    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        assert sorted(future.result(timeout=15) for future in futures) == [
            "published",
            "quota_rejected",
        ]
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == (
        2 if surface == "inbound" else 1
    )
    with Session(pg_engine) as verify:
        attachments = list(
            verify.scalars(
                select(MatterAttachment).where(MatterAttachment.matter_id == fixture.matter)
            )
        )
        assert (
            sum(row.size_bytes for row in attachments)
            == verify.get(Company, fixture.company).storage_quota_bytes
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("surface", ["inbound", "oc"])
@pytest.mark.parametrize("first", ["upload", "dispose"])
def test_upload_and_disposal_serialize_at_company(
    pg_engine,
    monkeypatch,
    tmp_path,
    race,  # noqa: F811
    autoflush,
    surface,
    first,
):
    fixture = _seed(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="clean", signature=None),
    )
    staged = 0
    place = document_storage._place_local_temp_file

    def store(temp, target):
        nonlocal staged
        result = place(temp, target)
        staged += 1
        if staged == (2 if surface == "inbound" else 1):
            race.pause_role = first
        return result

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    race.predicate = lambda sql: "FROM companies" in sql and "FOR NO KEY UPDATE" in sql
    if first == "dispose":
        # Pause upload before final admission so the real lifecycle service wins.
        race.pause_role = "upload"
        race.predicate = (
            lambda sql: staged == (2 if surface == "inbound" else 1)
            and "FROM companies" in sql
            and "FOR NO KEY UPDATE" in sql
        )
        race.after = False

        # Store enables the same upload pause, not the eventual contender role.
        def paused_store(temp, target):
            result = store(temp, target)
            race.pause_role = "upload"
            return result

        monkeypatch.setattr(document_storage, "_place_local_temp_file", paused_store)

    def upload():
        with race.session("upload") as session:
            try:
                _invoke(session, fixture, surface)
                return "published"
            except HTTPException as exc:
                assert exc.status_code == 409
                return "rejected"

    def dispose():
        with race.session("dispose") as session:
            return _mutate(session, fixture, "dispose")

    uploaded = race.submit("upload", upload)
    assert race.paused.wait(10)
    disposed = race.submit("dispose", dispose)
    if first == "upload":
        race.blocked("dispose", "upload", "FROM companies")
    else:
        disposed.result(timeout=10)
    race.release.set()
    assert uploaded.result(timeout=15) == ("published" if first == "upload" else "rejected")
    disposed.result(timeout=15)
    with Session(pg_engine) as verify:
        assert verify.get(Matter, fixture.matter).status == "disposed"


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize(
    "surface,change,table",
    [
        ("inbound", "membership_disabled", "company_memberships"),
        ("inbound", "session_cutoff", "company_memberships"),
        ("inbound", "user_disabled", "users"),
        ("oc", "grant_revoked", "matter_portal_grants"),
        ("oc", "portal_cutoff", "portal_users"),
        ("oc", "portal_disabled", "portal_users"),
    ],
)
@pytest.mark.parametrize("first", ["upload", "revoke"])
def test_final_upload_authority_lock_serializes_revocation(
    pg_engine,
    monkeypatch,
    tmp_path,
    race,  # noqa: F811
    autoflush,
    surface,
    change,
    table,
    first,  # noqa: F811
):
    fixture = _seed(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="clean", signature=None),
    )
    place = document_storage._place_local_temp_file
    staged, enter_final = Event(), Event()
    count = 0
    race.predicate = lambda sql: f"FROM {table}" in sql and (
        "FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql
    )

    def store(temp, target):
        nonlocal count
        result = place(temp, target)
        count += 1
        if count == (2 if surface == "inbound" else 1):
            race.pause_role = first
            staged.set()
            if first == "revoke":
                assert enter_final.wait(10)
        return result

    def upload():
        with race.session("upload") as session:
            try:
                _invoke(session, fixture, surface)
                return "published"
            except HTTPException as exc:
                assert exc.status_code in {401, 403, 404}
                return "rejected"

    def revoke():
        with race.session("revoke") as session:
            identity = (
                fixture.user
                if table == "users"
                else fixture.actor
                if surface == "inbound"
                else fixture.grant
                if change == "grant_revoked"
                else fixture.portal
            )
            session.execute(
                text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE"), {"id": identity}
            )
            _change_authority(session, fixture, change)

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    uploaded = race.submit("upload", upload)
    revoked = None
    try:
        assert staged.wait(10)
        if first == "revoke":
            revoked = race.submit("revoke", revoke)
        assert race.paused.wait(10)
        if first == "upload":
            revoked = race.submit("revoke", revoke)
            race.blocked("revoke", "upload", f"FROM {table}")
        else:
            enter_final.set()
            race.blocked("upload", "revoke", f"FROM {table}")
            with Session(pg_engine) as probe:
                probe.execute(
                    text("SELECT id FROM matters WHERE id=:id FOR UPDATE NOWAIT"),
                    {"id": fixture.matter},
                )
        race.release.set()
        assert uploaded.result(timeout=15) == ("published" if first == "upload" else "rejected")
        revoked.result(timeout=15)
    finally:
        enter_final.set()
        race.release.set()
    if first == "revoke":
        _assert_unpublished(pg_engine, fixture)
        assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("contender", ["communication", "oc_time", "oc_invoice"])
@pytest.mark.parametrize("admission", ["preflight", "final"])
@pytest.mark.parametrize("first", ["ordinary", "upload"])
def test_upload_authority_allows_ordinary_parent_first_actor_fks(
    pg_engine,
    monkeypatch,
    tmp_path,
    race,  # noqa: F811
    autoflush,
    contender,
    admission,  # noqa: F811
    first,
):
    fixture = _seed(pg_engine)
    surface = "inbound" if contender == "communication" else "oc"
    _local_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="clean", signature=None),
    )
    place = document_storage._place_local_temp_file
    staged, enter_final = Event(), Event()
    count = 0
    race.pause_role = first
    race.predicate = lambda sql: (
        "FROM matters" in sql
        and "FOR UPDATE" in sql
        and (first == "ordinary" or admission == "preflight" or staged.is_set())
    )

    def store(temp, target):
        nonlocal count
        result = place(temp, target)
        count += 1
        if admission == "final" and count == (2 if surface == "inbound" else 1):
            staged.set()
            if first == "ordinary":
                assert enter_final.wait(10)
        return result

    def upload():
        with race.session("upload") as session:
            return (
                _invoke(session, fixture, surface).id
                if surface == "oc"
                else _invoke(session, fixture, surface).communication.id
            )

    def ordinary():
        with race.session("ordinary") as session:
            if contender == "communication":
                return communications.create_matter_communication(
                    session,
                    context=_ip_race_context(
                        session, company_id=fixture.company, membership_id=fixture.actor
                    ),
                    matter_id=fixture.matter,
                    payload=CommunicationCreateRequest(
                        channel="note", body="Ordinary actor FK contender"
                    ),
                ).id
            user = session.get(PortalUser, fixture.portal)
            if contender == "oc_time":
                return portal_outside_counsel.submit_oc_time_entry(
                    session,
                    portal_user=user,
                    matter_id=fixture.matter,
                    work_date=datetime.now(UTC).date(),
                    description="Ordinary portal FK contender",
                    duration_minutes=30,
                    billable=False,
                    rate_currency="INR",
                    rate_amount_minor=None,
                ).id
            return portal_outside_counsel.submit_oc_invoice(
                session,
                portal_user=user,
                matter_id=fixture.matter,
                invoice_number=f"OC-{uuid4()}",
                issued_on=datetime.now(UTC).date(),
                due_on=None,
                currency="INR",
                line_items=[{"description": "Ordinary FK contender", "amount_minor": 100}],
            ).id

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    uploaded = None
    logged = None
    try:
        if first == "upload":
            uploaded = race.submit("upload", upload)
            assert race.paused.wait(10)
            logged = race.submit("ordinary", ordinary)
            race.blocked("ordinary", "upload", "SELECT matters.id")
        elif admission == "final":
            uploaded = race.submit("upload", upload)
            assert staged.wait(10)
        if first == "ordinary":
            logged = race.submit("ordinary", ordinary)
            assert race.paused.wait(10)
            if admission == "final":
                enter_final.set()
            else:
                uploaded = race.submit("upload", upload)
            race.blocked("upload", "ordinary", "SELECT matters.id")
        race.release.set()
        assert logged is not None
        assert uploaded is not None
        assert logged.result(timeout=15)
        assert uploaded.result(timeout=15)
    finally:
        enter_final.set()
        race.release.set()
