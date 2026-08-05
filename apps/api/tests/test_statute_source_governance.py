from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Statute, StatuteSection, StatuteSourceVersion
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.seed_statutes import _seed
from caseops_api.services.source_actions import inspect_source_action
from caseops_api.services.statute_source_governance import probe_statute_source
from tests.test_auth_company import auth_headers, bootstrap_company


def _setup_reviewers(client: TestClient) -> tuple[str, str]:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Independent Reviewer",
            "email": "reviewer@asterlegal.in",
            "password": "ReviewerPass123!",
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "reviewer@asterlegal.in",
            "password": "ReviewerPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    return owner_token, str(login.json()["access_token"])


def _seed_section() -> str:
    with get_session_factory()() as session:
        statute = Statute(
            id="trust-act-2026",
            short_name="Trust Act",
            long_name="Source Trust Act, 2026",
            enacted_year=2026,
            source_url="https://www.indiacode.nic.in/handle/123456789/2026",
        )
        section = StatuteSection(
            statute_id=statute.id,
            section_number="12",
            section_label="Source review",
            section_text="Unreviewed candidate text must remain hidden from legal users.",
            section_text_source="seed_catalog",
            section_text_fetched_at=datetime.now(UTC),
            source_publisher="India Code",
            verification_status="unverified",
            source_version=1,
            is_provisional=True,
        )
        session.add_all([statute, section])
        session.commit()
        return section.id


def _proposal_payload(*, expected_source_version: int = 1) -> dict:
    return {
        "expected_source_version": expected_source_version,
        "candidate_text": (
            "Section 12. Every statutory source must complete independent "
            "curator review before it may be used as enacted legal text."
        ),
        "source_url": (
            "https://www.indiacode.nic.in/show-data?actid=trust-2026&orderno=12"
        ),
        "source_publisher": "India Code",
        "issuing_body": "Legislative Department, Ministry of Law and Justice",
        "source_category": "consolidated_statute",
        "source_status": "official",
        "legal_status": "enacted",
        "source_locator_type": "section_deep_link",
        "exact_source_version": "consolidated-2026-08-04",
        "retrieved_at": "2026-08-04T10:00:00Z",
        "publication_date": "2026-01-01",
        "effective_from": "2026-02-01",
        "amendment_metadata": {"current_through": "2026-08-04"},
        "source_policy": {},
    }


def test_unreviewed_official_url_is_not_openable() -> None:
    action = inspect_source_action(
        "https://www.indiacode.nic.in/show-data?actid=x&orderno=12",
        verified=False,
    )
    assert action.state == "unverified"
    assert action.open_url is None


