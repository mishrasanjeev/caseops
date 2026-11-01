"""IPLF-032A bulk IP portfolio import (UJ-02).

Ownership: `bulk_import_jobs` is the **neutral** import owner tagged by domain;
`ip_import_rows` is the typed IP staging table. The legacy
`matter_bulk_import_jobs` and `employee_bulk_import_jobs` owners are untouched
and remain canonical for their domains. ARCH-OPS-23 forbids an IP-specific job
table, so no such table is introduced here, and Matter row-commit logic is not
reused as generic orchestration.

Commit materialises records through the existing `create_ip_docket` writer
rather than inserting docket rows directly.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from secrets import token_hex
from threading import Lock
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, status
from sqlalchemy import JSON, String, and_, column, func, select, text, type_coerce, values
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    BulkImportJob,
    IpAsset,
    IpDocketRecord,
    IpIdentifier,
    IpImportRow,
    IpTrademarkParticularVersion,
    IpWorkspaceConfiguration,
    Matter,
    TrademarkApplication,
)
from caseops_api.schemas.ip_imports import (
    IpImportCommitRequest,
    IpImportCommitResponse,
    IpImportDocketCreateRequest,
    IpImportJobCreateRequest,
    IpImportJobRecord,
    IpImportParticularPayload,
    IpImportPreviewResponse,
    IpImportReconciliationRequest,
    IpImportResumeRequest,
    IpImportRowRecord,
)
from caseops_api.schemas.ip_records import (
    IpApplicationNumberCreate,
    IpAssetCreateRequest,
    TrademarkApplicationCreateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.csv_security import csv_safe_mapping
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.ip_import_files import (
    HEADER_ALIASES,
    METADATA_FIELDS,
    normalize_header,
    source_value,
)
from caseops_api.services.ip_operations import _create_ip_docket_record as create_ip_docket
from caseops_api.services.ip_records import create_ip_asset, create_trademark_application
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

DOMAIN = "ip_trademark"
PREVIEW_TTL = timedelta(minutes=30)
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
IMPORT_MATERIALIZATION_ACTION = "ip_docket.source_materialized"
COMMIT_BATCH_SIZE = 50
_LOG = logging.getLogger(__name__)
REPRESENTATION_KIND_ALIASES = {"logo": "device", "color": "colour"}
REPRESENTATION_KINDS = {
    "word",
    "device",
    "composite",
    "label",
    "colour",
    "shape",
    "sound",
    "other",
}
# A source "Status" cell (B4-ADJ-11). Each recognised wording becomes a
# declared status; the application is created in the filing phase the
# interactive create command can set for it (draft, pre_filing or filed, the
# last with a confirmed application number). Later legal milestones such as
# registration are kept as the declared, unverified source status: only
# registry evidence or a lifecycle event may record them as legal state.
# Wording outside this table (registry exports vary) never blocks a row: it
# imports in the draft phase with its source wording kept and shown as
# unrecognised, exactly as every Status cell imported before this mapping.
SOURCE_STATUS_ALIASES = {
    "draft": "draft",
    "not filed": "draft",
    "unfiled": "draft",
    "pre filing": "pre_filing",
    "prefiling": "pre_filing",
    "to be filed": "pre_filing",
    "ready to file": "pre_filing",
    "ready for filing": "pre_filing",
    "filed": "filed",
    "application filed": "filed",
    "new application": "filed",
    "pending": "filed",
    "formalities chk pass": "formalities",
    "formalities check pass": "formalities",
    "formalities chk fail": "formalities",
    "formalities check fail": "formalities",
    "send to vienna codification": "formalities",
    "sent to vienna codification": "formalities",
    "marked for exam": "examination",
    "marked for examination": "examination",
    "under examination": "examination",
    "examination": "examination",
    "objected": "objected",
    "objection": "objected",
    "under objection": "objected",
    "examination report issued": "objected",
    "hearing": "hearing",
    "show cause hearing": "hearing",
    "ready for show cause hearing": "hearing",
    "accepted": "accepted",
    "accepted and advertised": "advertised",
    "accepted advertised": "advertised",
    "advertised": "advertised",
    "advertised before acceptance": "advertised",
    "advertised before accepted": "advertised",
    "published": "advertised",
    "opposed": "opposed",
    "under opposition": "opposed",
    "registered": "registered",
    "renewed": "registered",
    "refused": "refused",
    "rejected": "refused",
    "abandoned": "abandoned",
    "withdrawn": "withdrawn",
    "removed": "removed",
    "removed from register": "removed",
    "expired": "removed",
}
SOURCE_STATUS_PHASES = {"draft": "draft", "pre_filing": "pre_filing"}
TERMINAL_SOURCE_STATUSES = frozenset({"refused", "abandoned", "withdrawn", "removed"})


def source_status_key(value: Any) -> str | None:
    """Declared status for a source Status cell, or None when unrecognised."""

    text = " ".join(re.sub(r"[^0-9a-z]+", " ", str(value).casefold()).split())
    return SOURCE_STATUS_ALIASES.get(text)


@dataclass
class _LocalLockEntry:
    lock: Lock
    users: int = 0


_LOCAL_IMPORT_LOCKS_GUARD = Lock()
_LOCAL_IMPORT_LOCKS: dict[str, _LocalLockEntry] = {}


@dataclass
class _DuplicateWorkBudget:
    remaining: int = 10000

    def charge(self, count: int) -> None:
        self.remaining -= count
        if self.remaining < 0:
            raise HTTPException(
                422,
                {
                    "code": "ip_import_candidate_limit",
                    "message": (
                        "This import exceeds the identity-check work limit; use a smaller file."
                    ),
                },
            )


@contextmanager
def _local_import_locks(resources: tuple[str, ...]) -> Iterator[None]:
    """Serialize SQLite/local import tests across the writer's inner commits."""

    entries: list[tuple[str, _LocalLockEntry]] = []
    with _LOCAL_IMPORT_LOCKS_GUARD:
        for resource in resources:
            entry = _LOCAL_IMPORT_LOCKS.get(resource)
            if entry is None:
                entry = _LocalLockEntry(lock=Lock())
                _LOCAL_IMPORT_LOCKS[resource] = entry
            entry.users += 1
            entries.append((resource, entry))

    acquired: list[tuple[str, _LocalLockEntry]] = []
    try:
        for resource, entry in entries:
            entry.lock.acquire()
            acquired.append((resource, entry))
        yield
    finally:
        for _resource, entry in reversed(acquired):
            entry.lock.release()
        with _LOCAL_IMPORT_LOCKS_GUARD:
            for resource, entry in entries:
                entry.users -= 1
                if entry.users == 0 and _LOCAL_IMPORT_LOCKS.get(resource) is entry:
                    del _LOCAL_IMPORT_LOCKS[resource]


