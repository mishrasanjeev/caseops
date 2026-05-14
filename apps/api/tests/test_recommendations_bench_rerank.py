import json
import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    AuthorityCitation,
    AuthorityDocument,
    AuthorityDocumentType,
    CompanyMembership,
    Matter,
    MatterHearing,
    ModelRun,
    TenantAIPolicy,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.authorities import AuthoritySearchResult
from caseops_api.services.identity import SessionContext
from caseops_api.services.llm import LLMCompletion, LLMMessage
from caseops_api.services.recommendations import (
    _BENCH_RERANK_PURPOSE,
    RetrievedAuthority,
    _apply_bench_citation_rerank,
    _build_prompt,
    _record_bench_citation_rerank,
    generate_recommendation,
)
from tests.test_auth_company import bootstrap_company


@pytest.fixture
def tmp_path() -> Path:
    base = Path("tmp-pytest-g128") / uuid4().hex
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base.resolve()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _ctx(session, company_id: str) -> SessionContext:
    membership = session.scalar(
        select(CompanyMembership).where(CompanyMembership.company_id == company_id)
    )
    assert membership is not None
    return SessionContext(
        membership=membership,
        company=membership.company,
        user=membership.user,
    )


def _enable_predictive_policy(session, company_id: str, enabled: bool = True) -> None:
    policy = session.scalar(
        select(TenantAIPolicy).where(TenantAIPolicy.company_id == company_id)
    )
    if policy is None:
        policy = TenantAIPolicy(company_id=company_id)
        session.add(policy)
        session.flush()
    policy.predictive_bench_strategy_enabled = enabled


def _matter_with_hearing(session, company_id: str) -> Matter:
    matter = Matter(
        company_id=company_id,
        title="Bench rerank matter",
        matter_code=f"BR-{uuid4().hex[:8]}",
        client_name="Client",
        opposing_party="State",
        status="active",
        practice_area="arbitration",
        forum_level="high_court",
        court_name="Delhi High Court",
        is_active=True,
    )
    session.add(matter)
    session.flush()
    session.add(
        MatterHearing(
            matter_id=matter.id,
            hearing_on=date(2026, 6, 1),
            forum_name="Delhi High Court",
            judge_name="Justice Asha Rao",
            purpose="Final hearing",
        )
    )
    session.flush()
    return matter


def _matter_without_bench_context(session, company_id: str) -> Matter:
    matter = Matter(
        company_id=company_id,
        title="No bench context matter",
        matter_code=f"NB-{uuid4().hex[:8]}",
        client_name="Client",
        opposing_party="State",
        status="active",
        practice_area="arbitration",
        forum_level="high_court",
        court_name="Delhi High Court",
        is_active=True,
    )
    session.add(matter)
    session.flush()
    return matter


def _authority(
    session,
    *,
    title: str,
    judges: list[str] | None = None,
    outcome_label: str | None = None,
) -> AuthorityDocument:
    doc = AuthorityDocument(
        source="test",
        adapter_name="test",
        court_name="Delhi High Court",
        forum_level="high_court",
        document_type=AuthorityDocumentType.JUDGMENT,
        title=title,
        case_reference=title,
        bench_name=judges[0] if judges else None,
        neutral_citation=None,
        decision_date=date(2025, 1, 1),
        canonical_key=uuid4().hex,
        source_reference=title,
        summary=f"{title} summary",
        document_text=f"{title} text",
        extracted_char_count=len(title),
        judges_json=json.dumps(judges or []),
        outcome_label=outcome_label,
    )
    session.add(doc)
    session.flush()
    return doc


def _result(doc: AuthorityDocument) -> AuthoritySearchResult:
    return AuthoritySearchResult(
        authority_document_id=doc.id,
        title=doc.title,
        court_name=doc.court_name,
        forum_level="high_court",
        document_type="judgment",
        decision_date=doc.decision_date,
        case_reference=doc.case_reference,
        bench_name=doc.bench_name,
        summary=doc.summary,
        source=doc.source,
        source_reference=doc.source_reference,
        snippet=doc.summary,
        score=0,
        matched_terms=[],
    )


