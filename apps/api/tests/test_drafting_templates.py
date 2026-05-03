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
    AmendmentOfPleadingsFacts,
    AnticipatoryBailFacts,
    AppealMemorandumFacts,
    ArbitrationSection9Facts,
    BailFacts,
    CaveatPetitionFacts,
    ChequeBounceNoticeFacts,
    CivilSuitFacts,
    CompromisePetitionFacts,
    CriminalComplaintFacts,
    DivorcePetitionFacts,
    DraftTemplateType,
    DvQuashingPetitionFacts,
    ProbatePetitionFacts,
    PropertyDisputeNoticeFacts,
    QuashingPetitionFacts,
    ReplyCounterAffidavitFacts,
    VakalatnamaFacts,
    WritPetitionFacts,
    WrittenStatementFacts,
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
    # 31 templates after MOD-LSE-3 (2026-05-03) added the SC + escalation
    # pack (special_leave_petition, supreme_court_appeal, review_petition,
    # curative_petition, transfer_petition, contempt_petition,
    # interim_relief_application, condonation_of_delay,
    # exemption_application, synopsis_list_of_dates,
    # filing_index_checklist) on top of the 20 previously-registered
    # templates. Update this count + the route test below in lockstep
    # when a new template lands.
    assert len(schemas) == 31


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
# PG-005 Sprint 1 (2026-05-01): per-template prompt correctness for
# the four new high-frequency templates.
# ---------------------------------------------------------------


def test_writ_prompt_branches_on_writ_type_and_flags_laches() -> None:
    """Writ petition prompt must teach the LLM the per-writ-type relief
    language (mandamus / certiorari / prohibition / quo warranto /
    habeas corpus) AND must enforce laches awareness — writs have no
    fixed limitation but stale petitions get dismissed."""
    prompt = get_prompt_parts(DraftTemplateType.WRIT_PETITION)
    assert "Article 226" in prompt.system
    assert "Article 32" in prompt.system
    for writ_type in (
        "mandamus", "certiorari", "prohibition", "quo warranto", "habeas corpus",
    ):
        assert writ_type in prompt.system, (
            f"WRIT prompt missing relief language for {writ_type!r}"
        )
    assert "laches" in prompt.system.lower()


def test_quashing_prompt_invokes_gian_singh_on_compromise() -> None:
    """Quashing prompt must (a) cite BNSS s.528 / CrPC s.482 and (b)
    invoke Gian Singh + B.S. Joshi when compromise is recorded — these
    are the dispositive authorities on whether non-compoundable
    matters can be quashed on settlement."""
    prompt = get_prompt_parts(DraftTemplateType.QUASHING_PETITION)
    assert "528" in prompt.system  # BNSS s.528
    assert "482" in prompt.system  # CrPC s.482
    assert "Gian Singh" in prompt.system
    assert "B.S. Joshi" in prompt.system
    # And the heinous-offences carve-out must be enforced — Gian Singh
    # forbids quashing of murder / rape on settlement alone.
    assert "heinous" in prompt.system.lower() or "rape" in prompt.system.lower()


def test_written_statement_prompt_enforces_order_viii_timeline() -> None:
    """Written statement prompt must enforce Order VIII Rule 1's
    30-day default + 90-day cap, and the Commercial Courts Act 120-day
    cap for commercial suits."""
    prompt = get_prompt_parts(DraftTemplateType.WRITTEN_STATEMENT)
    assert "Order VIII" in prompt.system
    assert "30 days" in prompt.system or "30-day" in prompt.system.lower()
    assert "90 days" in prompt.system or "90-day" in prompt.system.lower()
    assert "120" in prompt.system  # Commercial Courts Act
    # And the silent-omission rule — every plaint paragraph must be
    # addressed because adverse inference attaches to silence.
    assert "silent" in prompt.system.lower() or "silence" in prompt.system.lower()


def test_reply_counter_affidavit_prompt_enforces_para_by_para() -> None:
    """Reply / counter-affidavit must enforce para-by-para coverage
    — silent omissions are treated as admissions in Indian pleading
    practice."""
    prompt = get_prompt_parts(DraftTemplateType.REPLY_COUNTER_AFFIDAVIT)
    assert "para" in prompt.system.lower()
    assert "silent" in prompt.system.lower() or "admission" in prompt.system.lower()
    # And the verification block — counter-affidavits are sworn.
    assert "verif" in prompt.system.lower()


