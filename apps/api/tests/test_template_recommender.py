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


# ---------------------------------------------------------------
# PG-005 Sprint 1 (2026-05-01): writ / quashing / written-statement /
# reply templates promoted into the recommender matrix.
# ---------------------------------------------------------------

def test_high_court_writ_recommends_writ_petition_primary() -> None:
    """HC + writ → WRIT_PETITION primary (replacing AFFIDAVIT primary).
    Article 226 writ filings are first-class petitions, not affidavit-led."""
    recs = recommend_templates(
        forum_level="high_court", practice_area="Writ",
    )
    assert recs[0].template_type == DraftTemplateType.WRIT_PETITION
    assert recs[0].relevance == "primary"


def test_supreme_court_writ_recommends_writ_petition_primary() -> None:
    """SC + writ → WRIT_PETITION primary. Article 32 is the SC's
    original constitutional jurisdiction."""
    recs = recommend_templates(
        forum_level="supreme_court", practice_area="Constitutional",
    )
    assert recs[0].template_type == DraftTemplateType.WRIT_PETITION
    assert recs[0].relevance == "primary"


def test_high_court_criminal_recommends_quashing_petition() -> None:
    """HC + criminal → QUASHING_PETITION as a primary recommendation.
    s.528 BNSS / s.482 CrPC quashing is the HC's inherent-powers
    jurisdiction and a daily filing on the criminal-side."""
    recs = recommend_templates(
        forum_level="high_court", practice_area="Criminal",
    )
    types = [r.template_type for r in recs]
    assert DraftTemplateType.QUASHING_PETITION in types
    rec = next(
        r for r in recs if r.template_type == DraftTemplateType.QUASHING_PETITION
    )
    assert rec.relevance == "primary"


def test_lower_court_civil_recommends_written_statement_primary() -> None:
    """Trial-court civil → WRITTEN_STATEMENT among primaries (every
    contested suit needs one within Order VIII Rule 1's timeline)."""
    recs = recommend_templates(
        forum_level="lower_court", practice_area="Civil",
    )
    primary_types = [r.template_type for r in recs if r.relevance == "primary"]
    assert DraftTemplateType.WRITTEN_STATEMENT in primary_types


def test_high_court_civil_includes_reply_counter_affidavit() -> None:
    """HC + civil → REPLY_COUNTER_AFFIDAVIT in the recommendation list
    (most contested HC matters generate at least one reply on
    interlocutory applications)."""
    recs = recommend_templates(
        forum_level="high_court", practice_area="Civil",
    )
    types = [r.template_type for r in recs]
    assert DraftTemplateType.REPLY_COUNTER_AFFIDAVIT in types


def test_high_court_writ_lists_reply_counter_affidavit() -> None:
    """HC + writ → REPLY_COUNTER_AFFIDAVIT for the State /
    authority respondents."""
    recs = recommend_templates(
        forum_level="high_court", practice_area="Writ",
    )
    types = [r.template_type for r in recs]
    assert DraftTemplateType.REPLY_COUNTER_AFFIDAVIT in types


def test_high_court_commercial_includes_written_statement() -> None:
    """HC + commercial → WRITTEN_STATEMENT (Commercial Courts Act
    120-day cap on filing the written statement)."""
    recs = recommend_templates(
        forum_level="high_court", practice_area="Commercial",
    )
    types = [r.template_type for r in recs]
    assert DraftTemplateType.WRITTEN_STATEMENT in types


# ---------------------------------------------------------------
# PG-005 Sprint 2 (2026-05-01): DV-quashing, Section 9 Arbitration,
# Caveat, Vakalatnama, Amendment, Compromise, Probate matrix coverage.
# ---------------------------------------------------------------


