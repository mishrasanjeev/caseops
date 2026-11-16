"""Presentation structures adapted from the owner's supplied drafting manual.

This is a format reference, never legal authority or a source of matter facts.
PDF page indices are deliberately distinct from the book's printed pagination.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass

SOURCE_SHA256 = "cc50806727ff07306d6fe0b0bceee500061edb10577b9c350b63e31ce35c6cd0"
SOURCE_LABEL = "Drafting-Pleadings-and-Conveyancing.pdf"
FORMAT_VERSION = "owner-manual-2026-11-15-v1"
CONVEYANCING_PAGES: dict[str, tuple[int, ...]] = {
    "Sale deed": (79, 80, 81),
    "Mortgage deed": (82, 83),
    "Partnership deed": (84, 85),
    "Dissolution of partnership": (86, 87),
    "Relinquishment deed": (88, 89),
    "Gift deed": (90, 91, 92),
}
CIVIL_SUIT_PAGES: dict[str, tuple[int, ...]] = {
    "General civil plaint": (1, 2, 3, 5, 6, 7, 13, 14, 15, 16, 17),
    "Summary recovery": (1, 2, 3),
    "Permanent injunction": (5, 6, 7),
    "Ejectment and damages": (13, 14, 15),
    "Specific performance": (16, 17),
}
SLP_PAGES: dict[str, tuple[int, ...]] = {
    "civil": (55, 56, 57, 58), "criminal": (59, 60, 61, 62),
}
WRIT_PAGES: dict[str, tuple[int, ...]] = {
    "civil": (49, 50), "criminal": (51, 52, 53, 54),
}
PROPERTY_NOTICE_PAGES: dict[str, tuple[int, ...]] = {
    "General property dispute": (93,), "Notice to quit / ejectment": (93,),
}
DOCUMENT_VARIANTS: dict[str, tuple[str, str | None, dict[str, tuple[int, ...]]]] = {
    "civil_suit": ("suit_format", "General civil plaint", CIVIL_SUIT_PAGES),
    "special_leave_petition": ("slp_kind", None, SLP_PAGES),
    "writ_petition": ("writ_kind", None, WRIT_PAGES),
    "property_dispute_notice": ("notice_format", "General property dispute", PROPERTY_NOTICE_PAGES),
}


def selected_conveyancing_instrument(facts: object, *, partial: bool = False) -> str | None:
    """Reject unsupported choices without echoing submitted transaction data."""
    value = facts.get("instrument_type") if isinstance(facts, dict) else None
    if value is None and partial:
        return None
    if not isinstance(value, str) or value not in CONVEYANCING_PAGES:
        raise ValueError("Choose one of the six supported deed formats.")
    return value


def selected_document_variant(
    template_type: str | None, facts: object, *, partial: bool = False,
) -> tuple[str, str, tuple[int, ...]] | None:
    """Bind supported existing subtypes to their exact source example pages."""
    specification = DOCUMENT_VARIANTS.get(template_type or "")
    if specification is None:
        return None
    field, default, choices = specification
    values = facts if isinstance(facts, dict) else {}
    if field not in values and (partial or default is None):
        return None
    value = values.get(field, default)
    if not isinstance(value, str) or value not in choices:
        raise ValueError("Choose a supported document format.")
    return field, value, choices[value]


@dataclass(frozen=True)
class DraftingFormat:
    key: str
    family: str
    sections: tuple[str, ...]
    pdf_pages: tuple[int, ...]
    direct_example: bool = True


@dataclass(frozen=True)
class ReferenceTemplate:
    label: str
    family: str
    pdf_pages: tuple[int, ...]
    instructions: str


REFERENCE_TEMPLATES: dict[str, ReferenceTemplate] = {
    "injunction_breach_application": ReferenceTemplate(
        "Application Concerning Breach of Injunction", "application", (10, 11),
        "Identify the actual injunction, its terms, supplied service or knowledge facts, and "
        "separately numbered alleged breaches. Do not presume disobedience was proved.",
    ),
    "indigent_person_application": ReferenceTemplate(
        "Application to Sue as an Indigent Person", "application", (12,),
        "Keep the proposed claim, disclosed assets and means, and requested permission distinct. "
        "Do not assert indigence or procedural eligibility without supplied support.",
    ),
    "execution_application": ReferenceTemplate(
        "Execution Application", "application", (27, 28),
        "Identify the decree or order, decree-holder and judgment-debtor, supplied satisfaction "
        "or payment history and requested execution measures. Unknown amounts or satisfaction "
        "details remain placeholders.",
    ),
    "restitution_conjugal_rights": ReferenceTemplate(
        "Restitution of Conjugal Rights Petition", "pleading", (31, 32),
        "Use supplied marriage and cohabitation particulars, alleged withdrawal and actual "
        "requested relief. Do not invent consent, conduct or the absence of a legal defence.",
    ),
    "judicial_separation_petition": ReferenceTemplate(
        "Judicial Separation Petition", "pleading", (33, 34),
        "Keep marriage particulars, distinct supplied grounds and the requested "
        "judicial-separation relief separate. Do not substitute a divorce prayer or presume a "
        "matrimonial allegation is established.",
    ),
    "mutual_consent_divorce": ReferenceTemplate(
        "Joint Petition for Divorce by Mutual Consent", "pleading", (38, 39),
        "Identify both parties as joint petitioners. Set out only supplied consent, separation "
        "and settlement terms. Do not invent consent, waive a statutory period or assert that "
        "eligibility requirements are met.",
    ),
    "letters_of_administration": ReferenceTemplate(
        "Petition for Letters of Administration", "pleading", (44, 45, 46),
        "Identify the deceased, applicant's stated basis, supplied estate and heir particulars "
        "and actual will position. Do not presume the applicant is an executor or fabricate an "
        "attesting-witness statement.",
    ),
    "succession_certificate": ReferenceTemplate(
        "Succession Certificate Petition", "pleading", (47, 48),
        "Set out supplied deceased and relationship particulars, heirs, debts and securities with "
        "a separate schedule and the requested certificate. Do not invent assets, exclusive "
        "entitlement or absence of competing proceedings.",
    ),
    "cheque_bounce_complaint": ReferenceTemplate(
        "Cheque Bounce Complaint", "pleading", (67, 68),
        "Use complainant and accused roles. Separate supplied debt or liability facts, cheque "
        "particulars, presentation, dishonour, notice, service and payment history. Do not "
        "presume statutory compliance, dates or limitation.",
    ),
    "maintenance_application": ReferenceTemplate(
        "Maintenance Application", "application", (69, 70),
        "Identify each applicant, any minor's supplied representation details and the respondent. "
        "Distinguish supplied relationship, needs, income and means, and each requested relief. "
        "Do not guess amounts or financial capacity.",
    ),
    "consumer_complaint": ReferenceTemplate(
        "Consumer Complaint", "pleading", (71, 72, 73),
        "Identify complainant and opposite parties, supplied transaction and grievance "
        "chronology, communications, valuation and requested remedies. Use the actual confirmed "
        "forum and governing law, not the historical forum or enactment in the sample.",
    ),
    "domestic_violence_complaint": ReferenceTemplate(
        "Domestic Violence Complaint", "pleading", (76, 77, 78),
        "Keep supplied relationship and household particulars, alleged acts, evidence and each "
        "requested remedy distinct. Do not invent violence, injuries, ownership, income or prior "
        "orders.",
    ),
    "government_suit_notice": ReferenceTemplate(
        "Notice Before Suit Against Government", "notice", (94, 95),
        "Identify the supplied sender or counsel and actual government recipient, subject, "
        "cause-of-action facts and requested relief. Use confirmed applicable notice "
        "requirements; do not copy the sample recipient or assume a notice period.",
    ),
    "legal_notice_reply": ReferenceTemplate(
        "Reply to Legal Notice", "correspondence_reply", (98, 99),
        "Identify the notice answered and its actual supplied date. Keep preliminary objections "
        "and paragraph-wise admissions, denials and explanations separate. Do not copy the "
        "sample's allegations of forgery or misuse, and do not turn this correspondence reply "
        "into a court counter-affidavit.",
    ),
}


_PLEADING = (
    "Court or forum heading and jurisdiction designation",
    "Proceeding number and year, when supplied",
    "Memo of parties with their correct procedural roles and supplied addresses",
    "Specific title of the pleading",
    "Numbered material facts in chronological order",
    "Jurisdiction, limitation and valuation particulars where applicable and supported",
    "Separate numbered grounds where appropriate to this document",
    "Prayer with separately lettered reliefs",
    "Place, date, party and advocate signature placeholders",
    "Verification identifying knowledge and information paragraph ranges where required",
)
_APPLICATION = (
    "Court or forum and existing proceeding particulars",
    "Applicant and respondent with their procedural roles",
    "Specific application title and supplied procedural basis",
    "Numbered facts supporting this particular application",
    "Grounds and any supported urgency or interim-relief grounds",
    "Separately lettered prayer",
    "Place, date and signature placeholders; verification or supporting affidavit as applicable",
)
_NOTICE = (
    "Advocate or sender details supplied by the user",
    "Date, supplied service mode and addressee details",
    "Precise subject identifying the actual notice",
    "Instructions and capacity of the sender",
    "Numbered material facts and supporting document references",
    "Specific demand or requested action and the applicable confirmed time period",
    "Closing and sender or advocate signature placeholder",
)
_AFFIDAVIT = (
    "Relevant proceeding heading where this is a supporting affidavit",
    "Affidavit title and deponent's supplied identity and capacity",
    "Numbered first-person statements, confined to supplied knowledge or information",
    "Verification specifying place, date and the actual paragraph ranges when supplied",
    "Deponent signature placeholder and separate attestation placeholder where applicable",
)
_REPLY = (
    "Proceeding heading or correspondence sender, date and addressee as appropriate",
    "Correct responding-party details and title identifying the document answered",
    "Distinct preliminary objections supported by supplied facts",
    "Paragraph-wise reply on merits, distinguishing admission, denial and lack of knowledge",
    "Relief or closing appropriate to a court response or correspondence reply",
    "Signature and any required verification or affidavit placeholders",
)

# Per-form particulars are more specific than a generic facts/grounds/prayer
# outline. These are adapted structures, with no sample allegations or law.
REFERENCE_SECTIONS: dict[str, tuple[str, ...]] = {
    "injunction_breach_application": (
        "Actual court, existing suit/application numbers and parties",
        "Title identifying the alleged breach of the actual injunction",
        "Order date and operative terms, followed by supplied service or knowledge particulars",
        "Separate numbered alleged breaches and supporting references; distinguish allegations "
        "from findings",
        "Requested measures and separately lettered relief; signature and applicable verification "
        "placeholders",
    ),
    "indigent_person_application": (
        "Actual court and parties, followed by the application title",
        "Proposed claim and basis of the requested permission",
        "Separate schedule of disclosed movable/immovable property, values and means",
        "Only supplied facts concerning ability to pay; do not assert eligibility from missing "
        "data",
        "Requested permission, date/place, signature and applicable verification placeholders",
    ),
    "execution_application": (
        "Actual executing court, execution number and originating suit number",
        "Decree-holder and judgment-debtor with the correct designations",
        "Numbered labelled execution particulars in this order: (1) suit number, (2) parties, (3) "
        "decree/order date, (4) appeal position, (5) payment or satisfaction, (6) prior execution "
        "applications with dates/results, (7) decree amount/interest or other relief, (8) awarded "
        "costs, (9) person against whom execution is sought, (10) specific court assistance "
        "requested",
        "Keep missing values as placeholders beside their labels; never substitute sample sums or "
        "assume no appeal/payment",
        "Use the heading PARTICULARS OF EXECUTION, then one numbered label and colon per row "
        "(for example '1. Suit number: [actual number]') through row 10, followed by PRAYER. "
        "Keep all ten rows and any continuation text in order; "
        "use no Markdown or HTML table syntax",
        "Prayer tied to the actual decree and requested mode, followed by place/date, "
        "decree-holder/counsel signature and verification placeholders",
        "Identify the actual decree/order attachment or a missing-document placeholder; do not "
        "claim certification or filing has occurred",
    ),
    "restitution_conjugal_rights": (
        "Actual matrimonial court, proceeding details and petitioner/respondent",
        "Marriage and residence particulars, jurisdiction and supplied cohabitation chronology",
        "Separate supplied withdrawal allegations, efforts described by the user and supported "
        "grounds",
        "Restitution relief actually requested; do not substitute judicial separation or divorce",
        "Place/date, party/counsel signatures and required verification or affidavit placeholders",
    ),
    "judicial_separation_petition": (
        "Actual matrimonial court, proceeding details and parties",
        "Supplied marriage, residence and family particulars",
        "Numbered supporting facts, distinct grounds and supplied prior-proceeding particulars",
        "Prayer specifically requesting judicial separation and only the additional relief "
        "supplied",
        "Place/date, signatures and required verification/affidavit placeholders",
    ),
    "mutual_consent_divorce": (
        "Actual matrimonial court, joint petition number slot and both joint petitioners",
        "Supplied marriage, cohabitation and separation particulars in chronological order",
        "Keep each joint petitioner's supplied status, age and residence before marriage and "
        "at the petition date distinct; unknown particulars remain placeholders",
        "Separate actual consent and agreed settlement particulars, including "
        "children/maintenance/property only when supplied",
        "Prior proceedings and applicable procedural particulars, without presumed waiver or "
        "satisfaction of a period",
        "Joint prayer, separate signature placeholders for both petitioners and counsel, and "
        "actual verification/affidavit placeholders",
    ),
    "letters_of_administration": (
        "Actual court and petition heading, applicant capacity and other supplied interested "
        "parties",
        "Deceased's supplied identity, death and residence particulars, and jurisdiction basis",
        "Actual will position, applicant's stated basis and known heirs/next-of-kin",
        "Separate estate/property and liabilities schedules with supplied values",
        "Prior applications, impediments and fee particulars only to the extent supplied",
        "Administration relief requested, signatures, verification and supporting affidavit "
        "placeholders; no invented executor or witness declaration",
    ),
    "succession_certificate": (
        "Actual court, succession-petition slot and petitioner/respondents as supplied",
        "Deceased's identity, death and residence particulars, relationship and known heirs",
        "Actual will position, stated claim and jurisdiction; no presumed intestacy, religion or "
        "exclusive entitlement",
        "Separate debts and securities schedule, values and stated purpose of the certificate",
        "Supplied prior probate/administration/certificate proceedings, applicable impediments "
        "and fee position",
        "Certificate powers actually requested, and any requested security exemption separately; "
        "no automatic exemption",
        "Place/date, petitioner/counsel signatures, knowledge/information verification ranges and "
        "supporting affidavit placeholders",
    ),
    "cheque_bounce_complaint": (
        "Actual magistrate/court, complaint slot, complainant and accused",
        "Supplied transaction/liability followed by the exact cheque, bank and presentation "
        "particulars",
        "Dishonour memo, notice, service and subsequent payment chronology as separate numbered "
        "facts",
        "Jurisdiction and limitation particulars supported by the actual dates and current "
        "confirmed law",
        "Requested cognizance/process or other supplied relief, document/witness references and "
        "signature/verification placeholders",
    ),
    "maintenance_application": (
        "Actual court, application title, every applicant and respondent",
        "Supplied relationship and any minor's representation particulars",
        "Separate needs, available resources, respondent's supplied means and alleged "
        "neglect/refusal facts",
        "A separately identified amount and requested relief for each applicant, with unknown "
        "figures left blank",
        "Place/date, applicant/counsel signatures and applicable verification/supporting "
        "affidavit placeholders",
    ),
    "consumer_complaint": (
        "Actual current consumer commission/forum, complaint slot, complainant and each opposite "
        "party",
        "Supplied purchase/service, payment and grievance chronology with actual "
        "communications/documents",
        "Distinct alleged defects/deficiency and supported grounds, without copying the sample "
        "telephone dispute",
        "Current confirmed jurisdiction/valuation and cause-of-action particulars; no historical "
        "forum thresholds",
        "Itemised requested refund, compensation, interest and costs only as supplied, avoiding "
        "duplicate recovery or invented calculations",
        "Separately lettered prayer, place/date, signatures and required supporting affidavit "
        "placeholders",
    ),
    "domestic_violence_complaint": (
        "Actual court, application/complaint heading, aggrieved person and each respondent",
        "Supplied domestic relationship, shared-household and any children's particulars; no "
        "invented family schedule",
        "If children are identified, keep only their supplied names, relationships, ages and "
        "status particulars; never populate the sample family",
        "Separate numbered alleged acts with supplied dates and source references",
        "Keep requested protection, residence, monetary and compensation measures distinct, "
        "including only the relief actually sought",
        "Itemise supplied monetary needs without importing the example's amounts or assuming "
        "property ownership",
        "Prayer, place/date, signatures, verification ranges and required supporting affidavit "
        "placeholders",
    ),
    "government_suit_notice": _NOTICE,
    "legal_notice_reply": (
        "Actual sender/counsel, date, service particulars and addressee",
        "Subject identifying the original notice and its actual supplied date/reference",
        "Preliminary response and objections actually instructed by the client",
        "Paragraph-wise reply matching the original notice, distinguishing admissions, denials, "
        "explanations and missing instructions",
        "Actual requested response or action, followed by closing and signature placeholder",
        "No court caption, court prayer or pleading verification unless separately required by "
        "the actual document",
    ),
}


def _format(
    key: str, family: str, pages: tuple[int, ...], *, direct: bool = True,
) -> DraftingFormat:
    sections = {"pleading": _PLEADING, "application": _APPLICATION,
                "notice": _NOTICE, "affidavit": _AFFIDAVIT, "reply": _REPLY,
                "correspondence_reply": _REPLY}[family]
    return DraftingFormat(key, family, sections, pages, direct)


# Each registered guided type has an explicit decision. Related structures are
# marked as adaptations rather than falsely attributed to an absent book form.
FORMATS: dict[str, DraftingFormat] = {
    "conveyancing_deed": DraftingFormat("conveyancing_deed", "deed", (
        "Selected instrument title", "Execution place and date placeholders",
        "Parties, capacities and defined instrument-specific roles",
        "Recitals of supplied title, background and transaction facts",
        "Numbered operative terms for this instrument only",
        "Consideration and its actual payment status where applicable",
        "Supplied property, asset or settlement schedules and boundaries where relevant",
        "Party execution and applicable witness or attestation placeholders",
    ), tuple(range(79, 93))),
    "bail": _format("bail", "application", (63, 64)),
    "anticipatory_bail": _format("anticipatory_bail", "application", (65, 66)),
    "divorce_petition": _format("divorce_petition", "pleading", (35, 36, 37)),
    "property_dispute_notice": _format("property_dispute_notice", "notice", (93,)),
    "cheque_bounce_notice": _format("cheque_bounce_notice", "notice", (96, 97)),
    "affidavit": _format("affidavit", "affidavit", (4, 40)),
    "criminal_complaint": _format("criminal_complaint", "pleading", (67, 68, 76, 77, 78)),
    "civil_suit": _format("civil_suit", "pleading", (1, 2, 3, 5, 6, 7, 13, 14, 15, 16, 17)),
    "appeal_memorandum": _format("appeal_memorandum", "pleading", (55, 56, 57, 58), direct=False),
    "writ_petition": _format("writ_petition", "pleading", (49, 50, 51, 52, 53, 54)),
    "quashing_petition": _format("quashing_petition", "pleading", (51, 52, 53, 54), direct=False),
    "written_statement": _format("written_statement", "reply", (18, 19, 20)),
    "reply_counter_affidavit": _format(
        "reply_counter_affidavit", "reply", (18, 19, 20, 40, 98, 99), direct=False,
    ),
    "dv_quashing_petition": _format(
        "dv_quashing_petition", "pleading", (51, 52, 76, 77, 78), direct=False,
    ),
    "arbitration_section_9": _format("arbitration_section_9", "application", (8, 9), direct=False),
    "caveat_petition": _format("caveat_petition", "application", (21,)),
    "vakalatnama": DraftingFormat("vakalatnama", "authorization", (
        "Proceeding particulars and appointing party", "Express scope of the advocate appointment",
        "Party signature, advocate acceptance and required execution particulars as placeholders",
    ), (), False),
    "amendment_of_pleadings": _format(
        "amendment_of_pleadings", "application", (8, 9), direct=False,
    ),
    "compromise_petition": _format("compromise_petition", "application", (8, 9), direct=False),
    "probate_petition": _format("probate_petition", "pleading", (41, 42, 43)),
    "special_leave_petition": _format("special_leave_petition", "pleading", tuple(range(55, 63))),
    "supreme_court_appeal": _format("supreme_court_appeal", "pleading", (55, 59), direct=False),
    "review_petition": _format("review_petition", "application", (8, 9), direct=False),
    "curative_petition": _format("curative_petition", "pleading", (55, 59), direct=False),
    "transfer_petition": _format("transfer_petition", "pleading", tuple(range(22, 27))),
    "contempt_petition": _format("contempt_petition", "pleading", (74, 75)),
    "interim_relief_application": _format("interim_relief_application", "application", (8, 9)),
    "condonation_of_delay": _format("condonation_of_delay", "application", (8, 9), direct=False),
    "exemption_application": _format("exemption_application", "application", (8, 9), direct=False),
    "synopsis_list_of_dates": DraftingFormat("synopsis_list_of_dates", "chronology", (
        "Proceeding particulars", "Concise synopsis",
        "Chronological date and event entries with supplied source references",
        "Place, date and advocate signature placeholders where applicable",
    ), (55, 59), False),
    "filing_index_checklist": DraftingFormat("filing_index_checklist", "index", (
        "Proceeding particulars",
        "Index with serial number, document description, date and confirmed page range",
        "Separate filing checklist with missing items honestly identified",
        "Signature and date placeholders where applicable",
    ), (), False),
}

for _reference_key, _reference_template in REFERENCE_TEMPLATES.items():
    FORMATS[_reference_key] = DraftingFormat(
        _reference_key, _reference_template.family, REFERENCE_SECTIONS[_reference_key],
        _reference_template.pdf_pages,
    )


def format_manifest(
    template_type: str | None, *, registry: bool = False, facts: object = None,
) -> dict[str, object]:
    """Capture the presentation decision on a new immutable draft version."""
    profile = FORMATS.get(template_type or "")
    captured: dict[str, object] = {
        "schema": "caseops.presentation-reference.v1",
        "version": FORMAT_VERSION,
        "source_filename": SOURCE_LABEL,
        "source_sha256": SOURCE_SHA256,
        "profile": "registry-adaptation" if registry else profile.key if profile else "generic",
        "family": "registry" if registry else profile.family if profile else "generic",
        "pdf_pages": [] if registry or profile is None else list(profile.pdf_pages),
        "direct_example": False if registry or profile is None else profile.direct_example,
        "legal_rules_verified": False,
    }
    if not registry and template_type == "conveyancing_deed":
        instrument = selected_conveyancing_instrument(facts)
        if instrument is None:
            raise ValueError("Choose one of the six supported deed formats.")
        captured["instrument_type"] = instrument
        captured["pdf_pages"] = list(CONVEYANCING_PAGES[instrument])
    elif not registry and template_type in DOCUMENT_VARIANTS:
        variant = selected_document_variant(template_type, facts)
        if variant is None:
            captured["direct_example"] = False
        else:
            field, selection, pages = variant
            captured[field] = selection
            captured["pdf_pages"] = list(pages)
            if selection in {"General civil plaint", "General property dispute"}:
                captured["direct_example"] = False
    return captured


def format_instructions(template_type: str | None, *, registry: bool = False) -> str:
    """Trusted presentation instructions; never insert book example facts."""
    profile = FORMATS.get(template_type or "")
    lines = [
        "=== DOCUMENT PRESENTATION REFERENCE ===",
        f"Format reference: {FORMAT_VERSION}. This reference supplies structure only, "
        + "not legal authority or facts.",
        "Preserve the selected document's specific statutory form, required declarations and "
        + "current court or registry rules; they take precedence over these presentation "
        + "conventions.",
        "Preserve explicit authorized workspace-template requirements; use this reference to fill "
        + "presentation gaps rather than overwrite them.",
        "Use only the actual proceeding, court or registry, parties and facts supplied in the "
        + "authorized context. Never adopt a sample venue, year, amount, interest rate, identity "
        + "or allegation from a model form.",
        "Use clear headings, short numbered paragraphs and consistent party designations. Keep "
        + "material facts, legal grounds and requested relief distinct where appropriate.",
        "Write document headings as plain text, without Markdown heading markers, emphasis "
        + "markup or HTML layout code. The saved body is the actual document text, not a "
        + "formatting program.",
        "Missing particulars require explicit square-bracket placeholders. Do not assert a "
        + "completed signature, oath, service, registration or attestation without evidence.",
        "Where verification is required, distinguish personal knowledge from information and "
        + "identify the correct paragraph ranges when available; leave unknown ranges as "
        + "placeholders.",
        "Preserve actual annexure identifiers and their supplied descriptions. Do not fabricate "
        + "annexures, page numbers, source references or witness details.",
        "Keep product labels, revision/status metadata and instructional notes out of the legal "
        + "document body.",
        "For a partial preview, render only the requested step or supplied portion in its proper "
        + "position; do not invent the remaining document.",
    ]
    if registry:
        lines.append(
            "This is a registry document: retain its governed template heading, form, proceeding "
            "identifiers, verification and evidence structure. Do not substitute a generic court "
            "caption or civil-suit format."
        )
    elif profile:
        relationship = (
            "direct worked-example family" if profile.direct_example
            else "adapted presentation; no exact worked example is claimed"
        )
        pages = ", ".join(map(str, profile.pdf_pages)) or "no direct example"
        lines.extend((
            f"Selected format: {profile.key}; {relationship}; PDF pages: {pages}.",
            "Expected sections, subject to the selected document's specific required order:",
        ))
        lines.extend(f"{index}. {section}" for index, section in enumerate(profile.sections, 1))
        if profile.family == "deed":
            lines.append(
                "Do not add a court-style prayer or pleading verification to a deed. Preserve its "
                "required execution and attestation fields without asserting they have been "
                "completed."
            )
        elif profile.family in {
            "notice", "correspondence_reply", "authorization", "chronology", "index",
        }:
            lines.append(
                "Include a court-style prayer or verification only if the actual document requires "
                "it; do not add them solely because this is a legal document."
            )
    else:
        lines.append(
            "Follow the document type actually requested: court pleadings use the relevant caption "
            "and relief structure; correspondence uses sender/addressee/subject/closing; deeds use "
            "parties, recitals, operative terms, schedules and execution. "
            "Never turn one family into another."
        )
    return "\n".join(lines)


def read_format_reference(template_manifest: object) -> dict[str, object] | None:
    """Read a supported frozen reference; never relabel an unknown revision."""
    if not isinstance(template_manifest, dict) or "presentation_reference" not in template_manifest:
        return None
    reference = template_manifest["presentation_reference"]
    if not isinstance(reference, dict) or not isinstance(reference.get("profile"), str):
        raise ValueError("The saved document format reference is unavailable.")
    profile = reference["profile"]
    registry = profile == "registry-adaptation"
    expected = format_manifest(
        None if registry or profile == "generic" else profile,
        registry=registry,
        facts={
            key: reference[key] for key in (
                "instrument_type", "suit_format", "slp_kind", "writ_kind", "notice_format",
            )
            if key in reference
        },
    )
    # Canonical JSON distinguishes booleans from numeric lookalikes and rejects
    # missing/extra claims without accepting a different source or version.
    try:
        equal = (
            json.dumps(reference, sort_keys=True, allow_nan=False)
            == json.dumps(expected, sort_keys=True)
        )
    except (TypeError, ValueError):
        equal = False
    if not equal:
        raise ValueError("The saved document format reference is unavailable.")
    return expected


@dataclass(frozen=True)
class DocumentLine:
    text: str
    alignment: str = "L"
    bold: bool = False
    keep_with_next: bool = False


_SECTION_HEADINGS = frozenset({
    "PRAYER", "PRAYER FOR INTERIM RELIEF", "VERIFICATION", "FACTS", "BRIEF FACTS",
    "GROUNDS", "PRELIMINARY OBJECTIONS", "REPLY ON MERITS", "RECITALS",
    "OPERATIVE TERMS", "EXECUTION", "WITNESSES", "SCHEDULE", "SCHEDULE OF PROPERTY",
    "LIST OF DATES", "SYNOPSIS", "ANNEXURE INDEX", "INDEX", "WHEREAS",
    "NOW THIS DEED WITNESSETH", "IN THE MATTER OF",
    "PARTICULARS OF EXECUTION", "EXECUTION PARTICULARS", "DEBTS AND SECURITIES",
    "PARAGRAPH-WISE REPLY", "PARA-WISE REPLY", "ESTATE SCHEDULE", "SCHEDULE I",
})
_CENTER_HEADINGS = frozenset({
    "VERSUS", "BETWEEN", "AND", "BY", "IN FAVOUR OF",
    "SALE DEED", "MORTGAGE DEED", "PARTNERSHIP DEED",
    "DISSOLUTION OF PARTNERSHIP", "DEED OF DISSOLUTION OF PARTNERSHIP", "DEED OF DISSOLUTION",
    "RELINQUISHMENT DEED", "GIFT DEED", "AFFIDAVIT", "VAKALATNAMA",
    "WRITTEN STATEMENT", "REVIEW PETITION", "CURATIVE PETITION", "CONTEMPT PETITION",
})
_CAPTION_PREFIXES = (
    "IN THE COURT ", "IN THE HIGH COURT ", "IN THE SUPREME COURT ", "BEFORE THE ",
    "SUIT FOR ", "PETITION FOR ", "APPLICATION FOR ", "APPLICATION UNDER ",
    "COMPLAINT UNDER ", "SPECIAL LEAVE PETITION ", "WRITTEN STATEMENT",
    "NOTICE UNDER ", "REPLY TO LEGAL NOTICE",
    "JOINT PETITION FOR ", "EXECUTION APPLICATION", "APPLICATION TO ",
    "CAVEAT ", "WRIT PETITION ", "MEMORANDUM OF APPEAL",
)
_SIGNATURE_LABELS = frozenset({
    "PLAINTIFF", "DEFENDANT", "PETITIONER", "RESPONDENT", "APPLICANT", "ACCUSED",
    "COMPLAINANT", "DEPONENT", "ADVOCATE", "DONOR", "DONEE", "VENDOR", "VENDEE",
    "MORTGAGOR", "MORTGAGEE", "RELEASOR", "RELEASEE",
    "DECREE HOLDER", "DECREE-HOLDER", "JUDGMENT DEBTOR", "CAVEATOR", "COUNSEL",
    "PETITIONERS", "JOINT PETITIONER", "JOINT PETITIONERS", "PARTNER", "PARTNERS",
})


def document_lines(body: str) -> Iterator[DocumentLine]:
    """Style existing text without rewriting facts, numbers, citations or names.

    No Markdown/HTML interpretation and no generated content. Original hard
    line breaks, blank lines and indentation remain represented in the result.
    """
    for text in body.split("\n"):
        normalized = text.strip().rstrip(":").upper()
        if not normalized:
            yield DocumentLine(text)
        elif normalized in _CENTER_HEADINGS or (
            len(normalized) <= 240 and normalized.startswith(_CAPTION_PREFIXES)
        ):
            yield DocumentLine(text, "C", True, True)
        elif normalized in _SECTION_HEADINGS:
            yield DocumentLine(text, "L", True, True)
        elif normalized in _SIGNATURE_LABELS:
            yield DocumentLine(text, "R")
        else:
            yield DocumentLine(text)
