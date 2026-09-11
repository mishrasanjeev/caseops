"""IPLF-028B / DATA-GOV-04,05 / UJ-64 authenticated preservation boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from caseops_api.core.security import create_access_token
from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    LegalHold,
    LegalHoldItem,
    LegalHoldReleaseRequest,
    User,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.data_governance import activate_legal_hold, resolve_hold_for_target
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company

BASE = "/api/admin/data-governance"

# These endpoint templates are exercised through BASE and f-string helpers
# below. Keep the concrete paths visible to the route-coverage audit.
ROUTE_COVERAGE_PATHS = (
    "/api/admin/data-governance/holds/{hold_id}/activate",
    "/api/admin/data-governance/holds/{hold_id}/release-requests",
    "/api/admin/data-governance/holds/{hold_id}/release-requests/{proposal_id}/approve",
)


def make_actors(client):
    bootstrap = bootstrap_company(client)
    company_id = bootstrap["company"]["id"]
    owner_id = bootstrap["membership"]["id"]
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(bootstrap["access_token"]),
        json={
            "email": f"hold-reviewer-{uuid4().hex}@example.com",
            "full_name": "Independent reviewer",
            "password": "SyntheticReview2026!",
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    with get_session_factory()() as session:
        owner = session.get(CompanyMembership, owner_id)
        reviewer = session.get(CompanyMembership, created.json()["membership_id"])
        assert reviewer.role == "admin"
        result = []
        for member in (owner, reviewer):
            now = datetime.now(UTC)
            session.add(
                UserMFAStepUp(
                    user_id=member.user_id,
                    membership_id=member.id,
                    purpose="legal_hold_change",
                    method="totp",
                    completed_at=now,
                    expires_at=now + timedelta(minutes=10),
                )
            )
            result.append(
                {
                    "id": member.id,
                    "user_id": member.user_id,
                    "company_id": company_id,
                    "headers": {
                        **auth_headers(
                            create_access_token(
                                user_id=member.user_id,
                                company_id=company_id,
                                membership_id=member.id,
                                role=member.role,
                            )
                        ),
                        "X-CaseOps-Automated-Test": "no-paid-providers",
                    },
                }
            )
        session.commit()
    # Every command supplies its actor explicitly. Bootstrap cookies would
    # otherwise override the independent Bearer identity on the PG HTTP client.
    client.cookies.clear()
    return result


@pytest.fixture
def actors(client):
    return make_actors(client)


def _create(client, actor, *, classes=None, key=None):
    payload = {
        "idempotency_key": key or uuid4().hex,
        "title": "Synthetic preservation",
        "authority_reference": "fixture://preservation-authority",
        "scope": "data_classes",
        "data_class_ids": classes or ["tenant_data_operations"],
    }
    response = client.post(f"{BASE}/holds", headers=actor["headers"], json=payload)
    assert response.status_code == 201, response.text
    return response.json(), payload


def _activate(client, reviewer, hold):
    response = client.post(
        f"{BASE}/holds/{hold['id']}/activate",
        headers=reviewer["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _proposal(client, owner, hold):
    dry_run = client.post(
        f"{BASE}/operations/dry-runs/tenant-scope",
        headers=owner["headers"],
        json={"operation_type": "tenant_offboarding", "data_class_ids": hold["data_class_ids"]},
    )
    assert dry_run.status_code == 201, dry_run.text
    payload = {
        "idempotency_key": uuid4().hex,
        "expected_updated_at": hold["updated_at"],
        "dry_run_id": dry_run.json()["id"],
        "reason_reference": "fixture://release-authority",
    }
    response = client.post(
        f"{BASE}/holds/{hold['id']}/release-requests", headers=owner["headers"], json=payload
    )
    assert response.status_code == 201, response.text
    return response.json(), payload


def test_two_people_preserve_release_and_reload_without_deletion(client, actors):
    owner, reviewer = actors
    hold, payload = _create(client, owner)
    replay = client.post(f"{BASE}/holds", headers=owner["headers"], json=payload)
    assert replay.status_code == 201 and replay.json()["id"] == hold["id"]
    hold = _activate(client, reviewer, hold)
    with get_session_factory()() as session:
        assert (
            resolve_hold_for_target(
                session, company_id=owner["company_id"], data_class_id="tenant_data_operations"
            )
            == hold["id"]
        )
        assert (
            resolve_hold_for_target(
                session, company_id=owner["company_id"], data_class_id="legal_holds"
            )
            is None
        )
    proposal, release_payload = _proposal(client, owner, hold)
    listed = client.get(
        f"{BASE}/holds/{hold['id']}/release-requests", headers=owner["headers"]
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["proposals"]] == [proposal["id"]]
    replay = client.post(
        f"{BASE}/holds/{hold['id']}/release-requests",
        headers=owner["headers"],
        json=release_payload,
    )
    assert replay.status_code == 201 and replay.json()["id"] == proposal["id"]
    response = client.post(
        f"{BASE}/holds/{hold['id']}/release-requests/{proposal['id']}/approve",
        headers=reviewer["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "released"
    assert response.json()["approved_by_membership_id"] == reviewer["id"]
    reloaded = client.get(f"{BASE}/holds", headers=owner["headers"])
    assert reloaded.status_code == 200 and reloaded.json()["holds"][0]["status"] == "released"
    with get_session_factory()() as session:
        assert session.get(LegalHold, hold["id"]) is not None
        assert (
            session.scalar(select(LegalHoldItem).where(LegalHoldItem.legal_hold_id == hold["id"]))
            is not None
        )
        assert session.get(LegalHoldReleaseRequest, proposal["id"]) is not None
        actions = list(
            session.scalars(select(AuditEvent.action).where(AuditEvent.target_id == hold["id"]))
        )
        assert sorted(actions) == sorted(
            [
                "legal_hold.created",
                "legal_hold.activated",
                "legal_hold.release_requested",
                "legal_hold.released",
            ]
        )
    execution = client.post(
        f"{BASE}/operations/{release_payload['dry_run_id']}/execute", headers=owner["headers"]
    )
    assert execution.status_code == 503
    stale = client.post(
        f"{BASE}/holds/{hold['id']}/activate",
        headers=reviewer["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert stale.status_code == 409 and stale.json()["type"] == "legal_hold_stale"


def test_self_approval_and_nominated_approver_are_rejected(client, actors):
    owner, reviewer = actors
    hold, _ = _create(client, owner)
    self_approval = client.post(
        f"{BASE}/holds/{hold['id']}/activate",
        headers=owner["headers"],
        json={"expected_updated_at": hold["updated_at"]},
    )
    assert self_approval.status_code == 409
    spoof = client.post(
        f"{BASE}/holds/{hold['id']}/activate",
        headers=owner["headers"],
        json={"expected_updated_at": hold["updated_at"], "approver_membership_id": reviewer["id"]},
    )
    assert spoof.status_code == 422
    with get_session_factory()() as session:
        context = SessionContext(
            company=session.get(Company, owner["company_id"]),
            membership=session.get(CompanyMembership, owner["id"]),
            user=session.get(User, owner["user_id"]),
        )
        with pytest.raises(HTTPException) as error:
            activate_legal_hold(
                session,
                context=context,
                hold_id=hold["id"],
                approver_membership_id=reviewer["id"],
                approver_label="Nominated",
            )
        assert error.value.status_code == 403
        assert session.get(LegalHold, hold["id"]).status == "draft"


@pytest.mark.parametrize(
    "failure", ["self", "expired", "scope_changed", "no_step_up", "revoked", "requester_revoked"]
)
def test_release_failures_preserve_the_active_hold(client, actors, monkeypatch, failure):
    owner, reviewer = actors
    hold = _activate(client, reviewer, _create(client, owner)[0])
    proposal, _ = _proposal(client, owner, hold)
    headers = reviewer["headers"]
    if failure == "self":
        headers = owner["headers"]
    elif failure == "expired":
        from caseops_api.services import legal_hold_workflow

        class FutureClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(minutes=31)

        monkeypatch.setattr(legal_hold_workflow, "datetime", FutureClock)
    elif failure == "scope_changed":
        _activate(client, reviewer, _create(client, owner)[0])
    else:
        with get_session_factory()() as session:
            if failure == "no_step_up":
                for row in session.scalars(
                    select(UserMFAStepUp).where(UserMFAStepUp.membership_id == reviewer["id"])
                ):
                    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                member_id = owner["id"] if failure == "requester_revoked" else reviewer["id"]
                session.get(CompanyMembership, member_id).is_active = False
            session.commit()
    response = client.post(
        f"{BASE}/holds/{hold['id']}/release-requests/{proposal['id']}/approve",
        headers=headers,
        json={"expected_updated_at": hold["updated_at"]},
    )
    if failure == "revoked":
        assert response.status_code in {401, 403}, response.text
    elif failure in {"no_step_up", "requester_revoked"}:
        assert response.status_code == 403, response.text
    else:
        expected_type = {
            "self": "legal_hold_approver_must_be_distinct",
            "expired": "legal_hold_release_expired",
            "scope_changed": "legal_hold_release_changed",
        }[failure]
        assert response.status_code == 409 and response.json()["type"] == expected_type
    with get_session_factory()() as session:
        assert session.get(LegalHold, hold["id"]).status == "active"
        assert (
            session.scalar(select(AuditEvent.id).where(AuditEvent.action == "legal_hold.released"))
            is None
        )


def test_whole_workspace_hold_cannot_be_released_with_partial_metadata_inventory(client, actors):
    owner, reviewer = actors
    response = client.post(
        f"{BASE}/holds",
        headers=owner["headers"],
        json={
            "idempotency_key": uuid4().hex,
            "title": "Workspace preservation",
            "authority_reference": "fixture://authority",
            "scope": "company",
            "data_class_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    hold = _activate(client, reviewer, response.json())
    dry = client.post(
        f"{BASE}/operations/dry-runs/tenant-scope",
        headers=owner["headers"],
        json={"operation_type": "tenant_offboarding", "data_class_ids": ["legal_holds"]},
    )
    assert dry.status_code == 201, dry.text
    release = client.post(
        f"{BASE}/holds/{hold['id']}/release-requests",
        headers=owner["headers"],
        json={
            "expected_updated_at": hold["updated_at"],
            "idempotency_key": uuid4().hex,
            "dry_run_id": dry.json()["id"],
            "reason_reference": "fixture://release",
        },
    )
    assert release.status_code == 503
    assert release.json()["type"] == "legal_hold_full_inventory_required"


def test_missing_step_up_unknown_classes_and_unauthenticated_reads_fail_closed(client, actors):
    owner, _ = actors
    client.cookies.clear()
    assert client.get(f"{BASE}/holds").status_code == 401
    payload = {
        "idempotency_key": uuid4().hex,
        "title": "Hold",
        "authority_reference": "fixture://authority",
        "scope": "data_classes",
        "data_class_ids": ["invented"],
    }
    invalid = client.post(f"{BASE}/holds", headers=owner["headers"], json=payload)
    assert invalid.status_code == 409
    with get_session_factory()() as session:
        for row in session.scalars(select(UserMFAStepUp)):
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    payload.update(scope="company", data_class_ids=[])
    denied = client.post(f"{BASE}/holds", headers=owner["headers"], json=payload)
    assert denied.status_code == 403
    with get_session_factory()() as session:
        assert session.scalar(select(LegalHold.id)) is None


def test_publicly_created_admin_can_approve_without_audit_export_or_custom_delegation(
    client, actors
):
    from caseops_api.services.capabilities import custom_role_capabilities_allowed

    owner, reviewer = actors
    assert "legal_holds:manage" not in custom_role_capabilities_allowed()
    hold = _activate(client, reviewer, _create(client, owner)[0])
    assert hold["approved_by_membership_id"] == reviewer["id"]
    assert client.get(f"{BASE}/holds", headers=reviewer["headers"]).status_code == 200
    assert client.get(f"{BASE}/operations/dry-runs", headers=reviewer["headers"]).status_code == 403
    with get_session_factory()() as session:
        session.get(CompanyMembership, reviewer["id"]).role = "member"
        session.commit()
    assert client.get(f"{BASE}/holds", headers=reviewer["headers"]).status_code == 403


@pytest.mark.parametrize("command", ["create", "activate", "release"])
def test_stale_reviewed_projection_cannot_authorize_hold_commands(
    client, actors, monkeypatch, command
):
    from caseops_api.governance import data_class_projection, generated_data_class_projection

    owner, reviewer = actors
    hold, payload = _create(client, owner)
    url, actor = f"{BASE}/holds", owner
    if command == "create":
        payload["idempotency_key"] = uuid4().hex
    elif command == "activate":
        url, actor = f"{BASE}/holds/{hold['id']}/activate", reviewer
        payload = {"expected_updated_at": hold["updated_at"]}
    else:
        hold = _activate(client, reviewer, hold)
        proposal, _ = _proposal(client, owner, hold)
        url, actor = (
            f"{BASE}/holds/{hold['id']}/release-requests/{proposal['id']}/approve",
            reviewer,
        )
        payload = {"expected_updated_at": hold["updated_at"]}
    monkeypatch.setattr(generated_data_class_projection, "ORM_SCHEMA_FINGERPRINT", "0" * 64)
    data_class_projection.reset_projection_state_cache()
    try:
        response = client.post(url, headers=actor["headers"], json=payload)
        assert response.status_code == 503, response.text
        assert response.json()["type"] == "data_class_projection_stale"
        with get_session_factory()() as session:
            rows = list(session.scalars(select(LegalHold)))
            assert len(rows) == 1 and rows[0].status == (
                "active" if command == "release" else "draft"
            )
    finally:
        data_class_projection.reset_projection_state_cache()