@contextmanager
def _import_commit_locks(session: Session, *resources: str) -> Iterator[Callable[[], None] | None]:
    """Hold import locks across the canonical writer's transaction boundaries.

    The import materializer commits each accepted row. A normal
    ``FOR UPDATE`` lock therefore protects only the first row and used to let a
    concurrent commit materialise the same remaining rows. PostgreSQL advisory
    session locks live on a dedicated autocommit connection without an idle
    transaction, and are explicitly released before returning it to the pool.
    SQLite is local/test-only
    and uses the equivalent in-process keyed locks.
    """

    ordered = tuple(sorted(set(resources)))
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        engine = getattr(bind, "engine", bind)
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock_connection:
            acquired = []
            completed = False
            try:
                for resource in ordered:
                    lock_connection.execute(
                        text("SELECT pg_advisory_lock(hashtextextended(:resource, 0))"),
                        {"resource": resource},
                    )
                    acquired.append(resource)

                def assert_claim_owned() -> None:
                    for resource in acquired:
                        owned = lock_connection.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() "
                                "AND locktype='advisory' AND granted AND objsubid=1 "
                                "AND ((classid::bigint << 32) | objid::bigint) "
                                "= hashtextextended(:resource, 0))"
                            ),
                            {"resource": resource},
                        )
                        if not owned:
                            raise HTTPException(
                                409,
                                {
                                    "code": "ip_import_claim_lost",
                                    "message": (
                                    "Import claim ownership changed. "
                                    "Reload its durable history."
                                    ),
                                },
                            )

                yield assert_claim_owned
                completed = True
            finally:
                try:
                    for resource in reversed(acquired):
                        released = lock_connection.scalar(
                            text("SELECT pg_advisory_unlock(hashtextextended(:resource, 0))"),
                            {"resource": resource},
                        )
                        if not released:
                            raise RuntimeError("Import claim lock ownership was lost.")
                except Exception as exc:
                    lock_connection.invalidate()
                    if completed:
                        raise RuntimeError(
                            "Import claim connection was lost; reload its durable history."
                        ) from exc
                    _LOG.warning(
                        "Import claim cleanup failed", extra={"error_type": type(exc).__name__}
                    )
        return

    with _local_import_locks(ordered):
        yield None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _neutralize(value: Any) -> Any:
    """Formula-injection protection for spreadsheet round-trips.

    A leading formula trigger is prefixed so a re-exported cell is inert in
    Excel/Sheets. The displayed value keeps its original characters.
    """

    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _missing(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and re.sub(r"[\s./]+", "", value).casefold() in {
        "",
        "na",
        "null",
        "none",
    }


def _parse_date(value: Any) -> str | None:
    if _missing(value):
        return None
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        pass
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError("invalid source date")


def _validate_row(
    session: Session,
    *,
    context: SessionContext,
    values: dict[str, Any],
    workspace_defaults: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    mapped: dict[str, Any] = {}
    mapping = []
    source_values = {}
    for header, raw in values.items():
        target = HEADER_ALIASES.get(normalize_header(header))
        mapping.append(
            {
                "source": header,
                "target": target,
                # The Status cell is retained as source evidence and also sets
                # the filing phase, so it is canonical input.
                "handling": "source_metadata"
                if target in METADATA_FIELDS and target != "source_status"
                else "canonical"
                if target
                else "unmapped",
            }
        )
        source_values[header] = source_value(raw)
        if target is None or _missing(raw):
            continue
        value = raw.strip() if isinstance(raw, str) else source_value(raw)
        if target in mapped and mapped[target] != value:
            errors.append({"field": target, "code": "ambiguous_headers"})
            continue
        mapped[target] = value

    normalized: dict[str, Any] = {
        "_column_mapping": mapping,
        "_source_values": source_values,
        "_warnings": warnings,
    }
    limits = {
        "title": 255,
        "mark_text": 255,
        "applicant_name": 255,
        "application_number": 120,
        "jurisdiction": 40,
        "office": 80,
        "specification": 4000,
        "agent_name": 255,
    }
    for field, limit in limits.items():
        raw = mapped.get(field)
        if raw is None:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            errors.append({"field": field, "code": "unsupported_value"})
            continue
        value = str(int(raw)) if isinstance(raw, float) and raw.is_integer() else str(raw)
        if len(value) > limit or (field != "application_number" and len(value) < 2):
            errors.append({"field": field, "code": "invalid_length"})
        else:
            normalized[field] = _neutralize(value)
    if normalized.get("application_number") and not normalize_ip_identifier(
        normalized["application_number"]
    ):
        errors.append({"field": "application_number", "code": "invalid_identifier"})

    if not normalized.get("title"):
        if normalized.get("mark_text"):
            normalized["title"] = normalized["mark_text"]
        elif normalized.get("application_number"):
            normalized["title"] = normalized["application_number"]
    if not normalized.get("title"):
        code = "blank_row" if all(_missing(value) for value in values.values()) else "unusable_row"
        errors.append({"field": "row", "code": code})
    elif len(normalized["title"]) < 2:
        errors.append({"field": "title", "code": "invalid_length"})

    classes = mapped.get("class_number")
    if classes is not None:
        if isinstance(classes, (int, float)) and not isinstance(classes, bool):
            parts = [str(classes)]
        else:
            parts = re.split(r"[,;/\s]+", re.sub(r"\band\b", " ", str(classes), flags=re.I))
        parsed_classes = []
        for part in filter(None, parts):
            try:
                number = float(part)
                if not number.is_integer():
                    raise ValueError
                number = int(number)
            except (ValueError, OverflowError):
                errors.append({"field": "class_number", "code": "not_an_integer"})
                break
            if not 1 <= number <= 45:
                errors.append({"field": "class_number", "code": "out_of_range"})
                break
            parsed_classes.append(number)
        else:
            normalized["class_numbers"] = sorted(set(parsed_classes))
            if len(normalized["class_numbers"]) == 1:
                normalized["class_number"] = normalized["class_numbers"][0]

    if workspace_defaults is None:
        workspace_defaults = _workspace_import_defaults(session, context=context)
    for field in ("jurisdiction", "office"):
        if normalized.get(field):
            continue
        if workspace_defaults.get(field):
            normalized[field] = workspace_defaults[field]
            warnings.append({"field": field, "code": "configured_workspace_context"})
        elif normalized.get("title"):
            errors.append({"field": field, "code": "workspace_context_required"})
    for field in ("application_date", "renewal_due_date", "priority_date"):
        raw = mapped.get(field)
        if raw is None:
            continue
        try:
            normalized[field] = _parse_date(raw)
        except ValueError:
            warnings.append({"field": field, "code": "invalid_optional_date"})
    for field in METADATA_FIELDS - {"priority_date"}:
        if field in mapped:
            normalized[field] = source_value(mapped[field])
    if "source_status" in mapped:
        declared = source_status_key(mapped["source_status"])
        if declared is None:
            warnings.append({"field": "source_status", "code": "unrecognised_status"})
        else:
            phase = SOURCE_STATUS_PHASES.get(declared, "filed")
            normalized["declared_status"] = declared
            normalized["filing_phase"] = phase
            # The same precondition the interactive create command applies.
            if phase == "filed" and not normalized.get("application_number"):
                errors.append(
                    {"field": "application_number", "code": "required_for_source_status"}
                )
            if declared not in {"draft", "pre_filing", "filed"}:
                warnings.append({"field": "source_status", "code": "declared_status_unverified"})
            if declared in TERMINAL_SOURCE_STATUSES:
                warnings.append({"field": "source_status", "code": "terminal_status_no_alert"})

    representation_kind = mapped.get("representation_kind")
    if representation_kind is not None:
        parsed_kind = str(representation_kind).casefold()
        parsed_kind = REPRESENTATION_KIND_ALIASES.get(parsed_kind, parsed_kind)
        if parsed_kind not in REPRESENTATION_KINDS:
            errors.append({"field": "representation_kind", "code": "unsupported"})
        else:
            normalized["representation_kind"] = parsed_kind

    # Names are preserved verbatim; punctuation is not a reliable party boundary.
    for field in ("applicant_name", "class_numbers", "specification", "mark_text"):
        if not normalized.get(field):
            warnings.append({"field": field, "code": "source_incomplete_draft"})
    if any(item["handling"] == "unmapped" for item in mapping):
        warnings.append({"field": "columns", "code": "unmapped_columns_retained"})
    if normalized.get("image_reference"):
        warnings.append({"field": "image_reference", "code": "source_reference_only"})
    matter_id = mapped.get("matter_id")
    if matter_id:
        from caseops_api.services.matter_access import can_access

        matter = session.scalar(
            select(Matter).where(
                Matter.id == str(matter_id),
                Matter.company_id == context.company.id,
            )
        )
        if matter is None or not can_access(session, context=context, matter=matter):
            errors.append({"field": "matter_id", "code": "unknown_reference"})
        else:
            normalized["matter_id"] = matter.id
    return normalized, errors


def _workspace_import_defaults(session: Session, *, context: SessionContext) -> dict[str, str]:
    row = session.scalar(
        select(IpWorkspaceConfiguration).where(
            IpWorkspaceConfiguration.company_id == context.company.id,
        )
    )
    result = {}
    if row is not None:
        for field, values in (
            ("jurisdiction", row.jurisdictions_json),
            ("office", row.offices_json),
        ):
            if len(values or []) == 1:
                result[field] = values[0]
    return result


def _duplicate_key(normalized: dict[str, Any]) -> tuple | None:
    jurisdiction = str(normalized.get("jurisdiction", "")).casefold()
    office = str(normalized.get("office", "")).casefold()
    number = normalized.get("application_number")
    if number:
        return ("application", jurisdiction, office, normalize_ip_identifier(str(number)))
    mark = str(normalized.get("mark_text") or "").strip().casefold()
    applicant = str(normalized.get("applicant_name") or "").strip().casefold()
    classes = tuple(normalized.get("class_numbers") or [])
    if mark and applicant and classes:
        return ("portfolio", jurisdiction, office, mark, applicant, classes)
    return None


def _duplicate_candidates_batch(
    session: Session,
    *,
    context: SessionContext,
    normalized_rows: list[dict[str, Any]],
) -> dict[tuple, list[dict[str, Any]]]:
    keys = {key for row in normalized_rows if (key := _duplicate_key(row))}
    if not keys:
        return {}
    indexed: dict[tuple, list[tuple[str, str]]] = {}
    numbers = {key[3] for key in keys if key[0] == "application"}
    if numbers:
        matches = session.execute(
            select(
                IpIdentifier.docket_id,
                IpIdentifier.jurisdiction,
                IpIdentifier.office,
                IpIdentifier.normalized_value,
            )
            .where(
                IpIdentifier.company_id == context.company.id,
                IpIdentifier.identifier_kind == "application",
                IpIdentifier.normalized_value.in_(numbers),
                IpIdentifier.effective_until.is_(None),
                IpIdentifier.superseded_by_identifier_id.is_(None),
            )
            .limit(10001)
        ).all()
        if len(matches) > 10000:
            raise HTTPException(422, "Too many identity matches; use a smaller import.")
        for docket_id, jurisdiction, office, number in matches:
            key = ("application", jurisdiction.casefold(), office.casefold(), number)
            if key in keys:
                indexed.setdefault(key, []).append((docket_id, "exact_application_number"))
    marks = {key[3] for key in keys if key[0] == "portfolio"}
    if marks:
        matches = session.execute(
            select(IpDocketRecord, TrademarkApplication, IpTrademarkParticularVersion)
            .join(
                TrademarkApplication,
                and_(
                    TrademarkApplication.docket_id == IpDocketRecord.id,
                    TrademarkApplication.company_id == IpDocketRecord.company_id,
                ),
            )
            .join(
                IpTrademarkParticularVersion,
                and_(
                    IpTrademarkParticularVersion.docket_id == IpDocketRecord.id,
                    IpTrademarkParticularVersion.company_id == IpDocketRecord.company_id,
                    IpTrademarkParticularVersion.version == IpDocketRecord.current_version,
                ),
            )
            .join(
                IpAsset,
                and_(
                    IpAsset.id == TrademarkApplication.asset_id,
                    IpAsset.company_id == TrademarkApplication.company_id,
                ),
            )
            .where(
                IpDocketRecord.company_id == context.company.id,
                func.lower(IpAsset.title).in_(marks),
            )
            .limit(10001)
        ).all()
        if len(matches) > 10000:
            raise HTTPException(422, "Too many portfolio matches; use a smaller import.")
        for docket, application, particulars in matches:
            parties = [
                p.get("name", "") for p in particulars.parties_json if p.get("role") == "applicant"
            ]
            if len(parties) != 1:
                continue
            key = (
                "portfolio",
                application.jurisdiction.casefold(),
                application.office.casefold(),
                str(particulars.representation_json.get("text") or "").strip().casefold(),
                parties[0].strip().casefold(),
                tuple(sorted(c["class_number"] for c in particulars.classes_json)),
            )
            if key in keys:
                indexed.setdefault(key, []).append((docket.id, "exact_portfolio_identity"))
    docket_ids = {docket_id for matches in indexed.values() for docket_id, _ in matches}
    accessible = (
        dict(
            session.execute(
                select(IpDocketRecord.id, IpDocketRecord.title).where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.id.in_(docket_ids),
                    visible_ip_dockets_filter(session, context=context),
                )
            ).all()
        )
        if docket_ids
        else {}
    )
    return {
        key: [
            {"docket_id": docket_id, "title": accessible[docket_id], "match_reasons": [reason]}
            if docket_id in accessible
            else {"match_reasons": ["identity_unavailable"]}
            for docket_id, reason in matches[:10]
        ]
        for key, matches in indexed.items()
    }


def _duplicate_candidates(
    session: Session,
    *,
    context: SessionContext,
    normalized: dict[str, Any],
    work_budget: _DuplicateWorkBudget | None = None,
) -> list[dict[str, Any]]:
    key = _duplicate_key(normalized)
    if key is None:
        return []
    if key[0] == "portfolio" and work_budget is not None:
        if work_budget.remaining <= 0:
            work_budget.charge(1)

        # Filter the complete identity in SQL before retaining any candidate.
        # Distinct same-mark applicants must not reload all preceding siblings.
        def elements(column, name):
            function = (
                func.json_array_elements
                if session.get_bind().dialect.name == "postgresql"
                else func.json_each
            )
            return function(column).table_valued("value").alias(name)

        parties = elements(IpTrademarkParticularVersion.parties_json, "candidate_party")
        party = type_coerce(parties.c.value, JSON)
        applicant = (
            select(1)
            .select_from(parties)
            .where(
                party["role"].as_string() == "applicant",
                func.lower(func.trim(party["name"].as_string())) == key[4],
            )
            .correlate(IpTrademarkParticularVersion)
            .exists()
        )
        one_applicant = (
            select(func.count())
            .select_from(parties)
            .where(
                party["role"].as_string() == "applicant",
            )
            .correlate(IpTrademarkParticularVersion)
            .scalar_subquery()
            == 1
        )
        classes = elements(IpTrademarkParticularVersion.classes_json, "candidate_class")
        scope = type_coerce(classes.c.value, JSON)
        predicates = [
            select(1)
            .select_from(classes)
            .where(
                scope["class_number"].as_integer() == number,
            )
            .correlate(IpTrademarkParticularVersion)
            .exists()
            for number in key[5]
        ]
        identifiers = session.scalars(
            select(IpDocketRecord.id)
            .join(
                TrademarkApplication,
                and_(
                    TrademarkApplication.docket_id == IpDocketRecord.id,
                    TrademarkApplication.company_id == IpDocketRecord.company_id,
                ),
            )
            .join(
                IpTrademarkParticularVersion,
                and_(
                    IpTrademarkParticularVersion.docket_id == IpDocketRecord.id,
                    IpTrademarkParticularVersion.company_id == IpDocketRecord.company_id,
                    IpTrademarkParticularVersion.version == IpDocketRecord.current_version,
                ),
            )
            .where(
                IpDocketRecord.company_id == context.company.id,
                func.lower(TrademarkApplication.jurisdiction) == key[1],
                func.lower(TrademarkApplication.office) == key[2],
                func.lower(
                    func.trim(IpTrademarkParticularVersion.representation_json["text"].as_string())
                )
                == key[3],
                applicant,
                one_applicant,
                func.json_array_length(IpTrademarkParticularVersion.classes_json) == len(key[5]),
                *predicates,
            )
            .limit(work_budget.remaining + 1)
        ).all()
        work_budget.charge(len(identifiers))
        if not identifiers:
            return []
        labels = dict(
            session.execute(
                select(IpDocketRecord.id, IpDocketRecord.title).where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.id.in_(identifiers[:10]),
                    visible_ip_dockets_filter(session, context=context),
                )
            ).all()
        )
        return [
            {
                "docket_id": identity,
                "title": labels[identity],
                "match_reasons": ["exact_portfolio_identity"],
            }
            if identity in labels
            else {"match_reasons": ["identity_unavailable"]}
            for identity in identifiers[:10]
        ]
    result = _duplicate_candidates_batch(
        session,
        context=context,
        normalized_rows=[normalized],
    ).get(key, [])
    if work_budget is not None:
        work_budget.charge(len(result))
    return result


