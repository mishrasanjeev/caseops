"""IPLF-073A/B: campaign evidence and canonical access-owner integration."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select

from caseops_api.db.models import (
    AccessReviewCampaign,
    AuditEvent,
    CompanyMembership,
    MatterAccessGrant,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from tests.test_20260909_legal_hold_workflow import make_actors
from tests.test_ip_record_access_workflow import _particulars

BASE = "/api/access-reviews"

# These endpoint templates are exercised through BASE and f-string helpers
# below. Keep the concrete paths visible to the route-coverage audit.
ROUTE_COVERAGE_PATHS = (
    "/api/access-reviews/scope",
    "/api/access-reviews/targets",
    "/api/access-reviews/{campaign_id}",
    "/api/access-reviews/{campaign_id}/decisions",
    "/api/access-reviews/{campaign_id}/finalize",
)


def setup_review(client, kind="ip_docket"):
    owner, reviewer = make_actors(client)
    if kind == "ip_docket":
        response = client.post(
            "/api/ip/dockets",
            headers=owner["headers"],
            json={"title": "Review scope ASTER", "particulars": _particulars("REVIEW")},
        )
    else:
        response = client.post(
            "/api/matters/",
            headers=owner["headers"],
            json={
                "title": "Review scope Matter",
                "matter_code": "REVIEW-M",
                "practice_area": "Intellectual Property",
                "forum_level": "high_court",
                "status": "active",
            },
        )
    assert response.status_code in (200, 201), response.text
    target_id = response.json()["id"]
    with get_session_factory()() as session:
        for actor in (owner, reviewer):
            session.add(
                UserMFAStepUp(
                    user_id=actor["user_id"],
                    membership_id=actor["id"],
                    purpose="record_access_change",
                    method="totp",
                    completed_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            )
        session.add(
            MatterAccessGrant(
                company_id=owner["company_id"],
                membership_id=owner["id"],
                **{"ip_docket_id" if kind == "ip_docket" else "matter_id": target_id},
                reason="Retained explicit access fixture",
            )
        )
        session.commit()
    scope = client.get(
        f"{BASE}/scope", headers=owner["headers"], params={"kind": kind, "target_id": target_id}
    )
    assert scope.status_code == 200, scope.text
    payload = {
        "target_type": kind,
        "target_id": target_id,
        "title": "September access review",
        "reason": "Periodic access certification",
        "trigger": "periodic",
        "expected_access_policy_version": scope.json()["access_policy_version"],
    }
    response = client.post(BASE, headers=owner["headers"], json=payload)
    assert response.status_code == 201, response.text
    return owner, reviewer, response.json(), payload


def decide(client, actor, campaign, decision="revoke", grant_id=None):
    return client.post(
        f"{BASE}/{campaign['id']}/decisions",
        headers=actor["headers"],
        json={
            "expected_version": campaign["version"],
            "grant_id": grant_id or campaign["snapshot"]["grants"][0]["id"],
            "decision": decision,
            "reason": "External engagement has concluded",
        },
    )


def finalize(client, actor, campaign):
    return client.post(
        f"{BASE}/{campaign['id']}/finalize",
        headers=actor["headers"],
        json={"expected_version": campaign["version"]},
    )


@pytest.mark.parametrize("kind", ["matter", "ip_docket"])
@pytest.mark.parametrize("outcome", ["keep", "revoke"])
def test_campaign_completes_through_canonical_owner_and_reloads(client, kind, outcome):
    owner, reviewer, campaign, _ = setup_review(client, kind)
    assert decide(client, owner, campaign).status_code == 409
    reviewed = decide(client, reviewer, campaign, outcome)
    assert reviewed.status_code == 200, reviewed.text
    assert finalize(client, reviewer, reviewed.json()).status_code == 409
    result = finalize(client, owner, reviewed.json())
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "finalized"
    assert finalize(client, owner, reviewed.json()).status_code == 409
    reload = client.get(f"{BASE}/{campaign['id']}", headers=owner["headers"])
    assert reload.json() == result.json()
    grant_id = campaign["snapshot"]["grants"][0]["id"]
    with get_session_factory()() as session:
        grant = session.get(MatterAccessGrant, grant_id)
        if outcome == "keep":
            assert grant is not None and grant.revoked_at is None
        elif kind == "matter":
            assert grant is None
        else:
            assert grant.revoked_at is not None and grant.record_version == 1
        actions = list(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.company_id == owner["company_id"])
            )
        )
        assert all(
            f"access.review.{action}" in actions for action in ("created", "decided", "finalized")
        )
        if outcome == "revoke":
            assert (
                "ip.access.revoke_grant" if kind == "ip_docket" else "matter.access_grant_removed"
            ) in actions


def test_campaign_stale_snapshot_and_decision_version_rejected(client):
    owner, reviewer, campaign, _ = setup_review(client)
    reviewed = decide(client, reviewer, campaign)
    assert reviewed.status_code == 200, reviewed.text
    assert decide(client, reviewer, campaign).status_code == 409
    with get_session_factory()() as session:
        grant = session.get(MatterAccessGrant, campaign["snapshot"]["grants"][0]["id"])
        grant.reason = "Changed after independent review"
        grant.record_version += 1
        session.commit()
    result = finalize(client, owner, reviewed.json())
    assert result.status_code == 409 and "stale" in result.text
    with get_session_factory()() as session:
        assert session.get(AccessReviewCampaign, campaign["id"]).status == "open"
        assert session.get(MatterAccessGrant, grant.id).revoked_at is None


def test_current_reviewer_authorization_and_missing_step_up(client):
    owner, reviewer, campaign, _ = setup_review(client)
    reviewed = decide(client, reviewer, campaign)
    assert reviewed.status_code == 200, reviewed.text
    with get_session_factory()() as session:
        session.get(CompanyMembership, reviewer["id"]).role = "member"
        session.commit()
    denied = finalize(client, owner, reviewed.json())
    assert denied.status_code == 409, denied.text
    assert client.get(BASE, headers=reviewer["headers"]).status_code == 403
    with get_session_factory()() as session:
        for step in session.scalars(
            select(UserMFAStepUp).where(UserMFAStepUp.user_id == owner["user_id"])
        ):
            step.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert finalize(client, owner, reviewed.json()).status_code == 403


def test_cross_tenant_scope_detail_cursor_and_commands_are_hidden(client):
    owner, reviewer, campaign, payload = setup_review(client)
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other review tenant",
            "company_slug": "other-review-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Other owner",
            "owner_email": "other-review@example.com",
            "owner_password": "OtherTenantProof2026!",
        },
    )
    assert response.status_code == 200, response.text
    from tests.test_auth_company import auth_headers

    foreign = auth_headers(response.json()["access_token"])
    client.cookies.clear()
    foreign_auth = response.json()
    with get_session_factory()() as session:
        session.add(UserMFAStepUp(
            user_id=foreign_auth["user"]["id"],
            membership_id=foreign_auth["membership"]["id"],
            purpose="record_access_change", method="totp",
            completed_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        ))
        session.commit()
    assert client.get(BASE, headers=foreign).json()["campaigns"] == []
    for path in (
        f"{BASE}/{campaign['id']}",
        f"{BASE}?before_id={campaign['id']}",
        f"{BASE}/scope?kind=ip_docket&target_id={payload['target_id']}",
    ):
        result = client.get(path, headers=foreign)
        assert result.status_code == 404, result.text
        assert campaign["title"] not in result.text
    assert decide(client, reviewer, campaign, grant_id="foreign-grant").status_code == 404
    assert decide(client, {"headers": foreign}, campaign).status_code == 404
    assert finalize(client, {"headers": foreign}, campaign).status_code == 404
    assert client.post(BASE, headers=foreign, json=payload).status_code == 404
    assert finalize(client, owner, campaign).status_code == 409


def test_campaign_register_keyset_is_batched_bounded_and_preserves_ties(client):
    owner, reviewer, campaign, _ = setup_review(client)
    with get_session_factory()() as session:
        source = session.get(AccessReviewCampaign, campaign["id"])
        for index in range(53):
            session.add(
                AccessReviewCampaign(
                    company_id=source.company_id,
                    ip_docket_id=source.ip_docket_id,
                    title=f"Retained campaign {index}",
                    reason=source.reason,
                    trigger=source.trigger,
                    creator_user_id=source.creator_user_id,
                    snapshot_json=source.snapshot_json,
                    snapshot_hash=source.snapshot_hash,
                    created_at=source.created_at,
                )
            )
        session.commit()
        engine = session.get_bind()
    statements, seen, cursor = [], [], None

    def capture(_conn, _cursor, sql, *_args):
        if "FROM access_review_" in sql:
            statements.append(sql)

    for page in range(3):
        statements.clear()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = client.get(
                BASE, headers=reviewer["headers"], params={"before_id": cursor} if cursor else {}
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert result.status_code == 200, result.text
        assert len(statements) == (2 if page == 0 else 3), statements
        assert "LIMIT" in statements[-1]
        seen.extend(row["id"] for row in result.json()["campaigns"])
        cursor = result.json()["next_before_id"]
    assert cursor is None and len(seen) == len(set(seen)) == 54


def test_team_subject_cannot_review_itself_and_team_change_stales_snapshot(client):
    from caseops_api.db.models import Team, TeamMembership

    owner, reviewer, campaign, payload = setup_review(client)
    with get_session_factory()() as session:
        team = Team(company_id=owner["company_id"], name="Reviewer's own team", slug="review-team")
        session.add(team)
        session.flush()
        session.add(TeamMembership(team_id=team.id, membership_id=reviewer["id"]))
        session.add(
            MatterAccessGrant(
                company_id=owner["company_id"], ip_docket_id=payload["target_id"], team_id=team.id
            )
        )
        session.commit()
        team_id = team.id
    opened = client.post(BASE, headers=owner["headers"], json=payload)
    assert opened.status_code == 201, opened.text
    team_campaign = opened.json()
    grant = next(g for g in team_campaign["snapshot"]["grants"] if g["subject_type"] == "team")
    rejected = decide(client, reviewer, team_campaign, grant_id=grant["id"])
    assert rejected.status_code == 409 and "own membership or team" in rejected.text
    with get_session_factory()() as session:
        session.add(TeamMembership(team_id=team_id, membership_id=owner["id"]))
        session.commit()
    stale = decide(client, reviewer, team_campaign)
    assert stale.status_code == 409 and "stale" in stale.text


def test_inventory_limit_fails_without_partial_campaign_or_hidden_truncation(client):
    from caseops_api.db.models import Team

    owner, reviewer, campaign, payload = setup_review(client)
    with get_session_factory()() as session:
        for index in range(20):
            team = Team(
                company_id=owner["company_id"],
                name=f"Review team {index}",
                slug=f"review-team-{index}",
            )
            session.add(team)
            session.flush()
            session.add(
                MatterAccessGrant(
                    company_id=owner["company_id"],
                    ip_docket_id=payload["target_id"],
                    team_id=team.id,
                )
            )
        session.commit()
    for response in (
        client.get(
            f"{BASE}/scope",
            headers=owner["headers"],
            params={"kind": "ip_docket", "target_id": payload["target_id"]},
        ),
        client.post(BASE, headers=owner["headers"], json=payload),
    ):
        assert response.status_code == 409 and "20-grant" in response.text
    assert len(client.get(BASE, headers=reviewer["headers"]).json()["campaigns"]) == 1


def test_current_visibility_hides_campaign_metadata_after_scope_restriction(client):
    from caseops_api.db.models import IpDocketRecord

    owner, reviewer, campaign, payload = setup_review(client)
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, payload["target_id"])
        docket.restricted = True
        docket.access_policy_version += 1
        session.commit()
    assert client.get(BASE, headers=reviewer["headers"]).json()["campaigns"] == []
    assert client.get(f"{BASE}/{campaign['id']}", headers=reviewer["headers"]).status_code == 404
    assert decide(client, reviewer, campaign).status_code == 404


def test_failed_second_revocation_rolls_back_first_and_retains_review(client, monkeypatch):
    from fastapi import HTTPException

    from caseops_api.db.models import Team
    from caseops_api.services import matter_access

    owner, reviewer, campaign, payload = setup_review(client)
    with get_session_factory()() as session:
        team = Team(
            company_id=owner["company_id"], name="Completed counsel", slug="completed-counsel"
        )
        session.add(team)
        session.flush()
        session.add(
            MatterAccessGrant(
                company_id=owner["company_id"], ip_docket_id=payload["target_id"], team_id=team.id
            )
        )
        session.commit()
    campaign = client.post(BASE, headers=owner["headers"], json=payload).json()
    for grant in campaign["snapshot"]["grants"]:
        response = decide(client, reviewer, campaign, grant_id=grant["id"])
        assert response.status_code == 200, response.text
        campaign = response.json()
    original = matter_access.apply_ip_access_change
    calls = []

    def fail_second(session, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise HTTPException(status_code=409, detail="Deterministic second-command conflict")
        assert kwargs["commit"] is False
        return original(session, **kwargs)

    monkeypatch.setattr(matter_access, "apply_ip_access_change", fail_second)
    rejected = finalize(client, owner, campaign)
    assert rejected.status_code == 409, rejected.text
    assert len(calls) == 2
    with get_session_factory()() as session:
        assert all(
            session.get(MatterAccessGrant, g["id"]).revoked_at is None
            for g in campaign["snapshot"]["grants"]
        )
        assert session.get(AccessReviewCampaign, campaign["id"]).status == "open"
        assert (
            session.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.company_id == owner["company_id"],
                    AuditEvent.action == "ip.access.revoke_grant",
                )
            )
            is None
        )
    monkeypatch.setattr(matter_access, "apply_ip_access_change", original)
    completed = finalize(client, owner, campaign)
    assert completed.status_code == 200, completed.text


def test_retained_access_history_is_charged_before_canonical_execution(client):
    owner, reviewer, campaign, payload = setup_review(client)
    response = decide(client, reviewer, campaign)
    assert response.status_code == 200, response.text
    campaign = response.json()
    with get_session_factory()() as session:
        for _ in range(256):
            session.add(
                MatterAccessGrant(
                    company_id=owner["company_id"],
                    ip_docket_id=payload["target_id"],
                    membership_id=owner["id"],
                    revoked_at=datetime.now(UTC),
                )
            )
        session.commit()
    rejected = finalize(client, owner, campaign)
    assert rejected.status_code == 409 and "256-row matter_access_grants" in rejected.text
    with get_session_factory()() as session:
        assert (
            session.get(MatterAccessGrant, campaign["snapshot"]["grants"][0]["id"]).revoked_at
            is None
        )
        assert session.get(AccessReviewCampaign, campaign["id"]).status == "open"


def test_terminal_target_cannot_be_selected_or_finalized_but_evidence_remains_readable(client):
    from caseops_api.db.models import IpDocketRecord

    owner, reviewer, campaign, payload = setup_review(client)
    response = decide(client, reviewer, campaign)
    assert response.status_code == 200, response.text
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, payload["target_id"])
        docket.is_active = False
        docket.status = "archived"
        session.commit()
    options = client.get(f"{BASE}/targets", headers=owner["headers"], params={"kind": "ip_docket"})
    assert options.status_code == 200 and options.json()["targets"] == []
    assert finalize(client, owner, response.json()).status_code == 409
    assert client.get(f"{BASE}/{campaign['id']}", headers=owner["headers"]).status_code == 200