def test_bench_rerank_boosts_authored_authorities_and_records_guardrails(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    with get_session_factory()() as session:
        _enable_predictive_policy(session, company_id, enabled=True)
        matter = _matter_with_hearing(session, company_id)
        general = _authority(session, title="General authority")
        bench_docs = [
            _authority(
                session,
                title=f"Asha Rao bench authority {i}",
                judges=["Asha Rao"],
                outcome_label="allowed",
            )
            for i in range(5)
        ]
        session.commit()

        context = _ctx(session, company_id)
        results = [_result(general), *[_result(doc) for doc in bench_docs]]
        reranked, trace = _apply_bench_citation_rerank(
            session,
            results,
            context=context,
            matter=matter,
        )
        run = _record_bench_citation_rerank(
            session,
            context=context,
            matter=matter,
            trace=trace,
        )
        session.commit()

        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "authority_rerank.bench_citation_relevance"
            )
        )
        persisted_run = session.get(ModelRun, run.id)

    assert trace.status == "applied"
    assert trace.sample_size == 5
    assert reranked[0].authority_document_id == bench_docs[0].id
    assert set(trace.source_authority_ids) == {doc.id for doc in bench_docs}
    assert set(trace.boosted_authority_ids) == {doc.id for doc in bench_docs}
    assert trace.metadata()["sample_size_band"] == "n=5, recall@10=not-measured"
    assert persisted_run is not None
    assert persisted_run.purpose == _BENCH_RERANK_PURPOSE
    assert persisted_run.provider == "internal"
    assert persisted_run.status == "applied"
    assert event is not None
    metadata = json.loads(event.metadata_json or "{}")
    assert metadata["model_run_id"] == run.id
    assert metadata["sample_size_band"] == "n=5, recall@10=not-measured"
    assert set(metadata) == {
        "status",
        "policy_enabled",
        "sample_size_band",
        "candidate_authority_ids",
        "boosted_authority_ids",
        "source_authority_ids",
        "model_run_id",
    }

    prompt = _build_prompt(
        rec_type="authority",
        matter=matter,
        authorities=[
            RetrievedAuthority(
                identifier=bench_docs[0].title,
                text=bench_docs[0].summary,
                rerank_explanation=trace.per_authority_explanations[bench_docs[0].id],
            )
        ],
    )
    assert "n=5, recall@10=not-measured" in prompt[1].content
    assert bench_docs[0].id in prompt[1].content
    surfaced_text = "\n".join(
        [
            persisted_run.purpose,
            persisted_run.model,
            event.action,
            event.metadata_json or "",
            prompt[1].content,
            trace.explanation,
            *trace.per_authority_explanations.values(),
        ]
    ).lower()
    forbidden_phrases = [
        "favorability",
        "favourability",
        "favorable judge",
        "favourable judge",
        "judge reputation",
        "judge likes",
        "judge dislikes",
        "will win",
        "win probability",
        "loss probability",
        "guaranteed outcome",
    ]
    assert all(phrase not in surfaced_text for phrase in forbidden_phrases)


def test_generate_recommendation_records_bench_rerank_in_real_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    with get_session_factory()() as session:
        _enable_predictive_policy(session, company_id, enabled=True)
        matter = _matter_with_hearing(session, company_id)
        general = _authority(session, title="General authority")
        bench_docs = [
            _authority(
                session,
                title=f"Asha Rao real-path authority {i}",
                judges=["Asha Rao"],
                outcome_label="allowed",
            )
            for i in range(5)
        ]
        session.commit()

        context = _ctx(session, company_id)
        search_results = [_result(general), *[_result(doc) for doc in bench_docs]]

        monkeypatch.setattr(
            "caseops_api.services.recommendations.search_authority_catalog",
            lambda *_args, **_kwargs: search_results,
        )

        class _Provider:
            name = "mock"
            model = "mock-recommendations"

            def generate(self, messages: list[LLMMessage], **_kwargs) -> LLMCompletion:
                payload = {
                    "title": "Use the cited authority",
                    "options": [
                        {
                            "label": "Use the bench-authored authority",
                            "rationale": bench_docs[0].summary,
                            "confidence": "medium",
                            "supporting_citations": [bench_docs[0].title],
                            "risk_notes": None,
                        }
                    ],
                    "primary_recommendation_label": "Use the bench-authored authority",
                    "rationale": bench_docs[0].summary,
                    "assumptions": [],
                    "missing_facts": [],
                    "confidence": "medium",
                    "next_action": None,
                }
                return LLMCompletion(
                    text=json.dumps(payload),
                    provider=self.name,
                    model=self.model,
                    prompt_tokens=10,
                    completion_tokens=20,
                    latency_ms=5,
                )

        recommendation = generate_recommendation(
            session,
            context=context,
            matter_id=matter.id,
            rec_type="authority",
            provider=_Provider(),
        )

        run = session.scalar(
            select(ModelRun).where(ModelRun.purpose == _BENCH_RERANK_PURPOSE)
        )
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "authority_rerank.bench_citation_relevance"
            )
        )

    assert recommendation.id
    assert run is not None
    assert run.status == "applied"
    assert event is not None
    metadata = json.loads(event.metadata_json or "{}")
    assert metadata["status"] == "applied"
    assert metadata["sample_size_band"] == "n=5, recall@10=not-measured"
    assert metadata["model_run_id"] == run.id