# ---------------------------------------------------------------
# PG-005 Sprint 1 — Pydantic facts-model validation for new templates.
# ---------------------------------------------------------------


def test_writ_facts_requires_at_least_one_prayer_clause() -> None:
    with pytest.raises(ValueError):
        WritPetitionFacts(
            matter_id="m",
            petitioner_name="Anil Sharma",
            respondent_name="State of Delhi",
            writ_court="high_court",
            writ_type="mandamus",
            impugned_action=(
                "The respondent has not processed the petitioner's "
                "RTI application despite repeated reminders over 18 months."
            ),
            prayer_clauses=[],  # invalid — at least one required
        )


def test_writ_facts_accepts_realistic_mandamus_fixture() -> None:
    facts = WritPetitionFacts(
        matter_id="22222222-2222-2222-2222-222222222222",
        petitioner_name="Anil Sharma",
        respondent_name="Union of India",
        writ_court="high_court",
        writ_type="mandamus",
        impugned_action=(
            "The respondent has failed to act on the petitioner's "
            "representation dated 2025-08-12 seeking sanction for "
            "prosecution under the PC Act, despite the statutory "
            "three-month timeline having long expired."
        ),
        impugned_action_date="2025-08-12",
        fundamental_rights_invoked=["Article 14", "Article 21"],
        statutory_violations=["Prevention of Corruption Act, 1988 s.19(1)"],
        prayer_clauses=[
            "Direct the respondent to dispose of the petitioner's "
            "representation within four weeks.",
            "Pass any other order this Hon'ble Court deems fit."
        ],
    )
    assert facts.writ_type == "mandamus"
    assert len(facts.prayer_clauses) == 2


def test_quashing_facts_compromise_flag_round_trips() -> None:
    facts = QuashingPetitionFacts(
        matter_id="33333333-3333-3333-3333-333333333333",
        petitioner_name="Vikram Singh",
        respondent_name="State of Maharashtra",
        fir_number="FIR 145/2025",
        police_station="Khar",
        impugned_proceedings_summary=(
            "FIR registered under BNS s.318 (cheating) arising out of "
            "a commercial dispute that has since been settled between "
            "the parties through a written compromise dated 2026-02-10."
        ),
        statutory_offences=["BNS s.318"],
        grounds_for_quashing=(
            "The dispute is predominantly civil and commercial in "
            "nature; the parties have entered into a written "
            "compromise; continuation of proceedings would be an "
            "abuse of process."
        ),
        compromise_recorded=True,
        victim_consent=True,
        court_name="Bombay High Court",
    )
    assert facts.compromise_recorded is True
    assert facts.victim_consent is True


def test_written_statement_facts_requires_paragraph_wise_reply() -> None:
    with pytest.raises(ValueError):
        WrittenStatementFacts(
            matter_id="m",
            defendant_name="D",
            plaintiff_name="P",
            suit_number="CS 123/2026",
            court_name="Bombay City Civil Court",
            paragraph_wise_reply="too short",  # below min_length
        )