def _apply_duplicate_defaults(
    session: Session,
    *,
    context: SessionContext,
    rows: list[IpImportRow],
) -> None:
    candidates = _duplicate_candidates_batch(
        session,
        context=context,
        normalized_rows=[row.normalized_json for row in rows if row.validation_status == "valid"],
    )
    admitted: dict[tuple, IpImportRow] = {}
    for row in rows:
        row.duplicate_candidates_json = []
        if row.validation_status != "valid":
            continue
        key = _duplicate_key(row.normalized_json)
        matches = list(candidates.get(key, []))
        prior = admitted.get(key) if key else None
        if prior is not None:
            matches.append(
                {
                    "staged_row_id": prior.id,
                    "row_number": prior.row_number,
                    "title": prior.normalized_json["title"],
                    "match_reasons": ["same_import"],
                }
            )
        row.duplicate_candidates_json = matches
        row.reconciliation_decision = "skip" if matches else None
        row.reconciled_target_docket_id = None
        # Invalid/skipped rows must never reserve the next row's identity.
        if key and not matches:
            admitted[key] = row


def _job_record(job: BulkImportJob) -> IpImportJobRecord:
    return IpImportJobRecord(
        id=job.id,
        domain=job.domain,
        filename=job.filename,
        source_sha256=job.source_sha256,
        status=job.status,
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        committed_rows=job.committed_rows,
        failed_rows=job.failed_rows,
        preview_token=job.preview_token,
        preview_expires_at=job.preview_expires_at,
        committed_at=job.committed_at,
        creator_label_snapshot=job.creator_label_snapshot,
        version=job.version,
        created_at=job.created_at,
        recovery_available=bool(job.idempotency_key and job.status in {"staged", "preview_ready"}),
        commit_batch_size=COMMIT_BATCH_SIZE,
    )


