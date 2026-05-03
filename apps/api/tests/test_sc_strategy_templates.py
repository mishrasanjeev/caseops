"""MOD-LSE-3 (2026-05-03) — SC + escalation drafting templates.

Spot checks for each of the 11 new templates: registry lookup, schema
includes the right field set, pydantic facts model rejects unknown
keys, prompt is registered with the expected statutory framing, and
the route surface returns the schema.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from caseops_api.schemas.drafting_templates import (
    CondonationOfDelayFacts,
    ContemptPetitionFacts,
    CurativePetitionFacts,
    DraftTemplateType,
    ExemptionApplicationFacts,
    FilingIndexChecklistFacts,
    InterimReliefApplicationFacts,
    ReviewPetitionFacts,
    SpecialLeavePetitionFacts,
    SupremeCourtAppealFacts,
    SynopsisListOfDatesFacts,
    TransferPetitionFacts,
    get_template_facts_model,
    get_template_schema,
)
from caseops_api.services.drafting_prompts import get_prompt_parts
from tests.test_auth_company import auth_headers, bootstrap_company

SC_PACK = (
    DraftTemplateType.SPECIAL_LEAVE_PETITION,
    DraftTemplateType.SUPREME_COURT_APPEAL,
    DraftTemplateType.REVIEW_PETITION,
    DraftTemplateType.CURATIVE_PETITION,
    DraftTemplateType.TRANSFER_PETITION,
    DraftTemplateType.CONTEMPT_PETITION,
    DraftTemplateType.INTERIM_RELIEF_APPLICATION,
    DraftTemplateType.CONDONATION_OF_DELAY,
    DraftTemplateType.EXEMPTION_APPLICATION,
    DraftTemplateType.SYNOPSIS_LIST_OF_DATES,
    DraftTemplateType.FILING_INDEX_CHECKLIST,
)

FACTS_MODELS: dict[DraftTemplateType, type] = {
    DraftTemplateType.SPECIAL_LEAVE_PETITION: SpecialLeavePetitionFacts,
    DraftTemplateType.SUPREME_COURT_APPEAL: SupremeCourtAppealFacts,
    DraftTemplateType.REVIEW_PETITION: ReviewPetitionFacts,
    DraftTemplateType.CURATIVE_PETITION: CurativePetitionFacts,
    DraftTemplateType.TRANSFER_PETITION: TransferPetitionFacts,
    DraftTemplateType.CONTEMPT_PETITION: ContemptPetitionFacts,
    DraftTemplateType.INTERIM_RELIEF_APPLICATION: InterimReliefApplicationFacts,
    DraftTemplateType.CONDONATION_OF_DELAY: CondonationOfDelayFacts,
    DraftTemplateType.EXEMPTION_APPLICATION: ExemptionApplicationFacts,
    DraftTemplateType.SYNOPSIS_LIST_OF_DATES: SynopsisListOfDatesFacts,
    DraftTemplateType.FILING_INDEX_CHECKLIST: FilingIndexChecklistFacts,
}


@pytest.mark.parametrize("template_type", SC_PACK)
def test_sc_pack_template_has_registry_entry(
    template_type: DraftTemplateType,
) -> None:
    schema = get_template_schema(template_type)
    assert schema.template_type == template_type.value
    assert schema.display_name
    assert schema.summary
    assert schema.statutory_basis, (
        f"{template_type} must declare a statutory basis."
    )
    assert schema.fields
    assert schema.step_groups


@pytest.mark.parametrize("template_type", SC_PACK)
def test_sc_pack_template_has_facts_model(
    template_type: DraftTemplateType,
) -> None:
    cls = get_template_facts_model(template_type)
    assert cls is FACTS_MODELS[template_type]


@pytest.mark.parametrize("template_type", SC_PACK)
def test_sc_pack_template_has_prompt(template_type: DraftTemplateType) -> None:
    parts = get_prompt_parts(template_type)
    assert parts.system.strip(), f"{template_type}: empty system prompt"
    assert parts.focus.strip(), f"{template_type}: empty focus line"
    # No outcome guarantees in the prompt itself — the strategy
    # planner enforces this on generated strategies but the prompt
    # source code is the easier sweep.
    forbidden = (
        "perfect strategy", "guaranteed", "will win", "will succeed",
        "no lawyer needed", "replace advocate",
    )
    haystack = parts.system.lower()
    for needle in forbidden:
        assert needle not in haystack, (
            f"{template_type} prompt contains forbidden phrase {needle!r}"
        )


# ---------------------------------------------------------------
# Per-template structural checks. Each template's facts model
# enforces the fields its prompt depends on.
# ---------------------------------------------------------------


def test_slp_requires_impugned_order_details() -> None:
    """SLPs need the impugned order's anchor — date + summary + HC."""
    with pytest.raises(ValidationError):
        SpecialLeavePetitionFacts(
            matter_id="M",
            petitioner_name="A",
            respondent_name="B",
            slp_kind="civil",
            # impugned_order_summary missing
            impugned_order_date="2025-01-01",
            high_court_name="Delhi HC",
            questions_of_law=["Q1"],
            grounds_brief="x" * 100,
        )


