"""Sprint R9 — per-template-type auto-suggest snippets.

When the stepper asks the user to fill the 'sections charged' field
for a bail application, we shouldn't make them remember the standard
BNS sections. Same for the 'relief' field on a civil suit, the
'dishonour reason' on a cheque-bounce notice, and the 'grounds'
block on a divorce petition.

Suggestions are a read-only catalogue — not opinions, not legal
advice. They're the same seed a paralegal would pull from a firm's
internal playbook.

Organised by (template_type, field_name, list of short strings). The
UI uses them as datalist options / quick-insert chips.
"""
from __future__ import annotations

from dataclasses import dataclass

from caseops_api.schemas.drafting_templates import DraftTemplateType


@dataclass(frozen=True)
class FieldSuggestions:
    field_name: str
    label: str
    options: list[str]


@dataclass(frozen=True)
class TemplateSuggestions:
    template_type: str
    fields: list[FieldSuggestions]


# ---------------------------------------------------------------
# Per-type suggestion maps. Keep each list tight — these are common
# first-picks, not a full catalogue.
# ---------------------------------------------------------------


_BAIL_SUGGESTIONS: list[FieldSuggestions] = [
    FieldSuggestions(
        field_name="sections_charged",
        label="Common BNS sections",
        options=[
            "BNS s.103 (murder)",
            "BNS s.109 (attempt to murder)",
            "BNS s.115 (voluntarily causing hurt)",
            "BNS s.318 (cheating)",
            "BNS s.335 (forgery of valuable security)",
            "BNS s.303 (theft)",
            "BNS s.64 (rape)",
            "NDPS Act s.20 (narcotic drugs — cannabis)",
            "NDPS Act s.22 (psychotropic substances)",
            "PMLA s.3 (money laundering)",
            "UAPA s.15 (terrorist act)",
        ],
    ),
    FieldSuggestions(
        field_name="grounds_brief",
        label="Standard bail grounds",
        options=[
            "Accused is not a flight risk — permanent residence + family ties.",
            "No allegation of tampering with evidence — investigation complete.",
            "No allegation of influencing witnesses — prosecution witnesses already examined.",
            "Parity with co-accused who has been granted bail.",
            "Prolonged custody without trial commencing.",
            "Triple test (Satender Kumar Antil line) satisfied.",
        ],
    ),
]


_ANTICIPATORY_BAIL_SUGGESTIONS: list[FieldSuggestions] = [
    FieldSuggestions(
        field_name="apprehended_sections",
        label="Common BNS sections for anticipatory bail",
        options=[
            "BNS s.318 (cheating)",
            "BNS s.316 (criminal breach of trust)",
            "BNS s.337 (forgery)",
            "BNS s.299 (fraud on revenue)",
            "IPC s.498A (historical — pre-2024 incidents only)",
            "NI Act s.138 (cheque dishonour — non-cognisable)",
        ],
    ),
    FieldSuggestions(
        field_name="apprehension_grounds",
        label="Apprehension framings",
        options=[
            "Applicant has been issued a s.41A BNSS notice.",
            "Police have called the applicant for questioning repeatedly.",
            "Complainant's allegations are mala fide / arise from commercial dispute.",
            "Applicant is willing to cooperate and produce documents.",
        ],
    ),
]


_CHEQUE_BOUNCE_SUGGESTIONS: list[FieldSuggestions] = [
    FieldSuggestions(
        field_name="dishonour_reason",
        label="Standard bank-memo dishonour reasons",
        options=[
            "Insufficient funds",
            "Exceeds arrangement",
            "Payment stopped by drawer",
            "Account closed",
            "Refer to drawer",
            "Signature mismatch",
        ],
    ),
    FieldSuggestions(
        field_name="boilerplate",
        label="Standard s.138 paragraph blocks",
        options=[
            "Demand notice under s.138 of the Negotiable Instruments Act, 1881.",
            "Statutory fifteen (15) days from the date of receipt of this notice.",
            "Failing which, the undersigned will be constrained to prosecute under s.138 NI Act.",
            "Amount in figures ₹______ and in words: Rupees ______ only.",
        ],
    ),
]


