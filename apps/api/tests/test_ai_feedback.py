from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AIFeedbackItem,
    AssistantSession,
    AssistantSessionStatus,
    AssistantTurn,
    AssistantTurnRole,
    AssistantTurnStatus,
    AuditEvent,
    CompanyMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _catalog_fingerprint(client: TestClient) -> str:
    response = client.get("/api/product-guide/catalog")
    assert response.status_code == 200
    return str(response.json()["catalog_fingerprint"])


def _product_payload(
    fingerprint: str,
    *,
    submission_key: str = "product-rating-0001",
) -> dict[str, object]:
    return {
        "submission_key": submission_key,
        "target_type": "product_guide_command",
        "target_id": "deadline-control",
        "catalog_fingerprint": fingerprint,
        "feedback_type": "rating",
        "rating": "helpful",
    }


def test_product_guide_feedback_is_catalog_validated_and_idempotent(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    fingerprint = _catalog_fingerprint(client)
    payload = _product_payload(fingerprint)

    created = client.post("/api/ai-feedback/product-guide", headers=headers, json=payload)
    replay = client.post("/api/ai-feedback/product-guide", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == created.json()["id"]
    assert created.json()["target_href"] == "/app/ip/docket"

    conflict_payload = {**payload, "rating": "not_helpful"}
    conflict = client.post(
        "/api/ai-feedback/product-guide",
        headers=headers,
        json=conflict_payload,
    )
    assert conflict.status_code == 409

    invented = client.post(
        "/api/ai-feedback/product-guide",
        headers=headers,
        json={
            **_product_payload(fingerprint, submission_key="product-rating-0002"),
            "target_id": "invented",
        },
    )
    stale = client.post(
        "/api/ai-feedback/product-guide",
        headers=headers,
        json={**_product_payload("0" * 64, submission_key="product-rating-0003")},
    )
    assert invented.status_code == 422
    assert stale.status_code == 409

    with get_session_factory()() as session:
        rows = list(session.scalars(select(AIFeedbackItem)))
        assert len(rows) == 1
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "ai.feedback.submitted")
        )
        assert audit is not None
        assert audit.metadata_json is not None
        assert "deadline-control" not in audit.metadata_json


def test_feedback_routes_apply_surface_specific_authorization(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    created_viewer = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Feedback Viewer",
            "email": "feedback-viewer@example.in",
            "password": "FeedbackViewer123!",
            "role": "viewer",
        },
    )
    assert created_viewer.status_code == 200, created_viewer.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "feedback-viewer@example.in",
            "password": "FeedbackViewer123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    viewer_headers = auth_headers(str(login.json()["access_token"]))

    product_feedback = client.post(
        "/api/ai-feedback/product-guide",
        headers=viewer_headers,
        json=_product_payload(
            _catalog_fingerprint(client),
            submission_key="viewer-product-rating-0001",
        ),
    )
    assert product_feedback.status_code == 201, product_feedback.text

    assistant_feedback = client.post(
        "/api/ai-feedback/workspace-assistant",
        headers=viewer_headers,
        json={
            "submission_key": "viewer-assistant-rating-0001",
            "session_id": "00000000-0000-4000-8000-000000000001",
            "turn_id": "00000000-0000-4000-8000-000000000002",
            "feedback_type": "rating",
            "rating": "not_helpful",
        },
    )
    assert assistant_feedback.status_code == 403