def _row_record(row: IpImportRow) -> IpImportRowRecord:
    return IpImportRowRecord(
        id=row.id,
        row_number=row.row_number,
        validation_status=row.validation_status,
        errors=list(row.errors_json or []),
        commit_status=row.commit_status,
        commit_error_code=row.commit_error_code,
        created_docket_id=row.created_docket_id,
        normalized=dict(row.normalized_json or {}),
        duplicate_candidates=list(row.duplicate_candidates_json or []),
        reconciliation_decision=row.reconciliation_decision,
        reconciled_target_docket_id=row.reconciled_target_docket_id,
    )


def _rows(session: Session, job: BulkImportJob) -> list[IpImportRow]:
    return list(
        session.scalars(
            select(IpImportRow)
            .where(IpImportRow.job_id == job.id, IpImportRow.company_id == job.company_id)
            .order_by(IpImportRow.row_number)
        ).all()
    )


def _job_or_404(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    for_update: bool = False,
) -> BulkImportJob:
    statement = select(BulkImportJob).where(
        BulkImportJob.id == job_id,
        BulkImportJob.company_id == context.company.id,
        BulkImportJob.domain == DOMAIN,
    )
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if job is None or job.created_by_membership_id != context.membership.id:
        raise HTTPException(status_code=404, detail="Import job not found.")
    return job


