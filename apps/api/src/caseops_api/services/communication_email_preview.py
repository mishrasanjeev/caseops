"""Short-lived approval of the exact rendered email, never of client-supplied facts."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from fastapi import HTTPException

from caseops_api.core.settings import get_settings
from caseops_api.db.models import EmailTemplate, Matter
from caseops_api.schemas.email_templates import EmailRenderResponse, MatterEmailPreviewRequest
from caseops_api.services.session_context import SessionContext

PREVIEW_TTL_SECONDS = 300
_DOMAIN = b"caseops.matter-email-preview.v1\x00"


def _now_epoch() -> int:
    return int(time.time())


def _fingerprint(
    *,
    context: SessionContext,
    matter: Matter,
    template: EmailTemplate | None,
    payload: MatterEmailPreviewRequest,
    rendered: EmailRenderResponse,
) -> str:
    snapshot = {
        "company_id": context.company.id,
        "membership_id": context.membership.id,
        "user_id": context.user.id,
        "matter": {
            "id": matter.id,
            "updated_at": matter.updated_at.isoformat(),
            "lifecycle_version": matter.lifecycle_version,
        },
        "template": {
            "id": template.id,
            "updated_at": template.updated_at.isoformat(),
            "subject": template.subject_template,
            "body": template.body_template,
            "variables": template.variables_json,
        }
        if template
        else None,
        "request": payload.model_dump(mode="json", exclude={"preview_token"}),
        "rendered": {
            "subject": rendered.subject,
            "body": rendered.body,
            "matter_values": rendered.resolved_variables,
            "missing": rendered.missing_variables,
            "invalid": rendered.invalid_placeholders,
        },
    }
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _signature(body: str) -> str:
    return hmac.new(
        get_settings().auth_secret.encode("utf-8"),
        _DOMAIN + body.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def issue_preview_token(
    *,
    context: SessionContext,
    matter: Matter,
    template: EmailTemplate | None,
    payload: MatterEmailPreviewRequest,
    rendered: EmailRenderResponse,
) -> tuple[str, datetime]:
    issued = _now_epoch()
    expires = issued + PREVIEW_TTL_SECONDS
    fingerprint = _fingerprint(
        context=context,
        matter=matter,
        template=template,
        payload=payload,
        rendered=rendered,
    )
    body = f"ep1.{issued}.{expires}.{fingerprint}"
    return f"{body}.{_signature(body)}", datetime.fromtimestamp(expires, UTC)


def require_preview_token(
    token: str,
    *,
    context: SessionContext,
    matter: Matter,
    template: EmailTemplate | None,
    payload: MatterEmailPreviewRequest,
    rendered: EmailRenderResponse,
) -> None:
    try:
        prefix, issued_text, expires_text, fingerprint, signature = token.split(".")
        body = ".".join((prefix, issued_text, expires_text, fingerprint))
        issued, expires = int(issued_text), int(expires_text)
        now = _now_epoch()
        expected = _fingerprint(
            context=context,
            matter=matter,
            template=template,
            payload=payload,
            rendered=rendered,
        )
        valid = (
            prefix == "ep1"
            and expires - issued == PREVIEW_TTL_SECONDS
            and issued <= now + 5
            and now < expires
            and hmac.compare_digest(signature, _signature(body))
            and hmac.compare_digest(fingerprint, expected)
        )
    except (ValueError, TypeError, UnicodeError):
        valid = False
    if not valid:
        raise HTTPException(
            status_code=409,
            detail=(
                "Email preview expired or changed. Preview the current message and "
                "recipient again before sending. No email was sent."
            ),
        )
