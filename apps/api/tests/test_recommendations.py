from __future__ import annotations

from collections.abc import Iterable

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    ModelRun,
    Recommendation,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _seed_authorities(records: Iterable[dict]) -> None:
    factory = get_session_factory()
    with factory() as session:
        for record in records:
            import hashlib as _h
            canonical = _h.sha256(
                (record["title"] + "|" + (record.get("case_reference") or "")).encode(
                    "utf-8"
                )
            ).hexdigest()[:40]
            doc = AuthorityDocument(
                title=record["title"],
                court_name=record["court_name"],
                forum_level=record["forum_level"],
                document_type=AuthorityDocumentType(record["document_type"]),
                decision_date=record["decision_date"],
                case_reference=record.get("case_reference"),
                summary=record.get("summary", ""),
                source=record.get("source", "manual"),
                adapter_name=record.get("adapter_name", "manual-seed"),
                source_reference=record.get("source_reference"),
                canonical_key=record.get("canonical_key", canonical),
                document_text=record["document_text"],
                extracted_char_count=len(record["document_text"]),
                ingested_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            )
            session.add(doc)
            session.flush()
            session.add(
                AuthorityDocumentChunk(
                    authority_document_id=doc.id,
                    chunk_index=0,
                    content=record["document_text"],
                )
            )
        session.commit()


def _setup_matter(client: TestClient) -> tuple[str, str, str]:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    company_slug = str(bootstrap_payload["company"]["slug"])
    matter = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Ssangyong-style arbitral award challenge",
            "matter_code": "ARB-2026-001",
            "practice_area": "Arbitration",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Ssangyong Engg",
            "opposing_party": "NHAI",
            "description": (
                "Limited challenge under Section 34 of the Arbitration Act. "
                "Primary ground considered: patent illegality."
            ),
            "status": "active",
        },
    )
    assert matter.status_code == 200, matter.text
    return token, company_slug, str(matter.json()["id"])


def _seed_relevant_authority() -> None:
    _seed_authorities(
        [
            {
                "title": "Ssangyong Engg v. NHAI (2019)",
                "court_name": "Supreme Court of India",
                "forum_level": "supreme_court",
                "document_type": "judgment",
                "decision_date": __import__("datetime").date(2019, 5, 8),
                "case_reference": "Ssangyong Engg v. NHAI (2019)",
                "summary": (
                    "Held that patent illegality survives Section 34 scrutiny where the "
                    "award is fundamentally opposed to Indian law."
                ),
                "document_text": (
                    "The Supreme Court held that patent illegality is a ground for "
                    "setting aside an arbitral award under Section 34 of the Arbitration "
                    "and Conciliation Act, 1996, where the award is fundamentally "
                    "opposed to Indian law or public policy."
                ),
            }
        ]
    )


def test_generate_recommendation_returns_verified_citations(client: TestClient) -> None:
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()

    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["type"] == "authority"
    assert payload["review_required"] is True
    assert payload["status"] == "proposed"
    assert payload["options"]
    assert any(option["supporting_citations"] for option in payload["options"])
    primary = payload["options"][payload["primary_option_index"]]
    assert primary["supporting_citations"]


