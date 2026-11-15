"""Owner-reference presentation contracts, separate from legal validity."""
import pytest

from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.drafting_formats import (
    CIVIL_SUIT_PAGES,
    CONVEYANCING_PAGES,
    FORMATS,
    PROPERTY_NOTICE_PAGES,
    SLP_PAGES,
    SOURCE_SHA256,
    WRIT_PAGES,
    document_lines,
    format_instructions,
    format_manifest,
    read_format_reference,
    selected_conveyancing_instrument,
    selected_document_variant,
)
from caseops_api.services.drafting_prompts import get_prompt_parts


def test_every_guided_type_has_an_explicit_format_decision():
    assert set(FORMATS) == {item.value for item in DraftTemplateType}
    assert SOURCE_SHA256 == "cc50806727ff07306d6fe0b0bceee500061edb10577b9c350b63e31ce35c6cd0"
    for key, profile in FORMATS.items():
        assert profile.key == key
        assert profile.sections
        assert all(1 <= page <= 99 for page in profile.pdf_pages)
        if profile.direct_example:
            assert profile.pdf_pages


@pytest.mark.parametrize("template", list(DraftTemplateType))
def test_shared_prompt_preserves_type_rules_and_adds_its_format(template):
    parts = get_prompt_parts(template)
    assert format_instructions(template.value) in parts.system
    assert f"Selected format: {template.value};" in parts.system
    assert parts.focus
    assert "current court or registry rules" in parts.system
    assert "not legal authority or facts" in parts.system
    assert (
        "Do not assert a completed signature, oath, service, registration or attestation"
        in parts.system
    )


def test_string_callers_retain_the_existing_strenum_lookup_behavior():
    assert get_prompt_parts("bail") == get_prompt_parts(DraftTemplateType.BAIL)


def test_correspondence_has_sender_and_demand_structure():
    profile = FORMATS["cheque_bounce_notice"]
    assert profile.family == "notice"
    assert profile.pdf_pages == (96, 97)
    assert any("addressee" in section for section in profile.sections)
    assert any("demand" in section for section in profile.sections)
    assert not any("lettered prayer" in section.lower() for section in profile.sections)


def test_written_statement_keeps_paragraph_wise_response_separate():
    profile = FORMATS["written_statement"]
    assert profile.pdf_pages == (18, 19, 20)
    assert "Paragraph-wise reply on merits" in "\n".join(profile.sections)
    assert "preliminary objections" in "\n".join(profile.sections)


def test_registry_format_does_not_receive_a_court_family_outline():
    prompt = format_instructions("trademark_opposition_notice", registry=True)
    assert "retain its governed template heading" in prompt
    assert "Do not substitute a generic court caption" in prompt
    assert "Expected sections" not in prompt
    assert "Selected format:" not in prompt


def test_missing_book_examples_are_honestly_labelled_adaptations():
    for key in ("curative_petition", "vakalatnama", "filing_index_checklist"):
        assert not FORMATS[key].direct_example
        assert "no exact worked example is claimed" in format_instructions(key)


def test_generic_path_keeps_the_requested_document_family():
    prompt = format_instructions(None)
    assert "deeds use parties, recitals, operative terms, schedules and execution" in prompt
    assert "Missing particulars require explicit square-bracket placeholders" in prompt
    assert "For a partial preview, render only the requested step" in prompt
    assert "4,19,200" not in prompt
    assert "Rohini" not in prompt
    assert "2017" not in prompt


def test_conveyancing_is_an_instrument_format_with_execution_not_a_plaint():
    profile = FORMATS["conveyancing_deed"]
    assert profile.family == "deed"
    assert profile.pdf_pages == tuple(range(79, 93))
    assert "Recitals" in "\n".join(profile.sections)
    assert "operative terms" in "\n".join(profile.sections)
    assert (
        "Do not add a court-style prayer or pleading verification"
        in format_instructions(profile.key)
    )


@pytest.mark.parametrize("instrument", [
    "Sale deed", "Mortgage deed", "Partnership deed",
    "Dissolution of partnership", "Relinquishment deed", "Gift deed",
])
def test_conveyancing_facts_accept_each_declared_instrument_without_court_fields(instrument):
    from caseops_api.schemas.drafting_templates import ConveyancingDeedFacts

    facts = ConveyancingDeedFacts(
        matter_id="matter-format-fixture", instrument_type=instrument,
        parties="Parties supplied for this test",
        transaction_facts="Transaction supplied for this test",
        governing_law="Confirmed law supplied for this test",
        operative_terms="Terms supplied for this test",
    )
    assert facts.instrument_type == instrument
    assert facts.execution_date is None
    assert facts.consideration is None
    assert "court_name" not in facts.model_dump()