def create_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    payload: IpImportJobCreateRequest,
) -> IpImportPreviewResponse:
    """Stage and validate rows; nothing is written to the portfolio yet."""

    numbers = [row.row_number for row in payload.rows]
    if len(set(numbers)) != len(numbers):
        raise HTTPException(status_code=422, detail="Duplicate row numbers in import.")

    digest = (
        getattr(payload, "source_sha256", None)
        or sha256(
            "|".join(
                f"{row.row_number}:{sorted(row.values.items())}" for row in payload.rows
            ).encode()
        ).hexdigest()
    )
    now = _now()
    job = BulkImportJob(
        company_id=context.company.id,
        domain=DOMAIN,
        filename=payload.filename,
        source_sha256=digest,
        status="preview_ready",
        total_rows=len(payload.rows),
        preview_token=token_hex(16),
        preview_expires_at=now + PREVIEW_TTL,
        created_by_membership_id=context.membership.id,
        creator_label_snapshot=context.user.full_name or context.user.email,
        version=1,
    )
    session.add(job)
    session.flush()

    valid = invalid = 0
    workspace_defaults = _workspace_import_defaults(session, context=context)
    staged_rows: list[IpImportRow] = []
    for item in payload.rows:
        normalized, errors = _validate_row(
            session,
            context=context,
            values=item.values,
            workspace_defaults=workspace_defaults,
        )
        if errors:
            invalid += 1
        else:
            valid += 1
        row = IpImportRow(
            company_id=context.company.id,
            job_id=job.id,
            row_number=item.row_number,
            raw_json={key: source_value(value) for key, value in item.values.items()},
            normalized_json=normalized,
            validation_status="invalid" if errors else "valid",
            errors_json=errors,
            duplicate_candidates_json=[],
            commit_status="pending",
        )
        session.add(row)
        staged_rows.append(row)
    session.flush()
    _apply_duplicate_defaults(session, context=context, rows=staged_rows)
    job.valid_rows = valid
    job.invalid_rows = invalid

    record_from_context(
        session,
        context,
        action="ip.import.staged",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={
            "domain": DOMAIN,
            "filename": payload.filename,
            "total_rows": job.total_rows,
            "valid_rows": valid,
            "invalid_rows": invalid,
        },
    )
    session.commit()
    session.refresh(job)
    return IpImportPreviewResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        preview_expired=False,
    )


def preview_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> IpImportPreviewResponse:
    job = _job_or_404(session, context=context, job_id=job_id)
    expires = _aware(job.preview_expires_at)
    return IpImportPreviewResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        preview_expired=bool(expires and expires <= _now()),
    )


def revalidate_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> IpImportPreviewResponse:
    """Refresh an expired preview while excluding a concurrent commit."""

    resource = f"ip-import-job:{context.company.id}:{job_id}"
    with _import_commit_locks(session, f"ip-import-tenant:{context.company.id}", resource):
        return _revalidate_ip_import_job_locked(
            session,
            context=context,
            job_id=job_id,
        )


def _revalidate_ip_import_job_locked(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> IpImportPreviewResponse:
    """UJ-02-EXC-01 — refresh an expired preview against current data."""

    from caseops_api.services.private_retrieval import lock_private_authority_writer

    lock_private_authority_writer(session, company_id=context.company.id)
    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)
    if job.status in {"committed", "committed_with_errors", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A terminal import job cannot be revalidated.",
        )
    valid = invalid = 0
    rows = _rows(session, job)
    workspace_defaults = _workspace_import_defaults(session, context=context)
    for row in rows:
        if row.commit_status != "pending":
            valid += row.validation_status == "valid"
            invalid += row.validation_status != "valid"
            continue
        recovered = (
            _recover_materialized_docket(session, context=context, row_id=row.id)
            if job.idempotency_key
            else None
        )
        if recovered is not None:
            row.commit_status = "committed"
            row.created_docket_id = recovered.id
            valid += 1
            continue
        normalized, errors = _validate_row(
            session,
            context=context,
            values=row.raw_json,
            workspace_defaults=workspace_defaults,
        )
        row.normalized_json = normalized
        row.errors_json = errors
        row.validation_status = "invalid" if errors else "valid"
        row.duplicate_candidates_json = []
        row.reconciliation_decision = None
        row.reconciled_target_docket_id = None
        if errors:
            invalid += 1
        else:
            valid += 1
    _apply_duplicate_defaults(
        session,
        context=context,
        rows=[row for row in rows if row.commit_status == "pending"],
    )
    job.valid_rows = valid
    job.invalid_rows = invalid
    job.committed_rows = sum(row.commit_status == "committed" for row in rows)
    job.status = "preview_ready"
    job.preview_token = token_hex(16)
    job.preview_expires_at = _now() + PREVIEW_TTL
    job.version += 1

    record_from_context(
        session,
        context,
        action="ip.import.revalidated",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={"valid_rows": valid, "invalid_rows": invalid, "version": job.version},
    )
    session.commit()
    session.refresh(job)
    return IpImportPreviewResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        preview_expired=False,
    )


def reconcile_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    payload: IpImportReconciliationRequest,
) -> IpImportPreviewResponse:
    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)
    if job.status != "preview_ready":
        raise HTTPException(
            status_code=409,
            detail="Only a preview-ready import can be reconciled.",
        )
    if job.version != payload.expected_job_version:
        raise HTTPException(status_code=409, detail="The import preview changed; reload it.")
    decision_ids = [decision.row_id for decision in payload.decisions]
    if len(decision_ids) != len(set(decision_ids)):
        raise HTTPException(status_code=422, detail="Each import row may be decided once.")
    rows = {row.id: row for row in _rows(session, job)}
    for decision in payload.decisions:
        row = rows.get(decision.row_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Import row not found.")
        key = _duplicate_key(row.normalized_json or {})
        if (
            decision.decision == "create_separate"
            and key
            and key[0] == "application"
            and row.duplicate_candidates_json
        ):
            raise HTTPException(
                409,
                {
                    "code": "ip_import_exact_identity_conflict",
                    "message": (
                        "This application identity already exists. "
                        "Skip it or link its accessible record."
                    ),
                },
            )
        if not row.duplicate_candidates_json:
            raise HTTPException(status_code=409, detail="This row has no duplicate candidates.")
        if decision.decision == "link_existing":
            allowed_targets = {
                candidate.get("docket_id")
                for candidate in row.duplicate_candidates_json
                if candidate.get("docket_id")
            }
            if decision.target_docket_id not in allowed_targets:
                raise HTTPException(
                    status_code=409,
                    detail="The selected target is not an accessible duplicate candidate.",
                )
            target = session.scalar(
                select(IpDocketRecord).where(
                    IpDocketRecord.id == decision.target_docket_id,
                    IpDocketRecord.company_id == context.company.id,
                    visible_ip_dockets_filter(session, context=context),
                )
            )
            if target is None:
                raise HTTPException(status_code=404, detail="Duplicate target not found.")
            row.reconciled_target_docket_id = target.id
        elif decision.target_docket_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Only link_existing accepts a target docket.",
            )
        else:
            row.reconciled_target_docket_id = None
        row.reconciliation_decision = decision.decision
    job.preview_token = token_hex(16)
    job.preview_expires_at = _now() + PREVIEW_TTL
    job.version += 1
    record_from_context(
        session,
        context,
        action="ip.import.duplicates_reconciled",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={
            "decision_count": len(payload.decisions),
            "job_version": job.version,
        },
    )
    session.commit()
    session.refresh(job)
    return IpImportPreviewResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        preview_expired=False,
    )


