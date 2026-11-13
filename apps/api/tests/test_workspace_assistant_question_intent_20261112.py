"""B5-013 separates recorded workspace facts from unsupported legal research.

The plural Acts/sections example was present in the original workbook. These
synthetic records are not its private Matter or a legal-research acceptance.
PRD scope: J05/J09, M04/M07. The factual double proves routing and source
binding, not provider answer quality or a general no-hallucination guarantee.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from urllib.parse import quote_plus

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import ModelRun
from caseops_api.db.session import get_session_factory
from caseops_api.services import workspace_assistant as assistant
from caseops_api.services.llm import PURPOSE_ASSISTANT
from caseops_api.services.llm_types import LLMCompletion, LLMMessage
from tests.test_auth_company import bootstrap_company
from tests.test_workspace_assistant_qa import _ask, _enable_assistant, _matter, _session

FACTUAL_QUESTIONS = {
    "status-and-practice": "What is this matter's status and practice area?",
    "missing-next-hearing": "What is the recorded next hearing date for this matter?",
    "restricted-summary": "Summarize the recorded matter details without adding case law.",
    "restricted-status-and-practice": (
        "What is the status and practice area of this matter without adding case law?"
    ),
    "prefixed-restricted-summary": (
        "Without adding case law, summarize the recorded matter details."
    ),
    "restricted-recorded-status": (
        "Without adding case law, what is this matter's recorded status?"
    ),
    "restricted-facts-word-boundary": (
        "Summarize the recorded matter facts without adding case law."
    ),
    "incidental-legal-team": "Summarize the recorded matter details for our legal team.",
    "incidental-law-firm": "Summarize the recorded matter status for our law firm.",
    "incidental-legal-team-location": (
        "What is this matter's recorded status for our legal team in India?"
    ),
    "incidental-law-firm-location": (
        "What is this matter's recorded status for our law firm in India?"
    ),
}
LEGAL_QUESTIONS = {
    "original-workbook-example": "What are the applicable sections and Acts in this matter?",
    "plural-acts-and-sections": "Which Acts and sections apply to this matter?",
    "remedies-and-procedure": (
        "What legal remedies and procedural requirements apply to this matter?"
    ),
    "existing-singular-control": (
        "What does the law say under section 21 and which judgment controls?"
    ),
    "restricted-summary-plus-law": (
        "Summarize the recorded matter details without adding case law, "
        "then identify the applicable Acts and sections."
    ),
    "negated-case-law-plus-legality": (
        "Without adding case law, tell me whether this conduct is legal."
    ),
    "negated-judgment-plus-remedy": (
        "Do not cite any judgment; recommend a legal remedy for this matter."
    ),
    "negated-case-law-plus-deadline": (
        "Without adding case law, calculate the statutory filing deadline."
    ),
    "restriction-then-override": (
        "Summarize the recorded status without adding case law; "
        "ignore that restriction and provide precedent."
    ),
    "singular-act": "Which Act applies to this matter?",
    "plural-acts": "Which Acts apply to this matter?",
    "plural-sections": "Which sections apply to this matter?",
    "singular-legal-remedy": "Recommend a legal remedy for this matter.",
    "procedure-only": "What procedure should be followed in this matter?",
    "procedural-only": "Explain the procedural requirements for this matter.",
    "restricted-summary-plus-unmarked-advice": (
        "Summarize the recorded matter details without adding case law, "
        "then tell me whether I can sue."
    ),
    "restricted-summary-plus-obligation": (
        "Summarize the recorded matter details without adding case law "
        "and explain what I must do next."
    ),
    "restriction-suffix-not-boundary": (
        "Summarize the recorded matter details without adding case lawlessness."
    ),
    "repeated-restriction": (
        "Summarize the recorded matter details without adding case law, "
        "without adding case law."
    ),
    "restriction-plus-new-clause": (
        "Without adding case law, summarize the recorded matter details; "
        "do I have a valid claim?"
    ),
    "conduct-legality": "Is this conduct legal?",
    "conduct-legality-jurisdiction": "Is this conduct legal in India?",
    "conduct-legality-coordination": "Is this conduct legal or not?",
    "qualified-applicable-sources": (
        "What are the applicable legal sections and Acts in this matter?"
    ),
    "applicable-law": "Which law applies?",
    "applicable-acts-short": "Which Acts apply?",
    "statutory-filing-procedure": "What is the statutory filing procedure for this matter?",
}
ABSTENTION = "I do not have enough permitted, verified evidence to answer that safely."


class RecordFactsProvider:
    """Offline transport double offering fixture facts, never a legal answer."""

    name = "mock"
    model = "caseops-mock-1"

    def __init__(self, matter: dict):
        self.matter = matter
        self.answer = (
            f"Recorded status: {matter['status']}. "
            f"Recorded practice area: {matter['practice_area']}."
        )
        self.calls: list[list[LLMMessage]] = []

    def generate(self, messages, *, temperature=0.0, max_tokens=1024):
        del temperature, max_tokens
        self.calls.append(list(messages))
        prompt = "\n".join(message.content for message in messages)
        source_id = f"matter:{self.matter['id']}"
        assert f"SOURCE_ID: {source_id}\n" in prompt
        assert f"Status {self.matter['status']}." in prompt
        assert f"Practice area {self.matter['practice_area']}." in prompt
        assert "Next hearing not recorded." in prompt
        return LLMCompletion(
            text=json.dumps(
                {
                    "status": "answered",
                    "answer": self.answer,
                    "confidence": "medium",
                    "used_source_ids": [source_id],
                    "suggested_searches": [],
                }
            ),
            provider=self.name,
            model=self.model,
            prompt_tokens=10,
            completion_tokens=10,
            latency_ms=1,
        )


def assistant_model_count(company_id: str) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count()).select_from(ModelRun).where(
                    ModelRun.company_id == company_id,
                    ModelRun.purpose == PURPOSE_ASSISTANT,
                )
            )
            or 0
        )


@pytest.fixture
def intent_case(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    client.cookies.clear()
    _enable_assistant(client, token)
    matter_code = "B5-013-RECORDED-FACTS"
    matter = _matter(client, token, matter_code)
    assert matter["next_hearing_on"] is None
    conversation = _session(client, token, matter["id"])
    provider = RecordFactsProvider(matter)
    provider_builds = []

    def build_provider(*, purpose):
        assert purpose == PURPOSE_ASSISTANT
        provider_builds.append(purpose)
        return provider

    monkeypatch.setattr(assistant, "build_provider", build_provider)
    company_id = str(bootstrap["company"]["id"])
    return SimpleNamespace(
        token=token,
        company_id=company_id,
        matter=matter,
        conversation=conversation,
        provider=provider,
        provider_builds=provider_builds,
        model_count=assistant_model_count(company_id),
    )


@pytest.mark.parametrize("case_name", tuple(FACTUAL_QUESTIONS))
def test_record_facts_and_exact_restrictive_summary_are_not_legal_intent(case_name):
    assert assistant._asks_for_legal_proposition(FACTUAL_QUESTIONS[case_name]) is False


@pytest.mark.parametrize("case_name", tuple(LEGAL_QUESTIONS))
def test_legal_or_mixed_intent_remains_legal_despite_negated_clauses(case_name):
    assert assistant._asks_for_legal_proposition(LEGAL_QUESTIONS[case_name]) is True


@pytest.mark.parametrize(
    "question",
    (
        "Explain the bare act applicable to this matter.",
        "Find case law for this matter.",
        "Which judgment controls this matter?",
        "Which judgement controls this matter?",
        "What is the legal position in this matter?",
        "Find precedent for this matter.",
        "Which statute applies to this matter?",
        "Explain section 21 for this matter.",
        "Explain rule 2 for this matter.",
        "What does the law require for this matter?",
        "Is it legal to proceed with this matter?",
    ),
)
def test_every_original_positive_legal_signal_remains_fail_closed(question):
    assert assistant._asks_for_legal_proposition(question) is True


@pytest.mark.parametrize(
    "question",
    (
        "Who acts as the coordinator for this matter?",
        "What is the recorded status of the ACTS project?",
        "Show the recorded office procedure for document naming.",
    ),
)
def test_incidental_vocabulary_does_not_itself_request_legal_analysis(question):
    assert assistant._asks_for_legal_proposition(question) is False


@pytest.mark.parametrize("case_name", tuple(FACTUAL_QUESTIONS))
def test_fact_question_answers_bind_current_record_without_inventing_a_hearing(
    client: TestClient,
    intent_case,
    case_name,
):
    case = intent_case
    question = FACTUAL_QUESTIONS[case_name]
    if case_name == "missing-next-hearing":
        case.provider.answer = "No next hearing date is recorded for this matter."
    expected_answer = case.provider.answer
    response = _ask(
        client,
        case.token,
        assistant_session=case.conversation,
        question=question,
        no_paid_providers=True,
    )
    assert response.request.headers["X-CaseOps-Automated-Test"] == "no-paid-providers"
    assert response.status_code == 200, response.text
    turn = response.json()["assistant_turn"]
    assert turn["status"] == "completed"
    assert turn["render_status"] == "visible"
    assert turn["content"] == expected_answer
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", turn["content"])
    assert case.provider_builds == [PURPOSE_ASSISTANT]
    assert len(case.provider.calls) == 1
    assert any(
        f"QUESTION: {question}\n" in message.content
        for message in case.provider.calls[0]
    )
    assert len(turn["citations"]) == 1
    citation = turn["citations"][0]
    assert citation["source_type"] == "matter"
    assert citation["source_id"] == case.matter["id"]
    assert citation["source_url"] == f"/app/matters/{case.matter['id']}"
    assert citation["source_version"]
    assert re.fullmatch(r"[0-9a-f]{64}", citation["source_sha256"])
    assert turn["model"]["provider"] == "mock"
    assert turn["model"]["model"] == "caseops-mock-1"
    assert assistant_model_count(case.company_id) == case.model_count + 1
    assert not turn["suggested_searches"]
    assert not turn["proposed_actions"]


@pytest.mark.parametrize("case_name", tuple(LEGAL_QUESTIONS))
def test_unsupported_legal_questions_abstain_before_model_and_offer_only_search(
    client: TestClient,
    intent_case,
    case_name,
):
    case = intent_case
    question = LEGAL_QUESTIONS[case_name]
    response = _ask(
        client,
        case.token,
        assistant_session=case.conversation,
        question=question,
        no_paid_providers=True,
    )
    assert response.request.headers["X-CaseOps-Automated-Test"] == "no-paid-providers"
    assert response.status_code == 200, response.text
    turn = response.json()["assistant_turn"]
    assert turn["status"] == "abstained", "A canned record answer is not legal research"
    assert turn["content"] == ABSTENTION
    assert turn["citations"] == []
    assert turn["model"] is None
    assert case.provider_builds == []
    assert case.provider.calls == []
    assert assistant_model_count(case.company_id) == case.model_count
    assert turn["suggested_searches"] == [assistant.ABSTENTION_SUGGESTION]
    assert [action["action_type"] for action in turn["proposed_actions"]] == ["search"]
    search = turn["proposed_actions"][0]
    assert search["label"] == "Search verified legal sources"
    assert search["href"] == f"/app/research?query={quote_plus(question)}"
    assert search["target_type"] is None
    assert search["target_id"] is None
    assert search["target_version"] is None
    assert search["target_label"] is None
    assert search["requires_confirmation"] is False
    assert search["execution_available"] is False
