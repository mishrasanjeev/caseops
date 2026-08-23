"""Deterministic validation for trademark pleading revisions.

The validator never calls an LLM. It compares a frozen draft revision with
the current canonical IP records and source versions so approval and filing
cannot rely on stale identifiers, changed documents, or unresolved drafting
placeholders.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    Draft,
    DraftVersion,
    IpDeadline,
    IpDocumentVersion,
    IpIdentifier,
    IpProceeding,
)

ValidationSeverity = Literal["warning", "blocker"]
_USABLE_SOURCE_STATES = frozenset({"approved", "filed", "served", "accepted"})
_SOURCE_ANCHOR_RE = re.compile(
    r"\[(SOURCE|EXHIBIT):([0-9a-f]{8}-[0-9a-f-]{27})\]",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r"(?:\{\{[^{}\n]{1,120}\}\}|<<[^<>\n]{1,120}>>|"
    r"\[(?:\s*_{2,}\s*|\s*(?:TBD|TODO|INSERT|ADD|DATE|NAME|ADDRESS|"
    r"NUMBER|AMOUNT|DETAILS?|PARTICULARS?|CITATION NEEDED)(?:\s+[^\]\n]{0,80})?)\])",
    re.IGNORECASE,
)
_GENERIC_EXHIBIT_RE = re.compile(r"\b(?:annexure|exhibit)\s+[-:]?\s*[A-Z0-9]+\b", re.I)


@dataclass(frozen=True)
class IpDraftValidationFinding:
    code: str
    severity: ValidationSeverity
    message: str
    references: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "references": list(self.references),
        }


@dataclass(frozen=True)
class IpDraftValidationReport:
    draft_id: str
    version_id: str
    revision: int
    evaluated_at: str
    blocker_count: int
    warning_count: int
    placeholder_count: int
    source_count: int
    source_anchor_count: int
    exhibit_anchor_count: int
    findings: tuple[IpDraftValidationFinding, ...]

    @property
    def can_approve(self) -> bool:
        return self.blocker_count == 0

    @property
    def can_file(self) -> bool:
        return self.blocker_count == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "version_id": self.version_id,
            "revision": self.revision,
            "evaluated_at": self.evaluated_at,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "placeholder_count": self.placeholder_count,
            "source_count": self.source_count,
            "source_anchor_count": self.source_anchor_count,
            "exhibit_anchor_count": self.exhibit_anchor_count,
            "can_approve": self.can_approve,
            "can_file": self.can_file,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def _json_object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_list(raw: str | None) -> list[Any]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _identifier_values(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for row in rows:
        kind = str(row.get("kind") or row.get("identifier_kind") or "").strip()
        value = str(row.get("value") or row.get("raw_value") or "").strip()
        if kind and value:
            values.setdefault(kind, set()).add(value.casefold())
    return values


def validate_ip_context_manifest(
    context_manifest: dict[str, Any],
    *,
    template_key: str,
) -> list[IpDraftValidationFinding]:
    """Validate identifier and event-date consistency before generation."""
    findings: list[IpDraftValidationFinding] = []
    identifiers = context_manifest.get("identifiers")
    identifier_rows = identifiers if isinstance(identifiers, list) else []
    grouped = _identifier_values([row for row in identifier_rows if isinstance(row, dict)])
    required = {"application"}
    if template_key != "trademark_opposition_notice":
        required.add("opposition")
    for kind in sorted(required):
        values = grouped.get(kind, set())
        if not values:
            findings.append(
                IpDraftValidationFinding(
                    code="context.identifier_missing",
                    severity="blocker",
                    message=f"A confirmed {kind} number is required for this pleading template.",
                    references=(kind,),
                )
            )
        elif len(values) > 1:
            findings.append(
                IpDraftValidationFinding(
                    code="context.identifier_conflict",
                    severity="blocker",
                    message=(
                        f"Multiple current confirmed {kind} numbers conflict "
                        "for this proceeding."
                    ),
                    references=tuple(sorted(values)),
                )
            )

    events = context_manifest.get("events")
    event_rows = events if isinstance(events, list) else []
    dates_by_key: dict[tuple[str, str], set[str]] = {}
    for row in event_rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip()
        source_reference = str(row.get("source_reference") or "").strip()
        effective_at = str(row.get("effective_at") or "").strip()
        if kind and source_reference and effective_at:
            dates_by_key.setdefault((kind, source_reference), set()).add(effective_at)
    for (kind, source_reference), dates in sorted(dates_by_key.items()):
        if len(dates) > 1:
            findings.append(
                IpDraftValidationFinding(
                    code="context.date_conflict",
                    severity="warning",
                    message=(
                        f"Registry event {kind!r} has conflicting dates for source "
                        f"reference {source_reference!r}; lawyer confirmation is required."
                    ),
                    references=tuple(sorted(dates)),
                )
            )
    return findings


def _authority_findings(
    session: Session,
    *,
    citations: list[str],
) -> list[IpDraftValidationFinding]:
    if not citations:
        return [
            IpDraftValidationFinding(
                code="citation.none_verified",
                severity="blocker",
                message=(
                    "At least one current verified authority is required before "
                    "approval or filing."
                ),
            )
        ]
    documents = list(
        session.scalars(
            select(AuthorityDocument).where(
                or_(
                    AuthorityDocument.id.in_(citations),
                    AuthorityDocument.neutral_citation.in_(citations),
                    AuthorityDocument.case_reference.in_(citations),
                )
            )
        )
    )
    current_aliases = {
        value.casefold()
        for row in documents
        for value in (row.id, row.neutral_citation, row.case_reference)
        if value
    }
    missing = [value for value in citations if value.casefold() not in current_aliases]
    if not missing:
        return []
    return [
        IpDraftValidationFinding(
            code="citation.source_lost",
            severity="blocker",
            message="One or more previously verified authorities are no longer available.",
            references=tuple(missing),
        )
    ]


def _current_context_findings(
    session: Session,
    *,
    draft: Draft,
    context_manifest: dict[str, Any],
    template_key: str,
) -> list[IpDraftValidationFinding]:
    findings = validate_ip_context_manifest(context_manifest, template_key=template_key)
    proceeding_data = context_manifest.get("proceeding")
    frozen_proceeding = proceeding_data if isinstance(proceeding_data, dict) else {}
    proceeding = session.scalar(
        select(IpProceeding).where(
            IpProceeding.id == draft.ip_proceeding_id,
            IpProceeding.company_id == draft.company_id,
            IpProceeding.docket_id == draft.ip_docket_id,
        )
    )
    if proceeding is None:
        findings.append(
            IpDraftValidationFinding(
                code="context.proceeding_missing",
                severity="blocker",
                message="The opposition proceeding captured by this revision no longer exists.",
            )
        )
        return findings
    if (
        proceeding.version != frozen_proceeding.get("version")
        or proceeding.stage != frozen_proceeding.get("stage")
    ):
        findings.append(
            IpDraftValidationFinding(
                code="context.proceeding_changed",
                severity="blocker",
                message=(
                    "The proceeding stage or version changed after this revision "
                    "was generated."
                ),
                references=(proceeding.stage, str(proceeding.version)),
            )
        )

    application_id = frozen_proceeding.get("application_id")
    current_identifiers = list(
        session.scalars(
            select(IpIdentifier).where(
                IpIdentifier.company_id == draft.company_id,
                IpIdentifier.docket_id == draft.ip_docket_id,
                IpIdentifier.effective_until.is_(None),
                IpIdentifier.reconciliation_status == "confirmed",
                or_(
                    IpIdentifier.proceeding_id == draft.ip_proceeding_id,
                    IpIdentifier.application_id == application_id,
                ),
            )
        )
    )
    frozen_rows = context_manifest.get("identifiers")
    frozen_grouped = _identifier_values(
        [row for row in frozen_rows if isinstance(row, dict)]
        if isinstance(frozen_rows, list)
        else []
    )
    current_grouped = _identifier_values(
        [
            {"identifier_kind": row.identifier_kind, "raw_value": row.raw_value}
            for row in current_identifiers
        ]
    )
    for kind in sorted(set(frozen_grouped) | set(current_grouped)):
        if frozen_grouped.get(kind, set()) != current_grouped.get(kind, set()):
            findings.append(
                IpDraftValidationFinding(
                    code="context.identifier_changed",
                    severity="blocker",
                    message=(
                        f"Current {kind} identifiers differ from this revision's "
                        "frozen context."
                    ),
                    references=tuple(sorted(current_grouped.get(kind, set()))),
                )
            )

    frozen_deadlines = context_manifest.get("deadlines")
    deadline_rows = (
        [row for row in frozen_deadlines if isinstance(row, dict)]
        if isinstance(frozen_deadlines, list)
        else []
    )
    deadline_ids = [str(row.get("id")) for row in deadline_rows if row.get("id")]
    current_deadlines = {
        row.id: row
        for row in session.scalars(
            select(IpDeadline).where(
                IpDeadline.company_id == draft.company_id,
                IpDeadline.id.in_(deadline_ids),
            )
        )
    } if deadline_ids else {}
    for frozen in deadline_rows:
        deadline_id = str(frozen.get("id") or "")
        current = current_deadlines.get(deadline_id)
        current_date = current.result_on.isoformat() if current and current.result_on else None
        if current is None or current_date != frozen.get("result_on"):
            findings.append(
                IpDraftValidationFinding(
                    code="context.deadline_changed",
                    severity="blocker",
                    message="A deadline date used by this revision changed or was removed.",
                    references=(deadline_id,),
                )
            )
    return findings


def evaluate_ip_draft_version(
    session: Session,
    *,
    draft: Draft,
    version: DraftVersion,
) -> IpDraftValidationReport:
    template_manifest = _json_object(version.template_manifest_json)
    context_manifest = _json_object(version.context_manifest_json)
    source_manifest = [
        row for row in _json_list(version.source_manifest_json) if isinstance(row, dict)
    ]
    citations = [
        str(row).strip()
        for row in _json_list(version.citations_json)
        if str(row).strip()
    ]
    findings: list[IpDraftValidationFinding] = []

    template_key = str(template_manifest.get("key") or draft.template_type or "")
    for field in ("key", "version", "format_profile"):
        if not template_manifest.get(field):
            findings.append(
                IpDraftValidationFinding(
                    code="template.manifest_incomplete",
                    severity="blocker",
                    message=f"The frozen template manifest is missing {field!r}.",
                    references=(field,),
                )
            )
    findings.extend(
        _current_context_findings(
            session,
            draft=draft,
            context_manifest=context_manifest,
            template_key=template_key,
        )
    )
    findings.extend(_authority_findings(session, citations=citations))

    placeholders = [match.group(0) for match in _PLACEHOLDER_RE.finditer(version.body)]
    if placeholders:
        findings.append(
            IpDraftValidationFinding(
                code="placeholder.unresolved",
                severity="blocker",
                message=(
                    f"The revision contains {len(placeholders)} unresolved "
                    "drafting placeholder(s)."
                ),
                references=tuple(dict.fromkeys(placeholders[:10])),
            )
        )

    anchors = [
        (kind.upper(), version_id.lower())
        for kind, version_id in _SOURCE_ANCHOR_RE.findall(version.body)
    ]
    manifest_by_id = {
        str(row.get("document_version_id") or "").lower(): row
        for row in source_manifest
        if row.get("document_version_id")
    }
    anchored_ids = {version_id for _, version_id in anchors}
    unknown_anchors = sorted(anchored_ids - set(manifest_by_id))
    if unknown_anchors:
        findings.append(
            IpDraftValidationFinding(
                code="source.anchor_unknown",
                severity="blocker",
                message="A source or exhibit anchor is not present in the frozen source manifest.",
                references=tuple(unknown_anchors),
            )
        )
    generic_exhibits = _GENERIC_EXHIBIT_RE.findall(version.body)
    exhibit_anchors = [version_id for kind, version_id in anchors if kind == "EXHIBIT"]
    if generic_exhibits and not exhibit_anchors:
        findings.append(
            IpDraftValidationFinding(
                code="exhibit.unmapped_reference",
                severity="blocker",
                message=(
                    "Annexure or exhibit references must use an exact "
                    "[EXHIBIT:<document-version-id>] anchor."
                ),
                references=tuple(dict.fromkeys(generic_exhibits[:10])),
            )
        )

    source_ids = list(manifest_by_id)
    current_versions = {
        row.id.lower(): row
        for row in session.scalars(
            select(IpDocumentVersion).where(
                IpDocumentVersion.company_id == draft.company_id,
                IpDocumentVersion.id.in_(source_ids),
            )
        )
    } if source_ids else {}
    for source_id, frozen in manifest_by_id.items():
        current = current_versions.get(source_id)
        if current is None:
            findings.append(
                IpDraftValidationFinding(
                    code="source.version_lost",
                    severity="blocker",
                    message="A frozen document version is no longer available.",
                    references=(source_id,),
                )
            )
            continue
        if current.sha256_hex != frozen.get("sha256"):
            findings.append(
                IpDraftValidationFinding(
                    code="source.hash_changed",
                    severity="blocker",
                    message="A frozen document version no longer matches its recorded SHA-256.",
                    references=(source_id,),
                )
            )
        if current.state not in _USABLE_SOURCE_STATES:
            findings.append(
                IpDraftValidationFinding(
                    code="source.state_invalid",
                    severity="blocker",
                    message="A frozen source is no longer in an approved or filing state.",
                    references=(source_id, current.state),
                )
            )

    unique_findings: list[IpDraftValidationFinding] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for finding in findings:
        key = (finding.code, finding.message, finding.references)
        if key not in seen:
            seen.add(key)
            unique_findings.append(finding)
    blockers = sum(row.severity == "blocker" for row in unique_findings)
    warnings = sum(row.severity == "warning" for row in unique_findings)
    return IpDraftValidationReport(
        draft_id=draft.id,
        version_id=version.id,
        revision=version.revision,
        evaluated_at=datetime.now(UTC).isoformat(),
        blocker_count=blockers,
        warning_count=warnings,
        placeholder_count=len(placeholders),
        source_count=len(source_manifest),
        source_anchor_count=len(anchors),
        exhibit_anchor_count=len(exhibit_anchors),
        findings=tuple(unique_findings),
    )


__all__ = [
    "IpDraftValidationFinding",
    "IpDraftValidationReport",
    "evaluate_ip_draft_version",
    "validate_ip_context_manifest",
]
