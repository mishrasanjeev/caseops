from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    EthicalWall,
    IpDocketRecord,
    Matter,
    MatterAccessGrant,
    NotificationDeliveryChannel,
    Team,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_access import IpAccessChangeRequest
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company


def _particulars(mark: str) -> dict[str, object]:
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {"text": mark},
        "classes": [{"class_number": 9, "specification": "Downloadable software"}],
        "parties": [{"role": "applicant", "name": "Access Workflow LLP"}],
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Mark representation",
                "required": True,
                "evidence_reference": "fixture:iplf-026b",
            }
        ],
    }


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"action": "grant"},
            "subject_type and subject_id are required for this action",
        ),
        ({"action": "revoke_grant"}, "grant_id is required for revoke_grant"),
        ({"action": "revoke_wall"}, "wall_id is required for revoke_wall"),
        (
            {"action": "set_restricted"},
            "restricted is required for set_restricted",
        ),
    ],
)
def test_ip_access_change_schema_requires_action_specific_fields(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        IpAccessChangeRequest(
            expected_access_policy_version=0,
            reason="Coverage regression assertion",
            **payload,
        )


def test_ip_access_change_schema_rejects_non_increasing_effective_window() -> None:
    effective_from = datetime(2026, 8, 12, tzinfo=UTC)
    with pytest.raises(ValidationError, match="expires_at must be later"):
        IpAccessChangeRequest(
            action="grant",
            expected_access_policy_version=0,
            reason="Coverage regression assertion",
            subject_type="membership",
            subject_id="membership-1",
            effective_from=effective_from,
            expires_at=effective_from - timedelta(seconds=1),
        )

    with pytest.raises(ValidationError, match="expires_at must be later"):
        IpAccessChangeRequest(
            action="grant",
            expected_access_policy_version=0,
            reason="Coverage regression assertion",
            subject_type="membership",
            subject_id="membership-1",
            expires_at=effective_from - timedelta(seconds=1),
        )


def test_ip_access_change_schema_rejects_whitespace_only_reason() -> None:
    with pytest.raises(ValidationError, match="at least 5 characters"):
        IpAccessChangeRequest(
            action="set_restricted",
            expected_access_policy_version=0,
            reason="     ",
            restricted=True,
        )

def _invite_admin(
    client: TestClient,
    *,
    owner_token: str,
    name: str,
    email: str,
) -> tuple[str, dict[str, str]]:
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": name,
            "email": email,
            "role": "admin",
            "password": "AccessWorkflow123!",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": email,
            "password": "AccessWorkflow123!",
        },
    )
    assert login.status_code == 200, login.text
    return str(created.json()["membership_id"]), auth_headers(
        str(login.json()["access_token"])
    )


