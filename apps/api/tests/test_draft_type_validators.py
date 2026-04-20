"""Sprint R5 — tests for per-type draft validators.

Each template gets two canonical fixtures: a "good" draft that should
pass all gates, and a "bad" draft that fires the rule the validator
is designed to catch. The rule names are asserted explicitly so a
prompt tweak that accidentally satisfies the regex without actually
fixing the pleading is caught.
"""
from __future__ import annotations

from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.draft_type_validators import (
    validate_draft_by_type,
)

# ---------------------------------------------------------------
# Bail
# ---------------------------------------------------------------


def test_bail_validator_passes_well_formed_draft() -> None:
    body = """
    Application for regular bail under BNSS s.483.
    Accused has been in custody since 01.03.2026 (over 50 days).
    Grounds — triple test satisfied: no flight risk, no tampering with
    evidence, no influencing the witnesses (already examined).
    Parity — co-accused Ravi Singh was granted bail by this Hon'ble Court.
    """
    res = validate_draft_by_type(
        template_type=DraftTemplateType.BAIL, body=body,
    )
    assert res.passed is True
    assert res.errors() == []


def test_bail_validator_catches_missing_statute() -> None:
    body = "Application for bail. Grounds: triple test satisfied. Custody since 2026-03-01."
    res = validate_draft_by_type(
        template_type=DraftTemplateType.BAIL, body=body,
    )
    assert res.passed is False
    rules = {f.rule for f in res.errors()}
    assert "bail_missing_statute" in rules


def test_bail_validator_warns_on_missing_triple_test() -> None:
    body = "Application for regular bail under BNSS s.483. Accused in custody since 2026-03-01."
    res = validate_draft_by_type(
        template_type=DraftTemplateType.BAIL, body=body,
    )
    # Statute is cited so no error; but triple-test missing warns.
    assert res.passed is True
    rules = {f.rule for f in res.warnings()}
    assert "bail_triple_test_missing" in rules


# ---------------------------------------------------------------
# Anticipatory bail
# ---------------------------------------------------------------


def test_anticipatory_bail_validator_catches_missing_statute() -> None:
    body = (
        "Application apprehending arrest. Applicant has received a notice."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.ANTICIPATORY_BAIL, body=body,
    )
    assert res.passed is False
    rules = {f.rule for f in res.errors()}
    assert "anticipatory_bail_missing_statute" in rules


def test_anticipatory_bail_validator_passes_with_bnss() -> None:
    body = (
        "Application for anticipatory bail under BNSS s.482. "
        "Applicant apprehends arrest based on the FIR filed."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.ANTICIPATORY_BAIL, body=body,
    )
    assert res.passed is True


# ---------------------------------------------------------------
# Cheque bounce
# ---------------------------------------------------------------


def test_cheque_bounce_validator_catches_missing_15_day_window() -> None:
    body = (
        "Statutory notice under s.138 of the NI Act. "
        "Please pay Rs. 5,00,000 (Rupees Five Lakhs only) at the earliest."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CHEQUE_BOUNCE_NOTICE, body=body,
    )
    assert res.passed is False
    rules = {f.rule for f in res.errors()}
    assert "cheque_bounce_missing_15_day_window" in rules


def test_cheque_bounce_validator_accepts_either_15_or_fifteen_days() -> None:
    body = (
        "Statutory notice under s.138 of the NI Act. "
        "Pay Rs.5,00,000 (Rupees Five Lakhs only) within fifteen days."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CHEQUE_BOUNCE_NOTICE, body=body,
    )
    assert res.passed is True


def test_cheque_bounce_validator_warns_on_amount_format() -> None:
    body = (
        "Statutory notice under s.138 of the NI Act. "
        "Pay the cheque amount within 15 days."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CHEQUE_BOUNCE_NOTICE, body=body,
    )
    # No error-level issues but amount-format warning must fire.
    assert res.passed is True
    rules = {f.rule for f in res.warnings()}
    assert "cheque_bounce_amount_format" in rules


# ---------------------------------------------------------------
# Civil suit
# ---------------------------------------------------------------


