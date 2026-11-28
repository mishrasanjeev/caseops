"""Repealed provisions are quoted with their repeal status, never as current law.

Retained repealed-law editions (CrPC 1973, IPC, Evidence Act and the
Income-tax Act, 1961) stay attachable so lawyers can work on matters governed
by the earlier law. Every prompt that quotes statute text (drafting, litigation
strategy, research answers and recommendations) must carry an explicit caution
beside each quoted repealed provision; current provisions must not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import Draft, Matter, StatuteSection
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.seed_statutes import _seed
from caseops_api.services.statute_selection import (
    REPEALED_EDITION_CAUTION,
    is_selectable_statute_section,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_matter_statute_references import _bootstrap_with_statutes_and_matter

SERVICES = Path(__file__).resolve().parents[1] / "src/caseops_api/services"


def _section(session, statute_id: str, number: str) -> StatuteSection:
    row = session.scalar(
        select(StatuteSection).where(
            StatuteSection.statute_id == statute_id,
            StatuteSection.section_number == number,
        )
    )
    assert row is not None, f"{statute_id} {number} is not catalogued"
    return row


def _attach_repealed_and_current(client: TestClient) -> str:
    token, matter_id, _ = _bootstrap_with_statutes_and_matter(client)
    with get_session_factory()() as session:
        repealed = _section(session, "crpc-1973", "Section 482")
        current = _section(session, "constitution-india", "Article 21")
        assert repealed.legal_status == "repealed"
        assert current.legal_status == "enacted"
        assert is_selectable_statute_section(repealed)
        assert is_selectable_statute_section(current)
        ids = [str(repealed.id), str(current.id)]
    for section_id in ids:
        response = client.post(
            f"/api/matters/{matter_id}/statute-references",
            json={"section_id": section_id, "relevance": "cited"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201, response.text
    return matter_id


def _block_for(prompt: str, marker: str) -> str:
    """The prompt lines from `marker` up to the next quoted provision."""
    start = prompt.index(marker)
    rest = prompt[start + len(marker):]
    ends = [i for i in (rest.find("\n["), rest.find("\n- [")) if i >= 0]
    return prompt[start: start + len(marker) + (min(ends) if ends else len(rest))]


def test_drafting_prompt_labels_only_the_repealed_provision(client: TestClient) -> None:
    from caseops_api.services.drafting import _attached_statute_refs, _build_messages

    matter_id = _attach_repealed_and_current(client)
    with get_session_factory()() as session:
        refs = _attached_statute_refs(session, matter_id)
        by_number = {ref["section_number"]: ref for ref in refs}
        assert by_number["Section 482"]["legal_status"] == "repealed"
        assert by_number["Article 21"]["legal_status"] == "enacted"
        matter = session.get(Matter, matter_id)
        draft = Draft(
            matter_id=matter.id, title="Repeal status draft",
            draft_type="appeal_memorandum", template_type="appeal_memorandum",
            facts_json="{}", status="drafted",
        )
        session.add(draft)
        session.flush()
        messages = _build_messages(matter, draft, [], None, bench_context=None, statute_refs=refs)
        session.rollback()
    prompt = "\n".join(message.content for message in messages)
    repealed_block = _block_for(prompt, "Section 482")
    current_block = _block_for(prompt, "Article 21")
    assert REPEALED_EDITION_CAUTION in repealed_block
    assert REPEALED_EDITION_CAUTION not in current_block
    assert prompt.count(REPEALED_EDITION_CAUTION) == 1


def test_strategy_prompt_labels_only_the_repealed_provision(client: TestClient) -> None:
    from caseops_api.services.litigation_strategy import _assemble_context, _build_prompt

    matter_id = _attach_repealed_and_current(client)
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        ctx = _assemble_context(session, matter)
        notes = {snippet.section_number: snippet.status_note for snippet in ctx.statute_snippets}
        assert notes == {"Section 482": REPEALED_EDITION_CAUTION, "Article 21": None}
        messages = _build_prompt(ctx=ctx, authorities=[])
    prompt = "\n".join(message.content for message in messages)
    repealed_block = _block_for(prompt, "s.Section 482")
    current_block = _block_for(prompt, "s.Article 21")
    assert f"STATUS: {REPEALED_EDITION_CAUTION}" in repealed_block
    assert "STATUS:" not in current_block


# --------------------------------------------------------------------------- #
# Research answers: the provision the question names is the first source.
# --------------------------------------------------------------------------- #

REPEALED_QUESTION = "Can the High Court quash an FIR under Section 482 CrPC?"
CURRENT_QUESTION = (
    "What must a complainant prove under Section 138 of the Negotiable Instruments Act?"
)


def _research_prompts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, question: str
) -> list[str]:
    """Every prompt the model receives for `question`, over the real catalogue."""
    from caseops_api.services import research_answers
    from tests.test_research_answers_20261124 import _answer, _ask, _Scripted

    token = bootstrap_company(client)["access_token"]
    with get_session_factory()() as session:
        _seed(session)
    provider = _Scripted(
        _answer(
            short_answer="The provision named in the question governs it [1].",
            key_points=["The provision sets the governing rule [1]."],
            sections=[{"key": "applicable_law", "paragraphs": ["The provision applies [1]."]}],
            authorities=[
                {"source": 1, "disposition": "supporting", "proposition": "The rule.",
                 "relevance": "Named in the question.", "passage": None},
            ],
        )
    )
    monkeypatch.setattr(research_answers, "build_provider", lambda **_: provider)
    record = _ask(client, token, query=question)
    assert provider.prompts, (record["status"], record["error_code"], record["message"])
    return provider.prompts


def _research_statute_sources(prompt: str) -> list[dict]:
    marker = "RESEARCH_INPUT:\n"
    payload, _end = json.JSONDecoder().raw_decode(prompt, prompt.index(marker) + len(marker))
    return [source for source in payload["sources"] if source["kind"] == "statute_section"]


def test_research_prompt_labels_a_repealed_focus_provision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts = _research_prompts(client, monkeypatch, REPEALED_QUESTION)
    with get_session_factory()() as session:
        crpc_482 = _section(session, "crpc-1973", "Section 482")
        assert crpc_482.legal_status == "repealed"
        assert is_selectable_statute_section(crpc_482)
    for prompt in prompts:
        statutes = _research_statute_sources(prompt)
        assert [source["citation"] for source in statutes] == ["CrPC, Section 482"]
        source = statutes[0]
        assert source["status"] == REPEALED_EDITION_CAUTION
        # Beside the text it qualifies: the quoted excerpt is the next field.
        keys = list(source)
        assert keys[keys.index("status") + 1] == "untrusted_excerpt"
        assert "inherent powers" in source["untrusted_excerpt"]
        assert prompt.count(REPEALED_EDITION_CAUTION) == 1


def test_research_prompt_leaves_a_current_provision_unlabelled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts = _research_prompts(client, monkeypatch, CURRENT_QUESTION)
    for prompt in prompts:
        statutes = _research_statute_sources(prompt)
        assert [source["citation"] for source in statutes] == ["NI Act, Section 138"]
        assert statutes[0]["untrusted_excerpt"]
        assert "status" not in statutes[0]
        assert "REPEALED LAW" not in prompt


# --------------------------------------------------------------------------- #
# Recommendations: linked statute references in the matter context.
# --------------------------------------------------------------------------- #

# A user note longer than a context line's whole budget.
LONG_NOTE = "Quashing petition filed in 2023 under the earlier Code. " * 25
CONTEXT_LINE_BUDGET = 700


def _recommendation_prompt(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    from caseops_api.services.llm import LLMCompletion
    from tests.test_recommendations import _seed_relevant_authority, _setup_matter

    token, _slug, matter_id = _setup_matter(client)
    _seed_relevant_authority()
    with get_session_factory()() as session:
        _seed(session)
        repealed = _section(session, "crpc-1973", "Section 482")
        current = _section(session, "ni-act-1881", "Section 138")
        assert (repealed.legal_status, current.legal_status) == ("repealed", "enacted")
        assert is_selectable_statute_section(repealed)
        assert is_selectable_statute_section(current)
        attachments = [(str(repealed.id), LONG_NOTE), (str(current.id), "Cheque returned unpaid.")]
    for section_id, notes in attachments:
        response = client.post(
            f"/api/matters/{matter_id}/statute-references",
            json={"section_id": section_id, "relevance": "cited", "notes": notes},
            headers=auth_headers(token),
        )
        assert response.status_code == 201, response.text

    prompts: list[str] = []

    class _Capture:
        name = "mock"
        model = "mock-repeal-status"

        def generate(self, messages, **_kwargs):
            prompts.append("\n".join(message.content for message in messages))
            payload = {
                "title": "Review the linked provisions",
                "options": [
                    {
                        "label": "Review the award challenge",
                        "rationale": (
                            "The award is said to be fundamentally opposed to Indian law, "
                            "which is the patent illegality ground under Section 34."
                        ),
                        "confidence": "medium",
                        "supporting_citations": ["[1] Ssangyong Engg v. NHAI (2019)"],
                        "risk_notes": None,
                    }
                ],
                "primary_recommendation_label": "Review the award challenge",
                "rationale": "Source-backed observations for lawyer review.",
                "assumptions": [],
                "missing_facts": [],
                "confidence": "medium",
                "next_action": None,
            }
            return LLMCompletion(
                text=json.dumps(payload), provider=self.name, model=self.model,
                prompt_tokens=11, completion_tokens=21, latency_ms=5,
            )

    monkeypatch.setattr(
        "caseops_api.services.recommendations.build_provider", lambda *a, **kw: _Capture()
    )
    response = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert response.status_code == 200, response.text
    assert len(prompts) == 1
    return prompts[0]


def test_recommendation_prompt_labels_only_the_repealed_provision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = _recommendation_prompt(client, monkeypatch)
    statute_lines = {
        line.split(" | ")[1]: line
        for line in prompt.split("\n")
        if line.startswith("- statute: ")
    }
    assert set(statute_lines) == {"Section 482", "Section 138"}
    repealed, current = statute_lines["Section 482"], statute_lines["Section 138"]
    assert repealed.startswith("- statute: CrPC | Section 482 | ")
    assert current.startswith("- statute: NI Act | Section 138 | ")
    assert REPEALED_EDITION_CAUTION in repealed
    # Ahead of the note and the text, the parts the line budget cuts.
    assert repealed.index(REPEALED_EDITION_CAUTION) < repealed.index("relevance=cited")
    assert "REPEALED LAW" not in current
    assert prompt.count(REPEALED_EDITION_CAUTION) == 1
    # The caution sits outside the line budget: the repealed provision keeps the
    # same room for its note and text as a current one.
    prefix = len("- statute: ")
    assert len(current) == prefix + CONTEXT_LINE_BUDGET
    assert len(repealed) - len(f"{REPEALED_EDITION_CAUTION} | ") == prefix + CONTEXT_LINE_BUDGET


# --------------------------------------------------------------------------- #
# Inventory: every service that reads statute text is accounted for.
# --------------------------------------------------------------------------- #

# Prompt builders that quote StatuteSection.section_text to a model.
QUOTES_STATUTE_TEXT_TO_A_MODEL = (
    "drafting",
    "litigation_strategy",
    "recommendations",
    "research_answers",
)
# Modules that read the text but send it to no generated answer.
READS_STATUTE_TEXT_WITHOUT_AN_ANSWER_PROMPT = {
    "judgment_alerts": "a judgment's cited-section list matched against watchlist terms",
    "legal_updates": "watchlist matching and a stored feed snippet; no model call",
    "statute_enrichment": "writes the text; its model prompt names the Act and section only",
    "statute_selection": "the attachable-provision predicate and the caution itself",
    "statute_source_governance": "diffs reviewed source text; no model call",
    "statute_vectors": "chunking, embedding and reranker scoring; no generated answer",
}


def test_every_service_reading_statute_text_is_accounted_for() -> None:
    readers = {
        path.stem
        for path in SERVICES.glob("*.py")
        if "section_text" in path.read_text(encoding="utf-8")
    }
    assert readers == {
        *QUOTES_STATUTE_TEXT_TO_A_MODEL,
        *READS_STATUTE_TEXT_WITHOUT_AN_ANSWER_PROMPT,
    }
    for name in QUOTES_STATUTE_TEXT_TO_A_MODEL:
        source = (SERVICES / f"{name}.py").read_text(encoding="utf-8")
        assert "repealed_edition_caution(" in source, name
