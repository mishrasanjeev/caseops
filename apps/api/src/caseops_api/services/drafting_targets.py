"""Typed targets and trademark pleading context for the shared drafting engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
    IpIdentifier,
    IpPartyAndRole,
    IpProceeding,
)
from caseops_api.services.matter_access import assert_ip_docket_access
from caseops_api.services.session_context import SessionContext


@dataclass(frozen=True)
class TrademarkPleadingTemplate:
    key: str
    label: str
    version: str
    draft_type: str
    sides: frozenset[str]
    stages: frozenset[str]
    jurisdictions: frozenset[str]
    format_profile: str
    instructions: str

    def manifest(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "version": self.version,
            "draft_type": self.draft_type,
            "allowed_sides": sorted(self.sides),
            "allowed_stages": sorted(self.stages),
            "jurisdictions": sorted(self.jurisdictions),
            "format_profile": self.format_profile,
        }


_INDIA_PROFILE = "india-trade-marks-registry-v1"
TRADEMARK_PLEADING_TEMPLATES: dict[str, TrademarkPleadingTemplate] = {
    "trademark_opposition_notice": TrademarkPleadingTemplate(
        key="trademark_opposition_notice",
        label="Notice of opposition",
        version="1.0",
        draft_type="notice",
        sides=frozenset({"opponent"}),
        stages=frozenset({"draft"}),
        jurisdictions=frozenset({"IN"}),
        format_profile=_INDIA_PROFILE,
        instructions=(
            "Prepare a Trade Marks Registry notice of opposition for the opponent. "
            "Use only the confirmed application/opposition identifiers, pleaded "
            "grounds, challenged goods/services, relied-on rights, and cited sources."
        ),
    ),
    "trademark_counterstatement": TrademarkPleadingTemplate(
        key="trademark_counterstatement",
        label="Counterstatement",
        version="1.0",
        draft_type="reply",
        sides=frozenset({"applicant"}),
        stages=frozenset({"service_pending", "counterstatement_due"}),
        jurisdictions=frozenset({"IN"}),
        format_profile=_INDIA_PROFILE,
        instructions=(
            "Prepare the applicant's counterstatement answering each confirmed "
            "opposition ground without inventing admissions, dates, use claims, or rights."
        ),
    ),
    "trademark_opponent_evidence": TrademarkPleadingTemplate(
        key="trademark_opponent_evidence",
        label="Opponent evidence affidavit",
        version="1.0",
        draft_type="brief",
        sides=frozenset({"opponent"}),
        stages=frozenset({"opponent_evidence_due"}),
        jurisdictions=frozenset({"IN"}),
        format_profile=_INDIA_PROFILE,
        instructions=(
            "Prepare the opponent's evidence affidavit, mapping each factual assertion "
            "to the supplied immutable document-version source list."
        ),
    ),
    "trademark_applicant_evidence": TrademarkPleadingTemplate(
        key="trademark_applicant_evidence",
        label="Applicant evidence affidavit",
        version="1.0",
        draft_type="brief",
        sides=frozenset({"applicant"}),
        stages=frozenset({"applicant_evidence_due"}),
        jurisdictions=frozenset({"IN"}),
        format_profile=_INDIA_PROFILE,
        instructions=(
            "Prepare the applicant's evidence affidavit, preserving the confirmed "
            "application identity and mapping assertions to supplied document versions."
        ),
    ),
    "trademark_reply_evidence": TrademarkPleadingTemplate(
        key="trademark_reply_evidence",
        label="Reply evidence affidavit",
        version="1.0",
        draft_type="reply",
        sides=frozenset({"opponent"}),
        stages=frozenset({"reply_evidence_due"}),
        jurisdictions=frozenset({"IN"}),
        format_profile=_INDIA_PROFILE,
        instructions=(
            "Prepare reply evidence confined to the applicant evidence and supplied "
            "sources; do not introduce unsupported new grounds or factual claims."
        ),
    ),
}


@dataclass(frozen=True)
class IpDraftingTarget:
    docket: IpDocketRecord
    proceeding: IpProceeding
    template: TrademarkPleadingTemplate
    template_manifest: dict[str, Any]
    context_manifest: dict[str, Any]
    source_manifest: list[dict[str, Any]]
    source_text: str


def load_ip_drafting_target(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    template_key: str,
) -> IpDraftingTarget:
    docket = session.scalar(
        select(IpDocketRecord).where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
    )
    if docket is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    assert_ip_docket_access(session, context=context, docket=docket)
    if not docket.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inactive IP docket records cannot create or change pleadings.",
        )
    proceeding = session.scalar(
        select(IpProceeding).where(
            IpProceeding.id == proceeding_id,
            IpProceeding.company_id == context.company.id,
            IpProceeding.docket_id == docket.id,
            IpProceeding.proceeding_kind == "opposition",
        )
    )
    if proceeding is None:
        raise HTTPException(status_code=404, detail="Opposition proceeding not found.")
    template = TRADEMARK_PLEADING_TEMPLATES.get(template_key)
    if template is None:
        raise HTTPException(status_code=422, detail="Unknown trademark pleading template.")
    incompatibilities: list[str] = []
    if proceeding.side not in template.sides:
        incompatibilities.append(f"represented side {proceeding.side!r}")
    if proceeding.stage not in template.stages:
        incompatibilities.append(f"stage {proceeding.stage!r}")
    if proceeding.jurisdiction.upper() not in template.jurisdictions:
        incompatibilities.append(f"jurisdiction {proceeding.jurisdiction!r}")
    if incompatibilities:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Template {template.label!r} is incompatible with "
                + ", ".join(incompatibilities)
                + ". Select a template allowed for the current proceeding."
            ),
        )

    identifiers = list(
        session.scalars(
            select(IpIdentifier)
            .where(
                IpIdentifier.company_id == context.company.id,
                IpIdentifier.docket_id == docket.id,
                IpIdentifier.effective_until.is_(None),
                IpIdentifier.reconciliation_status == "confirmed",
                or_(
                    IpIdentifier.proceeding_id == proceeding.id,
                    IpIdentifier.application_id == proceeding.application_id,
                ),
            )
            .order_by(IpIdentifier.identifier_kind, IpIdentifier.is_primary.desc())
            .limit(40)
        )
    )
    parties = list(
        session.scalars(
            select(IpPartyAndRole)
            .where(
                IpPartyAndRole.company_id == context.company.id,
                IpPartyAndRole.docket_id == docket.id,
                IpPartyAndRole.effective_until.is_(None),
                or_(
                    IpPartyAndRole.proceeding_id == proceeding.id,
                    IpPartyAndRole.proceeding_id.is_(None),
                ),
            )
            .order_by(IpPartyAndRole.role_kind, IpPartyAndRole.party_name)
            .limit(40)
        )
    )
    events = list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == context.company.id,
                IpDocketEvent.docket_id == docket.id,
                IpDocketEvent.candidate_status.in_(("confirmed", "reconciled")),
                or_(
                    IpDocketEvent.proceeding_id == proceeding.id,
                    IpDocketEvent.application_id == proceeding.application_id,
                ),
            )
            .order_by(IpDocketEvent.sequence.desc())
            .limit(50)
        )
    )
    deadlines = list(
        session.scalars(
            select(IpDeadline)
            .where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.docket_id == docket.id,
                IpDeadline.state.in_(("confirmed", "overdue")),
            )
            .order_by(IpDeadline.result_on, IpDeadline.created_at)
            .limit(40)
        )
    )
    context_manifest: dict[str, Any] = {
        "schema": "caseops.ip-drafting-context.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "company_id": context.company.id,
        "docket": {
            "id": docket.id,
            "title": docket.title,
            "record_type": docket.record_type,
            "status": docket.status,
            "lifecycle_version": docket.lifecycle_version,
        },
        "proceeding": {
            "id": proceeding.id,
            "kind": proceeding.proceeding_kind,
            "application_id": proceeding.application_id,
            "side": proceeding.side,
            "office": proceeding.office,
            "jurisdiction": proceeding.jurisdiction,
            "stage": proceeding.stage,
            "stage_template_version": proceeding.stage_template_version,
            "version": proceeding.version,
        },
        "identifiers": [
            {
                "id": row.id,
                "kind": row.identifier_kind,
                "value": row.raw_value,
                "office": row.office,
                "jurisdiction": row.jurisdiction,
                "source": row.source,
                "effective_from": row.effective_from.isoformat(),
            }
            for row in identifiers
        ],
        "parties": [
            {
                "id": row.id,
                "name": row.party_name,
                "role": row.role_kind,
                "source": row.source,
                "effective_from": row.effective_from.isoformat(),
            }
            for row in parties
        ],
        "events": [
            {
                "id": row.id,
                "sequence": row.sequence,
                "kind": row.event_kind,
                "effective_at": row.effective_at.isoformat(),
                "source": row.source,
                "source_reference": row.source_reference,
                "resulting_stage": row.resulting_stage,
                "payload": row.payload_json,
            }
            for row in reversed(events)
        ],
        "deadlines": [
            {
                "id": row.id,
                "title": row.title,
                "kind": row.deadline_kind,
                "state": row.state,
                "result_on": row.result_on.isoformat() if row.result_on else None,
                "result_at": row.result_at.isoformat() if row.result_at else None,
                "rule_citation": row.rule_citation,
                "rule_version_id": row.rule_version_id,
                "source_version": row.source_version,
            }
            for row in deadlines
        ],
    }
    source_manifest, source_text = _load_source_manifest(
        session,
        company_id=context.company.id,
        docket=docket,
        proceeding=proceeding,
    )
    template_manifest = {
        "schema": "caseops.drafting-template.v1",
        **template.manifest(),
        "selected_for": {
            "side": proceeding.side,
            "stage": proceeding.stage,
            "jurisdiction": proceeding.jurisdiction,
            "office": proceeding.office,
        },
    }
    return IpDraftingTarget(
        docket=docket,
        proceeding=proceeding,
        template=template,
        template_manifest=template_manifest,
        context_manifest=context_manifest,
        source_manifest=source_manifest,
        source_text=source_text,
    )


def _load_source_manifest(
    session: Session,
    *,
    company_id: str,
    docket: IpDocketRecord,
    proceeding: IpProceeding,
) -> tuple[list[dict[str, Any]], str]:
    conditions = [
        IpDocumentLink.docket_id == docket.id,
        IpDocumentLink.proceeding_id == proceeding.id,
    ]
    if proceeding.application_id:
        conditions.append(IpDocumentLink.application_id == proceeding.application_id)
    links = list(
        session.scalars(
            select(IpDocumentLink)
            .where(
                IpDocumentLink.company_id == company_id,
                or_(*conditions),
            )
            .order_by(IpDocumentLink.created_at.desc())
            .limit(50)
        )
    )
    if not links:
        return [], "No immutable IP document versions were linked to this proceeding."
    document_ids = {row.document_id for row in links}
    documents = {
        row.id: row
        for row in session.scalars(
            select(IpDocument).where(
                IpDocument.company_id == company_id,
                IpDocument.id.in_(document_ids),
            )
        )
    }
    versions = list(
        session.scalars(
            select(IpDocumentVersion).where(
                IpDocumentVersion.company_id == company_id,
                IpDocumentVersion.document_id.in_(document_ids),
            )
        )
    )
    by_id = {row.id: row for row in versions}
    by_number = {(row.document_id, row.version): row for row in versions}
    manifest: list[dict[str, Any]] = []
    excerpts: list[str] = []
    seen_versions: set[str] = set()
    for link in links:
        document = documents.get(link.document_id)
        if document is None:
            continue
        version = (
            by_id.get(link.version_id)
            if link.version_id
            else by_number.get((document.id, document.current_version))
        )
        if version is None or version.id in seen_versions:
            continue
        seen_versions.add(version.id)
        usable = version.state in {"approved", "filed", "served", "accepted"}
        manifest.append(
            {
                "document_id": document.id,
                "document_title": document.title,
                "document_version_id": version.id,
                "version": version.version,
                "display_name": version.display_name,
                "sha256": version.sha256_hex,
                "state": version.state,
                "processing_status": version.processing_status,
                "target_type": link.target_type,
                "target_id": link.target_id,
                "usable_for_generation": usable,
            }
        )
        if usable and version.extracted_text:
            excerpts.append(
                f"SOURCE {version.id} | {document.title} | SHA256 {version.sha256_hex}\n"
                + version.extracted_text[:4000]
            )
    return manifest, "\n\n".join(excerpts) or (
        "Linked document versions exist, but none has approved/filing state and "
        "extractable text. Do not infer their contents."
    )


def compatible_trademark_templates(proceeding: IpProceeding) -> list[dict[str, Any]]:
    return [
        template.manifest()
        for template in TRADEMARK_PLEADING_TEMPLATES.values()
        if proceeding.side in template.sides
        and proceeding.stage in template.stages
        and proceeding.jurisdiction.upper() in template.jurisdictions
    ]


__all__ = [
    "IpDraftingTarget",
    "TRADEMARK_PLEADING_TEMPLATES",
    "compatible_trademark_templates",
    "load_ip_drafting_target",
]
