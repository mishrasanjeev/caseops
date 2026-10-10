"""Public admissions and an enrollment-owned outbox; no synthetic tenant authority."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import BillingAdminNote, BillingEnrollment
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.saas_billing import DemoRequest, DemoRequestResponse

logger = logging.getLogger(__name__)
RETENTION_DAYS = 90
MAX_ATTEMPTS = 8
ADMISSION_CONTRACT = "seo_demo_20261009"


def _now() -> datetime:
    return datetime.now(UTC)


def _notification_enabled() -> bool:
    # Existing credentials are not approval to activate this new sender purpose.
    return os.environ.get("CASEOPS_DEMO_NOTIFICATION_ENABLED", "false").lower() == "true"


def _retention_enabled() -> bool:
    return os.environ.get("CASEOPS_DEMO_RETENTION_ENABLED", "false").lower() == "true"


def _state(row: BillingEnrollment) -> dict:
    return dict((row.status_timestamps_json or {}).get("demo_admission", {}))


def _save(row: BillingEnrollment, state: dict) -> None:
    row.status_timestamps_json = {**(row.status_timestamps_json or {}), "demo_admission": state}


def admit_demo(session: Session, payload: DemoRequest) -> DemoRequestResponse:
    identity = str(payload.idempotency_key or uuid4())
    qualified = payload.idempotency_key is not None
    entry_point = payload.source if qualified else "legacy_api"
    values = payload.model_dump(mode="json", exclude={"idempotency_key"})
    values["contact_email"] = str(payload.contact_email).lower()
    if not qualified:
        values["source"] = "legacy_api"
    fingerprint = hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    def replay(row: BillingEnrollment) -> DemoRequestResponse:
        if _state(row).get("request_sha256") != fingerprint:
            raise HTTPException(409, "This request key was already used for different details.")
        return DemoRequestResponse(id=row.id, status="demo_requested")

    existing = session.get(BillingEnrollment, identity)
    if existing is not None:
        return replay(existing)
    now = _now()
    row = BillingEnrollment(
        id=identity,
        contact_name=payload.contact_name,
        contact_email=values["contact_email"],
        contact_mobile=payload.contact_mobile,
        company_name=payload.company_name,
        segment=payload.segment,
        selected_plan=payload.selected_plan,
        source=entry_point,
        notes=payload.notes,
        status="demo_requested",
        utm_json={
            "entry_point": entry_point,
            "role": payload.role if qualified else "not_specified",
            "intent": payload.intent if qualified else "not_specified",
            "privacy_notice_version": payload.privacy_notice_version if qualified else None,
            "attribution_qualified": qualified,
        },
        status_timestamps_json={
            "demo_requested_at": now.isoformat(),
            "demo_admission": {
                "contract_version": ADMISSION_CONTRACT if qualified else "legacy_public_demo_v1",
                "request_sha256": fingerprint,
                "notification_status": "pending",
                "attempts": 0,
                "next_attempt_at": now.isoformat(),
                "expires_at": (now + timedelta(days=RETENTION_DAYS)).isoformat()
                if qualified
                else None,
            },
        },
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.get(BillingEnrollment, identity)
        if existing is None:
            raise
        return replay(existing)
    return DemoRequestResponse(id=identity, status="demo_requested")


def _send_notification(enrollment_id: str) -> None:
    user, password = os.environ.get("CASEOPS_SMTP_USER"), os.environ.get("CASEOPS_SMTP_PASSWORD")
    if not user or not password:
        raise ValueError("notification_configuration_unavailable")
    port = int(os.environ.get("CASEOPS_SMTP_PORT", "465"))
    host = os.environ.get("CASEOPS_SMTP_HOST", "smtp.gmail.com")
    message = EmailMessage()
    message["From"] = user
    message["To"] = os.environ.get("CASEOPS_DEMO_NOTIFY_TO", "sanjeev@orchestrum.in")
    message["Subject"] = "CaseOps demo request saved"
    message["Message-ID"] = f"<demo-{enrollment_id}@caseops.ai>"
    message.set_content(
        f"Enrollment {enrollment_id} is saved. Review it in the protected platform-admin workspace: https://caseops.ai/app/platform-admin\n"
    )
    transport = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    context = ssl.create_default_context()
    tls_options = {"context": context} if port == 465 else {}
    with transport(host, port, timeout=8, **tls_options) as smtp:
        if port != 465:
            smtp.starttls(context=context)
        smtp.login(user, password)
        smtp.send_message(message)


def deliver_demo_notification(enrollment_id: str) -> None:
    factory = get_session_factory()
    now, claim = _now(), str(uuid4())
    with factory() as session:
        row = session.scalar(
            select(BillingEnrollment).where(BillingEnrollment.id == enrollment_id).with_for_update()
        )
        if row is None:
            return
        state = _state(row)
        if not state or state["notification_status"] in {"sent", "exhausted"}:
            return
        if (
            state["next_attempt_at"] > now.isoformat()
            or state.get("lease_until", "") > now.isoformat()
        ):
            return
        if not _notification_enabled():
            state.update(
                last_error_code="sender_approval_pending",
                next_attempt_at=(now + timedelta(minutes=5)).isoformat(),
            )
            _save(row, state)
            session.commit()
            return
        if state["attempts"] >= MAX_ATTEMPTS:
            state.update(notification_status="exhausted", last_error_code="attempt_limit")
            state.pop("claim", None)
            state.pop("lease_until", None)
            _save(row, state)
            session.commit()
            return
        state.update(
            notification_status="sending",
            claim=claim,
            lease_until=(now + timedelta(seconds=60)).isoformat(),
            attempts=state["attempts"] + 1,
        )
        _save(row, state)
        session.commit()
    # The durable claim is committed and its session closed before transport.
    error = None
    try:
        _send_notification(enrollment_id)
    except TimeoutError:
        error = "timeout"
    except smtplib.SMTPException:
        error = "smtp_failure"
    except ValueError:
        error = "configuration_unavailable"
    except Exception:
        error = "transport_failure"
    with factory() as session:
        row = session.scalar(
            select(BillingEnrollment).where(BillingEnrollment.id == enrollment_id).with_for_update()
        )
        if row is None:
            return
        state = _state(row)
        if state.get("claim") != claim:
            return
        state.pop("claim", None)
        state.pop("lease_until", None)
        state.update(
            notification_status="sent" if error is None else "retry_pending", last_error_code=error
        )
        if error:
            state["next_attempt_at"] = (
                _now() + timedelta(seconds=min(3600, 60 * 2 ** min(state["attempts"], 6)))
            ).isoformat()
            if state["attempts"] >= MAX_ATTEMPTS:
                state["notification_status"] = "exhausted"
            logger.warning(
                "demo_notification_deferred",
                extra={"enrollment_id": enrollment_id, "error_code": error},
            )
        _save(row, state)
        session.commit()


def drain_demo_notifications(*, limit: int = 25) -> dict[str, int]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    with get_session_factory()() as session:
        state = BillingEnrollment.status_timestamps_json["demo_admission"]
        ids = list(
            session.scalars(
                select(BillingEnrollment.id)
                .where(
                    state["notification_status"]
                    .as_string()
                    .in_(["pending", "retry_pending", "sending"]),
                    state["next_attempt_at"].as_string() <= _now().isoformat(),
                    or_(
                        state["lease_until"].as_string().is_(None),
                        state["lease_until"].as_string() <= _now().isoformat(),
                    ),
                )
                .order_by(BillingEnrollment.created_at, BillingEnrollment.id)
                .limit(limit)
            )
        )
    for identity in ids:
        deliver_demo_notification(identity)
    return {"selected": len(ids)}


def purge_expired_demo_leads(*, limit: int = 100) -> dict[str, int]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not _retention_enabled():
        return {"deleted": 0, "policy_enabled": False}
    with get_session_factory()() as session:
        rows = list(
            session.scalars(
                select(BillingEnrollment)
                .where(
                    BillingEnrollment.company_id.is_(None),
                    BillingEnrollment.status == "demo_requested",
                    BillingEnrollment.status_timestamps_json["demo_admission"][
                        "contract_version"
                    ].as_string()
                    == ADMISSION_CONTRACT,
                    BillingEnrollment.utm_json["privacy_notice_version"].as_string()
                    == "2026-10-09",
                    ~select(BillingAdminNote.id)
                    .where(BillingAdminNote.enrollment_id == BillingEnrollment.id)
                    .exists(),
                    BillingEnrollment.status_timestamps_json["demo_admission"][
                        "expires_at"
                    ].as_string()
                    < _now().isoformat(),
                )
                .order_by(BillingEnrollment.created_at, BillingEnrollment.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            session.delete(row)
        session.commit()
    return {"deleted": len(rows)}


if __name__ == "__main__":
    print(
        json.dumps(
            {"retention": purge_expired_demo_leads(), "notifications": drain_demo_notifications()}
        )
    )