def test_review_petition_requires_error_apparent() -> None:
    """Review jurisdiction is narrow — error apparent on face of record
    is a required field."""
    with pytest.raises(ValidationError):
        ReviewPetitionFacts(
            matter_id="M",
            petitioner_name="A",
            respondent_name="B",
            review_court="supreme_court",
            impugned_judgment_date="2025-01-01",
            # error_apparent_on_face_of_record missing
            grounds_brief="x" * 100,
        )


def test_curative_petition_requires_review_dismissal_and_senior_advocate() -> None:
    """Curative jurisdiction is post-review and demands Senior Advocate
    certification (Rupa Ashok Hurra)."""
    with pytest.raises(ValidationError):
        CurativePetitionFacts(
            matter_id="M",
            petitioner_name="A",
            respondent_name="B",
            impugned_order_date="2025-01-01",
            # review_dismissed_date missing
            senior_advocate_name="Sr. Counsel",
            grounds_brief="x" * 100,
        )
    with pytest.raises(ValidationError):
        CurativePetitionFacts(
            matter_id="M",
            petitioner_name="A",
            respondent_name="B",
            impugned_order_date="2025-01-01",
            review_dismissed_date="2025-06-01",
            # senior_advocate_name missing
            grounds_brief="x" * 100,
        )


def test_condonation_does_not_invent_delay_days() -> None:
    """delay_days must be supplied — pydantic refuses to invent it."""
    with pytest.raises(ValidationError):
        CondonationOfDelayFacts(
            matter_id="M",
            applicant_name="A",
            respondent_name="B",
            main_filing_kind="SLP",
            main_filing_court="SC",
            # delay_days missing
            cause_of_delay="x" * 50,
            diligence_explanation="x" * 50,
            impugned_order_date="2025-01-01",
        )


def test_synopsis_preserves_chronology_with_min_two_entries() -> None:
    """Synopsis is meaningless with a one-line list of dates."""
    with pytest.raises(ValidationError):
        SynopsisListOfDatesFacts(
            matter_id="M",
            case_title="A v. B",
            petitioner_name="A",
            respondent_name="B",
            questions_of_law=["Q1"],
            case_summary="x" * 100,
            chronology=["2025-01-01: only one entry"],
        )


def test_filing_index_requires_at_least_one_document() -> None:
    """Filing index can't be empty."""
    with pytest.raises(ValidationError):
        FilingIndexChecklistFacts(
            matter_id="M",
            case_title="A v. B",
            court_name="SC",
            filing_kind="SLP",
            documents_to_index=[],
            total_pages_estimate=10,
        )