def test_reply_counter_affidavit_round_trips() -> None:
    facts = ReplyCounterAffidavitFacts(
        matter_id="44444444-4444-4444-4444-444444444444",
        deponent_name="Joint Secretary, Ministry of X",
        deponent_designation="Joint Secretary",
        deponent_address="North Block, New Delhi 110001",
        petition_number="W.P.(C) 1234/2026",
        petition_type="Writ Petition (C)",
        main_petition_summary=(
            "The petitioner challenges Notification No. 12/2025 dated "
            "2025-11-30 on the ground that it violates Article 14."
        ),
        court_name="Delhi High Court",
        paragraph_wise_response=(
            "The contents of paras 1 to 3 are matters of record. "
            "Para 4 is denied. The notification was issued after due "
            "consultation and an inter-ministerial review and is a "
            "valid exercise of statutory power. The remaining paras "
            "are denied save to the extent expressly admitted."
        ),
        relief_sought_against_petition="Dismiss the writ petition with costs.",
    )
    assert facts.petition_type == "Writ Petition (C)"


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
        DraftTemplateType.APPEAL_MEMORANDUM: AppealMemorandumFacts,
        DraftTemplateType.WRIT_PETITION: WritPetitionFacts,
        DraftTemplateType.QUASHING_PETITION: QuashingPetitionFacts,
        DraftTemplateType.WRITTEN_STATEMENT: WrittenStatementFacts,
        DraftTemplateType.REPLY_COUNTER_AFFIDAVIT: ReplyCounterAffidavitFacts,
        DraftTemplateType.DV_QUASHING_PETITION: DvQuashingPetitionFacts,
        DraftTemplateType.ARBITRATION_SECTION_9: ArbitrationSection9Facts,
        DraftTemplateType.CAVEAT_PETITION: CaveatPetitionFacts,
        DraftTemplateType.VAKALATNAMA: VakalatnamaFacts,
        DraftTemplateType.AMENDMENT_OF_PLEADINGS: AmendmentOfPleadingsFacts,
        DraftTemplateType.COMPROMISE_PETITION: CompromisePetitionFacts,
        DraftTemplateType.PROBATE_PETITION: ProbatePetitionFacts,
    }
    for template_type, cls in mapping.items():
        assert get_template_facts_model(template_type) is cls


# ---------------------------------------------------------------
# Route coverage.
# ---------------------------------------------------------------


def test_list_templates_route_returns_all_thirty_one(client: TestClient) -> None:
    """31 templates after MOD-LSE-3 (2026-05-03) added the SC +
    escalation pack on top of the 20 templates from PG-005 Sprint 2."""
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)

    resp = client.get("/api/drafting/templates", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["templates"]) == 31
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


# ---------------------------------------------------------------
# PG-005 Sprint 2 (2026-05-01): seven additional templates covering
# DV-quashing, Section 9 Arbitration, Caveat, Vakalatnama, Amendment
# of pleadings, Compromise, and Probate.
# ---------------------------------------------------------------


def test_dv_quashing_prompt_avoids_gian_singh_as_dispositive() -> None:
    """PWDVA quashing is quasi-civil — Gian Singh is criminal-FIR
    jurisprudence. The prompt must teach the LLM that the test is
    welfare + bona fides, not Gian Singh-style settlement."""
    prompt = get_prompt_parts(DraftTemplateType.DV_QUASHING_PETITION)
    assert "PWDVA" in prompt.system
    assert "528" in prompt.system  # BNSS s.528
    assert "Gian Singh" in prompt.system  # mentioned to disclaim
    # Must explicitly warn against Gian Singh as dispositive.
    assert "NOT" in prompt.system or "not cite" in prompt.system.lower()
    assert "welfare" in prompt.system.lower() or "children" in prompt.system.lower()
    assert "2(f)" in prompt.system or "domestic relationship" in prompt.system.lower()


def test_arbitration_section_9_prompt_enforces_three_part_test() -> None:
    """Section 9 prompt must enforce the three-part interim-relief
    test (prima facie / balance of convenience / irreparable injury)
    AND the s.9(3) tribunal-constituted carve-out."""
    prompt = get_prompt_parts(DraftTemplateType.ARBITRATION_SECTION_9)
    assert "Section 9" in prompt.system or "s.9" in prompt.system.lower()
    assert "1996" in prompt.system  # the Act year
    assert "9(3)" in prompt.system or "Section 9(3)" in prompt.system
    assert "prima facie" in prompt.system.lower()
    assert "balance of convenience" in prompt.system.lower()
    assert "irreparable" in prompt.system.lower()


def test_caveat_prompt_enforces_no_merits_pleading() -> None:
    """Caveat is procedural notice. The prompt must NOT let the LLM
    plead the merits of any dispute, and must mention the 90-day
    automatic lapse."""
    prompt = get_prompt_parts(DraftTemplateType.CAVEAT_PETITION)
    assert "148A" in prompt.system
    assert "90" in prompt.system  # 90-day lapse
    # Must forbid merits pleading.
    assert "merits" in prompt.system.lower() or "procedural" in prompt.system.lower()


