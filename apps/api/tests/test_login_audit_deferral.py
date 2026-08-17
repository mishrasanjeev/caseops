"""P1-1 — the employee.login audit + last_login write is deferred off
the login hot path into a FastAPI BackgroundTask running on a fresh DB
session.

These tests prove:
  * login still returns 200 with a token (hot path unaffected),
  * authenticate_user no longer performs the write synchronously,
  * the employee.login AuditEvent + EmployeeProfile.last_login_at are
    *eventually* written by the background task (Starlette's TestClient
    runs background tasks after the response, before the call returns),
  * a membership with no EmployeeProfile (e.g. the bootstrap owner)
    still logs in cleanly and the background task no-ops.
"""
from __future__ import annotations

import inspect

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.api.routes import auth as auth_routes
from caseops_api.db.models import AuditEvent, EmployeeProfile
from caseops_api.db.session import get_session_factory
from caseops_api.services.employees import record_employee_login_async
from caseops_api.services.identity import authenticate_user
from tests.test_auth_company import auth_headers, bootstrap_company

_SLUG = "aster-legal"  # bootstrap_company's fixed slug


def test_login_releases_identity_fence_before_registering_background_audit() -> None:
    """Keep the request/background transaction boundary explicit.

    FastAPI closes yielded dependencies only after Starlette finishes response
    BackgroundTasks. Registering the fresh-session audit while the login
    Membership/User fence is still open creates a cross-session self-deadlock
    that SQLite cannot reproduce, so preserve the exact ordering in source as
    a fast companion to the real PostgreSQL lock regression.
    """

    source = inspect.getsource(auth_routes.login)

    assert source.index("session.commit()") < source.index("background.add_task(")


def _create_employee(client: TestClient, owner_token: str, email: str) -> str:
    resp = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Deferred Audit Employee",
            "email": email,
            "role": "member",
            "password": "EmployeePass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["membership_id"]


def test_login_succeeds_and_defers_employee_login_write(
    client: TestClient,
) -> None:
    owner_token = str(bootstrap_company(client)["access_token"])
    email = "deferred@asterlegal.in"
    membership_id = _create_employee(client, owner_token, email)

    # Pre-state: no employee.login audit yet for this membership.
    factory = get_session_factory()
    with factory() as s:
        pre = s.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "employee.login",
                AuditEvent.actor_membership_id == membership_id,
            )
        )
        assert pre is None

    login = client.post(
        "/api/auth/login",
        json={"company_slug": _SLUG, "email": email, "password": "EmployeePass123!"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]

    # Starlette TestClient runs BackgroundTasks before returning, so by
    # now the deferred write must have landed — on its own session.
    with factory() as s:
        ev = s.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "employee.login",
                AuditEvent.actor_membership_id == membership_id,
            )
        )
        assert ev is not None, "deferred employee.login audit was not written"
        prof = s.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.membership_id == membership_id
            )
        )
        assert prof is not None
        assert prof.last_login_at is not None, "last_login_at not stamped"


def test_authenticate_user_does_not_write_synchronously(
    client: TestClient,
) -> None:
    """Genuine deferral proof — independent of TestClient's
    background-task behavior. Calling authenticate_user directly must
    perform NO audit/last_login write (hot path is read-only after
    password verification). Only record_employee_login_async does it."""
    owner_token = str(bootstrap_company(client)["access_token"])
    email = "sync-proof@asterlegal.in"
    membership_id = _create_employee(client, owner_token, email)
    factory = get_session_factory()

    # Call the hot-path function directly.
    with factory() as s:
        auth = authenticate_user(
            s, email=email, password="EmployeePass123!", company_slug=_SLUG
        )
        assert auth.access_token
        # Same session: authenticate_user must not have flushed/written
        # an employee.login row, and must not have stamped last_login.
        assert (
            s.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "employee.login",
                    AuditEvent.actor_membership_id == membership_id,
                )
            )
            is None
        )

    # Independent fresh session: still nothing (authenticate_user did
    # not commit anything either).
    with factory() as s:
        assert (
            s.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "employee.login",
                    AuditEvent.actor_membership_id == membership_id,
                )
            )
            is None
        )
        prof = s.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.membership_id == membership_id
            )
        )
        assert prof is not None and prof.last_login_at is None

    # The deferred entrypoint (what the BackgroundTask runs) DOES write.
    record_employee_login_async(membership_id)

    with factory() as s:
        assert (
            s.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "employee.login",
                    AuditEvent.actor_membership_id == membership_id,
                )
            )
            is not None
        )
        prof = s.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.membership_id == membership_id
            )
        )
        assert prof is not None and prof.last_login_at is not None


def test_login_without_employee_profile_still_succeeds(
    client: TestClient,
) -> None:
    """The bootstrap owner has no EmployeeProfile. Login must still 200
    and the background task must no-op without error (record_employee_login
    early-returns when profile is None)."""
    bootstrap_company(client)
    # bootstrap_company's fixed owner credentials.
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": _SLUG,
            "email": "owner@asterlegal.in",
            "password": "FoundersPass123!",
        },
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]