def test_conveyancing_does_not_admit_an_unspecified_or_unsupported_instrument():
    from pydantic import ValidationError

    from caseops_api.schemas.drafting_templates import ConveyancingDeedFacts

    supplied = dict(matter_id="matter-format-fixture", parties="Supplied parties",
                    transaction_facts="Supplied facts", governing_law="Supplied law",
                    operative_terms="Supplied terms")
    with pytest.raises(ValidationError):
        ConveyancingDeedFacts(**supplied)
    with pytest.raises(ValidationError):
        ConveyancingDeedFacts(**supplied, instrument_type="Unknown deed")
    for field in ("parties", "transaction_facts", "governing_law", "operative_terms"):
        with pytest.raises(ValidationError) as refused:
            ConveyancingDeedFacts(**{**supplied, field: " \t\n "}, instrument_type="Gift deed")
        assert any(error["loc"] == (field,) for error in refused.value.errors())


def test_every_deed_picker_option_is_admitted_by_its_actual_facts_model():
    from caseops_api.schemas.drafting_templates import (
        ConveyancingDeedFacts,
        get_template_schema,
    )

    schema = get_template_schema(DraftTemplateType.CONVEYANCING_DEED)
    picker = next(field for field in schema.fields if field.name == "instrument_type")
    assert picker.enum_options == [
        "Sale deed", "Mortgage deed", "Partnership deed",
        "Dissolution of partnership", "Relinquishment deed", "Gift deed",
    ]
    properties = ConveyancingDeedFacts.model_json_schema()["properties"]
    assert picker.enum_options == properties["instrument_type"]["enum"]
    assert {field.name for field in schema.fields} == (
        set(ConveyancingDeedFacts.model_fields) - {"matter_id", "focus_note"}
    )


@pytest.mark.parametrize("title,party_headings", [
    ("Sale deed", "BETWEEN\n[first]\nAND\n[second]"),
    ("Mortgage deed", "BY\n[first]\nIN FAVOUR OF\n[second]"),
    ("Partnership deed", "BETWEEN\n[first]\nAND\n[second]"),
    ("Dissolution of partnership", "BETWEEN\n[first]\nAND\n[second]"),
    ("Relinquishment deed", "BY\n[first]\nIN FAVOUR OF\n[second]"),
    ("Gift deed", "BETWEEN\n[first]\nAND\n[second]"),
])
def test_offline_structure_score_accepts_each_source_party_heading(title, party_headings):
    from caseops_api.scripts.eval_drafting_quality import _score_structure

    body = f"{title}\n{party_headings}\nRECITALS\n[background]\nOPERATIVE TERMS\nEXECUTION"
    score, present = _score_structure(body, "conveyancing_deed")
    assert score == 5.0 and "parties" in present
    # A lexical structure score is not a legal-validity verdict. It must still
    # distinguish an absent party block from the two source heading styles.
    score, present = _score_structure(
        body.replace(party_headings, "[unspecified]"), "conveyancing_deed",
    )
    assert score == 4.0 and "parties" not in present


def test_new_version_reference_does_not_claim_book_is_current_law():
    captured = format_manifest("bail")
    assert captured["source_sha256"] == SOURCE_SHA256
    assert captured["pdf_pages"] == [63, 64]
    assert captured["legal_rules_verified"] is False
    pages = captured["pdf_pages"]
    assert isinstance(pages, list)
    pages.clear()
    assert format_manifest("bail")["pdf_pages"] == [63, 64]
    registry = format_manifest("trademark_opposition_notice", registry=True)
    assert registry["direct_example"] is False
    assert registry["pdf_pages"] == []
    assert registry["profile"] == "registry-adaptation"


def test_deed_version_captures_the_selected_source_example():
    for instrument, pages in CONVEYANCING_PAGES.items():
        snapshot = format_manifest("conveyancing_deed", facts={"instrument_type": instrument})
        assert snapshot["instrument_type"] == instrument
        assert snapshot["pdf_pages"] == list(pages)
        assert snapshot["legal_rules_verified"] is False


