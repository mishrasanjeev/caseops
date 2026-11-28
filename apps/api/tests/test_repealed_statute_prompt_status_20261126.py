"""Repealed provisions are quoted with their repeal status, never as current law.

Retained repealed-law editions (CrPC 1973, IPC, Evidence Act and the
Income-tax Act, 1961) stay attachable so lawyers can work on matters governed
by the earlier law. Drafting and strategy prompts quote their text, so each
quoted repealed provision must carry an explicit caution; current provisions
must not.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import Draft, Matter, StatuteSection
from caseops_api.db.session import get_session_factory
from caseops_api.services.statute_selection import (
    REPEALED_EDITION_CAUTION,
    is_selectable_statute_section,
)
from tests.test_auth_company import auth_headers
from tests.test_matter_statute_references import _bootstrap_with_statutes_and_matter


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