def list_ip_import_jobs(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 50,
) -> list[IpImportJobRecord]:
    jobs = session.scalars(
        select(BulkImportJob)
        .where(
            BulkImportJob.company_id == context.company.id,
            BulkImportJob.domain == DOMAIN,
            BulkImportJob.created_by_membership_id == context.membership.id,
        )
        .order_by(BulkImportJob.created_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return [_job_record(job) for job in jobs]


def ip_import_error_report(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> bytes:
    job = _job_or_404(session, context=context, job_id=job_id)
    if job.created_by_membership_id != context.membership.id:
        raise HTTPException(status_code=404, detail="Import job not found.")
    output = io.StringIO(newline="")
    fieldnames = [
        "row_number",
        "validation_status",
        "validation_errors",
        "duplicate_candidates",
        "reconciliation_decision",
        "commit_status",
        "commit_error_code",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in _rows(session, job):
        writer.writerow(
            csv_safe_mapping(
                {
                    "row_number": row.row_number,
                    "validation_status": row.validation_status,
                    "validation_errors": "; ".join(
                        f"{error.get('field')}:{error.get('code')}"
                        for error in row.errors_json or []
                    ),
                    "duplicate_candidates": "; ".join(
                        str(candidate.get("docket_id") or candidate.get("staged_row_id"))
                        for candidate in row.duplicate_candidates_json or []
                    ),
                    "reconciliation_decision": row.reconciliation_decision or "",
                    "commit_status": row.commit_status,
                    "commit_error_code": row.commit_error_code or "",
                }
            )
        )
    record_from_context(
        session,
        context,
        action="ip.import.error_report_downloaded",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={"total_rows": job.total_rows},
    )
    session.commit()
    return output.getvalue().encode("utf-8-sig")


def _particulars_for(normalized: dict[str, Any], *, row_id: str) -> IpImportParticularPayload:
    return IpImportParticularPayload(
        form_key="TM-A",
        form_version="2026.1",
        mark_kind=normalized.get("representation_kind") or "other",
        representation={
            **({"text": normalized["mark_text"]} if normalized.get("mark_text") else {}),
            "portfolio_import": {
                "source_row_id": row_id,
                **{
                    field: normalized[field]
                    for field in (
                        "application_date",
                        "renewal_due_date",
                        "source_status",
                        "declared_status",
                        "image_reference",
                    )
                    if normalized.get(field) is not None
                },
            },
        },
        classes=[
            {"class_number": number, "specification": normalized.get("specification") or ""}
            for number in normalized.get("class_numbers", [])
        ],
        parties=(
            [{"role": "applicant", "name": normalized["applicant_name"]}]
            if normalized.get("applicant_name")
            else []
        ),
        agent={"name": normalized["agent_name"]} if normalized.get("agent_name") else None,
        # Imported particulars stay unverified until someone attaches the
        # source evidence; a mark the source says is already filed is
        # verified against the registry record, not prepared for filing.
        filing_manifest=[
            {
                "key": "portfolio_source_review",
                "label": (
                    "Verify imported source against the registry record"
                    if normalized.get("filing_phase") == "filed"
                    else "Verify imported source before filing"
                ),
                "required": True,
                "evidence_reference": None,
            }
        ],
    )


def _set_row_outcome(
    session: Session,
    *,
    row_id: str,
    commit_status: str,
    error_code: str | None = None,
    docket_id: str | None = None,
) -> None:
    """Persist one row's commit outcome in its own transaction."""

    row = session.get(IpImportRow, row_id)
    assert row is not None
    row.commit_status = commit_status
    row.commit_error_code = error_code
    row.created_docket_id = docket_id
    session.commit()


def _import_docket_id(row_id: str) -> str:
    """Stable materialization id derived from the durable staging-row owner."""

    return str(uuid5(NAMESPACE_URL, f"caseops:ip-import-row:{row_id}"))


def _recover_materialized_docket(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
) -> IpDocketRecord | None:
    """Reuse a docket committed before its staging-row outcome was recorded.

    The deterministic docket id and source audit event are committed in the
    canonical writer's transaction. Seeing both proves that this exact import
    row materialized the docket; a same-key retry can therefore repair the row
    outcome without invoking the writer again.
    """

    docket_id = _import_docket_id(row_id)
    docket = session.scalar(
        select(IpDocketRecord).where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
    )
    if docket is None:
        return None
    provenance = session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.company_id == context.company.id,
            AuditEvent.action == IMPORT_MATERIALIZATION_ACTION,
            AuditEvent.target_type == "ip_import_row",
            AuditEvent.target_id == row_id,
            AuditEvent.ip_docket_id == docket.id,
        )
    )
    if provenance is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_import_materialization_provenance_missing",
                "message": "A reserved docket exists without matching import provenance.",
            },
        )
    return docket


