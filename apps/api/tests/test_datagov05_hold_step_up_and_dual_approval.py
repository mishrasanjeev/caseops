"""DATA-GOV-05 using authenticated actors instead of nominated reviewers.

The former lifecycle assertions now exercise an actual second actor and an
immutable release proposal. No caller may invent reviewer attendance.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from caseops_api.db.models import LegalHold, UserMFAStepUp
from caseops_api.db.session import get_session_factory
from tests.test_20260909_legal_hold_workflow import (
    BASE,
    _activate,
    _create,
    _proposal,
    make_actors,
)


@pytest.fixture
def actors(client):
    return make_actors(client)


def _dry(client, actor):
    result = client.post(
        f"{BASE}/operations/dry-runs/tenant-scope",
        headers=actor["headers"],
        json={"operation_type": "tenant_offboarding", "data_class_ids": ["tenant_data_operations"]},
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def _request(client, actor, hold, dry_run_id):
    return client.post(
        f"{BASE}/holds/{hold['id']}/release-requests",
        headers=actor["headers"],
        json={
            "expected_updated_at": hold["updated_at"],
            "idempotency_key": uuid4().hex,
            "dry_run_id": dry_run_id,
            "reason_reference": "fixture://release-authority",
        },
    )


def test_the_requester_cannot_approve_their_own_activation(client, actors):
    owner, _ = actors
    hold, _ = _create(client, owner)
    response = client.post(
        f"{BASE}/holds/{hold['id']}/activate",
        headers=owner["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert response.status_code == 409
    assert response.json()["type"] == "legal_hold_approver_must_be_distinct"


def test_a_distinct_approver_activates(client, actors):
    owner, reviewer = actors
    hold = _activate(client, reviewer, _create(client, owner)[0])
    assert hold["status"] == "active" and hold["activated_at"]
    assert hold["approved_by_membership_id"] == reviewer["id"]


def test_only_a_draft_can_be_activated(client, actors):
    owner, reviewer = actors
    hold = _activate(client, reviewer, _create(client, owner)[0])
    again = client.post(
        f"{BASE}/holds/{hold['id']}/activate",
        headers=reviewer["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert again.status_code == 409 and again.json()["type"] == "legal_hold_not_draft"


def test_release_without_a_dry_run_is_refused(client, actors):
    owner, reviewer = actors
    hold = _activate(client, reviewer, _create(client, owner)[0])
    response = _request(client, owner, hold, "missing-dry-run")
    assert (
        response.status_code == 409
        and response.json()["type"] == "legal_hold_release_requires_dry_run"
    )


def test_a_dry_run_predating_the_hold_is_refused(client, actors):
    owner, reviewer = actors
    dry_run_id = _dry(client, owner)
    hold = _activate(client, reviewer, _create(client, owner)[0])
    response = _request(client, owner, hold, dry_run_id)
    assert (
        response.status_code == 409
        and response.json()["type"] == "legal_hold_release_requires_dry_run"
    )


def test_another_companys_dry_run_is_refused(client, actors):
    owner, reviewer = actors
    hold = _activate(client, reviewer, _create(client, owner)[0])
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Foreign synthetic workspace",
            "company_slug": "foreign-hold-workspace",
            "company_type": "law_firm",
            "owner_full_name": "Other owner",
            "owner_email": "other@hold.fixture",
            "owner_password": "SyntheticPass123!",
        },
    )
    assert response.status_code == 200, response.text
    foreign = {
        "headers": {
            "Authorization": f"Bearer {response.json()['access_token']}",
            "X-CaseOps-Automated-Test": "no-paid-providers",
        }
    }
    dry_run_id = _dry(client, foreign)
    denied = _request(client, owner, hold, dry_run_id)
    assert (
        denied.status_code == 409 and denied.json()["type"] == "legal_hold_release_requires_dry_run"
    )
    assert client.get(f"{BASE}/holds", headers=foreign["headers"]).json()["holds"] == []


def test_a_current_dry_run_releases(client, actors):
    owner, reviewer = actors
    hold = _activate(client, reviewer, _create(client, owner)[0])
    proposal, _ = _proposal(client, owner, hold)
    response = client.post(
        f"{BASE}/holds/{hold['id']}/release-requests/{proposal['id']}/approve",
        headers=reviewer["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "released" and response.json()["released_at"]
    with get_session_factory()() as session:
        assert session.get(LegalHold, hold["id"]).status == "released"


def test_the_requester_cannot_approve_their_own_release(client, actors):
    owner, reviewer = actors
    hold = _activate(client, reviewer, _create(client, owner)[0])
    proposal, _ = _proposal(client, owner, hold)
    response = client.post(
        f"{BASE}/holds/{hold['id']}/release-requests/{proposal['id']}/approve",
        headers=owner["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert (
        response.status_code == 409
        and response.json()["type"] == "legal_hold_approver_must_be_distinct"
    )


@pytest.mark.parametrize("action", ["activate", "release"])
def test_both_lifecycle_paths_demand_step_up(client, actors, action):
    owner, reviewer = actors
    hold, _ = _create(client, owner)
    path = f"{BASE}/holds/{hold['id']}/activate"
    if action == "release":
        hold = _activate(client, reviewer, hold)
        proposal, _ = _proposal(client, owner, hold)
        path = f"{BASE}/holds/{hold['id']}/release-requests/{proposal['id']}/approve"
    with get_session_factory()() as session:
        for row in session.scalars(
            select(UserMFAStepUp).where(UserMFAStepUp.membership_id == reviewer["id"])
        ):
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    response = client.post(
        path, headers=reviewer["headers"], json={"expected_updated_at": hold["updated_at"]}
    )
    assert response.status_code == 403 and "step-up" in response.json()["detail"].lower()


def test_the_purpose_is_registered():
    from caseops_api.schemas.security import MFAStepUpRequest

    assert (
        MFAStepUpRequest(code="123456", purpose="legal_hold_change").purpose == "legal_hold_change"
    )
