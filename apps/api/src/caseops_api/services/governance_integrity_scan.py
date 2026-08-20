"""Nightly retention and hold integrity scan (DATA-GOV-17).

The requirement names six checks: expired-unpurged, purged-still-searchable,
held-at-risk, orphan object/index, missing data-map, and provider-deletion
exceptions - reported "without exposing content".

Three of those cannot be evaluated yet, and the way that is reported is the
most important decision in this module.

A scan that returns "0 expired-unpurged" when it has no definition of *expired*
is worse than no scan. It reads as "nothing is overdue" when the truth is "we
cannot tell", and it is precisely the reassuring-zero that a detective control
exists to prevent. So every check reports one of three states:

    ok           checked, nothing found
    findings     checked, and here is what was found
    unavailable  NOT checked, and here is exactly what is missing

``unavailable`` is never collapsed into ``ok``, and the summary counts it
separately, so a green scan cannot be produced by a check that never ran.

Content minimisation: findings carry table names, data-class ids, counts and
record ids - never titles, party names, or document text. An operator needs to
know WHICH record is at risk, not what it says.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.repo_paths import repo_root_or_none
from caseops_api.db.models import Base, LegalHold, LegalHoldItem, LegalHoldStatus
from caseops_api.governance.data_class_projection import (
    admitted_data_class_ids,
    review_coverage,
)

CheckStatus = Literal["ok", "findings", "unavailable"]


@dataclass(frozen=True)
class IntegrityCheck:
    check_id: str
    status: CheckStatus
    summary: str
    # Ids and counts only. Never content.
    findings: tuple[str, ...] = ()
    blocked_by: str | None = None


@dataclass(frozen=True)
class IntegrityScanReport:
    checks: tuple[IntegrityCheck, ...] = field(default_factory=tuple)

    @property
    def ok_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "ok")

    @property
    def finding_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "findings")

    @property
    def unavailable_count(self) -> int:
        return sum(1 for check in self.checks if check.status == "unavailable")

    @property
    def is_complete(self) -> bool:
        """Whether every check actually ran.

        A caller must not read "no findings" as "healthy" while checks are
        unavailable - the two say very different things about the estate.
        """
        return self.unavailable_count == 0


def _registered_data_class_ids() -> set[str] | None:
    """Admitted ids, or None when the projection cannot be trusted.

    None rather than an empty set. An empty set here would make every active
    legal hold look unresolvable and report the estate as catastrophically
    broken, when the truth is that one artifact could not be read.
    """

    ids = admitted_data_class_ids()
    return None if ids is None else set(ids)


def _unavailable(check_id: str, summary: str, blocked_by: str) -> IntegrityCheck:
    return IntegrityCheck(
        check_id=check_id, status="unavailable", summary=summary, blocked_by=blocked_by
    )


def governance_map_path() -> pathlib.Path | None:
    """Where the committed data-governance map lives, if it is reachable.

    Resolved through a marker search rather than a fixed parent count. The
    original ``parents[5]`` worked in the checkout and raised IndexError in the
    container, where this module has only five parents - and it raised at
    IMPORT time, above the try/except below, so the "unavailable" answer that
    guard exists to give could never be reached in production.
    """
    root = repo_root_or_none(pathlib.Path(__file__))
    if root is None:
        return None
    return root / "docs" / "ip-implementation" / "DATA_GOVERNANCE_MAP.yaml"


def _governance_map_tables() -> set[str] | None:
    """Table names registered in the committed data-governance map.

    Returns ``None`` when the map is not reachable. The API image ships
    ``apps/api`` and not ``docs/``, so this check is repo-context only - and a
    check that cannot read its source must report unavailable rather than
    conclude that every table is unregistered, which would turn a packaging
    detail into 260 spurious findings.
    """
    path = governance_map_path()
    if path is None:
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {
        str(entry["table_name"])
        for entry in document.get("sql_tables", [])
        if isinstance(entry, dict) and entry.get("table_name")
    }


def _check_missing_data_map() -> IntegrityCheck:
    """Every SQL table must appear in the governance map."""
    registered = _governance_map_tables()
    if registered is None:
        return _unavailable(
            "missing_data_map",
            "cannot read the data-governance map from this runtime context",
            "map-not-packaged",
        )
    live = {table.name for table in Base.metadata.tables.values()}
    missing = sorted(live - registered)
    if missing:
        return IntegrityCheck(
            check_id="missing_data_map",
            status="findings",
            summary=f"{len(missing)} table(s) are not registered in the data-governance map",
            findings=tuple(missing),
        )
    return IntegrityCheck(
        check_id="missing_data_map",
        status="ok",
        summary=f"all {len(live)} tables are registered",
    )


def _check_held_at_risk(session: Session, *, company_id: str | None = None) -> IntegrityCheck:
    """Active holds whose coverage cannot be resolved to a registered class.

    A hold naming a data class the registry does not know is a hold nobody can
    enforce: the resolver will never match a target to it, so the preservation
    it promises does not happen.
    """
    registered = _registered_data_class_ids()
    if registered is None:
        # Without the reviewed projection every hold item would look
        # unresolvable, which would report the estate as broken when in fact one
        # artifact could not be read.
        return _unavailable(
            "held_at_risk",
            "cannot resolve hold coverage: the reviewed data-class projection is "
            "unavailable or stale",
            "data-class-projection",
        )
    statement = (
        select(LegalHoldItem.legal_hold_id, LegalHoldItem.data_class_id)
        .join(LegalHold, LegalHold.id == LegalHoldItem.legal_hold_id)
        .where(LegalHold.status == LegalHoldStatus.ACTIVE)
    )
    if company_id is not None:
        statement = statement.where(LegalHold.company_id == company_id)

    unresolvable = sorted(
        {
            f"{hold_id}:{data_class_id}"
            for hold_id, data_class_id in session.execute(statement).all()
            if data_class_id not in registered
        }
    )
    if unresolvable:
        return IntegrityCheck(
            check_id="held_at_risk",
            status="findings",
            summary=(
                f"{len(unresolvable)} active hold item(s) name a data class the registry "
                "does not know, so their coverage cannot be enforced"
            ),
            findings=tuple(unresolvable),
        )
    return IntegrityCheck(
        check_id="held_at_risk",
        status="ok",
        summary="every active hold item resolves to a registered data class",
    )


def _check_orphan_hold_items(session: Session, *, company_id: str | None = None) -> IntegrityCheck:
    """Hold items whose parent hold is no longer active.

    Preservation evidence pointing at a released or cancelled hold is not
    protecting anything, and it inflates any count of what is preserved.
    """
    statement = (
        select(LegalHoldItem.id)
        .join(LegalHold, LegalHold.id == LegalHoldItem.legal_hold_id)
        .where(LegalHold.status != LegalHoldStatus.ACTIVE)
    )
    if company_id is not None:
        statement = statement.where(LegalHold.company_id == company_id)

    orphans = sorted(row for (row,) in session.execute(statement).all())
    if orphans:
        return IntegrityCheck(
            check_id="orphan_hold_items",
            status="findings",
            summary=f"{len(orphans)} hold item(s) belong to a hold that is no longer active",
            findings=tuple(orphans),
        )
    return IntegrityCheck(
        check_id="orphan_hold_items",
        status="ok",
        summary="no hold items belong to an inactive hold",
    )


def _check_data_class_review_coverage(session: Session) -> IntegrityCheck:
    """How much of the inventoried estate carries a reviewed classification.

    The dry run admits six classes. The map inventories 271. Both numbers are
    true, and reporting only the first is how "we govern our data" becomes a
    claim nobody checked. This check exists so the remainder is a published
    count rather than an absence, and it cannot read ``ok`` while anything is
    unreviewed.
    """

    coverage = review_coverage(session)
    if coverage is None:
        return _unavailable(
            "data_class_review_coverage",
            "cannot measure review coverage: the reviewed data-class projection is "
            "unavailable or stale",
            "data-class-projection",
        )
    if coverage.unreviewed or coverage.undeclared_deployed_tables:
        findings = [
            f"unreviewed:{class_id}" for class_id in coverage.unreviewed_ids[:50]
        ] + [
            f"undeclared-deployed:{table}"
            for table in coverage.undeclared_deployed_tables[:50]
        ]
        return IntegrityCheck(
            check_id="data_class_review_coverage",
            status="findings",
            summary=(
                f"{coverage.reviewed} of {coverage.total} inventoried data classes "
                f"carry a reviewed classification; {coverage.unreviewed} do not"
                + (
                    f", and {len(coverage.undeclared_deployed_tables)} deployed "
                    "table(s) are not inventoried at all"
                    if coverage.undeclared_deployed_tables
                    else ""
                )
            ),
            findings=tuple(findings),
        )
    return IntegrityCheck(
        check_id="data_class_review_coverage",
        status="ok",
        summary=f"all {coverage.total} inventoried data classes are reviewed",
    )


def run_integrity_scan(session: Session, *, company_id: str | None = None) -> IntegrityScanReport:
    """Run every DATA-GOV-17 check, reporting unavailable ones as unavailable."""
    return IntegrityScanReport(
        checks=(
            _check_missing_data_map(),
            _check_data_class_review_coverage(session),
            _check_held_at_risk(session, company_id=company_id),
            _check_orphan_hold_items(session, company_id=company_id),
            # The three that cannot run. Each names its blocker rather than
            # returning a zero that would read as a clean bill of health.
            _unavailable(
                "expired_unpurged",
                "cannot determine what is expired: no approved retention schedule exists",
                "DATA-GOV-02",
            ),
            _unavailable(
                "purged_still_searchable",
                "cannot determine what was purged: no purge execute path exists",
                "DATA-GOV-08",
            ),
            _unavailable(
                "provider_deletion_exceptions",
                "cannot determine provider deletion state: no provider deletion path exists",
                "DATA-GOV-09",
            ),
        )
    )