def test_admin_queue_is_bounded_versioned_terminal_and_audit_redacted(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    fingerprint = _catalog_fingerprint(client)
    comment = "The cited destination appears unsafe for this workflow."
    created = client.post(
        "/api/ai-feedback/product-guide",
        headers=owner_headers,
        json={
            "submission_key": "product-report-0001",
            "target_type": "product_guide_section",
            "target_id": "getting-started",
            "catalog_fingerprint": fingerprint,
            "feedback_type": "report",
            "category": "unsafe_citation",
            "comment": comment,
        },
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["priority"] == "high"

    member = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Feedback Member",
            "email": "feedback-member@example.in",
            "password": "FeedbackMember123!",
            "role": "member",
        },
    )
    assert member.status_code == 200, member.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "feedback-member@example.in",
            "password": "FeedbackMember123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/admin/ai-feedback",
        headers=auth_headers(str(login.json()["access_token"])),
    )
    assert denied.status_code == 403

    listed = client.get(
        "/api/admin/ai-feedback",
        headers=owner_headers,
        params={"status": "open", "surface": "product_guide", "limit": 1},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["id"] == record["id"]
    assert listed.json()["limit"] == 1

    in_review = client.patch(
        f"/api/admin/ai-feedback/{record['id']}",
        headers=owner_headers,
        json={
            "expected_updated_at": record["updated_at"],
            "status": "in_review",
            "review_notes": "Verify the canonical destination before disposition.",
        },
    )
    assert in_review.status_code == 200, in_review.text
    stale = client.patch(
        f"/api/admin/ai-feedback/{record['id']}",
        headers=owner_headers,
        json={
            "expected_updated_at": record["updated_at"],
            "status": "resolved",
        },
    )
    assert stale.status_code == 409

    reviewed = in_review.json()
    resolved = client.patch(
        f"/api/admin/ai-feedback/{record['id']}",
        headers=owner_headers,
        json={
            "expected_updated_at": reviewed["updated_at"],
            "status": "resolved",
            "review_notes": "Canonical destination verified.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    reopen = client.patch(
        f"/api/admin/ai-feedback/{record['id']}",
        headers=owner_headers,
        json={
            "expected_updated_at": resolved.json()["updated_at"],
            "status": "in_review",
        },
    )
    assert reopen.status_code == 409

    with get_session_factory()() as session:
        audits = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action.like("ai.feedback.%"))
            )
        )
        assert len(audits) == 3
        encoded = json.dumps([row.metadata_json for row in audits])
        assert comment not in encoded
        assert "Canonical destination verified" not in encoded


def test_workspace_feedback_is_creator_private_and_tenant_fenced(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])

    member_response = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Private Assistant User",
            "email": "private-assistant@example.in",
            "password": "PrivateAssistant123!",
            "role": "member",
        },
    )
    assert member_response.status_code == 200, member_response.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "private-assistant@example.in",
            "password": "PrivateAssistant123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    member_token = str(login.json()["access_token"])

    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.email == "private-assistant@example.in"))
        assert user is not None
        membership = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.user_id == user.id,
            )
        )
        assert membership is not None
        assistant_session = AssistantSession(
            company_id=company_id,
            created_by_membership_id=membership.id,
            title="Private feedback target",
            status=AssistantSessionStatus.ACTIVE,
            version=1,
            policy_version=1,
            policy_snapshot_json={},
            retention_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        session.add(assistant_session)
        session.flush()
        answer = "Private answer text that must not be copied into feedback storage."
        turn = AssistantTurn(
            company_id=company_id,
            session_id=assistant_session.id,
            sequence=2,
            role=AssistantTurnRole.ASSISTANT,
            status=AssistantTurnStatus.COMPLETED,
            content_text=answer,
            content_sha256="a" * 64,
            retrieval_manifest_json={},
            permission_snapshot_json={},
            created_by_membership_id=membership.id,
        )
        session.add(turn)
        session.commit()
        session_id = assistant_session.id
        turn_id = turn.id

    payload = {
        "submission_key": "assistant-rating-0001",
        "session_id": session_id,
        "turn_id": turn_id,
        "feedback_type": "rating",
        "rating": "not_helpful",
    }
    created = client.post(
        "/api/ai-feedback/workspace-assistant",
        headers=auth_headers(member_token),
        json=payload,
    )
    assert created.status_code == 201, created.text
    owner_denied = client.post(
        "/api/ai-feedback/workspace-assistant",
        headers=owner_headers,
        json={**payload, "submission_key": "assistant-rating-0002"},
    )
    assert owner_denied.status_code == 404

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Feedback Other Tenant",
            "company_slug": "feedback-other-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "other-feedback@example.in",
            "owner_password": "OtherFeedback123!",
        },
    )
    assert other.status_code == 200, other.text
    cross_tenant = client.post(
        "/api/ai-feedback/workspace-assistant",
        headers=auth_headers(str(other.json()["access_token"])),
        json={**payload, "submission_key": "assistant-rating-0003"},
    )
    assert cross_tenant.status_code == 404

    with get_session_factory()() as session:
        item = session.scalar(
            select(AIFeedbackItem).where(AIFeedbackItem.target_id == turn_id)
        )
        assert item is not None
        assert item.parent_target_id == session_id
        assert item.target_href is None
        assert answer not in json.dumps(item.__dict__, default=str)
        assert item.submitted_by_membership_id != owner_membership_id