def _preflight_materialized_dockets(
    session: Session,
    *,
    context: SessionContext,
    rows: list[IpImportRow],
) -> dict[str, bool]:
    """Read scalar recovery facts; the caller applies errors in source-row order."""

    pending = [
        (row.id, _import_docket_id(row.id))
        for row in rows
        if row.commit_status == "pending" and row.validation_status == "valid"
    ]
    if not pending:
        return {}
    candidates = values(
        column("row_id", String(36)),
        column("docket_id", String(36)),
    ).data(pending).cte("ip_import_preflight_candidates")
    matched_docket = (
        select(IpDocketRecord.id)
        .where(
            IpDocketRecord.id == candidates.c.docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
        .correlate(candidates)
        .limit(1)
        .scalar_subquery()
    )
    # Scalar limited lookups retain candidate-bound seeks instead of allowing
    # a join or hashed EXISTS to read the tenant's full docket/receipt history.
    receipt = (
        select(1)
        .select_from(AuditEvent)
        .where(
            AuditEvent.company_id == context.company.id,
            AuditEvent.action == IMPORT_MATERIALIZATION_ACTION,
            AuditEvent.target_type == "ip_import_row",
            AuditEvent.target_id == candidates.c.row_id,
            AuditEvent.ip_docket_id == candidates.c.docket_id,
        )
        .correlate(candidates)
        .limit(1)
        .scalar_subquery()
    )
    statement = select(candidates.c.row_id, receipt.is_not(None)).where(
        matched_docket.is_not(None)
    )
    return {row_id: proven for row_id, proven in session.execute(statement)}


def _materialize_import_row(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
    normalized: dict[str, Any],
) -> IpDocketRecord:
    from caseops_api.services.private_retrieval import lock_private_authority_writer

    # Each canonical writer may commit; every next row needs fresh admission.
    with session.no_autoflush:
        lock_private_authority_writer(session, company_id=context.company.id)
    docket = _recover_materialized_docket(
        session,
        context=context,
        row_id=row_id,
    )
    if docket is None:
        created = create_ip_docket(
            session,
            context=context,
            payload=IpImportDocketCreateRequest(
                title=normalized["title"],
                matter_id=normalized.get("matter_id"),
                primary_identifier=normalized.get("application_number"),
                restricted=False,
                particulars=_particulars_for(normalized, row_id=row_id),
            ),
            docket_id=_import_docket_id(row_id),
            source_provenance=("ip_import_row", row_id),
            commit=False,
        )
        docket = session.get(IpDocketRecord, created.id)
        assert docket is not None
    asset = session.scalar(
        select(IpAsset).where(
            IpAsset.company_id == context.company.id,
            IpAsset.docket_id == docket.id,
        )
    )
    if asset is None:
        asset = create_ip_asset(
            session,
            context=context,
            docket_id=docket.id,
            payload=IpAssetCreateRequest(
                jurisdiction=normalized["jurisdiction"],
                title=normalized.get("mark_text") or normalized["title"],
            ),
            commit=False,
        )
    application_number = normalized.get("application_number")
    application = session.scalar(
        select(TrademarkApplication).where(
            TrademarkApplication.company_id == context.company.id,
            TrademarkApplication.docket_id == docket.id,
            TrademarkApplication.asset_id == asset.id,
        )
    )
    if application is None:
        create_trademark_application(
            session,
            context=context,
            docket_id=docket.id,
            payload=TrademarkApplicationCreateRequest(
                asset_id=asset.id,
                office=normalized["office"],
                jurisdiction=normalized["jurisdiction"],
                filing_phase=normalized.get("filing_phase", "draft"),
                application_number=(
                    IpApplicationNumberCreate(
                        raw_value=application_number,
                        source="portfolio_import",
                        effective_from=date.today(),
                    )
                    if application_number
                    else None
                ),
            ),
            commit=False,
        )
    from caseops_api.services.ip_renewals import schedule_imported_renewal_reminder

    # A source that says the mark was refused, abandoned, withdrawn or
    # removed gets no renewal alert; the row says so in its preview notes.
    reminder = (
        None
        if normalized.get("declared_status") in TERMINAL_SOURCE_STATUSES
        else schedule_imported_renewal_reminder(
            session,
            context=context,
            docket_id=docket.id,
            row_id=row_id,
            normalized=normalized,
        )
    )
    source_row = session.get(IpImportRow, row_id)
    assert source_row is not None
    source_row.normalized_json = {
        **normalized,
        "_renewal_reminder": {
            "status": str(reminder.status) if reminder else "not_scheduled",
            "scheduled_for": reminder.scheduled_for.isoformat() if reminder else None,
            "intent_id": reminder.id if reminder else None,
        },
    }
    session.commit()
    return docket


def commit_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    payload: IpImportCommitRequest,
) -> IpImportCommitResponse:
    """Materialise valid rows through the canonical docket writer.

    Idempotent by ``idempotency_key``: a repeated commit returns the original
    terminal result without creating a second record (UJ-02-EXC-03).
    """

    job_resource = f"ip-import-job:{context.company.id}:{job_id}"
    key_resource = f"ip-import-key:{context.company.id}:{DOMAIN}:{payload.idempotency_key}"
    tenant_resource = f"ip-import-tenant:{context.company.id}"
    with _import_commit_locks(session, tenant_resource, job_resource, key_resource) as claim_check:
        return _commit_ip_import_job_locked(
            session,
            context=context,
            job_id=job_id,
            payload=payload,
            claim_check=claim_check,
        )


def resume_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    payload: IpImportResumeRequest,
) -> IpImportCommitResponse:
    from caseops_api.services.private_retrieval import lock_private_authority_writer

    with _import_commit_locks(
        session,
        f"ip-import-tenant:{context.company.id}",
        f"ip-import-job:{context.company.id}:{job_id}",
    ) as claim_check:
        lock_private_authority_writer(session, company_id=context.company.id)
        job = _job_or_404(session, context=context, job_id=job_id, for_update=True)
        if job.version != payload.expected_job_version:
            raise HTTPException(409, "The import changed; reload its current history.")
        if not job.idempotency_key or job.status not in {"staged", "preview_ready"}:
            raise HTTPException(409, "This import has no recoverable commit claim.")
        return _commit_ip_import_job_locked(
            session,
            context=context,
            job_id=job_id,
            payload=IpImportCommitRequest(
                idempotency_key=job.idempotency_key,
                preview_token=payload.preview_token or "retained-claim",
            ),
            claim_check=claim_check,
        )