@pytest.mark.parametrize("selection,pages", [
    ("Summary recovery", [1, 2, 3]), ("Permanent injunction", [5, 6, 7]),
    ("Ejectment and damages", [13, 14, 15]), ("Specific performance", [16, 17]),
])
def test_civil_plaint_subtype_is_selectable_and_frozen_to_its_example(selection, pages):
    from caseops_api.schemas.drafting_templates import CivilSuitFacts, get_template_schema

    picker = next(field for field in get_template_schema(DraftTemplateType.CIVIL_SUIT).fields
                  if field.name == "suit_format")
    assert picker.enum_options == list(CIVIL_SUIT_PAGES)
    properties = CivilSuitFacts.model_json_schema()["properties"]
    assert picker.enum_options == properties["suit_format"]["enum"]
    snapshot = format_manifest("civil_suit", facts={"suit_format": selection})
    assert snapshot["suit_format"] == selection
    assert snapshot["pdf_pages"] == pages
    assert read_format_reference({"presentation_reference": snapshot}) == snapshot
    assert snapshot["legal_rules_verified"] is False


@pytest.mark.parametrize(
    "kind,pages", [("civil", [55, 56, 57, 58]), ("criminal", [59, 60, 61, 62])],
)
def test_slp_uses_the_existing_civil_criminal_picker_and_exact_source_pages(kind, pages):
    assert set(SLP_PAGES) == {"civil", "criminal"}
    snapshot = format_manifest("special_leave_petition", facts={"slp_kind": kind})
    assert snapshot["slp_kind"] == kind
    assert snapshot["pdf_pages"] == pages
    assert read_format_reference({"presentation_reference": snapshot}) == snapshot


@pytest.mark.parametrize("template,field,selection,pages,direct", [
    ("writ_petition", "writ_kind", "civil", [49, 50], True),
    ("writ_petition", "writ_kind", "criminal", [51, 52, 53, 54], True),
    ("property_dispute_notice", "notice_format", "Notice to quit / ejectment", [93], True),
    ("property_dispute_notice", "notice_format", "General property dispute", [93], False),
])
def test_notice_and_writ_choices_match_fields_models_and_saved_source(
    template, field, selection, pages, direct,
):
    from caseops_api.schemas.drafting_templates import get_template_facts_model, get_template_schema

    schema = get_template_schema(DraftTemplateType(template))
    model = get_template_facts_model(DraftTemplateType(template))
    picker = next(item for item in schema.fields if item.name == field)
    choices = WRIT_PAGES if template == "writ_petition" else PROPERTY_NOTICE_PAGES
    assert picker.enum_options == list(choices)
    assert picker.enum_options == model.model_json_schema()["properties"][field]["enum"]
    assert picker.required is False and not model.model_fields[field].is_required()
    assert {item.name for item in schema.fields} == (
        set(model.model_fields) - {"matter_id", "focus_note"}
    )
    snapshot = format_manifest(template, facts={field: selection})
    assert snapshot[field] == selection
    assert snapshot["pdf_pages"] == pages
    assert snapshot["direct_example"] is direct
    assert read_format_reference({"presentation_reference": snapshot}) == snapshot


def test_notice_and_criminal_writ_prompts_do_not_force_general_or_civil_structure():
    notice = get_prompt_parts(DraftTemplateType.PROPERTY_DISPUTE_NOTICE).system
    assert "For 'Notice to quit / ejectment'" in notice
    assert "Do not label a tenant a trespasser" in notice
    assert "response deadline is not a substitute" in notice
    writ = get_prompt_parts(DraftTemplateType.WRIT_PETITION).system
    assert "Writ Petition (Crl.) No. ___ of 20__" in writ
    assert "do not silently relabel a criminal matter as civil" in writ


def test_legacy_optional_civil_selector_has_an_honest_general_adaptation():
    snapshot = format_manifest("civil_suit", facts={})
    assert snapshot["suit_format"] == "General civil plaint"
    assert snapshot["direct_example"] is False
    assert selected_document_variant("civil_suit", {}, partial=True) is None


def test_a_free_form_slp_without_a_kind_is_not_relabelled_as_a_civil_petition():
    snapshot = format_manifest("special_leave_petition", facts={})
    assert "slp_kind" not in snapshot
    assert snapshot["pdf_pages"] == list(range(55, 63))
    assert snapshot["direct_example"] is False
    assert read_format_reference({"presentation_reference": snapshot}) == snapshot


def test_free_form_writ_and_general_notice_have_honest_adapted_provenance():
    writ = format_manifest("writ_petition", facts={})
    assert "writ_kind" not in writ and writ["direct_example"] is False
    assert writ["pdf_pages"] == [49, 50, 51, 52, 53, 54]
    notice = format_manifest("property_dispute_notice", facts={})
    assert notice["notice_format"] == "General property dispute"
    assert notice["direct_example"] is False
    assert selected_document_variant("property_dispute_notice", {}, partial=True) is None
    for reference in (writ, notice):
        assert read_format_reference({"presentation_reference": reference}) == reference


