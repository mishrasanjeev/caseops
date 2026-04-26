"""Format-to-forum template recommender tests (PRD §16.3,
2026-04-26).

Covers:
- High-court criminal → BAIL + ANTICIPATORY_BAIL primary,
  APPEAL_MEMORANDUM secondary.
- Supreme-court anything → APPEAL_MEMORANDUM dominates.
- s.138 NI Act → CHEQUE_BOUNCE_NOTICE primary.
- Practice-area normalisation: "Matrimonial law" → matrimonial bucket.
- Forum-default fallback when practice_area doesn't match.
- Unknown forum_level returns empty.
- Stable order: primary entries first, secondary second.
- Route returns the matrix response shape correctly.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.template_recommender import (
    recommend_templates,
)
from tests.test_auth_company import auth_headers, bootstrap_company


def test_high_court_criminal_recommends_bail_first() -> None:
    recs = recommend_templates(
        forum_level="high_court", practice_area="Criminal",
    )
    types = [r.template_type for r in recs]
    assert types[0] == DraftTemplateType.BAIL
    assert DraftTemplateType.ANTICIPATORY_BAIL in types[:2]
    assert DraftTemplateType.APPEAL_MEMORANDUM in types
    # Order invariant: primaries before secondaries.
    primary_idx = max(
        i for i, r in enumerate(recs) if r.relevance == "primary"
    )
    secondary_idx = min(
        (i for i, r in enumerate(recs) if r.relevance == "secondary"),
        default=999,
    )
    assert primary_idx < secondary_idx


def test_supreme_court_appellate_recommends_appeal_memorandum() -> None:
    recs = recommend_templates(
        forum_level="supreme_court", practice_area="Appellate",
    )
    assert recs[0].template_type == DraftTemplateType.APPEAL_MEMORANDUM
    assert recs[0].relevance == "primary"


def test_cheque_bounce_routes_to_ni_act_template() -> None:
    """s.138 NI Act practice → CHEQUE_BOUNCE_NOTICE primary, even
    when practice_area is phrased as 'Cheque bounce' / 'NI Act' /
    'banking'."""
    for area in ("Cheque bounce", "NI Act", "Banking", "Negotiable instruments"):
        recs = recommend_templates(
            forum_level="lower_court", practice_area=area,
        )
        types = [r.template_type for r in recs]
        assert DraftTemplateType.CHEQUE_BOUNCE_NOTICE in types[:2], (
            f"area={area!r}: expected CHEQUE_BOUNCE_NOTICE in top 2, "
            f"got {types}"
        )


def test_practice_area_normalisation_matrimonial() -> None:
    """'Matrimonial law', 'Divorce', 'Family' all bucket the same
    way → DIVORCE_PETITION primary."""
    for area in ("Matrimonial law", "Divorce", "Family"):
        recs = recommend_templates(
            forum_level="high_court", practice_area=area,
        )
        types = [r.template_type for r in recs]
        assert DraftTemplateType.DIVORCE_PETITION in types[:2], (
            f"area={area!r}: expected DIVORCE_PETITION in top 2, "
            f"got {types}"
        )


def test_unknown_practice_area_falls_through_to_forum_default() -> None:
    """Free-text practice_area like 'Misc' falls through to the
    forum-level default — for HC that's AFFIDAVIT primary."""
    recs = recommend_templates(
        forum_level="high_court", practice_area="Misc / Other",
    )
    assert recs[0].template_type == DraftTemplateType.AFFIDAVIT
    assert recs[0].relevance == "primary"


def test_unknown_forum_level_returns_empty() -> None:
    assert recommend_templates(
        forum_level="not-a-forum", practice_area="criminal",
    ) == []
    assert recommend_templates(
        forum_level="", practice_area="criminal",
    ) == []


def test_route_returns_recommendation_shape(client: TestClient) -> None:
    """GET /api/drafting/templates/recommend?forum_level=high_court
    &practice_area=Criminal returns the expected shape with reason +
    relevance per recommendation."""
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get(
        "/api/drafting/templates/recommend"
        "?forum_level=high_court&practice_area=Criminal",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["forum_level"] == "high_court"
    assert body["practice_area"] == "Criminal"
    assert len(body["recommendations"]) >= 2
    first = body["recommendations"][0]
    assert first["template_type"] == "bail"
    assert first["relevance"] == "primary"
    assert "HC criminal-side" in first["reason"]


def test_route_omits_practice_area_falls_through_to_forum_default(
    client: TestClient,
) -> None:
    """No practice_area query param → forum default kicks in."""
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get(
        "/api/drafting/templates/recommend?forum_level=supreme_court",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["practice_area"] is None
    types = [r["template_type"] for r in body["recommendations"]]
    assert "appeal_memorandum" in types


def test_route_requires_auth(client: TestClient) -> None:
    """Unauthenticated request returns 401."""
    resp = client.get(
        "/api/drafting/templates/recommend?forum_level=high_court",
    )
    assert resp.status_code == 401
