"""PG-005 Sprint 8 (2026-05-01) — pre-filing checklist per court.

What a fee-earner walks to the court counter with: copies of the
petition, vakalatnama, court fee, index, annexures, verification
affidavit, etc. The exact set varies by court rules + template type.

This module builds the checklist programmatically from
``(court_profile, template_type)`` so the UI can render a tickbox
list before the lawyer prints the bundle. Items the system can verify
itself (e.g., the matter already has a vakalat draft, or has N
attachments) are marked ``auto_satisfied`` so the lawyer's eye lands
on the gaps.

The checklist is descriptive — it does not block downloads or
filings. The lawyer is the final reviewer; we surface the
requirements + auto-tick what we can.

Data sources:

- Supreme Court Rules 2013, Order IV / Order XX.
- Delhi High Court (Original Side) Rules 2018 + Practice Directions.
- Bombay High Court (Original Side) Rules 1980, Rule 50.
- Madras / Calcutta / Karnataka HC Original-Side Rules.
- NCLT Rules 2016, NCLAT Rules 2016, DRT (Procedure) Rules 1993.
- CPC Order IV / VII / VIII (procedural defaults across civil
  filings).
- BNSS s.223 / s.480 / s.482 / s.483 / s.528 (procedural defaults
  for criminal-side filings).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Draft, MatterAttachment
from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.court_format_profiles import (
    CourtFormatProfile,
    CourtRequiredFieldFinding,
    resolve_profile,
    validate_required_fields,
)

ChecklistCategory = Literal["document", "fee", "procedure", "service"]


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    label: str
    description: str
    category: ChecklistCategory
    required: bool = True
    auto_satisfied: bool = False
    auto_satisfied_reason: str | None = None


@dataclass(frozen=True)
class FilingChecklist:
    matter_id: str
    draft_id: str
    template_type: str
    court_profile_key: str
    court_display_name: str
    items: list[ChecklistItem] = field(default_factory=list)
    court_fee_note: str = ""
    limitation_note: str | None = None
    copies_required: int = 1
    required_field_findings: list[CourtRequiredFieldFinding] = field(default_factory=list)
    missing_required_field_count: int = 0


# Base items every contested-matter filing needs. Court / template
# overrides extend this list.
_BASE_CONTESTED_ITEMS: list[ChecklistItem] = [
    ChecklistItem(
        id="memorandum",
        label="Main pleading / petition",
        description=(
            "Cause-titled, numbered paragraphs, signed by counsel. "
            "Use the court-format-aware PDF export."
        ),
        category="document",
    ),
    ChecklistItem(
        id="vakalatnama",
        label="Vakalatnama (executed by client + accepted by counsel)",
        description=(
            "Power-of-attorney authorising counsel to appear. The "
            "filing-bundle exporter generates a placeholder when no "
            "executed vakalat draft is present on the matter."
        ),
        category="document",
    ),
    ChecklistItem(
        id="index",
        label="Index of contents",
        description=(
            "Paginated index listing every document in the bundle "
            "with page references."
        ),
        category="document",
    ),
    ChecklistItem(
        id="court_fee",
        label="Court fee (e-stamp / treasury challan)",
        description=(
            "Affix the court-fee e-stamp or attach the treasury "
            "challan. Amount depends on the State Court-Fees Act + "
            "the relief sought."
        ),
        category="fee",
    ),
    ChecklistItem(
        id="proof_of_service",
        label="Proof of service on opposite party (if applicable)",
        description=(
            "Pre-filing service is required for some petition types "
            "(e.g., partition suits with multiple defendants). Verify "
            "against the local court rules."
        ),
        category="service",
        required=False,
    ),
]


# ---------------------------------------------------------------
# Court-specific overrides.
# ---------------------------------------------------------------


def _court_overrides(profile: CourtFormatProfile) -> list[ChecklistItem]:
    """Return court-specific checklist items that augment the base set
    for the resolved profile."""
    if profile.key == "supreme_court":
        return [
            ChecklistItem(
                id="synopsis_and_dates",
                label="Synopsis + List of dates",
                description=(
                    "Mandatory for SC petitions / SLPs (Order IV "
                    "Rule 1). Synopsis half a page; list of dates "
                    "chronological with page refs."
                ),
                category="document",
            ),
            ChecklistItem(
                id="caveat_search_certificate",
                label="Caveat search certificate",
                description=(
                    "Search the SC caveat register before filing; "
                    "attach the certificate if no caveat exists."
                ),
                category="procedure",
            ),
            ChecklistItem(
                id="memorandum_of_appearance",
                label="Memorandum of appearance for advocate-on-record",
                description=(
                    "Required even when senior counsel is also "
                    "appearing — only the AOR can sign filings."
                ),
                category="document",
            ),
        ]
    if profile.category == "high_court":
        return [
            ChecklistItem(
                id="synopsis_and_dates",
                label="Synopsis + List of dates",
                description=(
                    "HC original-side practice expects a half-page "
                    "synopsis + chronological list of dates."
                ),
                category="document",
            ),
            ChecklistItem(
                id="affidavit_verification",
                label="Affidavit verifying the petition",
                description=(
                    "Sworn before a notary / oath commissioner. "
                    "Required for writ + interlocutory applications."
                ),
                category="document",
            ),
        ]
    if profile.key in {"nclt", "nclat"}:
        return [
            ChecklistItem(
                id="statutory_form",
                label="Prescribed statutory form (NCLT-1 / NCLT-2 etc.)",
                description=(
                    "NCLT Rules 2016 / NCLAT Rules 2016 prescribe "
                    "specific forms by petition type. Match the form "
                    "to the relief sought."
                ),
                category="document",
            ),
            ChecklistItem(
                id="board_resolution",
                label="Board resolution authorising the filing",
                description=(
                    "When the petitioner is a company, attach the "
                    "board resolution authorising the named officer "
                    "to swear the petition."
                ),
                category="document",
            ),
        ]
    if profile.category == "district_court":
        return [
            ChecklistItem(
                id="court_format_required_fields",
                label="Court-format required fields reviewed",
                description=(
                    "Confirm court/forum name, parties, and any template-specific "
                    "criminal fields before filing."
                ),
                category="procedure",
            ),
            ChecklistItem(
                id="process_fee",
                label="Process fee / summons batta",
                description=(
                    "District Court filings often require process fee or summons "
                    "batta; verify the local filing counter requirement."
                ),
                category="fee",
                required=False,
            ),
        ]
    if profile.key == "drt":
        return [
            ChecklistItem(
                id="oa_form",
                label="Original Application in the prescribed DRT form",
                description=(
                    "DRT (Procedure) Rules 1993 prescribe the OA "
                    "form for recovery applications."
                ),
                category="document",
            ),
            ChecklistItem(
                id="schedule_of_debt",
                label="Schedule of debt with interest computation",
                description=(
                    "Itemised schedule showing principal, interest, "
                    "and aggregate as on the date of filing."
                ),
                category="document",
            ),
        ]
    if profile.key == "tribunal":
        return [
            ChecklistItem(
                id="prescribed_tribunal_form",
                label="Prescribed tribunal form",
                description=(
                    "Tribunal filings often use a prescribed form. Match the "
                    "form to the tribunal and relief sought."
                ),
                category="document",
            ),
            ChecklistItem(
                id="authorisation_document",
                label="Authorisation document",
                description=(
                    "Attach board resolution, authority letter, or vakalat as "
                    "applicable for the filing party."
                ),
                category="document",
                required=False,
            ),
        ]
    return []


# ---------------------------------------------------------------
# Template-specific overrides.
# ---------------------------------------------------------------


def _template_overrides(template_type: str) -> list[ChecklistItem]:
    """Return template-specific checklist items."""
    if template_type in (
        DraftTemplateType.BAIL.value,
        DraftTemplateType.ANTICIPATORY_BAIL.value,
    ):
        return [
            ChecklistItem(
                id="custody_certificate",
                label="Custody certificate (regular bail) OR FIR copy (anticipatory)",
                description=(
                    "Regular bail: jail authority's custody certificate. "
                    "Anticipatory: certified FIR copy + section list."
                ),
                category="document",
            ),
            ChecklistItem(
                id="surety_documents",
                label="Surety affidavit + ID proof (if surety bail)",
                description=(
                    "When the bail order requires surety, the surety's "
                    "affidavit + photo ID + financial-capacity proof "
                    "must be ready at the bail-hearing date."
                ),
                category="document",
                required=False,
            ),
        ]
    if template_type == DraftTemplateType.QUASHING_PETITION.value:
        return [
            ChecklistItem(
                id="impugned_fir_copy",
                label="Certified copy of the FIR / chargesheet",
                description=(
                    "Quashing petition cannot proceed without a "
                    "certified copy of the impugned proceedings."
                ),
                category="document",
            ),
            ChecklistItem(
                id="settlement_deed",
                label="Settlement deed (if compromise-based quashing)",
                description=(
                    "Required when relying on Gian Singh — annex the "
                    "executed settlement + the aggrieved party's "
                    "signed consent."
                ),
                category="document",
                required=False,
            ),
        ]
    if template_type == DraftTemplateType.WRIT_PETITION.value:
        return [
            ChecklistItem(
                id="impugned_order_copy",
                label="Certified copy of the impugned order / notification",
                description=(
                    "The writ petition must annex the impugned act / "
                    "order / inaction record. Without it, the court "
                    "may decline to entertain at the threshold."
                ),
                category="document",
            ),
        ]
    if template_type == DraftTemplateType.CHEQUE_BOUNCE_NOTICE.value:
        return [
            ChecklistItem(
                id="bank_memo",
                label="Original bank dishonour memo",
                description=(
                    "Mandatory for the s.138 NI Act notice + the "
                    "subsequent complaint."
                ),
                category="document",
            ),
            ChecklistItem(
                id="dispatch_proof",
                label="Proof of dispatch (RPAD receipt + tracking)",
                description=(
                    "RPAD acknowledgment is the standard trigger for "
                    "the 15-day notice period."
                ),
                category="service",
            ),
        ]
    if template_type == DraftTemplateType.CIVIL_SUIT.value:
        return [
            ChecklistItem(
                id="schedule_of_property",
                label="Schedule of suit property / valuation",
                description=(
                    "Required for property + commercial suits. "
                    "Pecuniary jurisdiction + court fee depend on "
                    "this schedule."
                ),
                category="document",
                required=False,
            ),
            ChecklistItem(
                id="cause_of_action_chronology",
                label="Cause-of-action chronology",
                description=(
                    "CPC Order VII Rule 1 — the plaint must aver the "
                    "place + date the cause of action arose."
                ),
                category="document",
            ),
        ]
    if template_type == DraftTemplateType.WRITTEN_STATEMENT.value:
        return [
            ChecklistItem(
                id="documents_relied_index",
                label="Order VIII Rule 1A — index of documents relied on",
                description=(
                    "Defendant must list every document relied on. "
                    "Failure to list at WS stage forfeits the right "
                    "to rely later (subject to court permission)."
                ),
                category="document",
            ),
        ]
    if template_type == DraftTemplateType.PROBATE_PETITION.value:
        return [
            ChecklistItem(
                id="will_original",
                label="Original will (or photocopy with verification)",
                description=(
                    "Probate cannot be granted without the will. "
                    "If only a photocopy exists, plead the loss + "
                    "annex an affidavit explaining the loss."
                ),
                category="document",
            ),
            ChecklistItem(
                id="death_certificate",
                label="Death certificate of the testator",
                description=(
                    "Required to establish the testator's death + "
                    "the date thereof."
                ),
                category="document",
            ),
            ChecklistItem(
                id="heir_citations",
                label="Citations to legal heirs (s.283)",
                description=(
                    "Notice to all legal heirs is mandatory. The "
                    "petition must list each heir with current "
                    "address."
                ),
                category="procedure",
            ),
        ]
    if template_type == DraftTemplateType.VAKALATNAMA.value:
        # Vakalat is itself a checklist item on every other filing,
        # so when the user is generating a vakalat in isolation, the
        # checklist is just the court-fee stamp.
        return [
            ChecklistItem(
                id="court_fee_stamp",
                label="Court-fee stamp on the vakalatnama",
                description=(
                    "Fixed-value court-fee stamp is required on the "
                    "vakalat in most courts; check the local rules."
                ),
                category="fee",
            ),
        ]
    return []


# ---------------------------------------------------------------
# Court-fee + limitation + copies guidance.
# ---------------------------------------------------------------


def _copies_required(profile_key: str) -> int:
    return {
        "supreme_court": 6,  # 1 + 5
        "high_court": 3,
        "delhi_hc": 3,
        "bombay_hc": 3,
        "madras_hc": 3,
        "calcutta_hc": 3,
        "karnataka_hc": 3,
        "district_court": 2,
        "tribunal": 5,
        "nclt": 5,
        "nclat": 5,
        "drt": 3,
    }.get(profile_key, 2)


def _court_fee_note(profile_key: str, template_type: str) -> str:
    if template_type in (
        DraftTemplateType.BAIL.value,
        DraftTemplateType.ANTICIPATORY_BAIL.value,
    ):
        return (
            "Bail applications attract a fixed court fee under the "
            "applicable State Court-Fees Act schedule (typically a "
            "single-digit-rupee stamp)."
        )
    if template_type == DraftTemplateType.WRIT_PETITION.value:
        return (
            "Writ petition court fee is a fixed amount per the State "
            "Court-Fees Act (typically INR 50-100 in HCs; SC writ "
            "petitions follow the SC court-fee schedule)."
        )
    if template_type == DraftTemplateType.CIVIL_SUIT.value:
        return (
            "Civil suit court fee is computed ad valorem on the suit "
            "valuation. Refer to Schedule II of the State Court-Fees "
            "Act + the Suits Valuation Act, 1887."
        )
    if template_type == DraftTemplateType.PROBATE_PETITION.value:
        return (
            "Probate court fee is computed on the aggregate estate "
            "value (Schedule III of most State Court-Fees Acts)."
        )
    if profile_key in {"tribunal", "nclt", "nclat"}:
        return (
            "NCLT / NCLAT fees are fixed per petition type per the "
            "Schedule of Fees Rules. Confirm the current schedule "
            "before filing."
        )
    if profile_key == "drt":
        return (
            "DRT application fee is computed on the debt amount per "
            "the DRT (Procedure) Rules 1993 + the relevant State "
            "Court-Fees Act."
        )
    if profile_key == "district_court":
        return (
            "District Court fee depends on the State Court-Fees Act, relief, "
            "valuation, and process fee schedule. Verify locally before filing."
        )
    return (
        "Court fee depends on the State Court-Fees Act schedule + the "
        "relief sought. Verify the fee at the filing counter before "
        "affixing the stamp."
    )


def _limitation_note(template_type: str) -> str | None:
    """Return a limitation reminder when the template has a hard
    statutory clock the lawyer must respect."""
    if template_type == DraftTemplateType.WRITTEN_STATEMENT.value:
        return (
            "Order VIII Rule 1 sets a 30-day default with a 90-day "
            "cap. Commercial Courts Act suits have a 120-day cap. "
            "If the cap has expired, plead delay condonation in the "
            "WS — do not conceal it."
        )
    if template_type == DraftTemplateType.APPEAL_MEMORANDUM.value:
        return (
            "Appeal limitation varies: 30 days (s.96 CPC + Order "
            "XLI), 90 days (Letters Patent), 60 days (s.374 BNSS / "
            "s.374 CrPC criminal). If filed late, attach a delay-"
            "condonation application."
        )
    if template_type == DraftTemplateType.CHEQUE_BOUNCE_NOTICE.value:
        return (
            "NI Act s.138: notice within 30 days of bank memo; "
            "complaint within 1 month of expiry of the 15-day notice "
            "period."
        )
    if template_type in (
        DraftTemplateType.WRIT_PETITION.value,
        DraftTemplateType.QUASHING_PETITION.value,
        DraftTemplateType.DV_QUASHING_PETITION.value,
    ):
        return (
            "Writs + s.528 quashing have NO fixed limitation but are "
            "subject to laches. Late petitions need a delay "
            "explanation in the body."
        )
    if template_type == DraftTemplateType.AMENDMENT_OF_PLEADINGS.value:
        return (
            "Order VI Rule 17 proviso: post-trial amendments require "
            "a due-diligence showing — flag if trial has commenced."
        )
    return None


# ---------------------------------------------------------------
# Auto-satisfaction over the matter's current state.
# ---------------------------------------------------------------


def _auto_satisfy(
    item: ChecklistItem,
    *,
    has_vakalat_draft: bool,
    attachment_count: int,
) -> ChecklistItem:
    """Decide whether the matter's current state already satisfies an
    item. Returns the item with auto_satisfied + reason set when so."""
    if item.id == "vakalatnama" and has_vakalat_draft:
        return ChecklistItem(
            id=item.id,
            label=item.label,
            description=item.description,
            category=item.category,
            required=item.required,
            auto_satisfied=True,
            auto_satisfied_reason=(
                "Vakalatnama draft found on this matter — the filing-"
                "bundle ZIP will pick it up automatically."
            ),
        )
    document_ids_satisfied_by_attachments = {
        "impugned_fir_copy",
        "impugned_order_copy",
        "bank_memo",
        "will_original",
        "death_certificate",
    }
    if item.id in document_ids_satisfied_by_attachments and attachment_count > 0:
        return ChecklistItem(
            id=item.id,
            label=item.label,
            description=item.description,
            category=item.category,
            required=item.required,
            auto_satisfied=True,
            auto_satisfied_reason=(
                f"Matter has {attachment_count} attachment(s) — verify "
                f"the right one is selected before filing."
            ),
        )
    return item


# ---------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------


def build_filing_checklist(
    session: Session,
    *,
    matter_id: str,
    draft: Draft,
    court_profile_key: str | None = None,
    court_name: str | None = None,
) -> FilingChecklist:
    """Build the filing checklist for the given draft. Pure-read; no
    DB writes."""
    profile = resolve_profile(
        explicit_key=court_profile_key, court_name=court_name,
    )

    template_type = draft.template_type or ""
    required_field_findings = validate_required_fields(
        profile,
        template_type=template_type,
        facts=_draft_facts(draft),
        matter_court_name=court_name,
    )
    missing_required_field_count = sum(
        1 for finding in required_field_findings if not finding.satisfied
    )

    items: list[ChecklistItem] = []
    items.extend(_BASE_CONTESTED_ITEMS)
    items.extend(_court_overrides(profile))
    items.extend(_template_overrides(template_type))

    # De-duplicate by id, keeping the first occurrence (template
    # overrides come last → if a template wants to refine the base
    # item, it should use a different id).
    seen: set[str] = set()
    deduped: list[ChecklistItem] = []
    for it in items:
        if it.id in seen:
            continue
        seen.add(it.id)
        deduped.append(it)

    # Auto-satisfaction probes.
    has_vakalat_draft = bool(
        session.scalar(
            select(Draft.id)
            .where(
                Draft.matter_id == matter_id,
                Draft.template_type == DraftTemplateType.VAKALATNAMA.value,
            )
            .limit(1)
        )
    )
    attachment_count = int(
        session.scalar(
            select(MatterAttachment.id)
            .where(MatterAttachment.matter_id == matter_id)
            .limit(1)
        ) is not None
    )
    if attachment_count:
        # Get full count for the reason text.
        attachment_count = len(
            list(
                session.scalars(
                    select(MatterAttachment.id)
                    .where(MatterAttachment.matter_id == matter_id)
                ).all()
            )
        )

    enriched = [
        _auto_satisfy(
            it,
            has_vakalat_draft=has_vakalat_draft,
            attachment_count=attachment_count,
        )
        for it in deduped
    ]

    return FilingChecklist(
        matter_id=matter_id,
        draft_id=draft.id,
        template_type=template_type,
        court_profile_key=profile.key,
        court_display_name=profile.display_name,
        items=enriched,
        court_fee_note=_court_fee_note(profile.key, template_type),
        limitation_note=_limitation_note(template_type),
        copies_required=_copies_required(profile.key),
        required_field_findings=required_field_findings,
        missing_required_field_count=missing_required_field_count,
    )


def _draft_facts(draft: Draft) -> dict[str, object]:
    if not draft.facts_json:
        return {}
    try:
        parsed = json.loads(draft.facts_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = [
    "ChecklistItem",
    "FilingChecklist",
    "build_filing_checklist",
]