def _commit_ip_import_job_locked(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    payload: IpImportCommitRequest,
    claim_check: Callable[[], None] | None = None,
) -> IpImportCommitResponse:
    """Commit while the job and tenant/idempotency-key locks are held."""

    from caseops_api.services.private_retrieval import lock_private_authority_writer

    # The outer advisory claims precede Company; the resumable job follows it.
    with session.no_autoflush:
        lock_private_authority_writer(session, company_id=context.company.id)
    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)

    if job.status in {"committed", "committed_with_errors"}:
        if job.idempotency_key and job.idempotency_key == payload.idempotency_key:
            return IpImportCommitResponse(
                job=_job_record(job),
                rows=[_row_record(row) for row in _rows(session, job)],
                replayed=True,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This import job has already been committed.",
        )
    if job.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Import job is cancelled.")

    staged_rows = _rows(session, job)
    if not job.idempotency_key and not any(row.validation_status == "valid" for row in staged_rows):
        raise HTTPException(
            409,
            {
                "code": "ip_import_no_eligible_rows",
                "message": (
                    "No usable rows can be committed. Correct the source and validate it again."
                ),
            },
        )
    defaults = _workspace_import_defaults(session, context=context)
    materialized = (
        _preflight_materialized_dockets(session, context=context, rows=staged_rows)
        if job.idempotency_key
        else {}
    )
    for row in staged_rows:
        if row.commit_status != "pending" or row.validation_status != "valid":
            continue
        if row.id in materialized:
            if not materialized[row.id]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ip_import_materialization_provenance_missing",
                        "message": "A reserved docket exists without matching import provenance.",
                    },
                )
            continue
        derived = {
            item["field"]
            for item in (row.normalized_json or {}).get("_warnings", [])
            if item.get("code") == "configured_workspace_context"
        }
        if any(defaults.get(field) != row.normalized_json.get(field) for field in derived):
            raise HTTPException(
                409,
                {
                    "code": "ip_import_preview_context_changed",
                    "message": (
                        "Workspace jurisdiction or office changed. Refresh and review the preview."
                    ),
                },
            )
    del materialized  # Never reuse preflight facts across the row writer's commits.
    if job.idempotency_key and job.idempotency_key != payload.idempotency_key:
        raise HTTPException(409, "Recover this import using its retained creator-authorized claim.")

    key_owner = session.scalar(
        select(BulkImportJob).where(
            BulkImportJob.company_id == context.company.id,
            BulkImportJob.domain == DOMAIN,
            BulkImportJob.idempotency_key == payload.idempotency_key,
            BulkImportJob.id != job.id,
        )
    )
    if key_owner is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_import_idempotency_key_reused",
                "message": "This idempotency key belongs to a different import job.",
            },
        )

    resuming = job.status == "staged" and bool(job.idempotency_key)
    if resuming:
        if job.idempotency_key != payload.idempotency_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This import is already claimed by a different idempotency key.",
            )
    else:
        if job.status != "preview_ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This import job is not ready to commit.",
            )
        if not job.preview_token or payload.preview_token != job.preview_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Import preview changed; preview again.",
            )
        expires = _aware(job.preview_expires_at)
        if expires and expires <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_import_preview_expired",
                    "message": "The import preview expired and must be revalidated.",
                },
            )

        # Persist the ownership claim before the canonical row writer starts
        # committing. If the worker exits between rows, the same key can resume
        # rows whose outcomes are still pending; a different key cannot.
        job.status = "staged"
        job.idempotency_key = payload.idempotency_key
        job.preview_token = None
        job.preview_expires_at = None
        job.version += 1
        session.commit()

    # The canonical docket writer commits per call, so each row's outcome is
    # persisted immediately. UJ-02-EXC-02: a later row that fails and rolls back
    # its own partial write cannot discard an already-recorded sibling result.
    plan = [
        (
            row.id,
            row.validation_status,
            row.commit_status,
            dict(row.normalized_json or {}),
            row.reconciliation_decision,
            row.reconciled_target_docket_id,
        )
        for row in _rows(session, job)
        if row.commit_status == "pending"
    ]
    duplicate_work = _DuplicateWorkBudget(remaining=COMMIT_BATCH_SIZE * 10)
    for (
        row_id,
        validation_status,
        commit_status,
        normalized,
        reconciliation_decision,
        _reconciled_target_docket_id,
    ) in plan[:COMMIT_BATCH_SIZE]:
        if claim_check is not None:
            claim_check()
        if commit_status in {"committed", "failed", "skipped"}:
            continue
        if validation_status != "valid":
            _set_row_outcome(session, row_id=row_id, commit_status="skipped")
            continue
        if reconciliation_decision == "skip":
            _set_row_outcome(
                session,
                row_id=row_id,
                commit_status="skipped",
                error_code="duplicate_skipped",
            )
            continue
        if reconciliation_decision == "link_existing":
            from caseops_api.services.ip_operations import _docket_or_404

            try:
                _docket_or_404(
                    session,
                    context=context,
                    docket_id=_reconciled_target_docket_id,
                    for_update=True,
                )
            except HTTPException:
                session.rollback()
                _set_row_outcome(
                    session,
                    row_id=row_id,
                    commit_status="failed",
                    error_code="target_unavailable",
                )
                continue
            _set_row_outcome(
                session,
                row_id=row_id,
                commit_status="committed",
                docket_id=None,
            )
            continue
        try:
            # Re-admit source cells and current identity under tenant authority.
            with session.no_autoflush:
                lock_private_authority_writer(session, company_id=context.company.id)
            row = session.get(IpImportRow, row_id)
            assert row is not None
            normalized, errors = _validate_row(
                session,
                context=context,
                values=row.raw_json,
                workspace_defaults={
                    field: normalized[field]
                    for field in ("jurisdiction", "office")
                    if normalized.get(field)
                },
            )
            if errors:
                raise HTTPException(409, {"code": "source_revalidation_failed"})
            recovered = _recover_materialized_docket(
                session,
                context=context,
                row_id=row_id,
            )
            duplicate_key = _duplicate_key(normalized)
            separate_fallback = bool(
                reconciliation_decision == "create_separate"
                and duplicate_key
                and duplicate_key[0] == "portfolio"
            )
            if (
                recovered is None
                and not separate_fallback
                and _duplicate_candidates(
                    session,
                    context=context,
                    normalized=normalized,
                    work_budget=duplicate_work,
                )
            ):
                _set_row_outcome(
                    session,
                    row_id=row_id,
                    commit_status="skipped",
                    error_code="duplicate_skipped",
                )
                continue
            docket = _materialize_import_row(
                session,
                context=context,
                row_id=row_id,
                normalized=normalized,
            )
        except HTTPException as exc:
            # Discard any partial write the rejected call had flushed.
            session.rollback()
            _set_row_outcome(
                session,
                row_id=row_id,
                commit_status="failed",
                error_code=(
                    str(exc.detail.get("code", "commit_rejected"))
                    if isinstance(exc.detail, dict)
                    else "commit_rejected"
                ),
            )
            continue
        if claim_check is not None:
            claim_check()
        _set_row_outcome(session, row_id=row_id, commit_status="committed", docket_id=docket.id)

    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)

    final_rows = _rows(session, job)
    committed = sum(row.commit_status == "committed" for row in final_rows)
    failed = sum(row.commit_status == "failed" for row in final_rows)

    job.committed_rows = committed
    job.failed_rows = failed
    pending = any(row.commit_status == "pending" for row in final_rows)
    job.status = "staged" if pending else "committed_with_errors" if failed else "committed"
    job.committed_at = None if pending else _now()
    job.preview_token = None
    job.version += 1

    record_from_context(
        session,
        context,
        action="ip.import.batch_committed" if pending else "ip.import.committed",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={
            "committed_rows": committed,
            "failed_rows": failed,
            "skipped_rows": sum(row.commit_status == "skipped" for row in final_rows),
            "idempotency_key": payload.idempotency_key,
            "status": job.status,
        },
    )
    session.commit()
    session.refresh(job)
    return IpImportCommitResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        replayed=False,
    )


__all__ = [
    "commit_ip_import_job",
    "create_ip_import_job",
    "ip_import_error_report",
    "list_ip_import_jobs",
    "preview_ip_import_job",
    "reconcile_ip_import_job",
    "revalidate_ip_import_job",
    "resume_ip_import_job",
]
