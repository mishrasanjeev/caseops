"""Nov 27 workbook row 7: Start session must not be an impossible action.

The readiness endpoint reports the start path's own prerequisites and the
next action, so the hearings page can show the checklist and enable Start
session only when POST /mock-hearings will succeed. Every state below asserts
that agreement: ``ready`` is false exactly when start returns 409.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuditEvent,
    DocumentProcessingStatus,
    MatterAttachment,
    MatterAttachmentChunk,
)
from caseops_api.db.session import get_session_factory
from tests.test_mock_hearing import _auth, _bootstrap, _create_matter, _dispose_matter

AFFIDAVIT_TEXT = (
    "Page 2. I state that on 12.04.2026 the respondent received goods "
    "worth Rs. 5,00,000. The invoice is annexed as Annexure A. "
    "The respondent defaulted on payment and no receipt is identified."
)


def _attachment(
    matter_id: str,
    *,
    text: str | None,
    document_type: str | None = "chief_affidavit",
    status: str = DocumentProcessingStatus.INDEXED,
    filename: str = "chief-affidavit.txt",
) -> str:
    attachment_id = str(uuid4())
    with get_session_factory()() as session:
        session.add(
            MatterAttachment(
                id=attachment_id,
                matter_id=matter_id,
                original_filename=filename,
                storage_key=f"test/readiness/{uuid4().hex}.txt",
                content_type="text/plain",
                size_bytes=len(text or ""),
                sha256_hex=(uuid4().hex + uuid4().hex)[:64],
                processing_status=status,
                extracted_char_count=len(text or ""),
                extracted_text=text,
                document_type=document_type,
            )
        )
        if text:
            session.add(
                MatterAttachmentChunk(
                    attachment_id=attachment_id,
                    chunk_index=0,
                    content=text,
                    token_count=len(text.split()),
                )
            )
        session.commit()
    return attachment_id


def _readiness(client: TestClient, token: str, matter_id: str) -> dict:
    response = client.get(f"/api/matters/{matter_id}/mock-hearing-readiness", headers=_auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def _start_status(client: TestClient, token: str, matter_id: str) -> int:
    return client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={"mode": "client_preparation"},
    ).status_code


def _assert_agrees_with_start(client: TestClient, token: str, matter_id: str) -> dict:
    readiness = _readiness(client, token, matter_id)
    if readiness["ready"]:
        assert readiness["next_action"] == "start_session"
    else:
        assert _start_status(client, token, matter_id) == 409
    return readiness


def _check(readiness: dict, key: str) -> str:
    return next(check["status"] for check in readiness["checks"] if check["key"] == key)


def test_readiness_walks_the_tester_from_no_affidavit_to_a_started_session(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"nov27-ready-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "NOV27-READY")

    empty = _assert_agrees_with_start(client, token, matter_id)
    assert empty["ready"] is False
    assert empty["next_action"] == "upload_affidavit"
    assert _check(empty, "affidavit_document") == "missing"
    assert _check(empty, "affidavit_run") == "missing"
    assert empty["affidavit_document_types"] == [
        "affidavit",
        "chief_affidavit",
        "counter_affidavit",
    ]

    # A document exists but nothing is marked as an affidavit.
    _attachment(matter_id, text=AFFIDAVIT_TEXT, document_type=None, filename="petition.txt")
    unmarked = _assert_agrees_with_start(client, token, matter_id)
    assert unmarked["next_action"] == "mark_affidavit"

    # A marked affidavit whose text has not been extracted yet.
    pending_id = _attachment(
        matter_id,
        text=None,
        status=DocumentProcessingStatus.PENDING,
        filename="pending-affidavit.pdf",
    )
    pending = _assert_agrees_with_start(client, token, matter_id)
    assert pending["next_action"] == "wait_for_processing"
    assert pending["next_action_attachment_id"] == pending_id
    assert _check(pending, "affidavit_text") == "pending"

    # A marked affidavit with readable text: the direct action is to run it.
    ready_id = _attachment(matter_id, text=AFFIDAVIT_TEXT)
    runnable = _assert_agrees_with_start(client, token, matter_id)
    assert runnable["next_action"] == "run_affidavit_intelligence"
    assert runnable["next_action_attachment_id"] == ready_id
    assert _check(runnable, "affidavit_document") == "met"
    assert _check(runnable, "affidavit_text") == "met"

    analyzed = client.post(
        f"/api/matters/{matter_id}/attachments/{ready_id}/affidavit-intelligence/analyze",
        headers=_auth(token),
    )
    assert analyzed.status_code == 200, analyzed.text

    ready = _readiness(client, token, matter_id)
    assert ready["ready"] is True
    assert ready["next_action"] == "start_session"
    assert ready["available_question_count"] > 0
    assert all(check["status"] == "met" for check in ready["checks"])
    assert _start_status(client, token, matter_id) == 200


def test_affidavit_without_findings_points_to_a_new_upload_not_a_rerun(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"nov27-nofind-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "NOV27-NOFIND")
    attachment_id = _attachment(
        matter_id,
        text="lorem ipsum dolor sit amet " * 8,
    )
    assert _readiness(client, token, matter_id)["next_action"] == "run_affidavit_intelligence"
    client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(token),
    )
    after = _assert_agrees_with_start(client, token, matter_id)
    assert after["ready"] is False
    assert after["next_action"] == "upload_affidavit"
    assert "no source-backed questions" in after["next_action_detail"]
    source = after["affidavit_sources"][0]
    assert source["latest_run_status"] == "no_findings"


def test_disposed_matter_is_never_ready(client: TestClient) -> None:
    boot = _bootstrap(client, f"nov27-disposed-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "NOV27-DISP")
    attachment_id = _attachment(matter_id, text=AFFIDAVIT_TEXT)
    client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(token),
    )
    _dispose_matter(matter_id)
    readiness = _assert_agrees_with_start(client, token, matter_id)
    assert readiness["ready"] is False
    assert readiness["next_action"] == "none"
    assert _check(readiness, "matter_operational") == "blocked"


def test_readiness_is_tenant_isolated_and_read_only(client: TestClient) -> None:
    owner = _bootstrap(client, f"nov27-owner-{uuid4().hex[:6]}")
    owner_token = str(owner["access_token"])
    matter_id = _create_matter(client, owner_token, "NOV27-ISO")
    _attachment(matter_id, text=AFFIDAVIT_TEXT)

    with get_session_factory()() as session:
        audit_before = session.scalar(select(func.count()).select_from(AuditEvent))
    _readiness(client, owner_token, matter_id)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == audit_before

    other = _bootstrap(client, f"nov27-other-{uuid4().hex[:6]}")
    response = client.get(
        f"/api/matters/{matter_id}/mock-hearing-readiness",
        headers=_auth(str(other["access_token"])),
    )
    assert response.status_code == 404
    assert "chief-affidavit" not in response.text


def _analyze(client: TestClient, token: str, matter_id: str, attachment_id: str) -> dict:
    response = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _replace_text(attachment_id: str, text: str) -> None:
    """What indexing or OCR does when it finishes: new readable chunks."""

    with get_session_factory()() as session:
        attachment = session.get(MatterAttachment, attachment_id)
        assert attachment is not None
        attachment.chunks.clear()
        session.flush()
        attachment.chunks.append(
            MatterAttachmentChunk(chunk_index=0, content=text, token_count=len(text.split()))
        )
        attachment.processing_status = DocumentProcessingStatus.INDEXED
        attachment.extracted_text = text
        attachment.extracted_char_count = len(text)
        session.commit()


def test_affidavit_analysed_before_its_text_was_readable_is_re_run_in_place(
    client: TestClient,
) -> None:
    """Review finding on row 7: a run that ended insufficient_source_text
    because OCR/indexing had not finished must not send the tester to upload
    the affidavit again once its text is readable."""

    boot = _bootstrap(client, f"nov27-rerun-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "NOV27-RERUN")
    attachment_id = _attachment(
        matter_id,
        text=None,
        status=DocumentProcessingStatus.PENDING,
        filename="scanned-affidavit.pdf",
    )
    early = _analyze(client, token, matter_id, attachment_id)
    assert early["runs"][0]["status"] == "insufficient_source_text"
    waiting = _assert_agrees_with_start(client, token, matter_id)
    assert waiting["next_action"] == "wait_for_processing"

    _replace_text(attachment_id, AFFIDAVIT_TEXT)

    stale = _assert_agrees_with_start(client, token, matter_id)
    assert stale["ready"] is False
    assert stale["next_action"] == "run_affidavit_intelligence"
    assert stale["next_action_attachment_id"] == attachment_id
    assert "re-run affidavit intelligence" in stale["next_action_detail"].lower()
    source = stale["affidavit_sources"][0]
    assert source["has_usable_text"] is True
    assert source["latest_run_status"] == "insufficient_source_text"

    _analyze(client, token, matter_id, attachment_id)
    ready = _readiness(client, token, matter_id)
    assert ready["ready"] is True
    assert ready["next_action"] == "start_session"
    assert _start_status(client, token, matter_id) == 200


def test_affidavit_whose_text_changed_after_a_no_findings_run_is_re_run(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"nov27-changed-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "NOV27-CHANGED")
    attachment_id = _attachment(matter_id, text="lorem ipsum dolor sit amet " * 8)
    _analyze(client, token, matter_id, attachment_id)
    assert _readiness(client, token, matter_id)["next_action"] == "upload_affidavit"

    # Re-processing replaced the garbled text layer with the real one.
    _replace_text(attachment_id, AFFIDAVIT_TEXT)
    changed = _assert_agrees_with_start(client, token, matter_id)
    assert changed["next_action"] == "run_affidavit_intelligence"
    assert changed["next_action_attachment_id"] == attachment_id
    assert "changed since" in changed["next_action_detail"]

    _analyze(client, token, matter_id, attachment_id)
    assert _readiness(client, token, matter_id)["ready"] is True
    assert _start_status(client, token, matter_id) == 200


def test_readiness_never_offers_a_run_that_would_repeat_the_latest_result(
    client: TestClient,
) -> None:
    """No loop: once every readable affidavit has a run over its current text,
    readiness stops offering a re-run, and unreadable ones are not offered."""

    boot = _bootstrap(client, f"nov27-norepeat-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "NOV27-NOREPEAT")
    unreadable_id = _attachment(
        matter_id,
        text=None,
        status=DocumentProcessingStatus.FAILED,
        filename="unreadable-affidavit.pdf",
    )
    _analyze(client, token, matter_id, unreadable_id)
    only_unreadable = _assert_agrees_with_start(client, token, matter_id)
    assert only_unreadable["next_action"] == "upload_affidavit"
    assert "No text could be read" in only_unreadable["next_action_detail"]

    readable_id = _attachment(matter_id, text="lorem ipsum dolor sit amet " * 8)
    assert _readiness(client, token, matter_id)["next_action_attachment_id"] == readable_id
    _analyze(client, token, matter_id, readable_id)
    settled = _assert_agrees_with_start(client, token, matter_id)
    assert settled["next_action"] == "upload_affidavit"
    assert settled["next_action_attachment_id"] is None
    assert "no source-backed questions" in settled["next_action_detail"]