def test_generate_recommendation_refuses_when_no_verified_citations(
    client: TestClient, monkeypatch
) -> None:
    """Guardrail: refuse to publish if every cited authority fails matching."""
    import json as _json

    from caseops_api.services.llm import LLMCompletion, LLMMessage

    _seed_relevant_authority()

    class _HallucinatingProvider:
        name = "mock"
        model = "mock-hallucinator"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            payload = {
                "title": "Fabricated recommendation",
                "options": [
                    {
                        "label": "Cite a case that does not exist",
                        "rationale": "Fabricated proposition about patent illegality.",
                        "confidence": "high",
                        "supporting_citations": ["Entirely Fake v. Nobody (2099)"],
                        "risk_notes": None,
                    }
                ],
                "primary_recommendation_label": None,
                "rationale": "Fabricated rationale.",
                "assumptions": [],
                "missing_facts": [],
                "confidence": "high",
                "next_action": None,
            }
            return LLMCompletion(
                text=_json.dumps(payload),
                provider=self.name,
                model=self.model,
                prompt_tokens=10,
                completion_tokens=20,
                latency_ms=5,
            )

    monkeypatch.setattr(
        "caseops_api.services.recommendations.build_provider",
        lambda: _HallucinatingProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert response.status_code == 422
    assert "verifiable citations" in response.json()["detail"]

    # ModelRun captures the refusal for audit.
    factory = get_session_factory()
    with factory() as session:
        runs = list(session.scalars(select(ModelRun)))
    assert any(run.status == "rejected_no_verified_citations" for run in runs)


def test_shared_citation_credits_every_option_that_cites_it(
    client: TestClient, monkeypatch
) -> None:
    """When two options cite the same authority, both must retain that
    citation after verification. The earlier bug collapsed
    citation_to_option into dict[str, int], so only the last option
    using a citation got credit — the earlier option looked unsupported."""
    import json as _json

    from caseops_api.services.llm import LLMCompletion, LLMMessage

    _seed_relevant_authority()  # seeds neutral_citation "Mock Corp v. State (2020)"

    class _SharedCitationProvider:
        name = "mock"
        model = "mock-shared-cite"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            payload = {
                "title": "Two routes to the same relief",
                "options": [
                    {
                        "label": "File writ petition",
                        "rationale": "Patent illegality supports relief.",
                        "confidence": "high",
                        "supporting_citations": ["Ssangyong Engg v. NHAI (2019)"],
                        "risk_notes": None,
                    },
                    {
                        "label": "Seek review instead",
                        "rationale": "The same ratio supports review jurisdiction.",
                        "confidence": "medium",
                        "supporting_citations": ["Ssangyong Engg v. NHAI (2019)"],
                        "risk_notes": None,
                    },
                ],
                "primary_recommendation_label": "File writ petition",
                "rationale": "Either route works.",
                "assumptions": [],
                "missing_facts": [],
                "confidence": "high",
                "next_action": None,
            }
            return LLMCompletion(
                text=_json.dumps(payload),
                provider=self.name,
                model=self.model,
                prompt_tokens=10,
                completion_tokens=20,
                latency_ms=5,
            )

    monkeypatch.setattr(
        "caseops_api.services.recommendations.build_provider",
        lambda: _SharedCitationProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    options = body["options"]
    assert len(options) == 2
    # Both options cited the same authority and both should retain it.
    for idx, opt in enumerate(options):
        assert opt["supporting_citations"] == ["Ssangyong Engg v. NHAI (2019)"], (
            f"Option {idx} lost its shared citation — attribution bug regression."
        )


def test_generate_recommendation_refuses_when_retrieval_is_empty(
    client: TestClient, monkeypatch
) -> None:
    """Guardrail: refuse when retrieval returns zero authorities — even if
    the model returns a confident-looking recommendation. PRD §6.1 / §17.4
    require citation-grounded output; "no retrieval at all" is a weaker
    foundation than "retrieval that failed verification", not a stronger one."""
    import json as _json

    from caseops_api.services.llm import LLMCompletion, LLMMessage

    # Deliberately DO NOT call _seed_relevant_authority() — retrieval
    # will return [] for this matter.

    class _ConfidentNoRetrievalProvider:
        name = "mock"
        model = "mock-no-retrieval"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            payload = {
                "title": "Proceed with writ petition",
                "options": [
                    {
                        "label": "File writ under Article 226",
                        "rationale": "The petitioner has a clear cause of action.",
                        "confidence": "high",
                        "supporting_citations": ["Some Case v. State (2020)"],
                        "risk_notes": None,
                    }
                ],
                "primary_recommendation_label": "File writ under Article 226",
                "rationale": "Proceed.",
                "assumptions": [],
                "missing_facts": [],
                "confidence": "high",
                "next_action": None,
            }
            return LLMCompletion(
                text=_json.dumps(payload),
                provider=self.name,
                model=self.model,
                prompt_tokens=10,
                completion_tokens=20,
                latency_ms=5,
            )

    monkeypatch.setattr(
        "caseops_api.services.recommendations.build_provider",
        lambda: _ConfidentNoRetrievalProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"].lower()
    assert "refusing" in detail or "refuse" in detail

    # No Recommendation row should have been persisted.
    factory = get_session_factory()
    with factory() as session:
        recs = list(session.scalars(select(Recommendation)))
    assert not recs, (
        f"Empty-retrieval path persisted {len(recs)} recommendation(s); "
        "fail-open regression."
    )
    # ModelRun captures the refusal for audit.
    with factory() as session:
        runs = list(session.scalars(select(ModelRun)))
    assert any(run.status == "rejected_no_verified_citations" for run in runs)


def test_recommendation_list_is_tenant_scoped(client: TestClient) -> None:
    # Company A creates a recommendation; Company B must not see it.
    token_a, _, matter_id_a = _setup_matter(client)
    _seed_relevant_authority()
    created = client.post(
        f"/api/matters/{matter_id_a}/recommendations",
        headers=auth_headers(token_a),
        json={"type": "authority"},
    )
    assert created.status_code == 200

    company_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Competitor LLP",
            "company_slug": "competitor-llp",
            "company_type": "law_firm",
            "owner_full_name": "Rival Owner",
            "owner_email": "owner@competitor-llp.in",
            "owner_password": "CompetitorPass123!",
        },
    )
    assert company_b.status_code == 200
    token_b = str(company_b.json()["access_token"])

    # Direct cross-tenant access on matter A must 404.
    listing = client.get(
        f"/api/matters/{matter_id_a}/recommendations",
        headers=auth_headers(token_b),
    )
    assert listing.status_code == 404


def test_decision_captures_accept(client: TestClient) -> None:
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    created = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    recommendation_id = created.json()["id"]

    listed = client.get(
        f"/api/matters/{matter_id}/recommendations", headers=auth_headers(token)
    )
    assert listed.status_code == 200
    assert listed.json()["recommendations"][0]["id"] == recommendation_id

    decision = client.post(
        f"/api/recommendations/{recommendation_id}/decisions",
        headers=auth_headers(token),
        json={"decision": "accepted", "selected_option_index": 0, "notes": "Partner approved"},
    )
    assert decision.status_code == 200
    payload = decision.json()
    assert payload["status"] == "accepted"
    assert payload["decisions"]
    assert payload["decisions"][-1]["decision"] == "accepted"


def test_decision_rejects_invalid_option_index(client: TestClient) -> None:
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    created = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    recommendation_id = created.json()["id"]
    # Mock emits exactly 2 options; index 5 passes schema (<= 20) but is out
    # of range for this recommendation → the service layer returns 400.
    bad = client.post(
        f"/api/recommendations/{recommendation_id}/decisions",
        headers=auth_headers(token),
        json={"decision": "accepted", "selected_option_index": 5},
    )
    assert bad.status_code == 400


def test_generate_writes_a_model_run_record(client: TestClient) -> None:
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    created = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert created.status_code == 200

    factory = get_session_factory()
    with factory() as session:
        runs = list(session.scalars(select(ModelRun)))
        recs = list(session.scalars(select(Recommendation)))

    assert runs, "ModelRun was not persisted"
    assert any(run.purpose == "recommendation:authority" for run in runs)
    assert any(run.prompt_tokens > 0 for run in runs)
    assert recs and recs[0].model_run_id


def test_unsupported_type_is_rejected(client: TestClient) -> None:
    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "settlement"},
    )
    # Pydantic literal validation rejects on schema
    assert response.status_code == 422
