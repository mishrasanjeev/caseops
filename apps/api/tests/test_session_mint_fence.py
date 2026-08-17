from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.security import decode_access_token, hash_password
from caseops_api.db.models import CompanyMembership
from caseops_api.db.session import get_session_factory
from caseops_api.services import identity as identity_service
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    lock_user_for_membership_deactivation,
)
from tests.test_auth_company import auth_headers, bootstrap_company


def test_login_final_fence_rechecks_password_after_reset_wins(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    factory = get_session_factory()
    original_issue = identity_service.issue_auth_session_under_fence
    reset_applied = False

    def reset_then_issue(session, **kwargs):
        nonlocal reset_applied
        if not reset_applied:
            reset_applied = True
            with factory() as reset_session:
                membership = lock_company_memberships_for_assignment(
                    reset_session,
                    company_id=company_id,
                    membership_ids=(membership_id,),
                )[membership_id]
                user = lock_user_for_membership_deactivation(
                    reset_session,
                    membership=membership,
                )
                user.password_hash = hash_password("ResetWinner123!")
                membership.sessions_valid_after = datetime.now(UTC)
                reset_session.commit()
        return original_issue(session, **kwargs)

    monkeypatch.setattr(
        identity_service,
        "issue_auth_session_under_fence",
        reset_then_issue,
    )

    with factory() as session, pytest.raises(HTTPException) as exc_info:
        identity_service.authenticate_user(
            session,
            email="owner@asterlegal.in",
            password="FoundersPass123!",
            company_slug="aster-legal",
        )

    assert reset_applied is True
    assert exc_info.value.status_code == 401


def test_refresh_final_fence_rechecks_original_token_cutoff(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    claims = decode_access_token(token)
    token_issued_at = float(claims["issued_at_precise"])
    membership_id = str(bootstrap["membership"]["id"])
    company_id = str(bootstrap["company"]["id"])
    factory = get_session_factory()

    with factory() as refresh_session:
        stale_context = identity_service.get_session_context(
            refresh_session,
            membership_id,
            token_issued_at=token_issued_at,
        )
        # End the advisory read transaction. The context intentionally remains
        # stale while another transaction advances the revocation cutoff.
        refresh_session.commit()
        with factory() as reset_session:
            membership = lock_company_memberships_for_assignment(
                reset_session,
                company_id=company_id,
                membership_ids=(membership_id,),
            )[membership_id]
            lock_user_for_membership_deactivation(
                reset_session,
                membership=membership,
            )
            membership.sessions_valid_after = datetime.now(UTC)
            reset_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            identity_service.refresh_auth_session(refresh_session, stale_context)

    assert exc_info.value.status_code == 401


def test_password_reset_response_token_is_after_its_revocation_cutoff(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Reset Fence Member",
            "email": "reset-fence@asterlegal.in",
            "password": "BeforeReset123!",
            "role": "member",
        },
    )
    assert created.status_code == 200, created.text
    membership_id = str(created.json()["membership_id"])

    reset = client.post(
        f"/api/companies/current/employees/{membership_id}/reset-password",
        headers=auth_headers(owner_token),
    )
    assert reset.status_code == 200, reset.text
    reset_token = reset.json()["debug_token"]
    assert reset_token

    completed = client.post(
        "/api/auth/password-reset/complete",
        json={"token": reset_token, "password": "AfterReset123!"},
    )
    assert completed.status_code == 200, completed.text
    access_token = str(completed.json()["access_token"])
    issued_at = float(decode_access_token(access_token)["issued_at_precise"])

    factory = get_session_factory()
    with factory() as session:
        membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.id == membership_id)
        )
        assert membership is not None
        assert membership.sessions_valid_after is not None
        cutoff = membership.sessions_valid_after
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        assert issued_at >= cutoff.timestamp()

    client.cookies.clear()
    assert (
        client.get("/api/auth/me", headers=auth_headers(access_token)).status_code
        == 200
    )
