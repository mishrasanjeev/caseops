from __future__ import annotations

from collections.abc import Iterable

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    Matter,
    MatterStrategyEntry,
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


def _create_matter(client: TestClient, token: str, *, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Matter {code}",
            "matter_code": code,
            "practice_area": "Arbitration",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Aster Legal",
            "opposing_party": "NHAI",
            "description": "Access control regression matter.",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _create_company_user(
    client: TestClient,
    owner_token: str,
    *,
    company_slug: str,
    email: str,
    role: str = "partner",
) -> tuple[str, str]:
    create = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": email.split("@")[0].replace("-", " ").title(),
            "email": email,
            "password": "MemberPass123!",
            "role": role,
        },
    )
    assert create.status_code == 200, create.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "MemberPass123!",
            "company_slug": company_slug,
        },
    )
    assert login.status_code == 200, login.text
    return str(create.json()["membership_id"]), str(login.json()["access_token"])


def _seed_recommendation_for_matter(
    matter_id: str,
    *,
    rec_type: str = "authority",
) -> str:
    factory = get_session_factory()
    with factory() as session:
        company_id = session.scalar(
            select(Matter.company_id).where(Matter.id == matter_id)
        )
        assert company_id is not None
        recommendation = Recommendation(
            company_id=company_id,
            matter_id=matter_id,
            type=rec_type,
            title="Seeded recommendation",
            rationale="Seeded for access-control regression.",
            primary_option_index=0,
            assumptions_json="[]",
            missing_facts_json="[]",
            confidence="low",
            review_required=True,
            status="proposed",
        )
        session.add(recommendation)
        session.commit()
        return recommendation.id


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
        lambda *a, **kw: _HallucinatingProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert response.status_code == 422
    # BUG-012 Hari 2026-04-21 reworded the detail to be actionable —
    # assert against the stable "verified authorities in the corpus"
    # phrase the user sees and the model_run_id going into a header
    # instead of the message body.
    detail = response.json()["detail"]
    assert "verified authorities" in detail or "verifiable citations" in detail
    assert "model_run_id=" not in detail
    assert "X-Model-Run-Id" in response.headers

    # ModelRun captures the refusal for audit.
    factory = get_session_factory()
    with factory() as session:
        runs = list(session.scalars(select(ModelRun)))
    assert any(run.status == "rejected_no_verified_citations" for run in runs)


