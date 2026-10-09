"""Portal authority and historical event provenance have distinct namespaces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    CompanyMembership,
    PortalUser,
    PrivateIndexGeneration,
    PrivateProjectionEvent,
    User,
)
from caseops_api.db.session import get_session_factory
from tests import test_clients, test_portal_matters
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_client_private_authority_postgres import _fixture, _write
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("provenance", ["missing", "foreign-inviter", "foreign-creator"])
def test_legacy_portal_kyc_without_private_generation_needs_no_event_actor(pg_engine, provenance):
    fixture = _fixture(pg_engine, "portal-kyc", indexed=False)
    foreign = _fixture(pg_engine, "portal-kyc", indexed=False)
    with Session(pg_engine) as session:
        assert not session.scalars(
            select(PrivateIndexGeneration).where(
                PrivateIndexGeneration.company_id == fixture["company_id"],
            )
        ).all()
        portal = session.get(PortalUser, fixture["portal_id"])
        client = session.get(Client, fixture["client_id"])
        portal.invited_by_membership_id = (
            foreign["actor_id"] if provenance == "foreign-inviter" else None
        )
        client.created_by_membership_id = (
            foreign["actor_id"] if provenance == "foreign-creator" else None
        )
        session.commit()
    with Session(pg_engine) as session:
        _write(session, fixture, "portal-kyc")
    with Session(pg_engine) as session:
        client = session.get(Client, fixture["client_id"])
        assert client.kyc_status == "submitted"
        assert client.kyc_submitted_at is not None
        assert not session.scalars(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture["company_id"],
            )
        ).all()


@pytest.mark.parametrize("provenance", ["missing", "foreign-inviter", "foreign-creator"])
def test_portal_kyc_refuses_invalid_historical_provenance_before_write(pg_engine, provenance):
    fixture = _fixture(pg_engine, "portal-kyc")
    foreign = _fixture(pg_engine, "portal-kyc")
    with Session(pg_engine) as session:
        portal = session.get(PortalUser, fixture["portal_id"])
        client = session.get(Client, fixture["client_id"])
        portal.invited_by_membership_id = (
            foreign["actor_id"] if provenance == "foreign-inviter" else None
        )
        client.created_by_membership_id = (
            foreign["actor_id"] if provenance == "foreign-creator" else None
        )
        session.commit()
    with Session(pg_engine) as session:
        with pytest.raises(HTTPException) as rejected:
            _write(session, fixture, "portal-kyc")
        assert rejected.value.status_code == 409
        assert rejected.value.detail == "Client verification provenance is unavailable."
        session.rollback()
    with Session(pg_engine) as session:
        client = session.get(Client, fixture["client_id"])
        assert client.kyc_status == "not_required"
        assert client.kyc_submitted_at is None
        assert not session.scalars(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture["company_id"],
            )
        ).all()


@pytest.mark.parametrize("revocation", ["membership", "user", "session"])
def test_client_kyc_http_current_actor_revocation_is_preserved(
    isolated_postgres_client,
    revocation,
):
    client = isolated_postgres_client
    boot = bootstrap_company(client)
    headers = auth_headers(boot["access_token"])
    created = client.post(
        "/api/clients/",
        headers=headers,
        json={"name": "Current actor KYC", "client_type": "individual"},
    )
    assert created.status_code == 200, created.text
    client_id = created.json()["id"]
    factory = get_session_factory()
    with factory() as session:
        if revocation == "membership":
            session.get(CompanyMembership, boot["membership"]["id"]).is_active = False
        elif revocation == "user":
            session.get(User, boot["user"]["id"]).is_active = False
        else:
            session.get(CompanyMembership, boot["membership"]["id"]).sessions_valid_after = (
                datetime.now(UTC) + timedelta(seconds=1)
            )
        session.commit()
    rejected = client.post(
        f"/api/clients/{client_id}/kyc/submit",
        headers=headers,
        json={"documents": []},
    )
    assert rejected.status_code == (401 if revocation == "session" else 403), rejected.text
    with factory() as session:
        saved = session.get(Client, client_id)
        assert saved.kyc_status == "not_required"
        assert saved.kyc_submitted_at is None


@pytest.mark.parametrize(
    "journey",
    [
        "test_matter_client_verification_workflow_links_attachment_and_audits_redacted",
        "test_matter_client_verification_respects_restricted_wall_and_team_access",
        "test_disposed_matter_rejects_client_link_and_verification_mutations",
    ],
)
def test_client_verification_http_contract_on_postgres(isolated_postgres_client, journey):
    getattr(test_clients, journey)(isolated_postgres_client)


def test_portal_kyc_http_contract_on_postgres(isolated_postgres_client):
    test_portal_matters.test_portal_kyc_submit_marks_one_client_and_audits(isolated_postgres_client)
