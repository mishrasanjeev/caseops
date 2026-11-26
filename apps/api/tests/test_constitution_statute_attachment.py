"""Workbook row 1 (2026-11-26): Constitution Articles must be attachable.

The tester could select only Article 14 because the Constitution was not in
the pinned official bundle. These journeys seed the real release data and
prove the server-owned selectable predicate, the attach endpoint and the
drafting/strategy prompt readers agree on the same provisions.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.api.routes.statutes import _is_selectable_statute_section
from caseops_api.db.models import Matter, StatuteSection
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_matter_statute_references import _bootstrap_with_statutes_and_matter

ATTACHABLE_ARTICLES = ("Article 19", "Article 21", "Article 32", "Article 226", "Article 227")
WITHHELD = (
    ("Article 31", "retired"),
    ("Article 379", "retired"),
    ("First Schedule", "quarantined"),
)


def _section(session, number: str) -> StatuteSection:
    row = session.scalar(
        select(StatuteSection).where(
            StatuteSection.statute_id == "constitution-india",
            StatuteSection.section_number == number,
        )
    )
    assert row is not None, f"{number} is not catalogued"
    return row


def _attach(client: TestClient, token: str, matter_id: str, section_id: str):
    return client.post(
        f"/api/matters/{matter_id}/statute-references",
        json={"section_id": section_id, "relevance": "cited"},
        headers=auth_headers(token),
    )


def constitution_articles_attach_after_seed(client: TestClient) -> None:
    token, matter_id, _ = _bootstrap_with_statutes_and_matter(client)
    with get_session_factory()() as session:
        rows = {number: _section(session, number) for number in ATTACHABLE_ARTICLES}
        for number, row in rows.items():
            assert _is_selectable_statute_section(row), number
        section_ids = {number: str(row.id) for number, row in rows.items()}
        article_14 = session.scalars(
            select(StatuteSection).where(
                StatuteSection.statute_id == "constitution-india",
                StatuteSection.section_number == "Article 14",
            )
        ).all()
        assert len(article_14) == 1

    for number, section_id in section_ids.items():
        response = _attach(client, token, matter_id, section_id)
        assert response.status_code == 201, (number, response.text)
        assert response.json()["section_number"] == number

    listed = client.get(
        "/api/statutes/constitution-india/sections", headers=auth_headers(token)
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["verified_section_count"] == 481
    assert body["catalog_section_count"] == 519
    states = {row["section_number"]: row["selection_state"] for row in body["catalog_sections"]}
    assert "verification_pending" not in states.values()
    for number in ATTACHABLE_ARTICLES:
        assert states[number] == "verified_selectable"


def constitution_withheld_entries_stay_unattachable(client: TestClient) -> None:
    token, matter_id, _ = _bootstrap_with_statutes_and_matter(client)
    with get_session_factory()() as session:
        withheld = {}
        for number, state in WITHHELD:
            row = _section(session, number)
            assert row.verification_status == state, number
            assert not _is_selectable_statute_section(row), number
            withheld[number] = str(row.id)
    for number, section_id in withheld.items():
        response = _attach(client, token, matter_id, section_id)
        assert response.status_code == 409, (number, response.text)
        assert response.json()["type"] == "statute_section_not_verified"


def test_constitution_articles_attach_after_seed(client: TestClient) -> None:
    constitution_articles_attach_after_seed(client)


def test_constitution_omitted_and_quarantined_entries_stay_unattachable(
    client: TestClient,
) -> None:
    constitution_withheld_entries_stay_unattachable(client)


def _attach_then_repeal_article_19(client: TestClient) -> str:
    """Attach Articles 19 and 21, then make 19 fail only the canonical rule.

    A repealed provision without a historical edition scope keeps every field
    the former drafting/strategy readers checked, so they kept quoting it.
    """
    token, matter_id, _ = _bootstrap_with_statutes_and_matter(client)
    with get_session_factory()() as session:
        ids = {number: str(_section(session, number).id) for number in ("Article 19", "Article 21")}
    for section_id in ids.values():
        assert _attach(client, token, matter_id, section_id).status_code == 201
    with get_session_factory()() as session:
        row = _section(session, "Article 19")
        row.legal_status = "repealed"
        session.commit()
        assert row.verification_status == "verified_official"
        assert not _is_selectable_statute_section(row)
    return matter_id


def test_drafting_quotes_only_attachable_statute_references(client: TestClient) -> None:
    from caseops_api.services.drafting import _attached_statute_refs

    matter_id = _attach_then_repeal_article_19(client)
    with get_session_factory()() as session:
        refs = _attached_statute_refs(session, matter_id)
    assert [ref["section_number"] for ref in refs] == ["Article 21"]
    assert refs[0]["section_text"].startswith("21. Protection of life and personal liberty.")


def test_strategy_context_carries_only_attachable_statute_references(
    client: TestClient,
) -> None:
    from caseops_api.services.litigation_strategy import _assemble_context

    matter_id = _attach_then_repeal_article_19(client)
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        snippets = _assemble_context(session, matter).statute_snippets
    assert [snippet.section_number for snippet in snippets] == ["Article 21"]