@pytest.mark.parametrize(
    "template,field", [
        ("civil_suit", "suit_format"), ("special_leave_petition", "slp_kind"),
        ("writ_petition", "writ_kind"), ("property_dispute_notice", "notice_format"),
    ],
)
@pytest.mark.parametrize("value", ["unsupported", "", None, {}, [], False, 1])
def test_unknown_existing_subtype_is_not_captured_or_previewed_as_another_format(
    template, field, value,
):
    with pytest.raises(ValueError, match="Choose a supported document format"):
        selected_document_variant(template, {field: value}, partial=True)
    with pytest.raises(ValueError):
        format_manifest(template, facts={field: value})


@pytest.mark.parametrize("key,expected_pages", [
    ("injunction_breach_application", [10, 11]), ("indigent_person_application", [12]),
    ("execution_application", [27, 28]), ("restitution_conjugal_rights", [31, 32]),
    ("judicial_separation_petition", [33, 34]), ("mutual_consent_divorce", [38, 39]),
    ("letters_of_administration", [44, 45, 46]), ("succession_certificate", [47, 48]),
    ("cheque_bounce_complaint", [67, 68]), ("maintenance_application", [69, 70]),
    ("consumer_complaint", [71, 72, 73]), ("domestic_violence_complaint", [76, 77, 78]),
    ("government_suit_notice", [94, 95]), ("legal_notice_reply", [98, 99]),
])
def test_additional_form_fields_match_the_actual_required_model_and_source(key, expected_pages):
    from caseops_api.schemas.drafting_templates import get_template_facts_model, get_template_schema

    template = DraftTemplateType(key)
    schema = get_template_schema(template)
    model = get_template_facts_model(template)
    assert {field.name for field in schema.fields} == (
        set(model.model_fields) - {"matter_id", "focus_note"}
    )
    for field in schema.fields:
        assert field.required == model.model_fields[field.name].is_required(), field.name
    assert "governing_law" in model.model_fields
    assert model.model_fields["governing_law"].is_required()
    assert schema.statutory_basis == []
    snapshot = format_manifest(key)
    assert snapshot["pdf_pages"] == expected_pages
    assert snapshot["direct_example"] is True
    assert read_format_reference({"presentation_reference": snapshot}) == snapshot