_DIVORCE_SUGGESTIONS: list[FieldSuggestions] = [
    FieldSuggestions(
        field_name="grounds",
        label="HMA s.13 / SMA s.27 grounds",
        options=[
            "Cruelty",
            "Desertion for 2+ years",
            "Adultery",
            "Conversion to another religion",
            "Unsoundness of mind",
            "Communicable disease",
            "Renunciation of the world",
            "Presumption of death",
            "Non-consummation",
            "Irretrievable breakdown (judicial doctrine)",
        ],
    ),
]


_PROPERTY_NOTICE_SUGGESTIONS: list[FieldSuggestions] = [
    FieldSuggestions(
        field_name="relief_sought",
        label="Typical reliefs demanded",
        options=[
            "Vacate and hand over peaceful possession of the property.",
            "Pay arrears of rent / mesne profits with interest.",
            "Cease and desist from further encroachment.",
            "Remove unauthorised construction within the deadline.",
            "Restore the sender's right of way / easement.",
        ],
    ),
]


_AFFIDAVIT_SUGGESTIONS: list[FieldSuggestions] = [
    FieldSuggestions(
        field_name="verification_block",
        label="Verification clauses",
        options=[
            "Paragraphs 1 to N are true to my personal knowledge.",
            "Paragraph M is on information received from the records of the matter, believed to be true.",
            "Paragraphs X to Y are based on legal advice received which I believe to be correct.",
        ],
    ),
]


_CRIMINAL_COMPLAINT_SUGGESTIONS: list[FieldSuggestions] = [
    FieldSuggestions(
        field_name="alleged_sections",
        label="Common BNS sections for private complaints",
        options=[
            "BNS s.318 (cheating)",
            "BNS s.316 (criminal breach of trust)",
            "BNS s.337 (forgery)",
            "BNS s.85 (cruelty — replaces IPC 498A)",
            "BNS s.74 (assault on woman with intent to outrage modesty)",
            "BNS s.351 (criminal intimidation)",
        ],
    ),
]


_CIVIL_SUIT_SUGGESTIONS: list[FieldSuggestions] = [
    FieldSuggestions(
        field_name="relief_sought",
        label="Common civil reliefs",
        options=[
            "Decree for recovery of the suit amount with interest.",
            "Decree for specific performance of the agreement.",
            "Declaration of the plaintiff's title to the suit property.",
            "Permanent injunction restraining the defendant.",
            "Mandatory injunction to remove the obstruction.",
            "Costs of the suit.",
        ],
    ),
]


_REGISTRY: dict[DraftTemplateType, list[FieldSuggestions]] = {
    DraftTemplateType.BAIL: _BAIL_SUGGESTIONS,
    DraftTemplateType.ANTICIPATORY_BAIL: _ANTICIPATORY_BAIL_SUGGESTIONS,
    DraftTemplateType.CHEQUE_BOUNCE_NOTICE: _CHEQUE_BOUNCE_SUGGESTIONS,
    DraftTemplateType.DIVORCE_PETITION: _DIVORCE_SUGGESTIONS,
    DraftTemplateType.PROPERTY_DISPUTE_NOTICE: _PROPERTY_NOTICE_SUGGESTIONS,
    DraftTemplateType.AFFIDAVIT: _AFFIDAVIT_SUGGESTIONS,
    DraftTemplateType.CRIMINAL_COMPLAINT: _CRIMINAL_COMPLAINT_SUGGESTIONS,
    DraftTemplateType.CIVIL_SUIT: _CIVIL_SUIT_SUGGESTIONS,
}


def get_template_suggestions(
    template_type: DraftTemplateType,
) -> TemplateSuggestions:
    """Return the curated suggestion set for ``template_type``.

    An unmapped type returns an empty ``fields`` list rather than
    raising, so the stepper can call this unconditionally and hide
    the auto-suggest UI when there's nothing to surface.
    """
    fields = _REGISTRY.get(template_type, [])
    return TemplateSuggestions(
        template_type=template_type.value,
        fields=list(fields),
    )


__all__ = [
    "FieldSuggestions",
    "TemplateSuggestions",
    "get_template_suggestions",
]
