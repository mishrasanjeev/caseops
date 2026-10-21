"""Run-scoped local public-lead fixtures; never shipped in the API image."""

from __future__ import annotations

import json
import os
import re
from atexit import register as register_shutdown
from datetime import UTC, datetime, timedelta

from calendar_oauth_emulator import require_test_environment
from caseops_api.db.models import (
    BillingEnrollment,
    PlatformAdminMembership,
    PlatformReportAdmin,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import billing_demo as demo
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from platform_console_emulator import MARKER, PREFIX, Cleanup, _origin, _run
from platform_report_fixtures import _fixture_environment
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

TARGET = "/api/billing/enrollments/demo-request"
EMAIL = re.compile(r"lead-([0-6])-([0-9a-f-]{36})@example\.com\Z")


class LeadSeed(Cleanup):
    historical_count: int = Field(default=251, ge=251, le=251)


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")
    web_origin: str = Field(min_length=1, max_length=255)


def _root(session, manager_id):
    manager = session.get(PlatformReportAdmin, manager_id)
    if (
        manager is None
        or manager.role != "manager"
        or manager.status not in {"pending", "active"}
    ):
        raise ValueError("Local lead manager is unavailable.")
    root = session.get(PlatformAdminMembership, manager.root_platform_admin_id)
    if root is None:
        raise ValueError("Local lead founder provenance is unavailable.")
    return {
        column.name: getattr(root, column.name) for column in root.__table__.columns
    }


def install_public_lead_emulator(app, capture):
    require_test_environment()
    original_receive = capture.receive
    original_sender = demo._send_via_sendgrid
    blocked_sender = capture.reject_external
    transport = os.environ["CASEOPS_CONSOLE_TEST_MAIL_URL"]
    changes = {
        "CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL": transport,
        "CASEOPS_DEMO_NOTIFICATION_ENABLED": "true",
        "CASEOPS_DEMO_RETENTION_ENABLED": "false",
    }
    previous = {key: os.environ.get(key) for key in changes}
    os.environ.update(changes)
    demo._send_via_sendgrid = blocked_sender

    def context(run_id, request, web_origin=None):
        require_test_environment()
        if request.headers.get("X-CaseOps-Automated-Test") != MARKER:
            raise HTTPException(403, "Canonical automated marker required.")
        try:
            _run(run_id)
            if web_origin is not None and _origin(web_origin) != capture.web_origin:
                raise ValueError("Origin mismatch.")
            state = capture.admit(run_id, MARKER)
            if state["state"] != "ready":
                raise ValueError("Local console run is not ready.")
        except ValueError as exc:
            raise HTTPException(409, "Local lead fixture is not admitted.") from exc
        return state

    def receive(payload):
        if not isinstance(payload, dict) or "lead_id" not in payload:
            return original_receive(payload)
        if set(payload) != {"lead_id", "to", "subject", "body"}:
            raise ValueError("Invalid local lead message shape.")
        identity = _run(payload["lead_id"])
        expected = (
            f"Public enquiry {identity} is saved.\n"
            "Review its details in the protected administrative dashboard: "
            "https://caseops.ai/platform/leads\n"
        )
        if (
            payload["to"] != demo.NOTIFICATION_RECIPIENT
            or payload["subject"] != "CaseOps public enquiry saved"
            or payload["body"] != expected
        ):
            raise ValueError("Only the canonical reference-only message is captured.")
        require_test_environment()
        with get_session_factory()() as session:
            row = session.get(BillingEnrollment, identity)
            match = EMAIL.fullmatch(row.contact_email or "") if row else None
            state = demo._state(row) if row else {}
            if (
                match is None
                or not demo._notification_eligible(row)
                or state.get("automated_request") is not True
                or state.get("notification_status") != "sending"
                or state.get("lease_until", "") <= datetime.now(UTC).isoformat()
            ):
                raise ValueError("No current marked local lead claim.")
            run_id = _run(match[2])
        with capture.lock:
            run = capture.runs.get(run_id, {})
            fixture = run.get("leads", {})
            if (
                run.get("state") != "ready"
                or fixture.get("phase") != "ready"
                or len(fixture["messages"]) >= 7
                or any(item["lead_id"] == identity for item in fixture["messages"])
            ):
                raise ValueError("Local lead capture is closed or duplicated.")
            fixture["messages"].append(
                {
                    "lead_id": identity,
                    "recipient_email": payload["to"],
                    "subject": payload["subject"],
                    "body": payload["body"],
                    "transport": "deterministic_local",
                    "provider_call_performed": False,
                    "automated_request_preserved": True,
                }
            )

    capture.receive = receive

    @app.middleware("http")
    async def local_admission_budget(request, call_next):
        length = request.headers.get("Content-Length", "")
        if (
            request.method == "POST"
            and request.url.path == TARGET
            and length.isdecimal()
            and int(length) <= 16_384
        ):
            try:
                data = json.loads(await request.body())
                match = EMAIL.fullmatch(data.get("contact_email", ""))
            except (ValueError, TypeError, AttributeError):
                match = None
            if match:
                try:
                    context(match[2], request)
                except HTTPException as exc:
                    return JSONResponse(
                        {"detail": exc.detail}, status_code=exc.status_code
                    )
                with capture.lock:
                    fixture = capture.runs[match[2]].get("leads", {})
                    if fixture.get("phase") != "ready":
                        return JSONResponse(
                            {"detail": "Local lead fixture is closed."}, status_code=409
                        )
                    if fixture["requests"] >= 5:
                        return JSONResponse(
                            {"detail": "Rate limit exceeded."}, status_code=429
                        )
                    fixture["requests"] += 1
        return await call_next(request)

    @app.post(
        PREFIX + "/fixtures/{run_id}/leads", include_in_schema=False, status_code=201
    )
    def seed(run_id: str, payload: LeadSeed, request: Request):
        with capture.lock:
            state = context(run_id, request, payload.web_origin)
            if payload.manager_id != state["manager_id"] or "leads" in state:
                raise HTTPException(
                    409, "Lead fixture seed was already attempted or mismatched."
                )
            capture.runs[run_id]["leads"] = {
                "phase": "seeding",
                "messages": [],
                "requests": 0,
            }
        _fixture_environment(
            run_id=run_id, web_origin=payload.web_origin, automated_marker=MARKER
        )
        now = datetime.now(UTC)
        with get_session_factory()() as session:
            founder = _root(session, payload.manager_id)
            rows = [
                BillingEnrollment(
                    is_public_lead=True,
                    contact_name=f"Synthetic retained enquiry {index}",
                    contact_email=f"retained-{index}-{run_id}@example.com",
                    contact_mobile="5550001234",
                    company_name="Synthetic retained practice",
                    segment="solo",
                    source="solo_lawyers",
                    status="converted" if index % 2 else "demo_requested",
                    notes="Synthetic retained enquiry; no historical notification eligibility.",
                    created_at=now - timedelta(days=60, seconds=index),
                    status_timestamps_json={
                        "demo_requested_at": (now - timedelta(days=60)).isoformat()
                    },
                )
                for index in range(payload.historical_count)
            ]
            commercial = BillingEnrollment(
                is_public_lead=False,
                contact_email=f"commercial-{run_id}@example.com",
                segment="firm",
                source="demo",
                notes="Synthetic unrelated commercial enrollment",
            )
            session.add_all([*rows, commercial])
            session.commit()
            identities, excluded = [row.id for row in rows], commercial.id
            if _root(session, payload.manager_id) != founder:
                raise RuntimeError("Lead fixture changed founder authority.")
        with capture.lock:
            capture.runs[run_id]["leads"].update(
                phase="ready",
                historical_ids=identities,
                excluded=excluded,
                manager_id=payload.manager_id,
                founder=founder,
                windows=0,
            )
        return {
            "run_id": run_id,
            "historical_ids": identities,
            "excluded_commercial_id": excluded,
            "transport": "deterministic_local",
            "external_calls": capture.external_calls,
            "automated_marker_required": True,
            "automated_request_preserved": True,
            "production_rate_limit": "5/hour",
            "founder_unchanged": True,
        }

    @app.post(PREFIX + "/fixtures/{run_id}/leads/window", include_in_schema=False)
    def window(run_id: str, payload: Window, request: Request):
        with capture.lock:
            context(run_id, request, payload.web_origin)
            fixture = capture.runs[run_id].get("leads", {})
            if fixture.get("phase") != "ready" or fixture["windows"] >= 4:
                raise HTTPException(409, "Local admission window is unavailable.")
            fixture.update(requests=0, windows=fixture["windows"] + 1)
        return {
            "run_id": run_id,
            "scope": "dedicated_loopback_test_limiter",
            "production_rate_limit": "5/hour",
            "no_paid_marker_preserved": True,
            "external_calls": capture.external_calls,
        }

    @app.get(PREFIX + "/fixtures/{run_id}/leads/mail", include_in_schema=False)
    def mail(run_id: str, request: Request):
        with capture.lock:
            context(run_id, request)
            fixture = capture.runs[run_id].get("leads", {})
            if fixture.get("phase") != "ready":
                raise HTTPException(409, "Local lead mail is unavailable.")
            return {
                "items": [dict(item) for item in fixture["messages"]],
                "external_calls": capture.external_calls,
            }

    @app.post(PREFIX + "/fixtures/{run_id}/leads/drain", include_in_schema=False)
    def drain(run_id: str, payload: Window, request: Request):
        with capture.lock:
            context(run_id, request, payload.web_origin)
            if capture.runs[run_id].get("leads", {}).get("phase") != "ready":
                raise HTTPException(409, "Local lead drain is unavailable.")
        with get_session_factory()() as session:
            identities = list(
                session.scalars(
                    select(BillingEnrollment.id)
                    .where(
                        BillingEnrollment.contact_email.like(
                            f"lead-%-{run_id}@example.com"
                        ),
                    )
                    .limit(8)
                )
            )
        for identity in identities:
            demo.deliver_demo_notification(identity)
        return {
            "run_id": run_id,
            "selected": len(identities),
            "external_calls": capture.external_calls,
        }

    @app.post(PREFIX + "/fixtures/{run_id}/leads/cleanup", include_in_schema=False)
    def cleanup(run_id: str, payload: Cleanup, request: Request):
        with capture.lock:
            context(run_id, request, payload.web_origin)
            fixture = capture.runs[run_id].get("leads", {})
            if (
                fixture.get("phase") != "ready"
                or payload.manager_id != fixture["manager_id"]
            ):
                raise HTTPException(409, "Local lead cleanup is unavailable.")
            fixture["phase"] = "cleaning"
        with get_session_factory()() as session:
            rows = list(
                session.scalars(
                    select(BillingEnrollment)
                    .where(
                        BillingEnrollment.contact_email.like(
                            f"lead-%-{run_id}@example.com"
                        ),
                    )
                    .limit(8)
                )
            )
            pending = sum(
                demo._state(row).get("notification_status")
                in {
                    "pending",
                    "retry_pending",
                    "sending",
                }
                for row in rows
            )
            expected = {*fixture["historical_ids"], fixture["excluded"]}
            retained = (
                set(
                    session.scalars(
                        select(BillingEnrollment.id).where(
                            BillingEnrollment.id.in_(expected),
                        )
                    )
                )
                == expected
            )
            unchanged = _root(session, payload.manager_id) == fixture["founder"]
        if pending or not retained or not unchanged or capture.external_calls:
            raise HTTPException(409, "Local lead closure could not be verified.")
        with capture.lock:
            fixture["phase"] = "cleaned"
        return {
            "run_id": run_id,
            "retained": retained,
            "persisted_verified": True,
            "no_provider_calls": True,
            "founder_unchanged": unchanged,
            "production_rate_limit": "5/hour",
            "pending_fixture_notifications": pending,
        }

    def close():
        capture.receive = original_receive
        if demo._send_via_sendgrid is blocked_sender:
            demo._send_via_sendgrid = original_sender
        for key, value in changes.items():
            if os.environ.get(key) == value:
                if previous[key] is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous[key]

    register_shutdown(close)
    return close
