from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentType,
    MatterForumLevel,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str) -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Drafting studio test — {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
            "description": "Seeded for drafting studio tests.",
            "court_name": "Delhi High Court",
            "judge_name": "Hon'ble Mr. Justice Bench",
            "client_name": "Aster Industries",
            "opposing_party": "State of Karnataka",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _seed_authority(
    neutral_citation: str = "2024 SCC OnLine SC 111",
    document_type: AuthorityDocumentType = AuthorityDocumentType.JUDGMENT,
) -> str:
    """Insert an AuthorityDocument directly so the citation verifier has
    something to match against."""
    factory = get_session_factory()
    session = factory()
    try:
        doc = AuthorityDocument(
            id=str(uuid.uuid4()),
            source="seed-tests",
            adapter_name="seed",
            court_name="Supreme Court of India",
            forum_level=MatterForumLevel.SUPREME_COURT,
            document_type=document_type,
            title="Seed authority for drafting tests",
            case_reference=None,
            bench_name="Bench",
            neutral_citation=neutral_citation,
            decision_date=date(2024, 3, 15),
            canonical_key=f"seed::{neutral_citation}",
            source_reference=None,
            summary=(
                "The Court held that the parties must comply with the "
                "procedural directions framed in the earlier order, "
                "subject to the reliefs prayed for in the present matter."
            ),
            document_text=None,
            ingested_at=datetime.now(UTC),
        )
        session.add(doc)
        session.commit()
        return str(doc.id)
    finally:
        session.close()


def _create_draft(client: TestClient, token: str, matter_id: str) -> dict:
    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Interim reply brief", "draft_type": "brief"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _generate(client: TestClient, token: str, matter_id: str, draft_id: str) -> dict:
    resp = client.post(
        f"/api/matters/{matter_id}/drafts/{draft_id}/generate",
        headers=auth_headers(token),
        json={},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_draft_starts_empty_and_review_required(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-001")

    draft = _create_draft(client, token, matter_id)
    assert draft["status"] == "draft"
    assert draft["review_required"] is True
    assert draft["versions"] == []
    assert draft["current_version_id"] is None


def test_generate_creates_version_and_resets_status(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-002")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 222")

    draft = _create_draft(client, token, matter_id)
    regenerated = _generate(client, token, matter_id, draft["id"])

    assert regenerated["status"] == "draft"
    assert regenerated["review_required"] is True
    assert len(regenerated["versions"]) == 1
    version = regenerated["versions"][0]
    assert version["revision"] == 1
    assert version["body"].startswith("Brief in")
    # Mock emits the seeded citation since retrieval returns one hit.
    assert version["verified_citation_count"] >= 1
    assert regenerated["current_version_id"] == version["id"]


def test_state_machine_submit_request_changes_submit_approve_finalize(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-003")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 333")

    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    submitted = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={"notes": "Ready for review."},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "in_review"

    reverted = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/request-changes",
        headers=auth_headers(token),
        json={"notes": "Tighten prayer clause."},
    )
    assert reverted.status_code == 200
    assert reverted.json()["status"] == "changes_requested"

    resubmit = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    assert resubmit.status_code == 200
    assert resubmit.json()["status"] == "in_review"

    approved = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={"notes": "Approved."},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved"
    assert body["review_required"] is False

    finalized = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/finalize",
        headers=auth_headers(token),
        json={},
    )
    assert finalized.status_code == 200
    assert finalized.json()["status"] == "finalized"

    # Review audit trail records every transition.
    actions = [r["action"] for r in finalized.json()["reviews"]]
    assert actions == ["submit", "request_changes", "submit", "approve", "finalize"]


def test_approve_blocked_when_no_verified_citations(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-004")
    # No authorities seeded — retrieval returns nothing, mock produces a
    # draft with no citations, so approve must fail closed.

    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    submitted = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "in_review"

    approve = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    assert approve.status_code == 422
    assert "verified citations" in approve.json()["detail"]

    # Seeded citations after the fact — regenerate to pick them up, then approve.
    _seed_authority(neutral_citation="2024 SCC OnLine SC 444")
    _generate(client, token, matter_id, draft["id"])
    # Regenerating resets status back to 'draft' — we must submit again.
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    approve2 = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    assert approve2.status_code == 200
    assert approve2.json()["status"] == "approved"


def test_finalized_draft_rejects_further_transitions(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-005")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 555")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/finalize",
        headers=auth_headers(token),
        json={},
    )

    # Submit / approve / regenerate / finalize all refused now.
    for path in ("submit", "approve", "finalize"):
        resp = client.post(
            f"/api/matters/{matter_id}/drafts/{draft['id']}/{path}",
            headers=auth_headers(token),
            json={},
        )
        assert resp.status_code == 409, resp.text

    regen = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/generate",
        headers=auth_headers(token),
        json={},
    )
    assert regen.status_code == 409


def test_drafts_list_is_tenant_scoped(client: TestClient) -> None:
    token_a = str(bootstrap_company(client)["access_token"])
    matter_a = _create_matter(client, token_a, "DS-TEN-A")
    draft_a = _create_draft(client, token_a, matter_a)

    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Firm",
            "company_slug": "second-drafts-firm",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@seconddrafts.in",
            "owner_password": "SecondPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    token_b = str(resp.json()["access_token"])

    cross = client.get(
        f"/api/matters/{matter_a}/drafts/{draft_a['id']}",
        headers=auth_headers(token_b),
    )
    assert cross.status_code == 404


def test_docx_export_returns_a_word_document(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-DOCX")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 777")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/export.docx",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert ".docx" in disposition
    # A valid DOCX is a ZIP archive — it starts with "PK\x03\x04".
    assert resp.content[:4] == b"PK\x03\x04"
    assert len(resp.content) > 2000  # sanity — a real .docx has meaningful bulk