def test_recommendation_format_error_retries_once_then_succeeds(
    client: TestClient, monkeypatch,
) -> None:
    """Ram BUG-029 (2026-05-01) regression: GPT-5.1 sporadically
    returns malformed JSON on long structured outputs (~1-2%). With
    the Anthropic→Haiku→OpenAI fallback ladder removed, a single
    transient format error used to put the user on a 502. The fix is
    a single retry on LLMResponseFormatError specifically — same
    provider, same model. This test asserts the retry happens AND
    that a successful retry yields a 200 (not the original 502)."""
    import json as _json

    from caseops_api.services.llm import (
        LLMCompletion,
        LLMMessage,
        LLMResponseFormatError,
    )

    _seed_relevant_authority()

    valid_payload = {
        "title": "Authority recommendation — retry succeeded",
        "options": [
            {
                "label": "File writ petition",
                "rationale": "The retrieved authorities support the relief sought.",
                "confidence": "medium",
                "supporting_citations": ["Ssangyong Engg v. NHAI (2019)"],
                "risk_notes": None,
            },
        ],
        "primary_recommendation_label": "File writ petition",
        "rationale": "The retrieved authority supports the proposition.",
        "assumptions": [],
        "missing_facts": [],
        "confidence": "medium",
        "next_action": None,
    }

    call_count = {"n": 0}

    class _FlakyJSONProvider:
        name = "mock"
        model = "mock-flaky-json"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise LLMResponseFormatError(
                    "mock:flaky-json did not return valid JSON. "
                    "raw[:500]='Here is the recommendation: [truncated]'"
                )
            return LLMCompletion(
                text=_json.dumps(valid_payload),
                provider=self.name,
                model=self.model,
                prompt_tokens=100,
                completion_tokens=200,
                latency_ms=10,
            )

    monkeypatch.setattr(
        "caseops_api.services.recommendations.build_provider",
        lambda *a, **kw: _FlakyJSONProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    # First call format-errored, retry succeeded → 200 not 502.
    assert response.status_code == 200, response.text
    assert call_count["n"] == 2, (
        f"Expected exactly 2 LLM calls (1 format-error + 1 retry); got {call_count['n']}"
    )


def test_recommendation_format_error_retry_also_fails_yields_502(
    client: TestClient, monkeypatch,
) -> None:
    """Ram BUG-029 regression — the retry on format error is bounded.
    If the retry ALSO produces a format error, the route surfaces a
    502 with the retry's detail (not an infinite loop)."""
    from caseops_api.services.llm import LLMMessage, LLMResponseFormatError

    _seed_relevant_authority()

    call_count = {"n": 0}

    class _AlwaysFlakyProvider:
        name = "mock"
        model = "mock-always-flaky"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            call_count["n"] += 1
            raise LLMResponseFormatError(
                "mock:always-flaky did not return valid JSON. raw[:500]=''"
            )

    monkeypatch.setattr(
        "caseops_api.services.recommendations.build_provider",
        lambda *a, **kw: _AlwaysFlakyProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert "LLMResponseFormatError" in detail
    assert call_count["n"] == 2  # retried exactly once before giving up


def test_recommendation_provider_error_returns_actionable_502(
    client: TestClient, monkeypatch,
) -> None:
    """Ram-BUG-007 / Hari-III-BUG-020 (2026-04-22): a 503 / overload from
    Anthropic was wrapped as ``LLMProviderError`` (parent of the
    format-error subclass we used to catch). The narrow ``except
    LLMResponseFormatError`` let it escape the Haiku-fallback branch
    and surface as an opaque 500 with no actionable detail. Regression:
    a primary provider that raises ``LLMProviderError`` must end up at
    a 502 with a detail string the user can act on (model name,
    "retry in a minute"), NOT at a 500 with no body."""
    from caseops_api.services.llm import LLMMessage, LLMProviderError

    _seed_relevant_authority()

    class _OverloadedProvider:
        name = "mock"
        model = "mock-overload-503"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            raise LLMProviderError("Anthropic call failed: 503 overloaded")

    monkeypatch.setattr(
        "caseops_api.services.recommendations.build_provider",
        lambda *a, **kw: _OverloadedProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    # 2026-04-30: gpt-5.1-only path. Single primary call → 502 with
    # actionable detail. No fallback ladder, no 3x token burn.
    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert "LLMProviderError" in detail
    assert "retry" in detail.lower()


def test_recommendation_quota_error_returns_actionable_503_without_raw_provider_leak(
    client: TestClient, monkeypatch,
) -> None:
    from caseops_api.services.llm import LLMMessage, LLMQuotaExhaustedError

    _seed_relevant_authority()

    class _QuotaProvider:
        name = "openai"
        model = "gpt-5-mini"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            raise LLMQuotaExhaustedError(
                "OpenAI quota exhausted: Error code: 429 - {'error': "
                "{'code': 'insufficient_quota', 'message': 'billing raw'}}"
            )

    monkeypatch.setattr(
        "caseops_api.services.recommendations.build_provider",
        lambda *a, **kw: _QuotaProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == "llm_quota_exhausted"
    assert "provider quota is exhausted" in body["detail"]
    assert "insufficient_quota" not in body["detail"]
    assert "billing raw" not in body["detail"]
    assert "No output was saved" in body["detail"]


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
        lambda *a, **kw: _SharedCitationProvider(),
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


def test_bracket_tag_citation_resolves_to_canonical_identifier(
    client: TestClient, monkeypatch
) -> None:
    """Grounding fast path end-to-end. Model emits "[1] paraphrased title"
    with a rationale that shares no tokens with the source text — the prior
    proposition gate would 422 this. With the bracket-tag fast path, the
    citation resolves by index, the proposition gate is skipped, and the UI
    surfaces the canonical identifier (no [1] prefix, no paraphrase)."""
    import json as _json

    from caseops_api.services.llm import LLMCompletion, LLMMessage

    _seed_relevant_authority()  # SSANGYONG is the only retrieved authority

    class _BracketTagProvider:
        name = "mock"
        model = "mock-bracket-tag"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            payload = {
                "title": "Section 34 challenge",
                "options": [
                    {
                        "label": "Press patent illegality",
                        # Rationale deliberately uses tokens absent from the
                        # source text — the proposition gate would have
                        # rejected this before the bracket-tag fast path.
                        "rationale": "Foundational ratio xyz qrs supports relief here.",
                        "confidence": "medium",
                        "supporting_citations": ["[1] paraphrased Ssangyong tag"],
                        "risk_notes": None,
                    }
                ],
                "primary_recommendation_label": None,
                "rationale": "Standard challenge.",
                "assumptions": [],
                "missing_facts": [],
                "confidence": "medium",
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
        lambda *a, **kw: _BracketTagProvider(),
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
    assert len(options) == 1
    cites = options[0]["supporting_citations"]
    assert cites, "bracket-tag citation should have verified"
    # UI surfaces the canonical identifier — no leading "[1]", no paraphrase.
    assert cites == ["Ssangyong Engg v. NHAI (2019)"], cites


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
        lambda *a, **kw: _ConfidentNoRetrievalProvider(),
    )

    token, _, matter_id = _setup_matter(client)
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"].lower()
    # BUG-012 reworded to actionable copy — pin the stable phrases
    # the user sees ("grounding authorities", "matter description")
    # and the clean-detail rule (no model_run_id leak).
    assert "grounding authorities" in detail or "matter description" in detail
    assert "model_run_id=" not in detail
    assert "X-Model-Run-Id" in response.headers

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


def test_accepted_decision_clears_review_required(client: TestClient) -> None:
    """Round-2 P1 #3: an ``accepted`` decision must clear
    ``review_required=False``. Until this fix the strategy page kept
    surfacing the 'Partner review required' badge after acceptance."""
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    created = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    rec_id = created.json()["id"]
    # Sanity check — review_required defaults to True for AI recs.
    assert created.json()["review_required"] is True

    decision = client.post(
        f"/api/recommendations/{rec_id}/decisions",
        headers=auth_headers(token),
        json={"decision": "accepted", "selected_option_index": 0},
    )
    assert decision.status_code == 200, decision.text
    body = decision.json()
    assert body["status"] == "accepted"
    assert body["review_required"] is False, (
        "Acceptance must clear review_required so the partner-review "
        "banner stops showing on the strategy / recommendations UI."
    )

    # Persisted state confirms the same.
    factory = get_session_factory()
    with factory() as session:
        rec = session.scalar(
            select(Recommendation).where(Recommendation.id == rec_id)
        )
        assert rec is not None
        assert rec.review_required is False


def test_non_accept_decisions_keep_review_required(client: TestClient) -> None:
    """Round-2 P1 #3 negative case: ``rejected`` / ``edited`` /
    ``deferred`` are not approvals — they keep review_required=True so
    the strategy banner stays visible until a real acceptance lands.

    We reuse one tenant + one matter and create a fresh recommendation
    per decision kind to avoid fighting the bootstrap_company singleton
    on duplicate slugs.
    """
    token, _, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    for decision_kind in ("rejected", "edited", "deferred"):
        created = client.post(
            f"/api/matters/{matter_id}/recommendations",
            headers=auth_headers(token),
            json={"type": "authority"},
        )
        assert created.status_code == 200, created.text
        rec_id = created.json()["id"]
        decision = client.post(
            f"/api/recommendations/{rec_id}/decisions",
            headers=auth_headers(token),
            json={"decision": decision_kind, "selected_option_index": 0},
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["review_required"] is True, (
            f"Decision {decision_kind!r} must NOT clear review_required."
        )


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


def test_strategy_entry_crud_is_access_gated_and_audited(
    client: TestClient,
) -> None:
    token, slug, matter_id = _setup_matter(client)
    member_resp = client.post(
        "/api/companies/current/users",
        headers=auth_headers(token),
        json={
            "full_name": "Strategy Member",
            "email": "strategy-member@example.com",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert member_resp.status_code == 200, member_resp.text
    member_login = client.post(
        "/api/auth/login",
        json={
            "email": "strategy-member@example.com",
            "password": "MemberPass123!",
            "company_slug": slug,
        },
    )
    assert member_login.status_code == 200, member_login.text
    member_token = str(member_login.json()["access_token"])

    denied = client.post(
        f"/api/matters/{matter_id}/strategy-entries",
        headers=auth_headers(member_token),
        json={
            "title": "Member-owned plan",
            "body": "This should be blocked for v1 strategy writes.",
        },
    )
    assert denied.status_code == 403

    created = client.post(
        f"/api/matters/{matter_id}/strategy-entries",
        headers=auth_headers(token),
        json={
            "title": "Settlement posture",
            "body": "Counsel-owned work product, not an AI recommendation.",
            "entry_type": "plan",
        },
    )
    assert created.status_code == 200, created.text
    entry = created.json()
    assert entry["entry_type"] == "plan"
    assert entry["owner_membership_id"] is not None

    listed = client.get(
        f"/api/matters/{matter_id}/strategy-entries",
        headers=auth_headers(token),
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["entries"]] == [entry["id"]]

    updated = client.patch(
        f"/api/matters/{matter_id}/strategy-entries/{entry['id']}",
        headers=auth_headers(token),
        json={"status": "active", "entry_type": "decision", "title": "Decision log"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["entry_type"] == "decision"
    assert updated.json()["title"] == "Decision log"

    deleted = client.delete(
        f"/api/matters/{matter_id}/strategy-entries/{entry['id']}",
        headers=auth_headers(token),
    )
    assert deleted.status_code == 204

    factory = get_session_factory()
    with factory() as session:
        actions = [
            row.action
            for row in session.scalars(
                select(AuditEvent)
                .where(AuditEvent.matter_id == matter_id)
                .order_by(AuditEvent.created_at.asc())
            )
        ]
    assert "matter_strategy.created" in actions
    assert "matter_strategy.updated" in actions
    assert "matter_strategy.deleted" in actions


def test_recommendation_decision_does_not_create_lawyer_strategy_entry(
    client: TestClient,
) -> None:
    token, _, matter_id = _setup_matter(client)
    factory = get_session_factory()
    with factory() as session:
        company_id = session.scalar(
            select(Recommendation.company_id).where(Recommendation.matter_id == matter_id)
        )
        if company_id is None:
            from caseops_api.db.models import Matter

            company_id = session.scalar(
                select(Matter.company_id).where(Matter.id == matter_id)
            )
        assert company_id is not None
        recommendation = Recommendation(
            company_id=company_id,
            matter_id=matter_id,
            type="litigation_strategy",
            title="AI escalation plan",
            rationale="Generated support only.",
            primary_option_index=0,
            assumptions_json="[]",
            missing_facts_json="[]",
            confidence="low",
            review_required=True,
            status="proposed",
        )
        session.add(recommendation)
        session.commit()
        rec_id = recommendation.id

    decision = client.post(
        f"/api/recommendations/{rec_id}/decisions",
        headers=auth_headers(token),
        json={"decision": "accepted", "notes": "Accept AI recommendation only."},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "accepted"

    entries = client.get(
        f"/api/matters/{matter_id}/strategy-entries",
        headers=auth_headers(token),
    )
    assert entries.status_code == 200, entries.text
    assert entries.json()["entries"] == []
    with factory() as session:
        assert session.scalar(select(MatterStrategyEntry.id)) is None


def test_recommendation_decision_requires_visible_matter_for_restricted_and_walled(
    client: TestClient,
) -> None:
    owner_token, company_slug, visible_matter_id = _setup_matter(client)
    decider_mid, decider_token = _create_company_user(
        client,
        owner_token,
        company_slug=company_slug,
        email="recommendation-decider@example.com",
        role="partner",
    )
    restricted_matter_id = _create_matter(
        client, owner_token, code="REC-DEC-RESTRICTED"
    )
    walled_matter_id = _create_matter(client, owner_token, code="REC-DEC-WALLED")
    visible_rec_id = _seed_recommendation_for_matter(visible_matter_id)
    restricted_rec_id = _seed_recommendation_for_matter(restricted_matter_id)
    walled_rec_id = _seed_recommendation_for_matter(walled_matter_id)

    restricted = client.post(
        f"/api/matters/{restricted_matter_id}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    wall = client.post(
        f"/api/matters/{walled_matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": decider_mid, "reason": "Conflict."},
    )
    assert wall.status_code == 200, wall.text

    allowed = client.post(
        f"/api/recommendations/{visible_rec_id}/decisions",
        headers=auth_headers(decider_token),
        json={"decision": "accepted", "notes": "Visible matter decision."},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "accepted"

    restricted_denied = client.post(
        f"/api/recommendations/{restricted_rec_id}/decisions",
        headers=auth_headers(decider_token),
        json={"decision": "accepted", "notes": "Should not mutate."},
    )
    assert restricted_denied.status_code == 404
    walled_denied = client.post(
        f"/api/recommendations/{walled_rec_id}/decisions",
        headers=auth_headers(decider_token),
        json={"decision": "rejected", "notes": "Should not mutate."},
    )
    assert walled_denied.status_code == 404

    factory = get_session_factory()
    with factory() as session:
        restricted_rec = session.get(Recommendation, restricted_rec_id)
        walled_rec = session.get(Recommendation, walled_rec_id)
        assert restricted_rec is not None
        assert walled_rec is not None
        assert restricted_rec.status == "proposed"
        assert restricted_rec.review_required is True
        assert walled_rec.status == "proposed"
        assert walled_rec.review_required is True


def test_recommendation_decision_requires_visible_matter_for_team_scoping(
    client: TestClient,
) -> None:
    owner_token, company_slug, _ = _setup_matter(client)
    decider_mid, decider_token = _create_company_user(
        client,
        owner_token,
        company_slug=company_slug,
        email="team-hidden-recommendation-decider@example.com",
        role="partner",
    )
    owner_headers = auth_headers(owner_token)
    litigation_team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Litigation", "slug": "litigation"},
    )
    assert litigation_team.status_code == 201, litigation_team.text
    team_id = litigation_team.json()["id"]
    matter_id = _create_matter(client, owner_token, code="REC-DEC-TEAM")
    assign_team = client.patch(
        f"/api/matters/{matter_id}",
        headers=owner_headers,
        json={"team_id": team_id},
    )
    assert assign_team.status_code == 200, assign_team.text
    recommendation_id = _seed_recommendation_for_matter(matter_id)
    scoping = client.put(
        "/api/teams/scoping",
        headers=owner_headers,
        json={"enabled": True},
    )
    assert scoping.status_code == 200, scoping.text

    hidden = client.post(
        f"/api/recommendations/{recommendation_id}/decisions",
        headers=auth_headers(decider_token),
        json={"decision": "accepted", "notes": "Should be team-hidden."},
    )
    assert hidden.status_code == 404

    add_to_team = client.post(
        f"/api/teams/{team_id}/members",
        headers=owner_headers,
        json={"membership_id": decider_mid},
    )
    assert add_to_team.status_code == 200, add_to_team.text
    visible = client.post(
        f"/api/recommendations/{recommendation_id}/decisions",
        headers=auth_headers(decider_token),
        json={"decision": "accepted", "notes": "Now visible."},
    )
    assert visible.status_code == 200, visible.text
    assert visible.json()["status"] == "accepted"


def test_strategy_entries_are_tenant_scoped(client: TestClient) -> None:
    token_a, _, matter_id_a = _setup_matter(client)
    created = client.post(
        f"/api/matters/{matter_id_a}/strategy-entries",
        headers=auth_headers(token_a),
        json={
            "title": "Tenant A plan",
            "body": "Must remain scoped to tenant A.",
        },
    )
    assert created.status_code == 200, created.text

    tenant_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Strategy Tenant B",
            "company_slug": "strategy-tenant-b",
            "company_type": "law_firm",
            "owner_full_name": "Tenant B Owner",
            "owner_email": "owner@strategy-tenant-b.example",
            "owner_password": "TenantBPass123!",
        },
    )
    assert tenant_b.status_code == 200, tenant_b.text
    token_b = str(tenant_b.json()["access_token"])

    listing = client.get(
        f"/api/matters/{matter_id_a}/strategy-entries",
        headers=auth_headers(token_b),
    )
    assert listing.status_code == 404
    cross_tenant_create = client.post(
        f"/api/matters/{matter_id_a}/strategy-entries",
        headers=auth_headers(token_b),
        json={"title": "Leaked plan", "body": "Should not write."},
    )
    assert cross_tenant_create.status_code == 404