def test_two_person_source_review_is_atomic_versioned_and_fail_closed(
    client: TestClient,
) -> None:
    proposer_token, reviewer_token = _setup_reviewers(client)
    section_id = _seed_section()

    hidden = client.get(
        "/api/statutes/trust-act-2026/sections",
        headers=auth_headers(proposer_token),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["sections"] == []

    landing_page = _proposal_payload()
    landing_page["source_url"] = (
        "https://www.indiacode.nic.in/handle/123456789/2026"
    )
    rejected_landing = client.post(
        f"/api/statutes/verification/sections/{section_id}/source-versions",
        headers=auth_headers(proposer_token),
        json=landing_page,
    )
    assert rejected_landing.status_code == 409
    assert "landing page" in rejected_landing.json()["detail"]

    proposal = client.post(
        f"/api/statutes/verification/sections/{section_id}/source-versions",
        headers=auth_headers(proposer_token),
        json=_proposal_payload(),
    )
    assert proposal.status_code == 201, proposal.text
    proposal_body = proposal.json()
    assert proposal_body["status"] == "pending"
    assert len(proposal_body["candidate_sha256"]) == 64
    assert proposal_body["diff_unified"]

    self_review = client.post(
        f"/api/statutes/verification/source-versions/{proposal_body['id']}/decision",
        headers=auth_headers(proposer_token),
        json={
            "expected_source_version": 1,
            "decision": "approve",
            "reason": "Compared against the exact official consolidation.",
        },
    )
    assert self_review.status_code == 409

    with patch(
        "caseops_api.services.statute_source_governance.probe_statute_source",
        return_value=("available", None),
    ):
        approved = client.post(
            f"/api/statutes/verification/source-versions/{proposal_body['id']}/decision",
            headers=auth_headers(reviewer_token),
            json={
                "expected_source_version": 1,
                "decision": "approve",
                "reason": "Compared against the exact official consolidation.",
            },
        )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    visible = client.get(
        "/api/statutes/trust-act-2026/sections",
        headers=auth_headers(proposer_token),
    )
    assert visible.status_code == 200, visible.text
    assert [row["section_number"] for row in visible.json()["sections"]] == ["12"]
    detail = client.get(
        "/api/statutes/trust-act-2026/sections/12",
        headers=auth_headers(proposer_token),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["section"]["source_action"]["state"] == "available"
    assert detail.json()["section"]["section_text"].startswith("Section 12")

    stale = client.post(
        f"/api/statutes/verification/sections/{section_id}/source-versions",
        headers=auth_headers(proposer_token),
        json=_proposal_payload(expected_source_version=1),
    )
    assert stale.status_code == 409

    changed = _proposal_payload(expected_source_version=2)
    changed["candidate_text"] += " The amended consolidation is preserved separately."
    next_version = client.post(
        f"/api/statutes/verification/sections/{section_id}/source-versions",
        headers=auth_headers(proposer_token),
        json=changed,
    )
    assert next_version.status_code == 201, next_version.text
    assert next_version.json()["proposed_source_version"] == 3


def test_rejected_candidate_preserves_canonical_text(client: TestClient) -> None:
    proposer_token, reviewer_token = _setup_reviewers(client)
    section_id = _seed_section()
    proposal = client.post(
        f"/api/statutes/verification/sections/{section_id}/source-versions",
        headers=auth_headers(proposer_token),
        json=_proposal_payload(),
    )
    proposal_id = proposal.json()["id"]
    rejected = client.post(
        f"/api/statutes/verification/source-versions/{proposal_id}/decision",
        headers=auth_headers(reviewer_token),
        json={
            "expected_source_version": 1,
            "decision": "reject",
            "reason": "The candidate contains an unresolved consolidation mismatch.",
        },
    )
    assert rejected.status_code == 200, rejected.text
    with get_session_factory()() as session:
        section = session.get(StatuteSection, section_id)
        assert section.section_text.startswith("Unreviewed candidate")
        assert section.verification_status == "unverified"
        assert section.source_version == 1
        proposal_row = session.scalar(
            select(StatuteSourceVersion).where(StatuteSourceVersion.id == proposal_id)
        )
        assert proposal_row.status == "rejected"


def test_link_probe_returns_typed_health_without_following_redirects() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(403, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        health, error = probe_statute_source(
            source_url="https://www.indiacode.nic.in/show-data?actid=x&orderno=12",
            source_status="official",
            source_policy={},
            client=client,
        )
    assert health == "protected"
    assert error == "http_403"
    assert seen[0].method == "HEAD"


def test_link_check_route_persists_typed_health(client: TestClient) -> None:
    owner_token, _ = _setup_reviewers(client)
    section_id = _seed_section()
    with get_session_factory()() as session:
        section = session.get(StatuteSection, section_id)
        assert section is not None
        section.section_url = (
            "https://www.indiacode.nic.in/show-data?actid=trust-2026&orderno=12"
        )
        section.source_status = "official"
        section.source_locator_type = "section_deep_link"
        session.commit()

    with patch(
        "caseops_api.services.statute_source_governance.probe_statute_source",
        return_value=("protected", "http_403"),
    ):
        response = client.post(
            f"/api/statutes/verification/sections/{section_id}/link-check",
            headers=auth_headers(owner_token),
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "section_id": section_id,
        "source_version": 1,
        "status": "protected",
        "checked_at": response.json()["checked_at"],
        "error_class": "http_403",
    }
    assert response.json()["checked_at"]
    with get_session_factory()() as session:
        section = session.get(StatuteSection, section_id)
        assert section is not None
        assert section.link_health_status == "protected"
        assert section.link_last_error == "http_403"
        assert section.link_last_checked_at is not None
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "statute_source_link.checked",
                AuditEvent.target_id == section_id,
            )
        )
        assert audit is not None
        assert audit.result == "protected"


def test_conflict_quarantines_immediately_and_decision_does_not_reactivate(
    client: TestClient,
) -> None:
    creator_token, reviewer_token = _setup_reviewers(client)
    section_id = _seed_section()
    opened = client.post(
        f"/api/statutes/verification/sections/{section_id}/conflicts",
        headers=auth_headers(creator_token),
        json={
            "expected_source_version": 1,
            "disputed_facts": {"effective_date": ["2026-02-01", "2026-03-01"]},
            "source_versions": [{"version": "A"}, {"version": "B"}],
            "authority_rank": {"A": 1, "B": 2},
            "affected_records": [{"type": "draft", "id": "draft-1"}],
            "impact_scan": {"completed": True, "count": 1},
        },
    )
    assert opened.status_code == 201, opened.text
    decided = client.post(
        f"/api/statutes/verification/conflicts/{opened.json()['id']}/decision",
        headers=auth_headers(reviewer_token),
        json={"decision": "Use version A after a new controlled source proposal."},
    )
    assert decided.status_code == 200, decided.text
    curator_search = client.get(
        "/api/statutes/verification/sections?verification_status=quarantined",
        headers=auth_headers(reviewer_token),
    )
    assert curator_search.status_code == 200, curator_search.text
    assert [row["id"] for row in curator_search.json()["sections"]] == [section_id]
    with get_session_factory()() as session:
        section = session.get(StatuteSection, section_id)
        assert section.verification_status == "quarantined"
        assert section.source_version == 2


def test_seed_job_cannot_downgrade_verified_provision(client: TestClient) -> None:
    bootstrap_company(client)
    with get_session_factory()() as session:
        _seed(session)
        section = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "ipc-1860",
                StatuteSection.section_number == "Section 302",
            )
        )
        section.section_text = "Reviewed canonical text that the seed must never replace."
        section.section_text_source = "official_source"
        section.verification_status = "verified_official"
        section.source_version = 9
        section.source_sha256 = "a" * 64
        section.section_url = (
            "https://www.indiacode.nic.in/show-data?actid=ipc&orderno=302"
        )
        session.commit()
        _seed(session)
        session.refresh(section)
        assert section.section_text.startswith("Reviewed canonical text")
        assert section.verification_status == "verified_official"
        assert section.source_version == 9


def test_licensed_policy_can_prohibit_export_without_blocking_internal_use(
    client: TestClient,
) -> None:
    proposer_token, _ = _setup_reviewers(client)
    section_id = _seed_section()
    payload = _proposal_payload()
    payload.update(
        {
            "source_url": "https://licensed.example/statutes/trust/section-12",
            "source_status": "licensed",
            "source_policy": {
                "lawful_access_approved": True,
                "permitted_uses": [
                    "fetch",
                    "cache",
                    "display",
                    "ai_retrieval",
                    "retention",
                    "deletion",
                ],
                "prohibited_uses": ["export", "redistribution"],
                "link_check_approved": False,
            },
        }
    )
    response = client.post(
        f"/api/statutes/verification/sections/{section_id}/source-versions",
        headers=auth_headers(proposer_token),
        json=payload,
    )
    assert response.status_code == 201, response.text
    assert response.json()["source_status"] == "licensed"
