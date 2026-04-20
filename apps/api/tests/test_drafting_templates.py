"""Sprint R1 / R2 — tests for per-draft-type templates + prompts.

Three layers:

- Schema coverage: every ``DraftTemplateType`` has a registered form
  schema, and the Pydantic facts model actually validates a realistic
  fixture.
- Prompt coverage: every template has a specialised prompt; the prompt
  for the statute-specific templates names the governing statute.
- Route coverage: the discovery endpoints return the list + individual
  schema + a 404 on an unknown type.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from caseops_api.schemas.drafting_templates import (
    AffidavitFacts,
    AnticipatoryBailFacts,
    BailFacts,
    ChequeBounceNoticeFacts,
    CivilSuitFacts,
    CriminalComplaintFacts,
    DivorcePetitionFacts,
    DraftTemplateType,
    PropertyDisputeNoticeFacts,
    get_template_facts_model,
    get_template_schema,
    list_template_schemas,
)
from caseops_api.services.drafting_prompts import get_prompt_parts


# ---------------------------------------------------------------
# Registry + schema coverage.
# ---------------------------------------------------------------


def test_registry_has_one_entry_per_template_type() -> None:
    schemas = list_template_schemas()
    types_in_registry = {s.template_type for s in schemas}
    expected = {t.value for t in DraftTemplateType}
    assert types_in_registry == expected
    assert len(schemas) == 8


def test_every_template_has_fields_and_step_groups() -> None:
    for template_type in DraftTemplateType:
        schema = get_template_schema(template_type)
        assert schema.fields, f"{template_type} has no fields"
        assert schema.step_groups, f"{template_type} has no step groups"
        # Every field must declare a step_group that appears in step_groups.
        groups = set(schema.step_groups)
        assert all(f.step_group in groups for f in schema.fields)


def test_every_template_has_a_prompt() -> None:
    for template_type in DraftTemplateType:
        parts = get_prompt_parts(template_type)
        assert parts.system.strip(), f"{template_type}: empty system prompt"
        assert parts.focus.strip(), f"{template_type}: empty focus line"


# ---------------------------------------------------------------
# Statute-correctness — each prompt must cite the right section.
# This is the guardrail against the review-rejection patterns called
# out in the prompt design.
# ---------------------------------------------------------------


def test_bail_prompt_cites_bnss_not_just_crpc() -> None:
    prompt = get_prompt_parts(DraftTemplateType.BAIL)
    assert "BNSS s.483" in prompt.system
    assert "triple test" in prompt.system.lower()


def test_anticipatory_bail_prompt_cites_bnss_s_482() -> None:
    prompt = get_prompt_parts(DraftTemplateType.ANTICIPATORY_BAIL)
    assert "BNSS s.482" in prompt.system
    assert "Sibbia" in prompt.system or "sibbia" in prompt.system.lower()


def test_cheque_bounce_prompt_enforces_15_day_window() -> None:
    prompt = get_prompt_parts(DraftTemplateType.CHEQUE_BOUNCE_NOTICE)
    assert "15" in prompt.system
    assert "s.138" in prompt.system
    # The NI Act section 138 demand notice period is statutory — the
    # prompt must not let the LLM invent a different number of days.
    # 'fifteen' as a word OR '15' as a digit is fine.
    assert "FIFTEEN" in prompt.system or "fifteen" in prompt.system


def test_criminal_complaint_prompt_uses_bns_not_ipc_by_default() -> None:
    prompt = get_prompt_parts(DraftTemplateType.CRIMINAL_COMPLAINT)
    assert "BNS" in prompt.system
    # And must mention the 2024-07-01 cutover so stale IPC references
    # aren't generated for pre-BNS incidents.
    assert "IPC" in prompt.system  # context only, not as default
    assert "2024" in prompt.system


def test_civil_suit_prompt_flags_commercial_courts_act() -> None:
    prompt = get_prompt_parts(DraftTemplateType.CIVIL_SUIT)
    assert "Commercial Courts Act" in prompt.system
    assert "Order VII" in prompt.system
    assert "s.12A" in prompt.system


def test_divorce_prompt_respects_act_choice() -> None:
    prompt = get_prompt_parts(DraftTemplateType.DIVORCE_PETITION)
    assert "HMA" in prompt.system and "SMA" in prompt.system
    # Must not hardcode a single ground — grounds come from the user.
    assert "DO NOT GUESS" in prompt.system


# ---------------------------------------------------------------
# Pydantic fact-model validation round-trips — the stepper will POST
# these shapes, so failing validation here is a UX regression.
# ---------------------------------------------------------------


def test_bail_facts_accepts_realistic_fixture() -> None:
    facts = BailFacts(
        matter_id="11111111-1111-1111-1111-111111111111",
        accused_name="Ramesh Kumar",
        fir_number="FIR 123/2026",
        police_station="Connaught Place",
        sections_charged=["BNS s.303", "BNS s.318"],
        custody_since="2026-03-01",
        court_name="Delhi High Court",
        prior_bail_applications=0,
        grounds_brief=(
            "Accused is in custody for 50 days. Co-accused Ravi Singh "
            "has been granted bail on parity by this Hon'ble Court. "
            "The triple test is satisfied: the accused has roots in "
            "Delhi, there is no allegation of tampering, and witnesses "
            "have already been examined."
        ),
    )
    assert facts.matter_id.startswith("1111")


def test_cheque_bounce_facts_rejects_non_positive_amount() -> None:
    with pytest.raises(ValueError):
        ChequeBounceNoticeFacts(
            matter_id="m",
            drawer_name="Ramesh",
            drawee_name="Suresh",
            cheque_number="000123",
            cheque_date="2026-03-01",
            cheque_amount_inr=0,  # invalid — must be > 0
            bank_name="SBI",
            bank_memo_date="2026-03-05",
        )


def test_affidavit_requires_at_least_one_paragraph() -> None:
    with pytest.raises(ValueError):
        AffidavitFacts(
            matter_id="m",
            deponent_name="Priya",
            deponent_age=40,
            deponent_occupation="Advocate",
            deponent_address="1 Chambers Rd, Mumbai",
            statement_paragraphs=[],
            sworn_place="Mumbai",
            sworn_date="2026-03-01",
        )


def test_civil_suit_requires_relief() -> None:
    with pytest.raises(ValueError):
        CivilSuitFacts(
            matter_id="m",
            plaintiff_name="P",
            defendant_name="D",
            cause_of_action_date="2026-01-01",
            cause_of_action_place="Mumbai",
            suit_valuation_inr=100000.0,
            relief_sought=[],  # invalid
            court_name="Bombay High Court",
            facts_brief="A " * 50,
        )


def test_facts_model_mapping_matches_enum() -> None:
    """Each enum value maps to the right facts class."""
    mapping = {
        DraftTemplateType.BAIL: BailFacts,
        DraftTemplateType.ANTICIPATORY_BAIL: AnticipatoryBailFacts,
        DraftTemplateType.DIVORCE_PETITION: DivorcePetitionFacts,
        DraftTemplateType.PROPERTY_DISPUTE_NOTICE: PropertyDisputeNoticeFacts,
        DraftTemplateType.CHEQUE_BOUNCE_NOTICE: ChequeBounceNoticeFacts,
        DraftTemplateType.AFFIDAVIT: AffidavitFacts,
        DraftTemplateType.CRIMINAL_COMPLAINT: CriminalComplaintFacts,
        DraftTemplateType.CIVIL_SUIT: CivilSuitFacts,
    }
    for template_type, cls in mapping.items():
        assert get_template_facts_model(template_type) is cls


# ---------------------------------------------------------------
# Route coverage.
# ---------------------------------------------------------------


def test_list_templates_route_returns_all_eight(client: TestClient) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)

    resp = client.get("/api/drafting/templates", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["templates"]) == 8
    types = {t["template_type"] for t in body["templates"]}
    assert types == {t.value for t in DraftTemplateType}


def test_get_template_route_returns_schema(client: TestClient) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    resp = client.get("/api/drafting/templates/bail", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_type"] == "bail"
    assert body["fields"]
    names = {f["name"] for f in body["fields"]}
    assert "custody_since" in names
    assert "sections_charged" in names


def test_get_template_route_404_on_unknown_type(client: TestClient) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    resp = client.get(
        "/api/drafting/templates/does-not-exist", headers=headers
    )
    assert resp.status_code == 404


def test_templates_route_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/drafting/templates")
    assert resp.status_code in {401, 403}