def test_civil_suit_validator_catches_missing_cause_of_action() -> None:
    body = (
        "Plaint for recovery of money. The plaintiff prays for the relief "
        "of ₹1,00,000 with interest. Valuation: ₹1,00,000."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CIVIL_SUIT, body=body,
    )
    assert res.passed is False
    rules = {f.rule for f in res.errors()}
    assert "civil_suit_cause_of_action_missing" in rules


def test_civil_suit_validator_passes_well_formed() -> None:
    body = (
        "Plaint. Cause of action arose on 15 Jan 2026 at Mumbai. "
        "Valuation: ₹1,00,000. Prayer: (a) recovery of ₹1,00,000; "
        "(b) costs."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CIVIL_SUIT, body=body,
    )
    assert res.passed is True


# ---------------------------------------------------------------
# Criminal complaint
# ---------------------------------------------------------------


def test_criminal_complaint_validator_catches_ipc_only() -> None:
    body = (
        "Complaint under BNSS s.223. Accused has committed offences "
        "under IPC s.420 and IPC s.406."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CRIMINAL_COMPLAINT, body=body,
    )
    # Statute is cited (no error) but IPC-only warning fires.
    assert res.passed is True
    rules = {f.rule for f in res.warnings()}
    assert "criminal_complaint_ipc_default" in rules


def test_criminal_complaint_validator_passes_with_bns() -> None:
    body = (
        "Complaint under BNSS s.223. Accused has committed offences "
        "under BNS s.318."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CRIMINAL_COMPLAINT, body=body,
    )
    assert res.passed is True
    assert res.warnings() == []


# ---------------------------------------------------------------
# Divorce
# ---------------------------------------------------------------


def test_divorce_validator_catches_missing_act() -> None:
    body = "Petition for dissolution of marriage on grounds of cruelty."
    res = validate_draft_by_type(
        template_type=DraftTemplateType.DIVORCE_PETITION, body=body,
    )
    assert res.passed is False
    rules = {f.rule for f in res.errors()}
    assert "divorce_missing_act" in rules


def test_divorce_validator_passes_with_hma() -> None:
    body = (
        "Petition under s.13 of the Hindu Marriage Act, 1955 on "
        "grounds of cruelty and desertion."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.DIVORCE_PETITION, body=body,
    )
    assert res.passed is True


# ---------------------------------------------------------------
# Affidavit
# ---------------------------------------------------------------


def test_affidavit_validator_catches_missing_affirmation() -> None:
    body = "I state as under: 1. This is my statement."
    res = validate_draft_by_type(
        template_type=DraftTemplateType.AFFIDAVIT, body=body,
    )
    assert res.passed is False
    rules = {f.rule for f in res.errors()}
    assert "affidavit_missing_affirmation" in rules


def test_affidavit_validator_passes_with_affirmation_and_verification() -> None:
    body = (
        "I, Priya, do hereby solemnly affirm and state as under: "
        "1. The facts are true to my personal knowledge. Verification: "
        "the above paragraphs are true."
    )
    res = validate_draft_by_type(
        template_type=DraftTemplateType.AFFIDAVIT, body=body,
    )
    assert res.passed is True


# ---------------------------------------------------------------
# Property dispute notice
# ---------------------------------------------------------------


def test_property_notice_validator_warns_on_no_deadline() -> None:
    body = "Demand notice: cease encroachment on the suit property."
    res = validate_draft_by_type(
        template_type=DraftTemplateType.PROPERTY_DISPUTE_NOTICE, body=body,
    )
    # No errors but missing-deadline warning fires.
    assert res.passed is True
    rules = {f.rule for f in res.warnings()}
    assert "property_notice_no_deadline" in rules


# ---------------------------------------------------------------
# API surface — every registered type produces a result object.
# ---------------------------------------------------------------


def test_validator_registry_covers_all_template_types() -> None:
    """Each DraftTemplateType should at least produce a result (even an
    empty one). No KeyError, no AttributeError."""
    for tt in DraftTemplateType:
        res = validate_draft_by_type(template_type=tt, body="placeholder")
        assert res.template_type == tt.value
