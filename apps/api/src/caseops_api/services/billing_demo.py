"""Public admissions and an enrollment-owned outbox; no synthetic tenant authority."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.db.models import BillingAdminNote, BillingEnrollment
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.saas_billing import DemoRequest, DemoRequestResponse
from caseops_api.services.sendgrid_transport import _send_via_sendgrid

logger = logging.getLogger(__name__)
RETENTION_DAYS = 90
MAX_ATTEMPTS = 8
ADMISSION_CONTRACT = "seo_demo_20261009"
NOTIFICATION_PURPOSE = "public_lead_20261021"
NOTIFICATION_POLICY = "owner_public_enquiries_v1"
NOTIFICATION_RECIPIENT = "sanjeev@orchestrum.in"


class NotificationRejected(Exception):
    def __init__(self, *, retryable: bool = False):
        self.retryable = retryable
        super().__init__("provider_rate_limited" if retryable else "provider_rejected")


class NotificationFenceClosed(Exception):
    pass


class NotificationPaused(Exception):
    pass


class NotificationConfigurationUnavailable(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _notification_enabled() -> bool:
    # Purpose approved by the owner on 2026-10-21; deployment still opts in.
    return os.environ.get("CASEOPS_DEMO_NOTIFICATION_ENABLED", "false").lower() == "true"


def _retention_enabled() -> bool:
    return os.environ.get("CASEOPS_DEMO_RETENTION_ENABLED", "false").lower() == "true"


def _local_notification_adapter() -> str | None:
    adapter = os.environ.get("CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL", "").strip()
    if not adapter:
        return None
    from caseops_api.core.settings import get_settings
    from caseops_api.services.platform_console import _test_mail_ready

    settings = get_settings()
    if (
        settings.env != "e2e"
        or not paid_providers_blocked_for_request()
        or (settings.sendgrid_api_key or "").strip()
        or not _test_mail_ready(settings, adapter)
    ):
        raise NotificationFenceClosed
    return adapter


def _notification_eligible(row: BillingEnrollment) -> bool:
    state = _state(row)
    # Only the fresh-admission constructor can grant this cohort. Reading,
    # replaying, retrying or migrating a retained request never upgrades it.
    return bool(
        row.is_public_lead
        and state.get("notification_purpose") == NOTIFICATION_PURPOSE
        and state.get("notification_policy") == NOTIFICATION_POLICY
        and state.get("notification_eligible") is True
    )


def _state(row: BillingEnrollment) -> dict:
    outer = row.status_timestamps_json
    state = outer.get("demo_admission") if isinstance(outer, dict) else None
    return dict(state) if isinstance(state, dict) else {}


def _save(row: BillingEnrollment, state: dict) -> None:
    row.status_timestamps_json = {**(row.status_timestamps_json or {}), "demo_admission": state}


def admit_demo(
    session: Session, payload: DemoRequest, *, automated: bool = False
) -> DemoRequestResponse:
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
    eligible = _notification_enabled()
    automated = automated or paid_providers_blocked_for_request()
    row = BillingEnrollment(
        id=identity,
        contact_name=payload.contact_name,
        contact_email=values["contact_email"],
        contact_mobile=payload.contact_mobile,
        company_name=payload.company_name,
        segment=payload.segment,
        selected_plan=payload.selected_plan,
        source=entry_point,
        is_public_lead=True,
        created_at=now,
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
                "notification_status": "pending" if eligible else "not_requested",
                "notification_purpose": NOTIFICATION_PURPOSE,
                "notification_policy": NOTIFICATION_POLICY,
                "notification_eligible": eligible,
                "notification_admitted_at": now.isoformat(),
                "automated_request": automated,
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


def _send_notification(enrollment_id: str, *, claim: str) -> None:
    from caseops_api.core.settings import get_settings

    adapter = _local_notification_adapter()
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, enrollment_id)
        state = _state(row) if row else {}
        if (
            row is None
            or not _notification_eligible(row)
            or (
                (state.get("automated_request") or paid_providers_blocked_for_request())
                and not adapter
            )
            or (adapter and state.get("automated_request") is not True)
            or state.get("notification_status") != "sending"
            or state.get("claim") != claim
            or state.get("lease_until", "") <= _now().isoformat()
        ):
            raise NotificationFenceClosed
        body = (
            f"Public enquiry {row.id} is saved.\n"
            "Review its details in the protected administrative dashboard: "
            "https://caseops.ai/platform/leads\n"
        )
    # Never retain a database session/transaction while calling the provider.
    if not _notification_enabled():
        raise NotificationPaused
    if adapter:
        response = httpx.post(
            adapter,
            json={
                "lead_id": enrollment_id,
                "to": NOTIFICATION_RECIPIENT,
                "subject": "CaseOps public enquiry saved",
                "body": body,
            },
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        )
        if response.status_code == 202:
            return
        if response.status_code >= 500:
            raise TimeoutError("transport_outcome_unknown")
        raise NotificationRejected(retryable=response.status_code == 429)
    settings = get_settings()
    if not (settings.sendgrid_api_key or "").strip() or not settings.sendgrid_sender_email:
        raise NotificationConfigurationUnavailable
    accepted, _, error = _send_via_sendgrid(
        to_email=NOTIFICATION_RECIPIENT,
        recipient_name=None,
        subject="CaseOps public enquiry saved",
        body_text=body,
        custom_args={"public_lead_id": enrollment_id},
    )
    if not accepted:
        # Consume only a fixed HTTP status, never retain provider response text.
        code = re.match(r"^sendgrid ([0-9]{3}):", error or "")
        if not code or int(code[1]) >= 500:
            raise TimeoutError("transport_outcome_unknown")
        raise NotificationRejected(retryable=bool(code and code[1] == "429"))


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
        if not state or not _notification_eligible(row):
            return
        # A marked replay cannot alter a human admission's durable obligation.
        if paid_providers_blocked_for_request() and state.get("automated_request") is not True:
            return
        if state.get("notification_status") not in {"pending", "retry_pending", "sending"}:
            return
        if (
            state["next_attempt_at"] > now.isoformat()
            or state.get("lease_until", "") > now.isoformat()
        ):
            return
        if state["notification_status"] == "sending":
            state.update(notification_status="outcome_unknown", last_error_code="claim_expired")
            state.pop("claim", None)
            state.pop("lease_until", None)
            _save(row, state)
            session.commit()
            return
        try:
            adapter = _local_notification_adapter()
        except NotificationFenceClosed:
            state.update(
                notification_status="exhausted", last_error_code="test_transport_not_admitted"
            )
            _save(row, state)
            session.commit()
            return
        if (state.get("automated_request") or paid_providers_blocked_for_request()) and not adapter:
            state.update(
                notification_status="exhausted", last_error_code="automated_request_blocked"
            )
            _save(row, state)
            session.commit()
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
        previous_status, previous_attempts = state["notification_status"], state["attempts"]
        state.update(
            notification_status="sending",
            claim=claim,
            lease_until=(now + timedelta(seconds=60)).isoformat(),
            attempts=state["attempts"] + 1,
        )
        changed = session.execute(
            update(BillingEnrollment)
            .where(
                BillingEnrollment.id == enrollment_id,
                BillingEnrollment.is_public_lead.is_(True),
                BillingEnrollment.status_timestamps_json["demo_admission"][
                    "notification_status"
                ].as_string()
                == previous_status,
                BillingEnrollment.status_timestamps_json["demo_admission"]["attempts"].as_integer()
                == previous_attempts,
                BillingEnrollment.status_timestamps_json["demo_admission"]["notification_eligible"]
                .as_boolean()
                .is_(True),
                BillingEnrollment.status_timestamps_json["demo_admission"][
                    "notification_policy"
                ].as_string()
                == NOTIFICATION_POLICY,
                BillingEnrollment.status_timestamps_json["demo_admission"][
                    "notification_purpose"
                ].as_string()
                == NOTIFICATION_PURPOSE,
                BillingEnrollment.status_timestamps_json["demo_admission"]["automated_request"]
                .as_boolean()
                .is_(bool(state.get("automated_request"))),
            )
            .values(
                status_timestamps_json={
                    **(row.status_timestamps_json or {}),
                    "demo_admission": state,
                }
            ),
            execution_options={"synchronize_session": False},
        )
        session.commit()
        if changed.rowcount != 1:
            return
    # The durable claim is committed and its session closed before transport.
    error, outcome = None, "sent"
    try:
        _send_notification(enrollment_id, claim=claim)
    except NotificationPaused:
        error, outcome = "sender_approval_pending", "retry_pending"
    except NotificationFenceClosed:
        error, outcome = "transport_fence_closed", "outcome_unknown"
    except NotificationRejected as exc:
        error = "provider_rate_limited" if exc.retryable else "provider_rejected"
        outcome = "retry_pending" if exc.retryable else "exhausted"
    except (httpx.HTTPError, TimeoutError, OSError):
        error, outcome = "transport_outcome_unknown", "outcome_unknown"
    except NotificationConfigurationUnavailable:
        error, outcome = "configuration_unavailable", "retry_pending"
    except Exception:
        error, outcome = "transport_outcome_unknown", "outcome_unknown"
    with factory() as session:
        row = session.scalar(
            select(BillingEnrollment).where(BillingEnrollment.id == enrollment_id).with_for_update()
        )
        if row is None:
            return
        state = _state(row)
        if (
            state.get("claim") != claim
            or state.get("notification_status") != "sending"
            or state.get("lease_until", "") <= _now().isoformat()
            or not _notification_eligible(row)
        ):
            return
        state.pop("claim", None)
        state.pop("lease_until", None)
        state.update(notification_status=outcome, last_error_code=error)
        if error and outcome == "retry_pending":
            state["next_attempt_at"] = (
                _now() + timedelta(seconds=min(3600, 60 * 2 ** min(state["attempts"], 6)))
            ).isoformat()
            if state["attempts"] >= MAX_ATTEMPTS:
                state["notification_status"] = "exhausted"
            logger.warning(
                "demo_notification_deferred",
                extra={"enrollment_id": enrollment_id, "error_code": error},
            )
        session.execute(
            update(BillingEnrollment)
            .where(
                BillingEnrollment.id == enrollment_id,
                BillingEnrollment.status_timestamps_json["demo_admission"]["claim"].as_string()
                == claim,
                BillingEnrollment.status_timestamps_json["demo_admission"][
                    "notification_status"
                ].as_string()
                == "sending",
                BillingEnrollment.status_timestamps_json["demo_admission"]["notification_eligible"]
                .as_boolean()
                .is_(True),
                BillingEnrollment.status_timestamps_json["demo_admission"][
                    "notification_policy"
                ].as_string()
                == NOTIFICATION_POLICY,
                BillingEnrollment.status_timestamps_json["demo_admission"][
                    "notification_purpose"
                ].as_string()
                == NOTIFICATION_PURPOSE,
                BillingEnrollment.status_timestamps_json["demo_admission"][
                    "lease_until"
                ].as_string()
                > _now().isoformat(),
            )
            .values(
                status_timestamps_json={
                    **(row.status_timestamps_json or {}),
                    "demo_admission": state,
                }
            ),
            execution_options={"synchronize_session": False},
        )
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
                    BillingEnrollment.is_public_lead.is_(True),
                    state["notification_purpose"].as_string() == NOTIFICATION_PURPOSE,
                    state["notification_policy"].as_string() == NOTIFICATION_POLICY,
                    state["notification_eligible"].as_boolean().is_(True),
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