def test_bench_rerank_keeps_order_without_candidates_or_bench_context(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    with get_session_factory()() as session:
        _enable_predictive_policy(session, company_id, enabled=True)
        matter = _matter_with_hearing(session, company_id)
        no_candidates, no_candidates_trace = _apply_bench_citation_rerank(
            session,
            [],
            context=_ctx(session, company_id),
            matter=matter,
        )
        matter_without_bench = _matter_without_bench_context(session, company_id)
        general = _authority(session, title="General authority")
        bench_doc = _authority(
            session,
            title="Bench authority without matter context",
            judges=["Asha Rao"],
            outcome_label="allowed",
        )
        session.commit()
        original = [_result(general), _result(bench_doc)]
        no_context, no_context_trace = _apply_bench_citation_rerank(
            session,
            original,
            context=_ctx(session, company_id),
            matter=matter_without_bench,
        )

    assert no_candidates == []
    assert no_candidates_trace.status == "no_candidates"
    assert no_context_trace.status == "no_bench_context"
    assert [r.authority_document_id for r in no_context] == [
        general.id,
        bench_doc.id,
    ]


def test_bench_rerank_boosts_authority_approvingly_cited_by_bench(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    with get_session_factory()() as session:
        _enable_predictive_policy(session, company_id, enabled=True)
        matter = _matter_with_hearing(session, company_id)
        general = _authority(session, title="General authority")
        cited = _authority(session, title="Authority cited approvingly")
        bench_sources = [
            _authority(
                session,
                title=f"Bench source {i}",
                judges=["Asha Rao"],
                outcome_label="allowed",
            )
            for i in range(5)
        ]
        for i, source in enumerate(bench_sources):
            session.add(
                AuthorityCitation(
                    source_authority_document_id=source.id,
                    cited_authority_document_id=cited.id,
                    citation_text=f"Authority cited approvingly {i}",
                    normalized_reference=f"authority-cited-approvingly-{i}",
                    treatment="followed",
                )
            )
        considered_source = _authority(
            session,
            title="Bench source that only considered authority",
            judges=["Asha Rao"],
            outcome_label="allowed",
        )
        session.add(
            AuthorityCitation(
                source_authority_document_id=considered_source.id,
                cited_authority_document_id=cited.id,
                citation_text="Authority cited but not applied",
                normalized_reference="authority-cited-considered",
                treatment="considered",
            )
        )
        session.commit()

        reranked, trace = _apply_bench_citation_rerank(
            session,
            [_result(general), _result(cited)],
            context=_ctx(session, company_id),
            matter=matter,
        )

    assert trace.status == "applied"
    assert trace.sample_size == 5
    assert reranked[0].authority_document_id == cited.id
    assert trace.boosted_authority_ids == (cited.id,)
    assert set(trace.source_authority_ids) == {doc.id for doc in bench_sources}
    assert considered_source.id not in trace.source_authority_ids
    explanation = trace.per_authority_explanations[cited.id]
    assert "approvingly_cited_by_bench" in explanation
    assert all(source.id in explanation for source in bench_sources)


def test_bench_rerank_honors_policy_off_and_insufficient_history(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    with get_session_factory()() as session:
        matter = _matter_with_hearing(session, company_id)
        general = _authority(session, title="General authority")
        bench_doc = _authority(
            session,
            title="Single bench authority",
            judges=["Asha Rao"],
            outcome_label="allowed",
        )
        session.commit()
        context = _ctx(session, company_id)
        original = [_result(general), _result(bench_doc)]

        policy_off, off_trace = _apply_bench_citation_rerank(
            session,
            original,
            context=context,
            matter=matter,
        )
        assert off_trace.status == "policy_disabled"
        assert [r.authority_document_id for r in policy_off] == [
            general.id,
            bench_doc.id,
        ]

        _enable_predictive_policy(session, company_id, enabled=True)
        session.commit()
        insufficient, insufficient_trace = _apply_bench_citation_rerank(
            session,
            original,
            context=context,
            matter=matter,
        )

    assert insufficient_trace.status == "insufficient_bench_history"
    assert insufficient_trace.sample_size == 1
    assert "n=1, recall@10=not-measured" in insufficient_trace.explanation
    assert [r.authority_document_id for r in insufficient] == [
        general.id,
        bench_doc.id,
    ]
