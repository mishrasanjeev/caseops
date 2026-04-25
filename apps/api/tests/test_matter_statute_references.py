"""Slice S4 (MOD-TS-017) — matter statute reference + drafting prompt
extension tests.

Maps to FT-S4-1 .. FT-S4-4 in
``docs/PRD_STATUTE_MODEL_2026-04-25.md`` §3 Slice S4.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    Draft,
    Matter,
    StatuteSection,
)
from caseops_api.scripts.seed_statutes import _seed
from caseops_api.services.drafting import _build_messages
from tests.test_auth_company import auth_headers, bootstrap_company


def _bootstrap_with_statutes_and_matter(client: TestClient):
    """Bootstrap a company, seed statutes, create one matter. Returns
    (token, matter_id, company_id)."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        _seed(s)
    resp = client.post(
        "/api/matters",
        json={
            "matter_code": f"S4-{__import__('uuid').uuid4().hex[:6]}",
            "title": "S4 statute refs test",
            "practice_area": "Criminal",
            "forum_level": "high_court",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return token, resp.json()["id"], company_id


def test_ft_s4_1_attach_statute_to_matter_returns_201(
    client: TestClient,
) -> None:
    """POST /matters/{id}/statute-references with a valid section_id
    creates a row + returns 201 with statute_short_name + section_number
    populated for UI rendering."""
    from caseops_api.db.session import get_session_factory

    token, matter_id, _ = _bootstrap_with_statutes_and_matter(client)
    with get_session_factory()() as s:
        section_id = s.scalar(
            select(StatuteSection.id).where(
                StatuteSection.statute_id == "crpc-1973",
                StatuteSection.section_number == "Section 482",
            )
        )
    resp = client.post(
        f"/api/matters/{matter_id}/statute-references",
        json={"section_id": section_id, "relevance": "cited"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["statute_short_name"] == "CrPC"
    assert body["section_number"] == "Section 482"
    assert body["relevance"] == "cited"


def test_ft_s4_2_post_is_idempotent_on_duplicate(client: TestClient) -> None:
    """Re-posting the same (section_id, relevance) returns the
    existing row without erroring (uq_matter_statute_references_unique
    handled at the route level)."""
    from caseops_api.db.session import get_session_factory

    token, matter_id, _ = _bootstrap_with_statutes_and_matter(client)
    with get_session_factory()() as s:
        section_id = s.scalar(
            select(StatuteSection.id).where(
                StatuteSection.statute_id == "ipc-1860",
                StatuteSection.section_number == "Section 302",
            )
        )
    payload = {"section_id": section_id, "relevance": "cited"}
    r1 = client.post(
        f"/api/matters/{matter_id}/statute-references",
        json=payload, headers=auth_headers(token),
    )
    r2 = client.post(
        f"/api/matters/{matter_id}/statute-references",
        json=payload, headers=auth_headers(token),
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    # Only one row exists.
    list_resp = client.get(
        f"/api/matters/{matter_id}/statute-references",
        headers=auth_headers(token),
    )
    assert len(list_resp.json()["references"]) == 1


def test_ft_s4_3_cross_tenant_matter_returns_404(client: TestClient) -> None:
    """Posting a statute reference against another tenant's matter id
    returns 404 (matter scope enforced via Matter.company_id)."""
    from caseops_api.db.session import get_session_factory

    token_a, matter_a_id, _ = _bootstrap_with_statutes_and_matter(client)
    # Bootstrap a second company directly; that token can't see matter_a.
    resp_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Co LLP",
            "company_slug": "other-co",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@otherco.in",
            "owner_password": "OtherPass123!",
        },
    )
    assert resp_b.status_code == 200, resp_b.text
    token_b = str(resp_b.json()["access_token"])
    with get_session_factory()() as s:
        section_id = s.scalar(
            select(StatuteSection.id).where(
                StatuteSection.statute_id == "crpc-1973",
                StatuteSection.section_number == "Section 482",
            )
        )
    resp = client.post(
        f"/api/matters/{matter_a_id}/statute-references",
        json={"section_id": section_id, "relevance": "cited"},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 404
    assert "matter not found" in resp.json()["detail"].lower()


def test_ft_s4_4_drafting_prompt_includes_statutory_text_block(
    client: TestClient,
) -> None:
    """When a matter has attached statute references, _build_messages
    injects a STATUTORY TEXT block into the prompt with section
    number + label + relevance + bare text (or 'not yet indexed'
    fallback when section_text is NULL).

    Per PRD §2.1 advocate-bias: relevance label preserved so the
    LLM knows whose argument the section supports.
    """
    from caseops_api.db.session import get_session_factory

    token, matter_id, _ = _bootstrap_with_statutes_and_matter(client)
    with get_session_factory()() as s:
        # Patch one section's bare text so we exercise both the
        # "verbatim quote" and the "not yet indexed" branches.
        sec_482 = s.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "crpc-1973",
                StatuteSection.section_number == "Section 482",
            )
        )
        sec_482.section_text = (
            "Nothing in this Code shall be deemed to limit or affect "
            "the inherent powers of the High Court to make such "
            "orders as may be necessary to give effect to any order "
            "under this Code, or to prevent abuse of the process of "
            "any Court or otherwise to secure the ends of justice."
        )
        s.commit()

    # Attach two refs: 'cited' Section 482 (with bare text) +
    # 'opposing' Section 302 IPC (no bare text).
    section_ids = []
    with get_session_factory()() as s:
        for stat_id, num in [
            ("crpc-1973", "Section 482"),
            ("ipc-1860", "Section 302"),
        ]:
            sid = s.scalar(
                select(StatuteSection.id).where(
                    StatuteSection.statute_id == stat_id,
                    StatuteSection.section_number == num,
                )
            )
            section_ids.append(sid)
    client.post(
        f"/api/matters/{matter_id}/statute-references",
        json={"section_id": section_ids[0], "relevance": "cited"},
        headers=auth_headers(token),
    )
    client.post(
        f"/api/matters/{matter_id}/statute-references",
        json={"section_id": section_ids[1], "relevance": "opposing"},
        headers=auth_headers(token),
    )

    # Build the prompt directly with the statute_refs we'd otherwise
    # fetch in generate_draft_version. Verifies _build_messages emits
    # the new block when statute_refs is non-empty.
    with get_session_factory()() as s:
        matter = s.scalar(select(Matter).where(Matter.id == matter_id))
        # Synthesise a minimal Draft with template_type appeal_memorandum
        # so the rest of _build_messages doesn't bail.
        draft = Draft(
            matter_id=matter.id, title="Test draft",
            draft_type="appeal_memorandum",
            template_type="appeal_memorandum",
            facts_json="{}", status="drafted",
        )
        s.add(draft)
        s.flush()

        statute_refs = [
            {
                "statute_short_name": "CrPC",
                "section_number": "Section 482",
                "section_label": "Saving of inherent powers of High Court",
                "section_text": (
                    "Nothing in this Code shall be deemed to limit or "
                    "affect the inherent powers of the High Court..."
                ),
                "section_url": "https://www.indiacode.nic.in/handle/123456789/15272",
                "relevance": "cited",
            },
            {
                "statute_short_name": "IPC",
                "section_number": "Section 302",
                "section_label": "Punishment for murder",
                "section_text": None,
                "section_url": "https://www.indiacode.nic.in/handle/123456789/2263",
                "relevance": "opposing",
            },
        ]
        messages = _build_messages(
            matter, draft, [], None,
            bench_context=None,
            statute_refs=statute_refs,
        )
    full_prompt = "\n".join(m.content for m in messages)
    # Block header present.
    assert "STATUTORY TEXT" in full_prompt
    # Both sections referenced.
    assert "CrPC Section 482" in full_prompt
    assert "IPC Section 302" in full_prompt
    # Relevance tags surfaced.
    assert "[cited]" in full_prompt
    assert "[opposing]" in full_prompt
    # Bare text rendered when present.
    assert "inherent powers of the High Court" in full_prompt
    # Fallback to source URL when section_text is NULL.
    assert "verify at:" in full_prompt or "indiacode.nic.in" in full_prompt
    # Required-phrasing instruction present.
    assert "verbatim" in full_prompt.lower()
    assert "NEVER" in full_prompt and "paraphrase" in full_prompt
