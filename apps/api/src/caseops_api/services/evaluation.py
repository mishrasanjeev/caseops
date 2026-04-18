"""Evaluation run + case recording (§7.3).

A deliberately thin service: the drafting / recommendation / hearing
pipelines call into this layer to say "I just generated output X; here
are the validator findings", and we persist enough to answer later
questions like "did the last prompt change raise the blocker rate?"

The service does not itself drive a benchmark loop — that belongs to a
CLI or a notebook that can stand up a tenant context. What we keep
here are the primitives:

- ``open_run`` — create a fresh ``EvaluationRun``.
- ``record_case`` — append an ``EvaluationCase`` to an open run.
- ``finalize_run`` — roll aggregates up + stamp ``completed_at``.

Metrics that matter at v1 are intentionally small: pass / fail counts,
blocker total, warning total. More come in as we learn what regresses
in practice.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import EvaluationCase, EvaluationRun
from caseops_api.services.draft_validators import DraftFinding


logger = logging.getLogger(__name__)


@dataclass
class CaseMetrics:
    """Per-case metrics that the drafting pipeline (or any caller) can
    hand to ``record_case``. Fields are optional so callers from other
    pipelines need not pretend every metric applies to them."""

    body_chars: int = 0
    verified_citation_count: int = 0
    extra: dict[str, object] = field(default_factory=dict)


CASE_STATUS_PASS = "pass"
CASE_STATUS_FAIL = "fail"
CASE_STATUS_ERROR = "error"


def _findings_summary(findings: Iterable[DraftFinding]) -> tuple[int, int, list[dict]]:
    blockers = 0
    warnings = 0
    serialised: list[dict] = []
    for f in findings:
        if f.severity == "blocker":
            blockers += 1
        elif f.severity == "warning":
            warnings += 1
        serialised.append({"code": f.code, "severity": f.severity, "message": f.message})
    return blockers, warnings, serialised


def open_run(
    session: Session,
    *,
    suite_name: str,
    provider: str,
    model: str,
    git_sha: str | None = None,
) -> EvaluationRun:
    """Start a new evaluation run. Caller commits when ready."""
    now = datetime.now(UTC)
    run = EvaluationRun(
        suite_name=suite_name,
        provider=provider,
        model=model,
        git_sha=git_sha,
        case_count=0,
        pass_count=0,
        fail_count=0,
        started_at=now,
        created_at=now,
    )
    session.add(run)
    session.flush()
    return run


def record_case(
    session: Session,
    *,
    run: EvaluationRun,
    case_key: str,
    findings: Iterable[DraftFinding],
    metrics: CaseMetrics | None = None,
    error: str | None = None,
) -> EvaluationCase:
    """Persist one case's result under the open run.

    A case is a fail if any ``findings`` has severity ``blocker`` OR
    an ``error`` was supplied. Warnings do not fail the case —
    they are signal, not policy. (The review workflow is the policy
    backstop.)
    """
    blockers, warnings, serialised = _findings_summary(findings)
    metrics = metrics or CaseMetrics()

    status = CASE_STATUS_PASS
    if error:
        status = CASE_STATUS_ERROR
    elif blockers > 0:
        status = CASE_STATUS_FAIL

    payload: dict[str, object] = {"findings": serialised}
    if metrics.extra:
        payload["extra"] = metrics.extra

    case = EvaluationCase(
        run_id=run.id,
        case_key=case_key,
        status=status,
        blocker_count=blockers,
        warning_count=warnings,
        findings_json=json.dumps(payload, separators=(",", ":")),
        body_chars=metrics.body_chars,
        verified_citation_count=metrics.verified_citation_count,
        error=error,
    )
    session.add(case)
    session.flush()
    return case


def finalize_run(session: Session, run: EvaluationRun) -> EvaluationRun:
    """Roll per-case counts into the run aggregates and stamp
    ``completed_at``. Idempotent — safe to call after each case if the
    caller prefers streaming progress."""
    by_status = session.execute(
        select(EvaluationCase.status, func.count(EvaluationCase.id))
        .where(EvaluationCase.run_id == run.id)
        .group_by(EvaluationCase.status)
    ).all()
    counts = {row[0]: int(row[1]) for row in by_status}
    case_count = sum(counts.values())
    pass_count = counts.get(CASE_STATUS_PASS, 0)
    fail_count = counts.get(CASE_STATUS_FAIL, 0) + counts.get(CASE_STATUS_ERROR, 0)

    # Metric means for the drafting suite — keep the body small so
    # we can eyeball a run later.
    metric_totals = session.execute(
        select(
            func.coalesce(func.avg(EvaluationCase.body_chars), 0),
            func.coalesce(func.avg(EvaluationCase.verified_citation_count), 0),
            func.coalesce(func.sum(EvaluationCase.blocker_count), 0),
            func.coalesce(func.sum(EvaluationCase.warning_count), 0),
        ).where(EvaluationCase.run_id == run.id)
    ).one()
    metrics = {
        "avg_body_chars": float(metric_totals[0] or 0.0),
        "avg_verified_citations": float(metric_totals[1] or 0.0),
        "total_blockers": int(metric_totals[2] or 0),
        "total_warnings": int(metric_totals[3] or 0),
        "by_status": counts,
    }

    run.case_count = case_count
    run.pass_count = pass_count
    run.fail_count = fail_count
    run.metrics_json = json.dumps(metrics, separators=(",", ":"))
    run.completed_at = datetime.now(UTC)
    session.flush()
    return run


__all__ = [
    "CASE_STATUS_ERROR",
    "CASE_STATUS_FAIL",
    "CASE_STATUS_PASS",
    "CaseMetrics",
    "finalize_run",
    "open_run",
    "record_case",
]