def test_arbitration_commercial_recommends_section_9_primary() -> None:
    """Arbitration + commercial → ARBITRATION_SECTION_9 primary
    (s.9 interim measures dominate arbitral filings before / during /
    after the tribunal)."""
    recs = recommend_templates(
        forum_level="arbitration", practice_area="Commercial",
    )
    primary_types = [r.template_type for r in recs if r.relevance == "primary"]
    assert DraftTemplateType.ARBITRATION_SECTION_9 in primary_types


def test_high_court_commercial_lists_arbitration_section_9() -> None:
    """HC + commercial → ARBITRATION_SECTION_9 in the recommendation
    list (commercial division frequently hears s.9 applications)."""
    recs = recommend_templates(
        forum_level="high_court", practice_area="Commercial",
    )
    types = [r.template_type for r in recs]
    assert DraftTemplateType.ARBITRATION_SECTION_9 in types


def test_pwdva_practice_area_routes_to_matrimonial_bucket() -> None:
    """'Domestic violence' / 'PWDVA' practice area normalises to the
    matrimonial bucket so DV_QUASHING_PETITION shows up at the HC."""
    for area in ("Domestic violence", "PWDVA matter"):
        recs = recommend_templates(
            forum_level="high_court", practice_area=area,
        )
        types = [r.template_type for r in recs]
        assert DraftTemplateType.DV_QUASHING_PETITION in types, (
            f"area={area!r}: expected DV_QUASHING_PETITION in recs, got {types}"
        )


def test_caveat_petition_appears_in_civil_buckets() -> None:
    """Caveat is a defensive filing that surfaces across HC + lower-court
    civil + commercial buckets."""
    for forum, area in (
        ("high_court", "Civil"),
        ("high_court", "Commercial"),
        ("lower_court", "Civil"),
    ):
        recs = recommend_templates(forum_level=forum, practice_area=area)
        types = [r.template_type for r in recs]
        assert DraftTemplateType.CAVEAT_PETITION in types, (
            f"{forum}/{area}: expected CAVEAT_PETITION, got {types}"
        )


def test_vakalatnama_appears_in_lower_court_buckets() -> None:
    """Every appearance needs a vakalat — surface it in the
    lower-court buckets where filings are most frequent."""
    recs = recommend_templates(
        forum_level="lower_court", practice_area="Civil",
    )
    types = [r.template_type for r in recs]
    assert DraftTemplateType.VAKALATNAMA in types


def test_amendment_of_pleadings_in_civil_buckets() -> None:
    """Order VI Rule 17 amendments are routine — present in HC civil
    + lower-court civil + HC commercial."""
    for forum, area in (
        ("high_court", "Civil"),
        ("lower_court", "Civil"),
        ("high_court", "Commercial"),
    ):
        recs = recommend_templates(forum_level=forum, practice_area=area)
        types = [r.template_type for r in recs]
        assert DraftTemplateType.AMENDMENT_OF_PLEADINGS in types, (
            f"{forum}/{area}: expected AMENDMENT_OF_PLEADINGS, got {types}"
        )


def test_compromise_petition_in_matrimonial_and_criminal_buckets() -> None:
    """Compromise petition surfaces in both matrimonial (HMA s.13B
    mutual-consent) and criminal (BNSS s.359 / s.528) buckets."""
    matrimonial = recommend_templates(
        forum_level="high_court", practice_area="Matrimonial",
    )
    criminal = recommend_templates(
        forum_level="high_court", practice_area="Criminal",
    )
    assert DraftTemplateType.COMPROMISE_PETITION in [r.template_type for r in matrimonial]
    assert DraftTemplateType.COMPROMISE_PETITION in [r.template_type for r in criminal]


def test_probate_petition_surfaces_in_lower_court_civil() -> None:
    """Probate is filed at the District Court for estates within
    pecuniary limit — should surface in lower_court + civil."""
    recs = recommend_templates(
        forum_level="lower_court", practice_area="Succession",
    )
    types = [r.template_type for r in recs]
    assert DraftTemplateType.PROBATE_PETITION in types