def test_docx_export_404_on_unknown_draft(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-DOCX-NF")
    resp = client.get(
        f"/api/matters/{matter_id}/drafts/00000000-0000-0000-0000-000000000000/export.docx",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_generate_increments_revision_and_keeps_history(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-006")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 666")
    draft = _create_draft(client, token, matter_id)
    first = _generate(client, token, matter_id, draft["id"])
    assert first["versions"][0]["revision"] == 1
    second = _generate(client, token, matter_id, draft["id"])
    revisions = sorted(v["revision"] for v in second["versions"])
    assert revisions == [1, 2]
    # current_version_id tracks the newest version.
    newest = next(v for v in second["versions"] if v["revision"] == 2)
    assert second["current_version_id"] == newest["id"]


def test_generate_draft_provider_error_returns_actionable_422(
    client: TestClient, monkeypatch,
) -> None:
    """Hari-III-BUG-019 + Strict Ledger #7 (2026-04-22) — mirrors
    the recommendations regression for the drafting endpoint. The
    Hari III sheet numbers this drafting bug as 'BUG-019'; the
    Hari II sheet numbered an outside-counsel bug as 'BUG-019'
    (see test_hari_ii_regressions.py). Always use the
    Hari-II / Hari-III prefix when cross-referencing.

    AnthropicProvider wraps
    503 / httpx timeout in ``LLMProviderError`` (parent of
    ``LLMResponseFormatError``). Before commit 4104265 the drafting
    service caught only the format-error child; 503s escaped past
    the Haiku fallback and surfaced as opaque 500s with no
    actionable detail.

    Regression: when the primary provider raises
    ``LLMProviderError`` AND the Haiku fallback is unavailable, the
    endpoint MUST return a 422 with detail that names the failure
    shape and tells the user what to do — not a 500 with no body.
    """
    from caseops_api.services.llm import LLMMessage, LLMProviderError

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-PROVIDER-503")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 503")
    draft = _create_draft(client, token, matter_id)

    class _OverloadedProvider:
        name = "mock"
        model = "mock-overload-503"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            raise LLMProviderError(
                "Anthropic call failed: 503 overloaded — please retry",
            )

    monkeypatch.setattr(
        "caseops_api.services.drafting.build_provider",
        lambda *a, **kw: _OverloadedProvider(),
    )
    # Force the no-fallback branch so we test the worst-case detail.
    monkeypatch.setattr(
        "caseops_api.services.drafting._haiku_fallback_provider",
        lambda: None,
    )

    resp = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/generate",
        headers=auth_headers(token),
        json={},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "primary model" in detail
    assert "LLMProviderError" in detail
    # Either retry-with-time-window or support contact must be present
    # so the user always has a next step.
    lowered = detail.lower()
    assert "retry" in lowered or "support" in lowered


def test_create_draft_stepper_facts_passthrough(client: TestClient) -> None:
    """R-UI: the stepper POSTs template_type + facts; both must be
    persisted and surfaced on the response, and the fact values must
    land in the LLM prompt so the generator can ground the body.
    """
    import json

    from caseops_api.db.models import Draft
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-FACTS")

    facts = {
        "applicant_name": "Aastha Mishra",
        "fir_number": "FIR 123/2026",
        "section_number": "BNS s.303",
        "period_of_custody_days": 45,
    }
    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Bail application — BNSS s.483",
            "draft_type": "brief",
            "template_type": "bail_application",
            "facts": facts,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_type"] == "bail_application"

    # DB row carries the full facts_json + template_type.
    factory = get_session_factory()
    session = factory()
    try:
        row = session.get(Draft, body["id"])
        assert row is not None
        assert row.template_type == "bail_application"
        assert row.facts_json is not None
        assert json.loads(row.facts_json) == facts
    finally:
        session.close()


def test_generate_draft_uses_stepper_facts_in_prompt(client: TestClient) -> None:
    """Prompt-assembly regression: when the Draft has facts_json set,
    the generated body echoes those facts rather than inserting
    bracketed placeholders."""
    from unittest.mock import patch

    from caseops_api.services import drafting as drafting_service

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-FACTS-2")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 777")

    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Bail — stepper-driven",
            "draft_type": "brief",
            "template_type": "bail_application",
            "facts": {"applicant_name": "Ravi Verma", "fir_number": "FIR 9/2026"},
        },
    )
    assert resp.status_code == 200, resp.text
    draft_id = resp.json()["id"]

    original_build = drafting_service._build_messages
    captured: dict[str, str] = {}

    def _spy(matter, draft, retrieved, focus_note, **kwargs):
        # **kwargs accepts the bench_context BAAD-001 slice 3 added
        # to _build_messages without breaking this test's spy.
        msgs = original_build(matter, draft, retrieved, focus_note, **kwargs)
        captured["user"] = next(m.content for m in msgs if m.role == "user")
        return msgs

    with patch.object(drafting_service, "_build_messages", _spy):
        _generate(client, token, matter_id, draft_id)

    user_msg = captured["user"]
    assert "STEPPER FACTS" in user_msg
    assert "applicant_name: Ravi Verma" in user_msg
    assert "fir_number: FIR 9/2026" in user_msg
    assert "Template: bail_application" in user_msg


def test_create_draft_rejects_oversized_facts(client: TestClient) -> None:
    """Defensive cap: >64 KiB of facts JSON → 413 so a pathological
    client can't inflate draft rows."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-FACTS-CAP")

    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Too much",
            "draft_type": "brief",
            "template_type": "bail_application",
            "facts": {"blob": "x" * (65 * 1024)},
        },
    )
    assert resp.status_code == 413, resp.text