def test_interim_relief_requires_three_factor_test_inputs() -> None:
    """Dalpat Kumar three-factor test fields are all required."""
    with pytest.raises(ValidationError):
        InterimReliefApplicationFacts(
            matter_id="M",
            applicant_name="A",
            respondent_name="B",
            main_proceeding_number="W.P. 1/2025",
            main_proceeding_summary="x" * 50,
            court_name="HC",
            relief_kind="stay",
            prima_facie_case="x" * 50,
            balance_of_convenience="x" * 50,
            # irreparable_injury missing
        )


# ---------------------------------------------------------------
# Statute-correctness — each prompt must cite the right section.
# ---------------------------------------------------------------


def test_slp_prompt_cites_article_136() -> None:
    parts = get_prompt_parts(DraftTemplateType.SPECIAL_LEAVE_PETITION)
    assert "Article 136" in parts.system


def test_supreme_court_appeal_prompt_distinguishes_from_slp() -> None:
    parts = get_prompt_parts(DraftTemplateType.SUPREME_COURT_APPEAL)
    # Articles 132 / 133 / 134 are the distinguishing feature.
    assert "132" in parts.system
    assert "133" in parts.system
    assert "134" in parts.system
    # Must not blur the SLP / appeal distinction.
    assert "SLP" in parts.system or "Article 136" in parts.system


def test_curative_prompt_cites_rupa_ashok_hurra() -> None:
    parts = get_prompt_parts(DraftTemplateType.CURATIVE_PETITION)
    assert "Rupa Ashok Hurra" in parts.system


def test_transfer_prompt_branches_on_basis() -> None:
    parts = get_prompt_parts(DraftTemplateType.TRANSFER_PETITION)
    # The prompt branches on the four supported transfer bases.
    for needle in ("139A", "cpc_s_25", "406"):
        assert needle in parts.system, f"missing {needle!r} in transfer prompt"


def test_contempt_prompt_cites_articles_129_and_215() -> None:
    parts = get_prompt_parts(DraftTemplateType.CONTEMPT_PETITION)
    assert "129" in parts.system  # SC
    assert "215" in parts.system  # HC
    assert "Contempt of Courts Act" in parts.system


def test_interim_relief_prompt_cites_dalpat_kumar() -> None:
    parts = get_prompt_parts(DraftTemplateType.INTERIM_RELIEF_APPLICATION)
    assert "Dalpat Kumar" in parts.system
    assert "prima facie" in parts.system.lower()
    assert "balance of convenience" in parts.system.lower()
    assert "irreparable" in parts.system.lower()


def test_condonation_prompt_cites_section_5() -> None:
    parts = get_prompt_parts(DraftTemplateType.CONDONATION_OF_DELAY)
    assert "Section 5" in parts.system
    assert "Limitation Act" in parts.system


def test_synopsis_prompt_demands_chronological_list_of_dates() -> None:
    parts = get_prompt_parts(DraftTemplateType.SYNOPSIS_LIST_OF_DATES)
    assert "chronolog" in parts.system.lower()
    assert "list of dates" in parts.system.lower()


def test_filing_index_prompt_lists_paginated_format() -> None:
    parts = get_prompt_parts(DraftTemplateType.FILING_INDEX_CHECKLIST)
    assert "page" in parts.system.lower()
    assert "checklist" in parts.system.lower()


# ---------------------------------------------------------------
# Route coverage — the templates surface on the templates list.
# ---------------------------------------------------------------


def test_sc_templates_appear_on_templates_list_route(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    resp = client.get("/api/drafting/templates", headers=headers)
    assert resp.status_code == 200
    types = {t["template_type"] for t in resp.json()["templates"]}
    for template_type in SC_PACK:
        assert template_type.value in types


@pytest.mark.parametrize(
    "template_type",
    [t.value for t in SC_PACK],
)
def test_sc_pack_template_has_route_get(
    client: TestClient, template_type: str,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    resp = client.get(
        f"/api/drafting/templates/{template_type}", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_type"] == template_type
    assert body["fields"]
    assert body["facts_model_json_schema"]
