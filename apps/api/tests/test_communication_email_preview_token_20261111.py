from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from caseops_api.schemas.email_templates import EmailRenderResponse, MatterEmailPreviewRequest
from caseops_api.services import communication_email_preview as previews


def _snapshot():
    now = datetime(2026, 11, 11, 12, tzinfo=UTC)
    return dict(
        context=SimpleNamespace(
            company=SimpleNamespace(id="tenant"),
            membership=SimpleNamespace(id="actor"),
            user=SimpleNamespace(id="user"),
        ),
        matter=SimpleNamespace(id="matter", updated_at=now, lifecycle_version=1),
        template=SimpleNamespace(
            id="template",
            updated_at=now,
            subject_template="Subject",
            body_template="Body",
            variables_json=[],
        ),
        payload=MatterEmailPreviewRequest(
            template_id="template", recipient_email="client@example.com"
        ),
        rendered=EmailRenderResponse(
            subject="Subject", body="Body", resolved_variables={"client_name": "Reviewed client"}
        ),
    )


@pytest.mark.parametrize(
    "change",
    [
        "company",
        "membership",
        "user",
        "matter",
        "lifecycle",
        "matter_version",
        "template",
        "template_version",
        "template_text",
        "recipient",
        "recipient_name",
        "subject",
        "body",
        "variables",
        "client",
        "rendered",
        "source",
    ],
)
def test_preview_token_is_bound_to_complete_authority_and_message(monkeypatch, change):
    monkeypatch.setattr(previews, "_now_epoch", lambda: 1000)
    snapshot = _snapshot()
    token, _ = previews.issue_preview_token(**snapshot)
    previews.require_preview_token(token, **snapshot)
    if change in ("company", "membership", "user"):
        getattr(snapshot["context"], change).id = "different"
    elif change == "matter":
        snapshot["matter"].id = "different"
    elif change == "lifecycle":
        snapshot["matter"].lifecycle_version += 1
    elif change == "matter_version":
        snapshot["matter"].updated_at += timedelta(microseconds=1)
    elif change == "template":
        snapshot["template"].id = "different"
    elif change == "template_version":
        snapshot["template"].updated_at += timedelta(microseconds=1)
    elif change == "template_text":
        snapshot["template"].body_template = "Changed"
    elif change == "rendered":
        snapshot["rendered"].body = "Changed rendered message"
    elif change == "source":
        snapshot["rendered"].resolved_variables["client_name"] = "Changed client"
    else:
        field = {"recipient": "recipient_email", "client": "client_id"}.get(change, change)
        value = {"recipient": "other@example.com", "variables": {"note": "changed"}}.get(
            change, "changed"
        )
        snapshot["payload"] = snapshot["payload"].model_copy(update={field: value})
    with pytest.raises(HTTPException) as rejected:
        previews.require_preview_token(token, **snapshot)
    assert rejected.value.status_code == 409


@pytest.mark.parametrize("now,valid", [(1299, True), (1300, False), (1301, False), (994, False)])
def test_preview_expiry_is_bounded(monkeypatch, now, valid):
    monkeypatch.setattr(previews, "_now_epoch", lambda: 1000)
    snapshot = _snapshot()
    token, expires = previews.issue_preview_token(**snapshot)
    assert int(expires.timestamp()) == 1300
    monkeypatch.setattr(previews, "_now_epoch", lambda: now)
    if valid:
        previews.require_preview_token(token, **snapshot)
    else:
        with pytest.raises(HTTPException) as rejected:
            previews.require_preview_token(token, **snapshot)
        assert rejected.value.status_code == 409


@pytest.mark.parametrize(
    "token", ["garbage", "ep1.1.301.hash.\u00e9", "ep1.0.99999999.hash.signature"]
)
def test_untrusted_tokens_fail_closed_without_raw_payload(monkeypatch, token):
    monkeypatch.setattr(previews, "_now_epoch", lambda: 1000)
    with pytest.raises(HTTPException) as rejected:
        previews.require_preview_token(token, **_snapshot())
    assert rejected.value.status_code == 409
