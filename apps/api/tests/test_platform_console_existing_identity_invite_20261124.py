"""Report-console invitation for an invitee who already has a CaseOps identity.

Production 2026-11-24: an invitee repeatedly received 401 from
/auth/invitations/complete on fresh links. The backend requires an existing
identity's *current* password, but the setup page asked for a new password and
reported every mismatch as an invalid link. The page now inspects the link
first (without consuming it), and a wrong existing password is a distinct,
audited failure that leaves the link usable.
"""

import pytest
from sqlalchemy import select

from caseops_api.core.console_auth import CONSOLE_SESSION_COOKIE
from caseops_api.db.models import PlatformConsoleToken, PlatformReportAuditEvent, User
from caseops_api.db.session import get_session_factory
from caseops_api.services import platform_console as console
from tests import test_platform_console as old

OWNER_EMAIL = "owner@asterlegal.in"
OWNER_PASSWORD = "FoundersPass123!"


@pytest.fixture
def report_console(client, monkeypatch):
    return old.report_console.__wrapped__(client, monkeypatch)


def _inspect(client, token):
    return client.post(old.BASE + "/auth/invitations/inspect", json={"token": token})


def _token_row(raw):
    with get_session_factory()() as session:
        return session.scalar(
            select(PlatformConsoleToken).where(
                PlatformConsoleToken.token_hash == console._digest(raw)
            )
        )


def _manager_invites(data, email):
    old._manager(data)
    old._invite(data, email)
    token = old._link(data["messages"])
    data["client"].cookies.clear()
    return token


def test_existing_identity_is_told_to_use_current_password_and_link_survives_mismatch(
    report_console,
):
    data = report_console
    client = data["client"]
    token = _manager_invites(data, OWNER_EMAIL)
    with get_session_factory()() as session:
        before = session.get(User, data["tenant"]["user"]["id"])
        before_hash, before_name = before.password_hash, before.full_name

    inspected = _inspect(client, token)
    assert inspected.status_code == 200
    assert inspected.json() == {"account": "existing", "email": OWNER_EMAIL}
    assert inspected.headers["Cache-Control"] == "private, no-store"
    assert CONSOLE_SESSION_COOKIE not in client.cookies
    assert _token_row(token).consumed_at is None

    # The original failure: a "new" password typed into the old form.
    wrong = client.post(old.BASE + "/auth/invitations/complete", json={
        "token": token, "password": old.PASSWORD, "full_name": "Someone Else",
    })
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "console_invitation_password_invalid"
    assert "current password" in wrong.json()["detail"]
    assert _token_row(token).consumed_at is None
    with get_session_factory()() as session:
        denied = session.scalars(
            select(PlatformReportAuditEvent).where(
                PlatformReportAuditEvent.action == "console.invitation_completed",
                PlatformReportAuditEvent.result == "denied",
            )
        ).all()
        assert [row.reason for row in denied] == ["existing_password_mismatch"]

    # Same link, current password, no name field: accepted.
    assert _inspect(client, token).json()["account"] == "existing"
    accepted = client.post(old.BASE + "/auth/invitations/complete", json={
        "token": token, "password": OWNER_PASSWORD,
    })
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["state"] == "mfa_enrollment_required"
    assert _token_row(token).consumed_at is not None
    with get_session_factory()() as session:
        after = session.get(User, data["tenant"]["user"]["id"])
        assert (after.password_hash, after.full_name) == (before_hash, before_name)

    # A used link is reported as used, by both endpoints.
    client.cookies.clear()
    assert _inspect(client, token).json()["code"] == "console_link_invalid"
    replay = client.post(old.BASE + "/auth/invitations/complete", json={
        "token": token, "password": OWNER_PASSWORD,
    })
    assert replay.status_code == 401
    assert replay.json()["code"] == "console_link_invalid"


def test_new_identity_inspects_as_new_and_requires_a_name(report_console):
    data = report_console
    client = data["client"]
    token = _manager_invites(data, "fresh.viewer@console.example")

    inspected = _inspect(client, token)
    assert inspected.status_code == 200
    assert inspected.json() == {"account": "new", "email": "fresh.viewer@console.example"}

    nameless = client.post(old.BASE + "/auth/invitations/complete", json={
        "token": token, "password": old.PASSWORD,
    })
    assert nameless.status_code == 422
    assert nameless.json()["code"] == "console_validation_failed"
    assert _token_row(token).consumed_at is None

    old._accept(client, token)
    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.email == "fresh.viewer@console.example"))
        assert user.full_name == "Report User"


def test_inspect_rejects_unknown_superseded_and_non_invite_links(report_console):
    data = report_console
    client = data["client"]
    original = _manager_invites(data, "second.viewer@console.example")
    assert _inspect(client, "x" * 43).json()["code"] == "console_link_invalid"
    assert _inspect(client, "x" * 43).status_code == 401

    # An invitee-requested resend supersedes the earlier link.
    with get_session_factory()() as session:
        token = _token_row(original)
        session.execute(
            PlatformConsoleToken.__table__.update()
            .where(PlatformConsoleToken.id == token.id)
            .values(created_at=token.created_at.replace(year=token.created_at.year - 1))
        )
        session.commit()
    assert client.post(old.BASE + "/auth/invitations/resend", json={
        "email": "second.viewer@console.example",
    }).status_code == 200
    replacement = old._link(data["messages"])
    assert replacement != original
    assert _inspect(client, original).status_code == 401
    assert _inspect(client, replacement).json()["account"] == "new"
    # Inspection is read-only even when repeated.
    assert _inspect(client, replacement).status_code == 200
    assert _token_row(replacement).consumed_at is None
