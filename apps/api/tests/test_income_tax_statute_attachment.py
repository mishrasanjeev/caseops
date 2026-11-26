"""Workbook row 1 (2026-11-26): the Income-tax Act, 1961 must be attachable.

The tester saw "0 of 298 verified" because no official consolidated edition
was pinned. The Income Tax Department edition (as amended by the Finance Act,
2026) is now compiled from its hash-checked release asset as a retained
repealed-law edition. These journeys seed the real release data and prove the
server-owned predicate and the attach endpoint agree: verified sections attach
and stay labelled repealed; quarantined, omitted and unprinted ones do not.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.api.routes.statutes import _is_selectable_statute_section
from caseops_api.db.models import StatuteSection
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_matter_statute_references import _bootstrap_with_statutes_and_matter

ACT = "income-tax-1961"
ATTACHABLE = ("Section 80C", "Section 148A", "Section 194-I", "Section 292A")
WITHHELD = (
    ("Section 139", "quarantined"),
    ("Section 282B", "quarantined"),
    ("Section 20", "retired"),
    ("Section 103", "retired"),
    ("Thirteenth Schedule", "quarantined"),
    ("Section 186", "unverified"),
)


def _section(session, number: str) -> StatuteSection:
    row = session.scalar(
        select(StatuteSection).where(
            StatuteSection.statute_id == ACT, StatuteSection.section_number == number
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


def test_income_tax_sections_attach_as_a_labelled_repealed_edition(client: TestClient) -> None:
    token, matter_id, _ = _bootstrap_with_statutes_and_matter(client)
    with get_session_factory()() as session:
        rows = {number: _section(session, number) for number in ATTACHABLE}
        for number, row in rows.items():
            assert _is_selectable_statute_section(row), number
            assert row.legal_status == "repealed"
            assert row.source_policy_json["edition_scope"] == "historical_repealed_law"
            assert row.effective_to == date(2026, 3, 31)
        section_ids = {number: str(row.id) for number, row in rows.items()}

    for number, section_id in section_ids.items():
        response = _attach(client, token, matter_id, section_id)
        assert response.status_code == 201, (number, response.text)
        assert response.json()["section_number"] == number

    listed = client.get(f"/api/statutes/{ACT}/sections", headers=auth_headers(token))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["verified_section_count"] == 823
    # 965 printed identities and Schedules plus the unprinted Section 186 placeholder.
    assert body["catalog_section_count"] == 966
    states = {row["section_number"]: row["selection_state"] for row in body["catalog_sections"]}
    for number in ATTACHABLE:
        assert states[number] == "verified_selectable"
    detail = client.get(
        f"/api/statutes/{ACT}/sections/Section%2080C", headers=auth_headers(token)
    ).json()["section"]
    assert detail["legal_status"] == "repealed"
    assert detail["effective_to"] == "2026-03-31"
    assert detail["section_text"].startswith("80C. (1) In computing the total income")


def test_income_tax_withheld_entries_stay_unattachable(client: TestClient) -> None:
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