def test_execution_keeps_all_ten_source_particulars_in_order_without_sample_values():
    system = get_prompt_parts(DraftTemplateType.EXECUTION_APPLICATION).system
    labels = [
        "(1) suit number", "(2) parties", "(3) decree/order date", "(4) appeal position",
        "(5) payment or satisfaction", "(6) prior execution applications with dates/results",
        "(7) decree amount/interest or other relief", "(8) awarded costs",
        "(9) person against whom execution is sought", "(10) specific court assistance requested",
    ]
    positions = [system.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "decree-holder and judgment-debtor" in system.lower()
    assert "2017" not in system and "2015" not in system


def test_joint_petition_and_notice_reply_retain_their_distinct_procedural_roles():
    joint = get_prompt_parts(DraftTemplateType.MUTUAL_CONSENT_DIVORCE).system
    assert "both parties as joint petitioners" in joint
    assert "separate signature placeholders for both petitioners" in joint
    reply = get_prompt_parts(DraftTemplateType.LEGAL_NOTICE_REPLY).system
    assert "Paragraph-wise reply matching the original notice" in reply
    assert "without a court caption or pleading verification" in reply


def test_partial_preview_can_be_incomplete_but_cannot_select_an_unknown_deed():
    assert selected_conveyancing_instrument({}, partial=True) is None
    for value in ["Unknown deed", "", {}, [], 1]:
        with pytest.raises(ValueError, match="Choose one of the six supported deed formats"):
            selected_conveyancing_instrument({"instrument_type": value}, partial=True)
    with pytest.raises(ValueError):
        format_manifest("conveyancing_deed", facts={})


def test_legacy_versions_are_not_relabelled_with_the_new_reference():
    assert read_format_reference(None) is None
    assert read_format_reference({"key": "bail", "schema": "caseops.drafting-template.v1"}) is None


@pytest.mark.parametrize("field,value", [
    ("source_sha256", "0" * 64), ("version", "unknown-future-format"),
    ("legal_rules_verified", True), ("legal_rules_verified", 0),
    ("pdf_pages", [True]), ("profile", "unknown-profile"),
])
def test_export_does_not_substitute_a_different_reference(field, value):
    reference = format_manifest("bail")
    reference[field] = value
    with pytest.raises(ValueError):
        read_format_reference({"presentation_reference": reference})


def test_supported_reference_is_checked_and_returned_without_shared_list_state():
    reference = format_manifest("bail")
    recovered = read_format_reference({"presentation_reference": reference})
    assert recovered == reference
    assert recovered is not reference
    assert recovered["pdf_pages"] is not reference["pdf_pages"]


def test_body_layout_preserves_every_supplied_character_and_line_break():
    body = (
        "IN THE COURT OF [court]\n\n1. Amount ₹0.50; party आशा; reference [2026:XYZ:1].\n"
        "  Indented schedule\nPRAYER:\n(a) Supplied relief.\nVERIFICATION:\n"
        "[paragraph ranges]\nDeponent\n"
    )
    lines = tuple(document_lines(body))
    assert "\n".join(line.text for line in lines) == body
    assert lines[0].alignment == "C" and lines[0].bold
    assert next(line for line in lines if line.text == "PRAYER:").keep_with_next
    assert next(line for line in lines if line.text == "Deponent").alignment == "R"
    assert next(line for line in lines if line.text.startswith("1.")).alignment == "L"


def test_deed_heading_and_execution_do_not_create_a_pleading():
    body = (
        "GIFT DEED\nBETWEEN\n[donor]\nAND\n[donee]\nRECITALS\n[background]\n"
        "EXECUTION\nDonor\nDonee"
    )
    lines = tuple(document_lines(body))
    assert "\n".join(line.text for line in lines) == body
    assert lines[0].alignment == "C" and lines[0].bold
    assert lines[-2].alignment == "R" and lines[-1].alignment == "R"
    assert all("PRAYER" not in line.text for line in lines)


def test_preview_rejects_an_invalid_deed_before_provider_construction(monkeypatch):
    from fastapi import HTTPException

    from caseops_api.services import drafting_preview

    calls = []
    monkeypatch.setattr(
        drafting_preview, "_default_preview_provider", lambda: calls.append("provider"),
    )
    with pytest.raises(HTTPException) as failure:
        drafting_preview.generate_step_preview(
            template_type=DraftTemplateType.CONVEYANCING_DEED,
            facts={"instrument_type": "unsupported", "private_fact": "must-not-be-reflected"},
        )
    assert failure.value.status_code == 422
    assert failure.value.detail[0]["loc"] == ["body", "facts", "instrument_type"]
    assert "must-not-be-reflected" not in str(failure.value.detail)
    assert calls == []


@pytest.mark.parametrize("template,field", [
    (DraftTemplateType.CIVIL_SUIT, "suit_format"),
    (DraftTemplateType.SPECIAL_LEAVE_PETITION, "slp_kind"),
    (DraftTemplateType.WRIT_PETITION, "writ_kind"),
    (DraftTemplateType.PROPERTY_DISPUTE_NOTICE, "notice_format"),
])
def test_preview_rejects_unknown_existing_subtypes_before_provider_work(
    monkeypatch, template, field,
):
    from fastapi import HTTPException

    from caseops_api.services import drafting_preview

    calls = []
    monkeypatch.setattr(
        drafting_preview, "_default_preview_provider", lambda: calls.append("provider"),
    )
    with pytest.raises(HTTPException) as failure:
        drafting_preview.generate_step_preview(
            template_type=template,
            facts={field: "unsupported", "private_fact": "PRIVATE-SUBTYPE-INPUT"},
        )
    assert failure.value.status_code == 422
    assert failure.value.detail[0]["loc"] == ["body", "facts", field]
    assert "PRIVATE-SUBTYPE-INPUT" not in str(failure.value.detail)
    assert calls == []


def test_generation_rejects_invalid_retained_selection_before_retrieval(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from caseops_api.db.models import DraftStatus
    from caseops_api.services import drafting

    matter = SimpleNamespace(id="matter-format-fixture")
    draft = SimpleNamespace(
        template_type="conveyancing_deed", status=DraftStatus.DRAFT,
        facts_json='{"instrument_type":"unsupported"}',
    )
    monkeypatch.setattr(drafting, "_load_matter", lambda *a, **kw: matter)
    monkeypatch.setattr(drafting, "require_operational_matter", lambda *a, **kw: matter)
    monkeypatch.setattr(drafting, "_load_draft", lambda *a, **kw: draft)
    calls = []
    monkeypatch.setattr(drafting, "_retrieve_for_draft", lambda *a, **kw: calls.append("retrieve"))
    with pytest.raises(HTTPException) as failure:
        drafting.generate_draft_version(
            None, context=None, matter_id=matter.id, draft_id="draft-format-fixture",
        )
    assert failure.value.status_code == 422
    assert calls == []
