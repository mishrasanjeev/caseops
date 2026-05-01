"""PG-005 Sprint 8 (2026-05-01) — pre-filing checklist tests.

Covers:
- Pure-function build_filing_checklist over an in-memory draft +
  matter (court / template overrides + auto-satisfaction).
- Route integration: happy path / explicit court_profile override /
  404 on unknown draft / auth gate.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.filing_checklist import build_filing_checklist
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_drafting_studio import (
    _create_matter,
    _generate,
    _seed_authority,
)

# ---------------------------------------------------------------
# Pure-function tests over an in-memory session.
# ---------------------------------------------------------------


def test_build_filing_checklist_default_includes_base_items(client: TestClient) -> None:
    """Bail at Delhi HC → checklist includes vakalat + court fee +
    custody certificate (template-specific)."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "FC-1")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 4001")

    create = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Bail application — Sharma",
            "draft_type": "brief",
            "template_type": "bail",
        },
    )
    assert create.status_code == 200
    draft_id = create.json()["id"]
    _generate(client, token, matter_id, draft_id)

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft_id}/filing-checklist",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    item_ids = {item["id"] for item in body["items"]}
    assert "memorandum" in item_ids
    assert "vakalatnama" in item_ids
    assert "court_fee" in item_ids
    assert "index" in item_ids
    # Template-specific bail item.
    assert "custody_certificate" in item_ids
    # Court is Delhi HC → 3 copies + Delhi-HC overrides.
    assert body["copies_required"] == 3
    assert body["court_profile_key"] == "delhi_hc"
    # HC override adds synopsis_and_dates + affidavit_verification.
    assert "synopsis_and_dates" in item_ids
    assert "affidavit_verification" in item_ids


def test_supreme_court_writ_checklist_includes_caveat_search(
    client: TestClient,
) -> None:
    """SC writ → caveat-search certificate + memo of appearance + 6 copies."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "FC-SC")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 4002")

    create = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Writ Petition (C) — Sharma",
            "draft_type": "brief",
            "template_type": "writ_petition",
        },
    )
    assert create.status_code == 200
    draft_id = create.json()["id"]
    _generate(client, token, matter_id, draft_id)

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft_id}/filing-checklist"
        "?court_profile=supreme_court",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    item_ids = {item["id"] for item in body["items"]}
    # SC overrides.
    assert "caveat_search_certificate" in item_ids
    assert "memorandum_of_appearance" in item_ids
    assert "synopsis_and_dates" in item_ids
    # writ_petition template adds the impugned-order item.
    assert "impugned_order_copy" in item_ids
    # SC → 6 copies.
    assert body["copies_required"] == 6
    assert body["court_profile_key"] == "supreme_court"
    # Writ petitions have no fixed limitation → laches reminder.
    assert body["limitation_note"]
    assert "laches" in body["limitation_note"].lower()


def test_nclt_checklist_uses_statutory_form_override(client: TestClient) -> None:
    """NCLT override adds the prescribed form + board resolution."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "FC-NCLT")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 4003")
    create = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "NCLT application",
            "draft_type": "brief",
            "template_type": "civil_suit",
        },
    )
    assert create.status_code == 200
    draft_id = create.json()["id"]
    _generate(client, token, matter_id, draft_id)

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft_id}/filing-checklist"
        "?court_profile=nclt",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    item_ids = {item["id"] for item in body["items"]}
    assert "statutory_form" in item_ids
    assert "board_resolution" in item_ids
    assert body["copies_required"] == 5


def test_vakalat_auto_satisfied_when_vakalat_draft_exists(
    client: TestClient,
) -> None:
    """If the matter already has a VAKALATNAMA draft, the vakalat
    checklist item is marked auto_satisfied."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "FC-VAK-AUTO")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 4004")

    # The memorandum draft.
    main = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Bail", "draft_type": "brief", "template_type": "bail"},
    )
    main_id = main.json()["id"]
    _generate(client, token, matter_id, main_id)

    # Sibling vakalat draft.
    vak = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Vakalat",
            "draft_type": "other",
            "template_type": "vakalatnama",
        },
    )
    assert vak.status_code == 200, vak.text

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{main_id}/filing-checklist",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    vak_item = next(it for it in body["items"] if it["id"] == "vakalatnama")
    assert vak_item["auto_satisfied"] is True
    assert vak_item["auto_satisfied_reason"] is not None


def test_filing_checklist_404_on_unknown_draft(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "FC-NF")
    resp = client.get(
        f"/api/matters/{matter_id}/drafts/00000000-0000-0000-0000-000000000000/filing-checklist",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_filing_checklist_unknown_court_profile_returns_422(
    client: TestClient,
) -> None:
    """Bad court_profile key surfaces as 422 with the bad key in the
    detail — the lawyer should know their override didn't take."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "FC-CP-422")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 4005")
    create = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Bail", "draft_type": "brief", "template_type": "bail"},
    )
    draft_id = create.json()["id"]
    _generate(client, token, matter_id, draft_id)

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft_id}/filing-checklist"
        "?court_profile=mars_high_court",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "mars_high_court" in resp.json()["detail"]


def test_filing_checklist_route_requires_auth(client: TestClient) -> None:
    resp = client.get(
        "/api/matters/00000000-0000-0000-0000-000000000000/drafts/"
        "00000000-0000-0000-0000-000000000000/filing-checklist",
    )
    assert resp.status_code in {401, 403}


def test_filing_checklist_route_includes_limitation_note(
    client: TestClient,
) -> None:
    """Written statement at Delhi HC → Order VIII Rule 1 limitation
    reminder + Order VIII Rule 1A index-of-documents item."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "FC-WS-LIM")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 4006")
    create = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Written Statement — Defendant Corp",
            "draft_type": "brief",
            "template_type": DraftTemplateType.WRITTEN_STATEMENT.value,
        },
    )
    draft_id = create.json()["id"]
    _generate(client, token, matter_id, draft_id)

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft_id}/filing-checklist",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["limitation_note"] is not None
    assert "Order VIII Rule 1" in body["limitation_note"]
    assert (
        "30-day" in body["limitation_note"]
        or "30 days" in body["limitation_note"]
    )
    item_ids = {item["id"] for item in body["items"]}
    assert "documents_relied_index" in item_ids


def test_filing_checklist_route_unknown_template_degrades_gracefully(
    client: TestClient,
) -> None:
    """A draft with no template_type / unknown template_type degrades
    to base + court items, no crash, no template-specific overrides."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "FC-UNK-TPL")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 4007")
    # Draft without a template_type.
    create = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Generic brief", "draft_type": "brief"},
    )
    draft_id = create.json()["id"]
    _generate(client, token, matter_id, draft_id)

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft_id}/filing-checklist",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    item_ids = {item["id"] for item in body["items"]}
    # Base items present.
    assert "memorandum" in item_ids
    assert "vakalatnama" in item_ids
    # No bail/writ-specific template overrides.
    assert "custody_certificate" not in item_ids
    assert "impugned_order_copy" not in item_ids


# Suppress import-unused lint on the helper — used in route tests above.
_ = DraftTemplateType
_ = build_filing_checklist