def test_vakalatnama_prompt_branches_on_court_format() -> None:
    """Vakalat prompt must teach the LLM the right court-specific
    header for SC / Delhi HC / Bombay HC."""
    prompt = get_prompt_parts(DraftTemplateType.VAKALATNAMA)
    assert "SUPREME COURT OF INDIA" in prompt.system
    assert "DELHI" in prompt.system
    assert "BOMBAY" in prompt.system
    # Counsel acceptance block + bar enrolment must be enforced.
    assert "enrol" in prompt.system.lower() or "Enrolment" in prompt.system


def test_amendment_prompt_enforces_due_diligence_post_trial() -> None:
    """Order VI Rule 17 prompt must enforce the due-diligence proviso
    when trial has commenced — the most-litigated point on amendment
    applications."""
    prompt = get_prompt_parts(DraftTemplateType.AMENDMENT_OF_PLEADINGS)
    assert "Order VI Rule 17" in prompt.system
    assert "due diligence" in prompt.system.lower()
    assert "trial" in prompt.system.lower()


def test_compromise_prompt_branches_on_statutory_basis() -> None:
    """Compromise prompt must branch correctly across CPC Order XXIII
    Rule 3 / BNSS s.359 / BNSS s.528 / HMA s.13B and surface the
    Gian Singh heinous-offences carve-out for s.528 settlements."""
    prompt = get_prompt_parts(DraftTemplateType.COMPROMISE_PETITION)
    assert "Order XXIII" in prompt.system or "Order 23" in prompt.system
    assert "359" in prompt.system  # BNSS s.359
    assert "528" in prompt.system  # BNSS s.528
    assert "13B" in prompt.system  # HMA s.13B
    assert "heinous" in prompt.system.lower()
    assert "Gian Singh" in prompt.system


def test_probate_prompt_enforces_two_attestor_rule() -> None:
    """Probate prompt must enforce s.63(c) two-attestor rule and
    s.283 citation-to-heirs requirement."""
    prompt = get_prompt_parts(DraftTemplateType.PROBATE_PETITION)
    assert "Indian Succession Act" in prompt.system
    assert "63(c)" in prompt.system
    assert "283" in prompt.system  # citation to heirs
    assert "two" in prompt.system.lower() or "TWO" in prompt.system
    # Letters of Administration carve-out must be flagged.
    assert "Letters of Administration" in prompt.system or "intestate" in prompt.system.lower()


# ---------------------------------------------------------------
# PG-005 Sprint 2 — Pydantic facts-model validation for new templates.
# ---------------------------------------------------------------


def test_dv_quashing_facts_round_trips_with_settlement() -> None:
    facts = DvQuashingPetitionFacts(
        matter_id="55555555-5555-5555-5555-555555555555",
        petitioner_name="Aman Verma",
        aggrieved_person_name="Priya Verma",
        pwdva_application_number="MA 412/2025",
        magistrate_court_name="MM-08, Saket Courts",
        high_court_name="Delhi High Court",
        impugned_reliefs_in_pwdva_app=["protection", "monetary", "residence"],
        grounds_for_quashing=(
            "The aggrieved person and the petitioner have arrived at a "
            "settlement of their disputes; the magistrate proceedings are "
            "an abuse of process and serve no useful purpose."
        ),
        settlement_recorded=True,
        aggrieved_consent=True,
        children_minor_count=1,
    )
    assert facts.settlement_recorded is True
    assert facts.children_minor_count == 1


def test_arbitration_s9_requires_at_least_one_interim_relief() -> None:
    with pytest.raises(ValueError):
        ArbitrationSection9Facts(
            matter_id="m",
            applicant_name="ABC Pvt Ltd",
            respondent_name="XYZ Ltd",
            court_name="Bombay High Court",
            arbitration_status="pre_arbitration",
            arbitration_agreement_summary=(
                "Clause 18 of the Master Services Agreement dated "
                "2024-04-01 referring disputes to a sole arbitrator."
            ),
            interim_reliefs_sought=[],  # invalid — at least one required
            underlying_cause_of_action=(
                "The respondent has commenced parallel litigation in "
                "violation of the arbitration clause and is dissipating "
                "the security deposit."
            ),
            urgency_basis=(
                "Without immediate court intervention, the security "
                "deposit will be irrevocably lost."
            ),
        )