def _create_linked_restricted_docket(
    client: TestClient,
    *,
    owner_headers: dict[str, str],
) -> tuple[dict, str]:
    matter = client.post(
        "/api/matters/",
        headers=owner_headers,
        json={
            "title": "Restricted linked Matter",
            "matter_code": "IPLF-026B-MATTER",
            "practice_area": "Intellectual Property",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert matter.status_code == 200, matter.text
    matter_id = str(matter.json()["id"])
    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=owner_headers,
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    docket = client.post(
        "/api/ip/dockets",
        headers=owner_headers,
        json={
            "title": "Restricted ASTER workflow",
            "matter_id": matter_id,
            "restricted": True,
            "particulars": _particulars("ASTER"),
        },
    )
    assert docket.status_code == 201, docket.text
    return docket.json(), matter_id


def _preview(
    client: TestClient,
    *,
    headers: dict[str, str],
    docket_id: str,
    payload: dict[str, object],
) -> dict:
    response = client.post(
        f"/api/ip/dockets/{docket_id}/access/preview",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(
    client: TestClient,
    *,
    headers: dict[str, str],
    docket_id: str,
    payload: dict[str, object],
    preview: dict,
) -> dict:
    response = client.post(
        f"/api/ip/dockets/{docket_id}/access/apply",
        headers=headers,
        json={**payload, "preview_token": preview["preview_token"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ip_access_preview_apply_revocation_and_delivery_reauthorization(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_id, member_headers = _invite_admin(
        client,
        owner_token=owner_token,
        name="IP Access Reviewer",
        email="ip-access-reviewer@asterlegal.in",
    )
    docket, matter_id = _create_linked_restricted_docket(
        client,
        owner_headers=owner_headers,
    )
    docket_id = str(docket["id"])

    panel = client.get(
        f"/api/ip/dockets/{docket_id}/access",
        headers=owner_headers,
    )
    assert panel.status_code == 200, panel.text
    assert panel.json()["access_policy_version"] == 1
    assert panel.json()["excluded_persistence"] == [
        "portal_grants",
        "access_review_campaigns",
        "emergency_access_sessions",
    ]
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 404
    hidden_list = client.get("/api/ip/dockets", headers=member_headers)
    assert hidden_list.status_code == 200, hidden_list.text
    assert hidden_list.json()["count"] == 0
    assert client.get(
        f"/api/ip/dockets/{docket_id}/audit", headers=member_headers
    ).status_code == 404

    grant_payload: dict[str, object] = {
        "action": "grant",
        "expected_access_policy_version": 1,
        "reason": "Assigned for privileged trademark review.",
        "subject_type": "membership",
        "subject_id": member_id,
    }
    grant_preview = _preview(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=grant_payload,
    )
    assert grant_preview["visibility_gain_count"] == 1
    assert grant_preview["linked_matter_mismatch"] is True
    assert grant_preview["requires_step_up"] is True
    cross_actor_apply = client.post(
        f"/api/ip/dockets/{docket_id}/access/apply",
        headers=member_headers,
        json={**grant_payload, "preview_token": grant_preview["preview_token"]},
    )
    assert cross_actor_apply.status_code == 409
    assert "does not match" in cross_actor_apply.text
    granted = _apply(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=grant_payload,
        preview=grant_preview,
    )
    assert granted["panel"]["access_policy_version"] == 2
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 200
    assert client.get(
        f"/api/matters/{matter_id}", headers=member_headers
    ).status_code == 404

    stale = client.post(
        f"/api/ip/dockets/{docket_id}/access/apply",
        headers=owner_headers,
        json={**grant_payload, "preview_token": grant_preview["preview_token"]},
    )
    assert stale.status_code == 409

    with get_session_factory()() as session:
        owner_membership = session.get(CompanyMembership, owner_membership_id)
        member = session.get(CompanyMembership, member_id)
        docket_row = session.get(IpDocketRecord, docket_id)
        assert owner_membership is not None and member is not None
        assert docket_row is not None
        context = SessionContext(
            company=session.get(Company, owner_membership.company_id),
            user=session.get(User, owner_membership.user_id),
            membership=owner_membership,
        )
        assert context.company is not None and context.user is not None
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=member,
            channel=NotificationDeliveryChannel.IN_APP,
            event_type="ip.access.fixture",
            source_type="ip_docket_record",
            source_id=docket_id,
            ip_docket=docket_row,
            title="Restricted docket update",
            body="Review the restricted docket in CaseOps.",
        )
        assert intent is not None
        intent_id = intent.id
        session.commit()

    active_grant = next(
        row
        for row in granted["panel"]["grants"]
        if row["subject_id"] == member_id and row["revoked_at"] is None
    )
    revoke_payload: dict[str, object] = {
        "action": "revoke_grant",
        "expected_access_policy_version": 2,
        "reason": "Privileged review assignment has ended.",
        "grant_id": active_grant["id"],
    }
    revoke_preview = _preview(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=revoke_payload,
    )
    assert revoke_preview["visibility_loss_count"] == 1
    assert revoke_preview["queued_delivery_recheck_count"] == 1
    revoked = _apply(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=revoke_payload,
        preview=revoke_preview,
    )
    assert revoked["panel"]["access_policy_version"] == 3
    revoked_grant = next(
        row for row in revoked["panel"]["grants"] if row["id"] == active_grant["id"]
    )
    assert revoked_grant["revoked_at"] is not None
    assert revoked_grant["revoked_by_membership_id"] == owner_membership_id
    assert revoked_grant["record_version"] == 1
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 404
    revoked_list = client.get("/api/ip/dockets", headers=member_headers)
    assert revoked_list.status_code == 200, revoked_list.text
    assert revoked_list.json()["count"] == 0
    assert client.get(
        f"/api/ip/dockets/{docket_id}/audit", headers=member_headers
    ).status_code == 404

    with get_session_factory()() as session:
        owner_membership = session.get(CompanyMembership, owner_membership_id)
        assert owner_membership is not None
        context = SessionContext(
            company=session.get(Company, owner_membership.company_id),
            user=session.get(User, owner_membership.user_id),
            membership=owner_membership,
        )
        result = process_notification_delivery_intent(
            session,
            intent_id=intent_id,
            context=context,
        )
        session.commit()
        assert result.blocked is True
        assert result.external_calls == 0

        audit = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.action == "ip.access.revoke_grant",
                AuditEvent.ip_docket_id == docket_id,
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        metadata = json.loads(str(audit.metadata_json))
        assert metadata["access_policy_version_before"] == 2
        assert metadata["access_policy_version_after"] == 3
        assert metadata["linked_matter_permissions_copied"] is False
        assert metadata["invalidation_contract"] == [
            "access_policy_generation",
            "result_hydration",
            "queued_delivery_reauthorization",
        ]


def test_ip_access_rejects_cross_company_subject_and_self_lockout(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    owner_membership_id = str(bootstrap["membership"]["id"])
    docket, _ = _create_linked_restricted_docket(
        client,
        owner_headers=owner_headers,
    )
    docket_id = str(docket["id"])

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other IP LLP",
            "company_slug": "other-ip",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-ip.example",
            "owner_password": "OtherOwner123!",
        },
    )
    assert other.status_code == 200, other.text
    cross_company = client.post(
        f"/api/ip/dockets/{docket_id}/access/preview",
        headers=owner_headers,
        json={
            "action": "grant",
            "expected_access_policy_version": 1,
            "reason": "This cross-company subject must be rejected.",
            "subject_type": "membership",
            "subject_id": other.json()["membership"]["id"],
        },
    )
    assert cross_company.status_code == 400

    panel = client.get(
        f"/api/ip/dockets/{docket_id}/access",
        headers=owner_headers,
    ).json()
    creator_grant = next(
        row
        for row in panel["grants"]
        if row["subject_id"] == owner_membership_id and row["revoked_at"] is None
    )
    self_revoke = client.post(
        f"/api/ip/dockets/{docket_id}/access/preview",
        headers=owner_headers,
        json={
            "action": "revoke_grant",
            "expected_access_policy_version": panel["access_policy_version"],
            "reason": "Attempting to remove the final creator access.",
            "grant_id": creator_grant["id"],
        },
    )
    assert self_revoke.status_code == 409
    assert "different authorized owner" in self_revoke.text


def test_ip_access_change_fails_closed_for_terminal_linked_matter(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    docket, matter_id = _create_linked_restricted_docket(
        client,
        owner_headers=owner_headers,
    )
    docket_id = str(docket["id"])
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        docket_row = session.get(IpDocketRecord, docket_id)
        assert matter is not None and docket_row is not None
        matter.status = "disposed"
        matter.is_active = False
        # Simulate a stale operational child to prove the access loader also
        # checks the authoritative parent lifecycle, not only child flags.
        docket_row.is_active = True
        docket_row.archived_by_matter_disposal = False
        session.commit()

    payload = {
        "action": "set_restricted",
        "expected_access_policy_version": 1,
        "reason": "Terminal docket mutation must fail closed.",
        "restricted": False,
    }
    preview = client.post(
        f"/api/ip/dockets/{docket_id}/access/preview",
        headers=owner_headers,
        json=payload,
    )
    assert preview.status_code == 404
    apply = client.post(
        f"/api/ip/dockets/{docket_id}/access/apply",
        headers=owner_headers,
        json={**payload, "preview_token": "0" * 64},
    )
    assert apply.status_code == 404
    with get_session_factory()() as session:
        docket_row = session.get(IpDocketRecord, docket_id)
        assert docket_row is not None
        assert docket_row.access_policy_version == 1


def test_ip_access_preview_batches_linked_matter_visibility(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.services import matter_access

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    member_id, _ = _invite_admin(
        client,
        owner_token=owner_token,
        name="Batch Visibility Reviewer",
        email="batch-visibility@asterlegal.in",
    )
    docket, _ = _create_linked_restricted_docket(
        client,
        owner_headers=owner_headers,
    )

    def reject_per_membership_query(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("linked Matter preview performed a per-membership query")

    monkeypatch.setattr(matter_access, "can_access", reject_per_membership_query)
    preview = client.post(
        f"/api/ip/dockets/{docket['id']}/access/preview",
        headers=owner_headers,
        json={
            "action": "grant",
            "expected_access_policy_version": 1,
            "reason": "Bounded linked visibility calculation.",
            "subject_type": "membership",
            "subject_id": member_id,
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["linked_matter_mismatch"] is True


def test_ip_access_preview_matches_matter_scoping_for_inactive_team(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    member_id, member_headers = _invite_admin(
        client,
        owner_token=owner_token,
        name="Inactive Team Reviewer",
        email="inactive-team-reviewer@asterlegal.in",
    )
    team_response = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Former IP Team", "slug": "former-ip-team"},
    )
    assert team_response.status_code == 201, team_response.text
    team_id = str(team_response.json()["id"])
    membership_response = client.post(
        f"/api/teams/{team_id}/members",
        headers=owner_headers,
        json={"membership_id": member_id, "is_lead": False},
    )
    assert membership_response.status_code == 200, membership_response.text
    docket, matter_id = _create_linked_restricted_docket(
        client,
        owner_headers=owner_headers,
    )
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        team = session.get(Team, team_id)
        assert matter is not None and team is not None
        company = session.get(Company, matter.company_id)
        assert company is not None
        matter.team_id = team_id
        matter.restricted_access = False
        team.is_active = False
        company.team_scoping_enabled = True
        session.add(
            EthicalWall(
                company_id=company.id,
                matter_id=matter.id,
                excluded_team_id=team_id,
                reason="Inactive-team walls do not apply to canonical Matter access.",
                created_by_membership_id=str(bootstrap["membership"]["id"]),
            )
        )
        session.commit()

    # Canonical Matter access intentionally retains any existing team
    # membership for the direct team-scoping gate, even after deactivation.
    assert client.get(
        f"/api/matters/{matter_id}", headers=member_headers
    ).status_code == 200
    preview = _preview(
        client,
        headers=owner_headers,
        docket_id=str(docket["id"]),
        payload={
            "action": "set_restricted",
            "expected_access_policy_version": 1,
            "reason": "Align the IP record with canonical Matter visibility.",
            "restricted": False,
        },
    )
    member_effect = next(
        row
        for row in preview["affected_memberships"]
        if row["membership_id"] == member_id
    )
    assert member_effect["after_visible"] is True
    assert member_effect["linked_matter_visible"] is True
    assert preview["linked_matter_mismatch"] is False


def test_ip_access_apply_rolls_back_when_response_panel_cannot_be_built(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.services import matter_access

    bootstrap = bootstrap_company(client)
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    docket, _ = _create_linked_restricted_docket(
        client,
        owner_headers=owner_headers,
    )
    docket_id = str(docket["id"])
    payload: dict[str, object] = {
        "action": "set_restricted",
        "expected_access_policy_version": 1,
        "reason": "Materialize the committed response under lifecycle locks.",
        "restricted": False,
    }
    preview = _preview(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=payload,
    )
    def reject_panel_after_mutation(*args, **kwargs):  # noqa: ARG001
        raise HTTPException(status_code=404, detail="Lifecycle transition won.")

    monkeypatch.setattr(matter_access, "get_ip_access_panel", reject_panel_after_mutation)
    applied = client.post(
        f"/api/ip/dockets/{docket_id}/access/apply",
        headers=owner_headers,
        json={**payload, "preview_token": preview["preview_token"]},
    )
    assert applied.status_code == 404, applied.text
    with get_session_factory()() as session:
        docket_row = session.get(IpDocketRecord, docket_id)
        assert docket_row is not None
        assert docket_row.restricted is True
        assert docket_row.access_policy_version == 1
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "ip.access.set_restricted",
                AuditEvent.ip_docket_id == docket_id,
            )
        )
        assert audit is None


def test_ip_access_wall_workflow_is_effective_dated_and_reversible(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    member_id, member_headers = _invite_admin(
        client,
        owner_token=str(bootstrap["access_token"]),
        name="Conflict Reviewer",
        email="conflict-reviewer@asterlegal.in",
    )
    docket = client.post(
        "/api/ip/dockets",
        headers=owner_headers,
        json={
            "title": "Default-visible ASTER workflow",
            "restricted": False,
            "particulars": _particulars("ASTER WALL"),
        },
    )
    assert docket.status_code == 201, docket.text
    docket_id = str(docket.json()["id"])
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 200

    wall_payload: dict[str, object] = {
        "action": "add_wall",
        "expected_access_policy_version": 0,
        "reason": "Conflict check requires immediate exclusion.",
        "subject_type": "membership",
        "subject_id": member_id,
    }
    wall_preview = _preview(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=wall_payload,
    )
    walled = _apply(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=wall_payload,
        preview=wall_preview,
    )
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 404
    wall = next(row for row in walled["panel"]["walls"] if row["revoked_at"] is None)

    revoke_payload: dict[str, object] = {
        "action": "revoke_wall",
        "expected_access_policy_version": 1,
        "reason": "Conflict review cleared the exclusion.",
        "wall_id": wall["id"],
    }
    revoke_preview = _preview(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=revoke_payload,
    )
    cleared = _apply(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=revoke_payload,
        preview=revoke_preview,
    )
    stored_wall = next(row for row in cleared["panel"]["walls"] if row["id"] == wall["id"])
    assert stored_wall["revoked_at"] is not None
    assert stored_wall["record_version"] == 1
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 200


def test_ip_access_grant_rows_remain_on_the_canonical_owner(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    member_id, _ = _invite_admin(
        client,
        owner_token=str(bootstrap["access_token"]),
        name="Canonical Owner Fixture",
        email="canonical-owner-fixture@asterlegal.in",
    )
    docket = client.post(
        "/api/ip/dockets",
        headers=owner_headers,
        json={
            "title": "Canonical access owner",
            "restricted": True,
            "particulars": _particulars("CANONICAL"),
        },
    ).json()
    payload: dict[str, object] = {
        "action": "grant",
        "expected_access_policy_version": 1,
        "reason": "Canonical storage verification.",
        "subject_type": "membership",
        "subject_id": member_id,
    }
    preview = _preview(
        client,
        headers=owner_headers,
        docket_id=str(docket["id"]),
        payload=payload,
    )
    _apply(
        client,
        headers=owner_headers,
        docket_id=str(docket["id"]),
        payload=payload,
        preview=preview,
    )
    with get_session_factory()() as session:
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == docket["id"],
                MatterAccessGrant.membership_id == member_id,
                MatterAccessGrant.revoked_at.is_(None),
            )
        )
        assert grant is not None
        assert grant.matter_id is None


def test_ip_access_team_grant_and_wall_apply_to_every_active_team_member(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    member_id, member_headers = _invite_admin(
        client,
        owner_token=str(bootstrap["access_token"]),
        name="Team Access Reviewer",
        email="team-access-reviewer@asterlegal.in",
    )
    team_response = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Restricted IP Review", "slug": "restricted-ip-review"},
    )
    assert team_response.status_code == 201, team_response.text
    team_id = str(team_response.json()["id"])
    membership_response = client.post(
        f"/api/teams/{team_id}/members",
        headers=owner_headers,
        json={"membership_id": member_id, "is_lead": False},
    )
    assert membership_response.status_code == 200, membership_response.text
    docket = client.post(
        "/api/ip/dockets",
        headers=owner_headers,
        json={
            "title": "Team-scoped access owner",
            "restricted": True,
            "particulars": _particulars("TEAM ACCESS"),
        },
    ).json()
    docket_id = str(docket["id"])
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 404

    grant_payload: dict[str, object] = {
        "action": "grant",
        "expected_access_policy_version": 1,
        "reason": "The review team needs controlled access.",
        "subject_type": "team",
        "subject_id": team_id,
    }
    grant_preview = _preview(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=grant_payload,
    )
    assert grant_preview["visibility_gain_count"] == 1
    _apply(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=grant_payload,
        preview=grant_preview,
    )
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 200

    wall_payload: dict[str, object] = {
        "action": "add_wall",
        "expected_access_policy_version": 2,
        "reason": "A team conflict now requires exclusion.",
        "subject_type": "team",
        "subject_id": team_id,
    }
    wall_preview = _preview(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=wall_payload,
    )
    assert wall_preview["visibility_loss_count"] == 1
    _apply(
        client,
        headers=owner_headers,
        docket_id=docket_id,
        payload=wall_payload,
        preview=wall_preview,
    )
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 404
