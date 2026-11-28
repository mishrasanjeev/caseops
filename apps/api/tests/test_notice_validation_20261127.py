"""Notice Received / Notice Sent validation (Aishwarya, nova-legal, 2026-11-27).

Workbook rows 2 and 3: the matter Notices forms uploaded notices with no date,
no subject, no type, negative amounts, a reply-required notice with no due
date, a due date before receipt, recovered above dispute, unsupported or
oversized files and the same notice twice.  Every invalid case below is sent
through both the create and the edit path of both notice writers (matter
attachment and company register) and must create or change nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, CompanyNotice, MatterAttachment
from caseops_api.db.session import get_session_factory
from caseops_api.services.file_security import (
    ALLOWED_UPLOADS,
    DEFAULT_MAX_BYTES,
    allowed_upload_extensions,
)
from caseops_api.services.notice_rules import notice_today

_PASSWORD = "NoticeRules2026!"
TODAY = notice_today()
RECEIVED = (TODAY - timedelta(days=10)).isoformat()
DUE = (TODAY + timedelta(days=5)).isoformat()
FUTURE = (TODAY + timedelta(days=1)).isoformat()
BEFORE_RECEIPT = (TODAY - timedelta(days=11)).isoformat()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, prefix: str) -> dict[str, object]:
    slug = f"{prefix}-{uuid4().hex[:8]}"
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{prefix.title()} Legal",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Notice Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": _PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _matter(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": "Notice validation matter",
            "matter_code": f"NV-{uuid4().hex[:8].upper()}",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _received_form(**overrides: str) -> dict[str, str]:
    """Exactly what the Notice Received form posts for a complete notice."""

    form = {
        "document_type": "notice",
        "lifecycle_stage": "initiation",
        "document_date": RECEIVED,
        "notice_direction": "received",
        "notice_document_role": "notice",
        "notice_type": "Legal demand",
        "notice_subject": "Demand for unpaid invoices",
        "notice_received_on": RECEIVED,
        "notice_received_from": "Opposing counsel",
        "notice_source": "Opposing counsel",
        "notice_status": "Open",
        "notice_currency": "INR",
        "notice_amount_minor": "1250000",
        "notice_reply_required": "true",
        "notice_reply_sent": "false",
        "notice_reply_due_on": DUE,
    }
    form.update(overrides)
    return {key: value for key, value in form.items() if value is not None}


def _sent_form(**overrides: str) -> dict[str, str]:
    form = {
        "document_type": "notice",
        "lifecycle_stage": "initiation",
        "document_date": RECEIVED,
        "notice_direction": "sent",
        "notice_document_role": "notice",
        "notice_type": "Recovery notice",
        "notice_subject": "Recovery of outstanding dues",
        "notice_sent_on": RECEIVED,
        "notice_authority": "Debtor Pvt Ltd",
        "notice_status": "Dispatched",
        "notice_currency": "INR",
        "notice_dispute_amount_minor": "1500000",
        "notice_recovered_amount_minor": "250000",
        "notice_reply_required": "false",
        "notice_reply_sent": "false",
    }
    form.update(overrides)
    return {key: value for key, value in form.items() if value is not None}


def _upload(
    client: TestClient,
    token: str,
    matter_id: str,
    form: dict[str, str],
    *,
    name: str = "notice.txt",
    body: bytes | None = None,
    content_type: str = "text/plain",
):
    if body is None:
        body = f"notice {uuid4().hex}".encode()
    return client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=_auth(token),
        data=form,
        files={"file": (name, body, content_type)},
    )


def _notice_attachment_count(matter_id: str) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count(MatterAttachment.id)).where(
                    MatterAttachment.matter_id == matter_id,
                    MatterAttachment.document_type == "notice",
                )
            )
            or 0
        )


def _error_fields(response) -> dict[str, str]:  # type: ignore[no-untyped-def]
    body = response.json()
    return {str(item["loc"][-1]): str(item["msg"]) for item in body.get("errors", [])}


RECEIVED_INVALID = [
    pytest.param(
        {"notice_received_on": None, "document_date": None},
        "notice_received_on",
        "Enter the date of receipt.",
        id="no-date-of-receipt",
    ),
    pytest.param(
        {"notice_subject": None}, "notice_subject", "Enter the notice subject.", id="no-subject"
    ),
    pytest.param(
        {"notice_subject": "   "}, "notice_subject", "Enter the notice subject.", id="blank-subject"
    ),
    pytest.param(
        {"notice_type": None}, "notice_type", "Enter the type of notice.", id="no-type"
    ),
    pytest.param(
        {"notice_received_on": "2026-02-30"}, "notice_received_on", None, id="invalid-date"
    ),
    pytest.param(
        {"notice_received_on": "0020-03-02"},
        "notice_received_on",
        "Enter a date between 1900 and 2100.",
        id="browser-completed-year-0020",
    ),
    pytest.param(
        {"notice_received_on": FUTURE},
        "notice_received_on",
        "Date of receipt cannot be in the future.",
        id="future-date",
    ),
    pytest.param(
        {"notice_amount_minor": "-100"}, "notice_amount_minor", None, id="negative-amount"
    ),
    pytest.param(
        {"notice_reply_due_on": None},
        "notice_reply_due_on",
        "Enter the reply due date, or clear Reply required.",
        id="reply-required-without-due-date",
    ),
    pytest.param(
        {"notice_reply_due_on": BEFORE_RECEIPT},
        "notice_reply_due_on",
        "Reply due date cannot be earlier than the date of receipt.",
        id="due-before-receipt",
    ),
    pytest.param(
        {"notice_reply_sent": "true", "notice_reply_sent_on": BEFORE_RECEIPT},
        "notice_reply_sent_on",
        "Reply sent date cannot be earlier than the date of receipt.",
        id="reply-sent-before-receipt",
    ),
]

SENT_INVALID = [
    pytest.param(
        {"notice_sent_on": None, "document_date": None},
        "notice_sent_on",
        "Enter the notice sent date.",
        id="no-sent-date",
    ),
    pytest.param(
        {"notice_subject": None}, "notice_subject", "Enter the notice subject.", id="no-subject"
    ),
    pytest.param(
        {"notice_type": ""}, "notice_type", "Enter the type of notice.", id="empty-type"
    ),
    pytest.param({"notice_sent_on": "2026-13-01"}, "notice_sent_on", None, id="invalid-date"),
    pytest.param(
        {"notice_sent_on": "0001-03-02"},
        "notice_sent_on",
        "Enter a date between 1900 and 2100.",
        id="browser-completed-year-0001",
    ),
    pytest.param(
        {"notice_sent_on": FUTURE},
        "notice_sent_on",
        "Notice sent date cannot be in the future.",
        id="future-date",
    ),
    pytest.param(
        {"notice_dispute_amount_minor": "-1"},
        "notice_dispute_amount_minor",
        None,
        id="negative-dispute",
    ),
    pytest.param(
        {"notice_recovered_amount_minor": "-1"},
        "notice_recovered_amount_minor",
        None,
        id="negative-recovered",
    ),
    pytest.param(
        {"notice_recovered_amount_minor": "1500001"},
        "notice_recovered_amount_minor",
        "Recovered amount cannot exceed the dispute amount.",
        id="recovered-above-dispute",
    ),
]


@pytest.mark.parametrize(("overrides", "field", "message"), RECEIVED_INVALID)
def test_notice_received_upload_rejects_each_invalid_detail(
    client: TestClient, overrides: dict[str, str | None], field: str, message: str | None
) -> None:
    boot = _bootstrap(client, "nv-recv")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)

    response = _upload(client, token, matter_id, _received_form(**overrides))

    assert response.status_code == 422, response.text
    errors = _error_fields(response)
    assert field in errors, errors
    if message is not None:
        assert errors[field] == message
    assert _notice_attachment_count(matter_id) == 0


@pytest.mark.parametrize(("overrides", "field", "message"), SENT_INVALID)
def test_notice_sent_upload_rejects_each_invalid_detail(
    client: TestClient, overrides: dict[str, str | None], field: str, message: str | None
) -> None:
    boot = _bootstrap(client, "nv-sent")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)

    response = _upload(client, token, matter_id, _sent_form(**overrides))

    assert response.status_code == 422, response.text
    errors = _error_fields(response)
    assert field in errors, errors
    if message is not None:
        assert errors[field] == message
    assert _notice_attachment_count(matter_id) == 0


def test_complete_notices_upload_and_reply_documents_stay_metadata_free(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "nv-ok")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)

    received = _upload(client, token, matter_id, _received_form())
    assert received.status_code == 200, received.text
    assert received.json()["notice_reply_status"] == "reply_due_in_days"
    sent = _upload(client, token, matter_id, _sent_form())
    assert sent.status_code == 200, sent.text
    # Reply already sent at upload: no due date is needed.
    replied = _upload(
        client,
        token,
        matter_id,
        _received_form(
            notice_subject="Already answered notice",
            notice_reply_due_on=None,
            notice_reply_sent="true",
            notice_reply_sent_on=RECEIVED,
        ),
    )
    assert replied.status_code == 200, replied.text
    # Informational notice: reply not required, no due date.
    informational = _upload(
        client,
        token,
        matter_id,
        _received_form(
            notice_subject="Informational circular",
            notice_reply_required="false",
            notice_reply_due_on=None,
        ),
    )
    assert informational.status_code == 200, informational.text
    # Reply and supporting documents are children; their subject is derived.
    reply = _upload(
        client,
        token,
        matter_id,
        {
            "document_type": "notice",
            "notice_direction": "received",
            "notice_document_role": "reply",
            "notice_parent_attachment_id": received.json()["id"],
            "notice_subject": "Reply - Demand for unpaid invoices",
        },
    )
    assert reply.status_code == 200, reply.text
    assert _notice_attachment_count(matter_id) == 5


def test_notice_document_is_required_and_file_rules_come_from_one_policy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot = _bootstrap(client, "nv-file")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)

    no_file = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=_auth(token),
        data=_sent_form(),
    )
    assert no_file.status_code == 422, no_file.text

    unsupported = _upload(
        client, token, matter_id, _sent_form(), name="notice.exe",
        body=b"MZ\x90\x00binary", content_type="application/octet-stream",
    )
    assert unsupported.status_code == 400, unsupported.text
    assert "not allowed" in unsupported.json()["detail"]

    workspace = client.get(f"/api/matters/{matter_id}/workspace", headers=_auth(token))
    policy = workspace.json()["storage_governance"]
    assert policy["allowed_upload_extensions"] == sorted(
        {kind.extension for kind in ALLOWED_UPLOADS}
    )
    assert policy["allowed_upload_extensions"] == allowed_upload_extensions()
    assert ".exe" not in policy["allowed_upload_extensions"]
    assert policy["max_upload_size_bytes"] == min(
        DEFAULT_MAX_BYTES, get_settings().max_attachment_size_bytes
    )
    register_policy = client.get("/api/notices/upload-policy", headers=_auth(token))
    assert register_policy.status_code == 200, register_policy.text
    assert register_policy.json()["allowed_upload_extensions"] == policy[
        "allowed_upload_extensions"
    ]
    assert register_policy.json()["max_upload_size_bytes"] == policy["max_upload_size_bytes"]

    # The advertised cap is the enforced cap: one byte over it is refused.
    monkeypatch.setenv("CASEOPS_MAX_ATTACHMENT_SIZE_BYTES", "64")
    get_settings.cache_clear()
    shrunk = client.get("/api/notices/upload-policy", headers=_auth(token)).json()
    assert shrunk["max_upload_size_bytes"] == 64
    at_cap = _upload(client, token, matter_id, _sent_form(), body=b"a" * 64)
    assert at_cap.status_code == 200, at_cap.text
    oversize = _upload(
        client, token, matter_id,
        _sent_form(notice_subject="Oversize notice"), body=b"b" * 65,
    )
    assert oversize.status_code == 413, oversize.text
    assert _notice_attachment_count(matter_id) == 1


def test_duplicate_notice_returns_409_with_existing_reference(client: TestClient) -> None:
    boot = _bootstrap(client, "nv-dup")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _matter(client, token)
    other_matter_id = _matter(client, token)
    body = b"Recovery notice body 2026-11-27"

    first = _upload(client, token, matter_id, _sent_form(), body=body)
    assert first.status_code == 200, first.text
    first_id = first.json()["id"]

    # Same file again, even with different details and an override: refused.
    same_file = _upload(
        client, token, matter_id,
        _sent_form(notice_subject="Different subject", allow_duplicate="true"),
        name="renamed.txt", body=body,
    )
    assert same_file.status_code == 409, same_file.text
    payload = same_file.json()
    assert payload["duplicate_kind"] == "same_file"
    assert payload["override_allowed"] is False
    assert payload["existing_notice"]["id"] == first_id
    assert payload["existing_notice"]["subject"] == "Recovery of outstanding dues"

    # Same direction + date + subject + counterparty with new bytes: refused,
    # case and spacing do not matter, and the override is offered.
    same_details = _upload(
        client, token, matter_id,
        _sent_form(
            notice_subject="  recovery of   OUTSTANDING dues ",
            notice_authority="debtor pvt ltd",
        ),
    )
    assert same_details.status_code == 409, same_details.text
    assert same_details.json()["duplicate_kind"] == "same_details"
    assert same_details.json()["override_allowed"] is True
    assert same_details.json()["existing_notice"]["id"] == first_id
    assert _notice_attachment_count(matter_id) == 1

    overridden = _upload(client, token, matter_id, _sent_form(allow_duplicate="true"))
    assert overridden.status_code == 200, overridden.text
    with get_session_factory()() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "matter_attachment.notice_duplicate_override",
            )
        )
        assert audit is not None
        assert audit.target_id == overridden.json()["id"]
        assert json.loads(audit.metadata_json or "{}")["existing_notice_id"] == first_id

    # Another matter, or a received notice with the same subject, is not a duplicate.
    elsewhere = _upload(client, token, other_matter_id, _sent_form(), body=body)
    assert elsewhere.status_code == 200, elsewhere.text
    other_direction = _upload(
        client, token, matter_id,
        _received_form(notice_subject="Recovery of outstanding dues"),
    )
    assert other_direction.status_code == 200, other_direction.text

    # Tenant isolation: another company's identical notice is never matched.
    other = _bootstrap(client, "nv-dup-other")
    other_token = str(other["access_token"])
    other_tenant_matter = _matter(client, other_token)
    cross = _upload(client, other_token, other_tenant_matter, _sent_form(), body=body)
    assert cross.status_code == 200, cross.text


def _primary_notice(client: TestClient, token: str, matter_id: str, form: dict[str, str]):
    response = _upload(client, token, matter_id, form)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        pytest.param({"notice_subject": ""}, "notice_subject", id="clear-subject"),
        pytest.param({"notice_type": None}, "notice_type", id="clear-type"),
        pytest.param({"notice_received_on": None}, "notice_received_on", id="clear-date"),
        pytest.param({"notice_received_on": FUTURE}, "notice_received_on", id="future-date"),
        pytest.param({"notice_reply_due_on": None}, "notice_reply_due_on", id="clear-due"),
        pytest.param(
            {"notice_reply_due_on": BEFORE_RECEIPT}, "notice_reply_due_on", id="due-before"
        ),
        pytest.param(
            {"notice_reply_sent": True, "notice_reply_sent_on": FUTURE},
            "notice_reply_sent_on",
            id="reply-sent-in-future",
        ),
        pytest.param({"notice_amount_minor": -5}, "notice_amount_minor", id="negative"),
    ],
)
def test_received_notice_edit_cannot_introduce_invalid_details(
    client: TestClient, patch: dict[str, object], field: str
) -> None:
    boot = _bootstrap(client, "nv-edit-r")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)
    notice = _primary_notice(client, token, matter_id, _received_form())

    response = client.patch(
        f"/api/matters/{matter_id}/attachments/{notice['id']}/metadata",
        headers=_auth(token),
        json=patch,
    )

    assert response.status_code == 422, response.text
    assert field in _error_fields(response)
    workspace = client.get(f"/api/matters/{matter_id}/workspace", headers=_auth(token)).json()
    stored = next(row for row in workspace["attachments"] if row["id"] == notice["id"])
    for key in ("notice_subject", "notice_type", "notice_received_on", "notice_reply_due_on"):
        assert stored[key] == notice[key]


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        pytest.param({"notice_sent_on": None}, "notice_sent_on", id="clear-date"),
        pytest.param({"notice_type": "  "}, "notice_type", id="blank-type"),
        pytest.param(
            {"notice_recovered_amount_minor": 1500001},
            "notice_recovered_amount_minor",
            id="recovered-above-dispute",
        ),
        pytest.param(
            {"notice_dispute_amount_minor": 100},
            "notice_recovered_amount_minor",
            id="dispute-below-recovered",
        ),
        pytest.param(
            {"notice_dispute_amount_minor": -1}, "notice_dispute_amount_minor", id="negative"
        ),
    ],
)
def test_sent_notice_edit_cannot_introduce_invalid_details(
    client: TestClient, patch: dict[str, object], field: str
) -> None:
    boot = _bootstrap(client, "nv-edit-s")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)
    notice = _primary_notice(client, token, matter_id, _sent_form())

    response = client.patch(
        f"/api/matters/{matter_id}/attachments/{notice['id']}/metadata",
        headers=_auth(token),
        json=patch,
    )

    assert response.status_code == 422, response.text
    assert field in _error_fields(response)


def test_reclassifying_a_document_as_a_notice_needs_notice_details(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "nv-reclass")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)
    document = _upload(
        client, token, matter_id, {"document_type": "correspondence"}, name="letter.txt"
    )
    assert document.status_code == 200, document.text
    # The Documents page posting document_type=notice with no details is the
    # same defect as the Notices form; neither the upload nor a reclassify may
    # create a notice without its details.
    bare_upload = _upload(client, token, matter_id, {"document_type": "notice"})
    assert bare_upload.status_code == 422, bare_upload.text

    bare = client.patch(
        f"/api/matters/{matter_id}/attachments/{document.json()['id']}/metadata",
        headers=_auth(token),
        json={"document_type": "notice"},
    )
    assert bare.status_code == 422, bare.text
    complete = client.patch(
        f"/api/matters/{matter_id}/attachments/{document.json()['id']}/metadata",
        headers=_auth(token),
        json={
            "document_type": "notice",
            "notice_direction": "received",
            "notice_subject": "Letter treated as notice",
            "notice_type": "Legal demand",
            "notice_received_on": RECEIVED,
            "notice_reply_required": False,
        },
    )
    assert complete.status_code == 200, complete.text


def _legacy_notice(matter_id: str, membership_id: str) -> str:
    """A notice stored before these rules: no subject, type, date or due date."""

    with get_session_factory()() as session:
        row = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=membership_id,
            original_filename="legacy-notice.pdf",
            storage_key=f"legacy/{uuid4()}/legacy-notice.pdf",
            content_type="application/pdf",
            size_bytes=128,
            sha256_hex="c" * 64,
            processing_status="indexed",
            extracted_char_count=10,
            document_type="notice",
            notice_direction="received",
            notice_document_role="notice",
            notice_reply_required=True,
            created_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
        )
        session.add(row)
        session.commit()
        return row.id


def test_legacy_incomplete_notice_still_reads_and_takes_unrelated_edits(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "nv-legacy")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)
    legacy_id = _legacy_notice(matter_id, str(boot["membership"]["id"]))

    workspace = client.get(f"/api/matters/{matter_id}/workspace", headers=_auth(token))
    assert workspace.status_code == 200, workspace.text
    assert legacy_id in {row["id"] for row in workspace.json()["attachments"]}
    register = client.get(f"/api/notices/?matter_id={matter_id}", headers=_auth(token))
    assert register.status_code == 200, register.text
    assert legacy_id in {row["id"] for row in register.json()["notices"]}

    # Mark reply sent on a legacy row is not blocked by its pre-existing gaps.
    marked = client.patch(
        f"/api/matters/{matter_id}/attachments/{legacy_id}/metadata",
        headers=_auth(token),
        json={"notice_reply_sent": True, "notice_reply_sent_on": TODAY.isoformat()},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["notice_reply_status"] == "reply_sent"
    # ...but an edit that adds a new violation still is.
    worse = client.patch(
        f"/api/matters/{matter_id}/attachments/{legacy_id}/metadata",
        headers=_auth(token),
        json={"notice_amount_minor": -1},
    )
    assert worse.status_code == 422, worse.text


# --- Company notice register (the second notice writer) ---------------------


def _register_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "direction": "received",
        "subject": "Register demand notice",
        "type": "Legal demand",
        "received_on": RECEIVED,
        "received_from": "Opposing counsel",
        "reply_required": True,
        "reply_due_on": DUE,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def _register_count(company_id: str) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count(CompanyNotice.id)).where(CompanyNotice.company_id == company_id)
            )
            or 0
        )


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        pytest.param(_register_payload(received_on=None), "received_on", id="no-receipt"),
        pytest.param(_register_payload(type=None), "type", id="no-type"),
        pytest.param(_register_payload(received_on=FUTURE), "received_on", id="future"),
        pytest.param(
            _register_payload(reply_due_on=None), "reply_due_on", id="reply-without-due"
        ),
        pytest.param(
            _register_payload(reply_due_on=BEFORE_RECEIPT), "reply_due_on", id="due-before"
        ),
        pytest.param(
            {
                "direction": "sent",
                "subject": "Register sent notice",
                "type": "Recovery notice",
                "dispute_amount_minor": 100,
                "recovered_amount_minor": 101,
                "sent_on": RECEIVED,
            },
            "recovered_amount_minor",
            id="recovered-above-dispute",
        ),
        pytest.param(
            {"direction": "sent", "subject": "Register sent", "type": "Recovery notice"},
            "sent_on",
            id="no-sent-date",
        ),
    ],
)
def test_register_create_applies_the_same_notice_rules(
    client: TestClient, payload: dict[str, object], field: str
) -> None:
    boot = _bootstrap(client, "nv-reg")
    token = str(boot["access_token"])

    response = client.post("/api/notices/", headers=_auth(token), json=payload)

    assert response.status_code == 422, response.text
    assert field in _error_fields(response)
    assert _register_count(str(boot["company"]["id"])) == 0


def test_register_edit_duplicate_and_same_file_rules(client: TestClient) -> None:
    boot = _bootstrap(client, "nv-reg-dup")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])

    created = client.post("/api/notices/", headers=_auth(token), json=_register_payload())
    assert created.status_code == 201, created.text
    notice = created.json()

    cleared = client.patch(
        f"/api/notices/{notice['id']}",
        headers=_auth(token),
        json={"expected_updated_at": notice["updated_at"], "received_on": None},
    )
    assert cleared.status_code == 422, cleared.text
    assert "received_on" in _error_fields(cleared)
    backwards = client.patch(
        f"/api/notices/{notice['id']}",
        headers=_auth(token),
        json={"expected_updated_at": notice["updated_at"], "reply_due_on": BEFORE_RECEIPT},
    )
    assert backwards.status_code == 422, backwards.text

    duplicate = client.post(
        "/api/notices/",
        headers=_auth(token),
        json=_register_payload(subject="REGISTER  demand notice"),
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["existing_notice"]["id"] == notice["id"]
    assert duplicate.json()["override_allowed"] is True
    assert _register_count(company_id) == 1
    allowed = client.post(
        "/api/notices/", headers=_auth(token), json=_register_payload(allow_duplicate=True)
    )
    assert allowed.status_code == 201, allowed.text

    body = b"Register notice document bytes"
    first_file = client.post(
        f"/api/notices/{notice['id']}/file",
        headers=_auth(token),
        data={"expected_updated_at": notice["updated_at"]},
        files={"file": ("register.txt", body, "text/plain")},
    )
    assert first_file.status_code == 200, first_file.text
    second = allowed.json()
    same_file = client.post(
        f"/api/notices/{second['id']}/file",
        headers=_auth(token),
        data={"expected_updated_at": second["updated_at"]},
        files={"file": ("copy.txt", body, "text/plain")},
    )
    assert same_file.status_code == 409, same_file.text
    assert same_file.json()["duplicate_kind"] == "same_file"
    assert same_file.json()["existing_notice"]["id"] == notice["id"]

    other = _bootstrap(client, "nv-reg-other")
    cross = client.post(
        "/api/notices/", headers=_auth(str(other["access_token"])), json=_register_payload()
    )
    assert cross.status_code == 201, cross.text


def test_register_legacy_row_without_dates_still_accepts_unrelated_edits(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "nv-reg-legacy")
    token = str(boot["access_token"])
    with get_session_factory()() as session:
        row = CompanyNotice(
            company_id=str(boot["company"]["id"]),
            created_by_membership_id=str(boot["membership"]["id"]),
            direction="received",
            subject="Legacy register notice",
            status="Open",
            currency="INR",
            reply_required=False,
            reply_sent=False,
        )
        session.add(row)
        session.commit()
        notice_id = row.id
    detail = client.get(f"/api/notices/{notice_id}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    edited = client.patch(
        f"/api/notices/{notice_id}",
        headers=_auth(token),
        json={"expected_updated_at": detail.json()["updated_at"], "status": "Closed"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "Closed"


def test_future_bound_uses_the_latest_civil_day() -> None:
    from caseops_api.services.notice_rules import NoticeState, notice_rule_violations

    state = NoticeState(
        direction="received",
        subject="s",
        notice_type="t",
        received_on=date(2026, 11, 28),
        sent_on=None,
        reply_required=False,
        reply_sent=False,
        reply_due_on=None,
        reply_sent_on=None,
        amount_minor=None,
        dispute_amount_minor=None,
        recovered_amount_minor=None,
    )
    assert notice_rule_violations(state, today=date(2026, 11, 28)) == []
    assert [v.code for v in notice_rule_violations(state, today=date(2026, 11, 27))] == [
        "received_on_in_future"
    ]


# --- Round 2: the duplicate rule on edits and across the two stores ---------


def _audit_metadata(company_id: str, action: str) -> list[dict[str, object]]:
    with get_session_factory()() as session:
        rows = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.company_id == company_id, AuditEvent.action == action)
            .order_by(AuditEvent.created_at.asc())
        )
        return [json.loads(row.metadata_json or "{}") for row in rows]


def _register_patch(client: TestClient, token: str, notice: dict[str, object], **changes: object):
    return client.patch(
        f"/api/notices/{notice['id']}",
        headers=_auth(token),
        json={"expected_updated_at": notice["updated_at"], **changes},
    )


def test_register_edit_cannot_make_a_notice_a_duplicate(client: TestClient) -> None:
    """Tester row 3 reached by edit: a second notice edited into the first's details."""

    boot = _bootstrap(client, "nv-reg-edit-dup")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    first = client.post("/api/notices/", headers=_auth(token), json=_register_payload())
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    def second(**overrides: object) -> dict[str, object]:
        created = client.post(
            "/api/notices/", headers=_auth(token), json=_register_payload(**overrides)
        )
        assert created.status_code == 201, created.text
        return created.json()

    # Each compared field, edited into a match, is refused with the create 409.
    for overrides, change in (
        ({"subject": "Second demand notice"}, {"subject": "  REGISTER demand   notice "}),
        ({"received_on": BEFORE_RECEIPT}, {"received_on": RECEIVED}),
        ({"received_from": "Another firm"}, {"received_from": "opposing COUNSEL"}),
    ):
        other = second(**overrides)
        refused = _register_patch(client, token, other, **change)
        assert refused.status_code == 409, refused.text
        body = refused.json()
        assert body["duplicate_kind"] == "same_details"
        assert body["override_allowed"] is True
        assert body["existing_notice"]["id"] == first_id
        assert body["existing_notice"]["source_kind"] == "standalone"
        stored = client.get(f"/api/notices/{other['id']}", headers=_auth(token)).json()
        assert stored["updated_at"] == other["updated_at"]
        for key in change:
            assert stored[key] == other[key]

    # "Save anyway" keeps the edit and is audited against the matched notice.
    allowed = _register_patch(
        client, token, other, received_from="Opposing counsel", allow_duplicate=True
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["received_from"] == "Opposing counsel"
    assert _audit_metadata(company_id, "notice.updated")[-1]["duplicate_override_of"] == first_id
    # The overridden pair still takes unrelated edits, and an edit that keeps
    # the compared details unchanged never re-runs the rule.
    closed = _register_patch(client, token, allowed.json(), status="Closed")
    assert closed.status_code == 200, closed.text
    recased = _register_patch(client, token, closed.json(), subject="register demand notice")
    assert recased.status_code == 200, recased.text
    assert "duplicate_override_of" not in _audit_metadata(company_id, "notice.updated")[-1]

    # Another tenant's identical notice is never matched on edit either.
    other_boot = _bootstrap(client, "nv-reg-edit-dup-other")
    other_token = str(other_boot["access_token"])
    foreign = client.post(
        "/api/notices/",
        headers=_auth(other_token),
        json=_register_payload(subject="Foreign notice"),
    ).json()
    foreign_edit = _register_patch(client, other_token, foreign, subject="Register demand notice")
    assert foreign_edit.status_code == 200, foreign_edit.text


def test_matter_notice_edit_cannot_make_a_notice_a_duplicate(client: TestClient) -> None:
    boot = _bootstrap(client, "nv-mat-edit-dup")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _matter(client, token)
    first = _primary_notice(client, token, matter_id, _received_form())
    other = _primary_notice(
        client, token, matter_id, _received_form(notice_subject="Second demand")
    )

    def patch(attachment_id: str, **changes: object):
        return client.patch(
            f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
            headers=_auth(token),
            json=changes,
        )

    refused = patch(other["id"], notice_subject="demand for UNPAID invoices")
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["duplicate_kind"] == "same_details"
    assert body["override_allowed"] is True
    assert body["existing_notice"]["id"] == first["id"]
    assert body["existing_notice"]["source_kind"] == "legacy_attachment"
    assert body["existing_notice"]["matter_id"] == matter_id
    with get_session_factory()() as session:
        stored = session.get(MatterAttachment, other["id"])
        assert stored is not None
        assert stored.notice_subject == "Second demand"

    allowed = patch(
        other["id"], notice_subject="Demand for unpaid invoices", allow_duplicate=True
    )
    assert allowed.status_code == 200, allowed.text
    overrides = _audit_metadata(company_id, "matter_attachment.notice_duplicate_override")
    assert overrides[-1]["existing_notice_id"] == first["id"]
    assert overrides[-1]["operation"] == "metadata_update"
    # Unrelated edits on the overridden pair (Mark reply sent) still save.
    marked = patch(other["id"], notice_reply_sent=True, notice_reply_sent_on=TODAY.isoformat())
    assert marked.status_code == 200, marked.text

    # A plain document reclassified as a notice is checked for identical bytes.
    body_bytes = b"identical notice bytes 2026-11-28"
    third = _upload(
        client, token, matter_id, _sent_form(notice_subject="Bytes notice"), body=body_bytes
    )
    assert third.status_code == 200, third.text
    plain = _upload(client, token, matter_id, {"document_type": "correspondence"}, body=body_bytes)
    assert plain.status_code == 200, plain.text
    reclassified = patch(
        plain.json()["id"],
        document_type="notice",
        notice_direction="sent",
        notice_document_role="notice",
        notice_type="Recovery notice",
        notice_subject="A different subject",
        notice_sent_on=RECEIVED,
        notice_authority="Someone else",
        allow_duplicate=True,
    )
    assert reclassified.status_code == 409, reclassified.text
    assert reclassified.json()["duplicate_kind"] == "same_file"
    assert reclassified.json()["existing_notice"]["id"] == third.json()["id"]


def test_register_and_matter_notices_are_compared_with_each_other(client: TestClient) -> None:
    """One notice must not be entered once on the matter and again in the register."""

    from tests.test_notices import _invite

    boot = _bootstrap(client, "nv-cross-store")
    token = str(boot["access_token"])
    matter_id = _matter(client, token)
    attached = _primary_notice(client, token, matter_id, _received_form())
    same_details = _register_payload(
        subject="Demand for unpaid invoices",
        received_from="Opposing counsel",
        matter_ids=[matter_id],
    )

    # Register create, against a matter-attached notice anywhere in the company.
    for payload in (same_details, {**same_details, "matter_ids": []}):
        refused = client.post("/api/notices/", headers=_auth(token), json=payload)
        assert refused.status_code == 409, refused.text
        existing = refused.json()["existing_notice"]
        assert existing["id"] == attached["id"]
        assert existing["source_kind"] == "legacy_attachment"
        assert existing["matter_id"] == matter_id
        # The register dialog opens the matched notice by this ID.
        opened = client.get(f"/api/notices/{existing['id']}", headers=_auth(token))
        assert opened.status_code == 200, opened.text
    assert _register_count(str(boot["company"]["id"])) == 0

    # Register edit into the attached notice's details.
    register_row = client.post(
        "/api/notices/",
        headers=_auth(token),
        json={**same_details, "subject": "Register-only subject"},
    )
    assert register_row.status_code == 201, register_row.text
    linked = register_row.json()
    edit = _register_patch(client, token, linked, subject="Demand for unpaid invoices")
    assert edit.status_code == 409, edit.text
    assert edit.json()["existing_notice"]["id"] == attached["id"]

    # Matter upload and matter edit, against a register notice linked to the matter.
    upload = _upload(
        client, token, matter_id, _received_form(notice_subject="Register-only subject")
    )
    assert upload.status_code == 409, upload.text
    assert upload.json()["existing_notice"]["id"] == linked["id"]
    assert upload.json()["existing_notice"]["source_kind"] == "standalone"
    other = _primary_notice(
        client, token, matter_id, _received_form(notice_subject="Another subject")
    )
    matter_edit = client.patch(
        f"/api/matters/{matter_id}/attachments/{other['id']}/metadata",
        headers=_auth(token),
        json={"notice_subject": "register-only SUBJECT"},
    )
    assert matter_edit.status_code == 409, matter_edit.text
    assert matter_edit.json()["existing_notice"]["id"] == linked["id"]
    # A register notice not linked to a matter is outside that matter's scope.
    unlinked_matter = _matter(client, token)
    elsewhere = _upload(
        client, token, unlinked_matter, _received_form(notice_subject="Register-only subject")
    )
    assert elsewhere.status_code == 200, elsewhere.text

    # A notice on a matter the caller is walled from is never disclosed.
    partner_id, partner_token = _invite(
        client, owner_token=token, slug=str(boot["company"]["slug"]), role="partner"
    )
    walled_matter = _matter(client, token)
    restricted = client.post(
        f"/api/matters/{walled_matter}/access/restricted",
        headers=_auth(token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    wall = client.post(
        f"/api/matters/{walled_matter}/access/walls",
        headers=_auth(token),
        json={"excluded_membership_id": partner_id, "reason": "Duplicate disclosure test"},
    )
    assert wall.status_code == 200, wall.text
    _primary_notice(client, token, walled_matter, _received_form(notice_subject="Walled subject"))
    walled = client.post(
        "/api/notices/",
        headers=_auth(partner_token),
        json=_register_payload(subject="Walled subject", received_from="Opposing counsel"),
    )
    assert walled.status_code == 201, walled.text