def test_caveat_facts_round_trips() -> None:
    facts = CaveatPetitionFacts(
        matter_id="66666666-6666-6666-6666-666666666666",
        caveator_name="Sonia Trading Co.",
        caveator_address="Plot 42, Industrial Area, Phase II, Gurgaon",
        apprehended_applicant_name="Counter-party Industries Pvt Ltd",
        apprehended_proceeding_summary=(
            "An ex parte injunction application restraining the "
            "caveator from invoking bank guarantee BG/2025/0142."
        ),
        court_name="Delhi High Court",
    )
    assert facts.apprehended_applicant_name.startswith("Counter-party")


def test_vakalatnama_facts_accept_optional_case_number() -> None:
    """Fresh-filing vakalats omit case number — must round-trip with
    case_number=None."""
    facts = VakalatnamaFacts(
        matter_id="77777777-7777-7777-7777-777777777777",
        client_name="Ravi Mehta",
        client_address="Flat 304, Vasant Kunj, New Delhi",
        counsel_name="Adv. Sneha Iyer",
        counsel_enrollment_number="D/12345/2018",
        counsel_address="Chamber 22, Tis Hazari Courts, Delhi",
        case_title="Mehta v. State of Delhi",
        case_number=None,
        court_name="Delhi High Court",
        party_role="petitioner",
    )
    assert facts.case_number is None
    assert facts.party_role == "petitioner"


def test_amendment_facts_round_trips_with_due_diligence() -> None:
    facts = AmendmentOfPleadingsFacts(
        matter_id="88888888-8888-8888-8888-888888888888",
        applicant_name="Plaintiff Corp",
        applicant_role="plaintiff",
        suit_number="CS 99/2024",
        court_name="Bombay City Civil Court",
        pleading_to_amend="plaint",
        proposed_amendments=(
            "Add para 14-A: 'The plaintiff has, after the filing of "
            "this suit, discovered Annexure P-12 (the original board "
            "resolution dated 2023-11-15) which establishes the "
            "respondent's authority to bind itself.'"
        ),
        reason_for_amendment=(
            "The board resolution was not previously available to the "
            "plaintiff because it was retained by the respondent and "
            "produced for the first time during third-party "
            "discovery on 2026-03-10."
        ),
        trial_commenced=True,
        due_diligence_explanation=(
            "The plaintiff conducted document searches in 2024 + 2025 "
            "and the respondent did not produce this document until "
            "compelled discovery in March 2026; the plaintiff could "
            "not have discovered the document despite due diligence."
        ),
    )
    assert facts.trial_commenced is True
    assert facts.due_diligence_explanation is not None


def test_compromise_facts_requires_min_settlement_terms_length() -> None:
    """settlement_terms must be ≥80 chars — terse settlements are a
    drafting smell."""
    with pytest.raises(ValueError):
        CompromisePetitionFacts(
            matter_id="m",
            matter_type="civil",
            party_a_name="A",
            party_b_name="B",
            case_number="CS 1/2026",
            court_name="Court",
            statutory_basis="cpc_order_23_rule_3",
            settlement_terms="short",  # below 80 chars
        )


def test_probate_facts_requires_two_attesting_witnesses() -> None:
    """s.63(c) demands ≥2 attesting witnesses — Pydantic enforces it."""
    with pytest.raises(ValueError):
        ProbatePetitionFacts(
            matter_id="m",
            petitioner_name="Executor X",
            petitioner_relationship_to_deceased="Son",
            deceased_name="Late Y",
            deceased_date_of_death="2025-06-01",
            deceased_last_residence="123 Main Street, Mumbai",
            deceased_religion="hindu",
            will_date="2024-01-15",
            will_attesting_witnesses=["Witness A only"],  # only 1
            estate_assets_summary=(
                "Movable: bank deposits ~50L; immovable: flat at "
                "Andheri ~3Cr."
            ),
            estate_total_value_inr=35000000.0,
            legal_heirs=["Y's spouse", "Y's son", "Y's daughter"],
            court_name="Bombay High Court",
        )
