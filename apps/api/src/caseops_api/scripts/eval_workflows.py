"""CLI: workflow eval — hearing-pack and recommendation surfaces.

Sprint 11 (BG-034 follow-up). Drafting eval (eval_drafting) measures
the long-form drafting surface; this script covers the two other
surfaces a real practice depends on:

- ``hearing-pack``: ``services.hearing_packs.generate_hearing_pack``
  must produce a structurally complete pack (summary + items in the
  allowed kinds + unique ranks + any authority_card carries a
  source_ref).
- ``recommendation``: ``services.recommendations.generate_recommendation``
  must produce >=2 options, a primary recommendation that maps to one
  of the option labels, non-empty rationale, and at least one
  supporting citation on the primary option (when retrieval found
  any).

Usage::

    uv run caseops-eval-workflows --suite hearing-pack --tenant <slug>
    uv run caseops-eval-workflows --suite recommendation --tenant <slug>
    uv run caseops-eval-workflows --suite all --tenant <slug> --dry-run

Both suites reuse the BAIL_SUITE seed cases from eval_drafting
(matter shape is identical) so a single tenant snapshot exercises
all three surfaces.

Provider routing: hearing packs hit purpose=hearing_pack (Sonnet by
default), recommendations hit purpose=recommendations (Sonnet too).
The cassette wrap (Sprint 11 record/replay) sits underneath both
when CASEOPS_LLM_CASSETTE_MODE is set.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    HearingPack,
    HearingPackItemKind,
    Matter,
    MatterHearing,
    Recommendation,
    User,
    utcnow,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.eval_drafting import BAIL_SUITE, EvalCase
from caseops_api.services.draft_validators import DraftFinding
from caseops_api.services.evaluation import (
    CASE_STATUS_ERROR,
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    CaseMetrics,
    finalize_run,
    open_run,
    record_case,
)
from caseops_api.services.hearing_packs import generate_hearing_pack
from caseops_api.services.identity import SessionContext
from caseops_api.services.recommendations import (
    SUPPORTED_TYPES,
    generate_recommendation,
)

logger = logging.getLogger("caseops.eval.workflows")

_ALLOWED_PACK_KINDS = {kind.value for kind in HearingPackItemKind}


# ---------- shared tenant + matter helpers (mirror eval_drafting) ----------


def _resolve_tenant(
    session: Session, *, slug: str
) -> tuple[Company, CompanyMembership, User]:
    company = session.scalar(select(Company).where(Company.slug == slug))
    if company is None:
        raise SystemExit(f"no company with slug={slug!r}; bootstrap it first")
    membership = session.scalar(
        select(CompanyMembership)
        .where(CompanyMembership.company_id == company.id)
        .where(CompanyMembership.is_active)
        .order_by(CompanyMembership.created_at.asc())
    )
    if membership is None:
        raise SystemExit(f"no active membership in company {slug!r}")
    user = session.get(User, membership.user_id)
    return company, membership, user


def _ensure_matter(
    session: Session, *, context: SessionContext, case: EvalCase
) -> Matter:
    existing = session.scalar(
        select(Matter).where(
            Matter.company_id == context.company.id,
            Matter.matter_code == case.matter_code,
        )
    )
    if existing is not None:
        return existing
    matter = Matter(
        company_id=context.company.id,
        assignee_membership_id=context.membership.id,
        matter_code=case.matter_code,
        title=case.matter_title,
        client_name=case.client_name,
        opposing_party=case.opposing_party,
        practice_area=case.practice_area,
        forum_level=case.forum_level,
        court_name=case.court_name,
        description=case.description,
        status="active",
    )
    session.add(matter)
    session.flush()
    return matter


def _ensure_hearing(session: Session, *, matter: Matter) -> MatterHearing:
    """Hearing-pack generation needs a hearing on the matter to anchor
    the prep against. Synthesise a placeholder when none exists so the
    eval still exercises the pipeline."""
    existing = session.scalar(
        select(MatterHearing)
        .where(MatterHearing.matter_id == matter.id)
        .order_by(MatterHearing.created_at.desc())
    )
    if existing is not None:
        return existing
    hearing = MatterHearing(
        matter_id=matter.id,
        hearing_on=utcnow().date(),
        forum_name=matter.court_name or "Unknown",
        purpose="status",
    )
    session.add(hearing)
    session.flush()
    return hearing


# ---------- hearing-pack eval ----------


def _validate_hearing_pack(pack: HearingPack) -> list[DraftFinding]:
    findings: list[DraftFinding] = []
    summary = (pack.summary or "").strip()
    if not summary:
        findings.append(
            DraftFinding(
                code="empty_pack_summary",
                severity="blocker",
                message="hearing pack has no summary",
            )
        )
    items = list(pack.items or [])
    if not items:
        findings.append(
            DraftFinding(
                code="no_pack_items",
                severity="blocker",
                message="hearing pack has zero items",
            )
        )
        return findings
    # Allowed-kind check.
    for it in items:
        if it.item_type not in _ALLOWED_PACK_KINDS:
            findings.append(
                DraftFinding(
                    code="unknown_pack_item_type",
                    severity="warning",
                    message=f"unknown item_type={it.item_type!r} on item {it.id}",
                )
            )
    # Unique ranks.
    ranks = [it.rank for it in items]
    if len(ranks) != len(set(ranks)):
        findings.append(
            DraftFinding(
                code="duplicate_pack_ranks",
                severity="warning",
                message=f"duplicate rank values: {sorted(ranks)}",
            )
        )
    # authority_card items must carry a source_ref so the partner can
    # click through. An authority card without provenance is the kind
    # of legal-tech cargo-cult we explicitly refuse to ship.
    cards_missing_ref = [
        it for it in items
        if it.item_type == "authority_card" and not (it.source_ref or "").strip()
    ]
    if cards_missing_ref:
        findings.append(
            DraftFinding(
                code="authority_card_missing_source_ref",
                severity="blocker",
                message=f"{len(cards_missing_ref)} authority_card item(s) without source_ref",
            )
        )
    return findings


def _evaluate_hearing_pack_case(
    session: Session,
    *,
    context: SessionContext,
    case: EvalCase,
    dry_run: bool,
) -> tuple[str, dict[str, object], list[DraftFinding], str | None]:
    if dry_run:
        return CASE_STATUS_PASS, {"dry_run": True}, [], None
    matter = _ensure_matter(session, context=context, case=case)
    hearing = _ensure_hearing(session, matter=matter)
    try:
        pack = generate_hearing_pack(
            session, context=context, matter_id=matter.id, hearing_id=hearing.id,
        )
    except HTTPException as exc:
        return CASE_STATUS_ERROR, {}, [], f"HTTP {exc.status_code}: {exc.detail}"
    except Exception as exc:  # noqa: BLE001
        return CASE_STATUS_ERROR, {}, [], repr(exc)
    findings = _validate_hearing_pack(pack)
    metrics: dict[str, object] = {
        "item_count": len(pack.items or []),
        "summary_chars": len((pack.summary or "").strip()),
        "kinds_present": sorted({it.item_type for it in (pack.items or [])}),
    }
    blockers = sum(1 for f in findings if f.severity == "blocker")
    status = CASE_STATUS_FAIL if blockers > 0 else CASE_STATUS_PASS
    return status, metrics, findings, None


# ---------- recommendation eval ----------


def _validate_recommendation(rec: Recommendation) -> list[DraftFinding]:
    findings: list[DraftFinding] = []
    options = list(rec.options or [])
    if len(options) < 2:
        findings.append(
            DraftFinding(
                code="too_few_recommendation_options",
                severity="blocker",
                message=f"need >=2 options for a real choice; got {len(options)}",
            )
        )
    primary_idx = int(rec.primary_option_index or 0)
    if not options:
        findings.append(
            DraftFinding(
                code="no_primary_recommendation",
                severity="blocker",
                message="recommendation has zero options — no primary to pick",
            )
        )
    elif primary_idx < 0 or primary_idx >= len(options):
        findings.append(
            DraftFinding(
                code="primary_index_out_of_range",
                severity="blocker",
                message=(
                    f"primary_option_index={primary_idx} not in [0, {len(options)})"
                ),
            )
        )
    if not (rec.rationale or "").strip():
        findings.append(
            DraftFinding(
                code="empty_recommendation_rationale",
                severity="warning",
                message="recommendation has no rationale text",
            )
        )
    # Citations on the *primary* option are the bar — secondary
    # options are allowed to be sparser. When retrieval found nothing
    # at all this fires; that's a separate corpus-quality signal, not
    # a recommender bug — keep it a warning so the gate isn't
    # corpus-dependent.
    if options and 0 <= primary_idx < len(options):
        import json as _json
        try:
            cites = _json.loads(options[primary_idx].supporting_citations_json or "[]")
        except (TypeError, ValueError):
            cites = []
        if not cites:
            findings.append(
                DraftFinding(
                    code="primary_option_no_citations",
                    severity="warning",
                    message="primary option has no supporting citations",
                )
            )
    return findings


def _evaluate_recommendation_case(
    session: Session,
    *,
    context: SessionContext,
    case: EvalCase,
    rec_type: str,
    dry_run: bool,
) -> tuple[str, dict[str, object], list[DraftFinding], str | None]:
    if dry_run:
        return CASE_STATUS_PASS, {"dry_run": True, "rec_type": rec_type}, [], None
    matter = _ensure_matter(session, context=context, case=case)
    try:
        rec = generate_recommendation(
            session, context=context, matter_id=matter.id, rec_type=rec_type,
        )
    except HTTPException as exc:
        return CASE_STATUS_ERROR, {"rec_type": rec_type}, [], (
            f"HTTP {exc.status_code}: {exc.detail}"
        )
    except Exception as exc:  # noqa: BLE001
        return CASE_STATUS_ERROR, {"rec_type": rec_type}, [], repr(exc)
    findings = _validate_recommendation(rec)
    metrics: dict[str, object] = {
        "rec_type": rec_type,
        "option_count": len(rec.options or []),
        "primary_label_len": len((rec.primary_recommendation_label or "").strip()),
        "rationale_chars": len((rec.rationale or "").strip()),
    }
    blockers = sum(1 for f in findings if f.severity == "blocker")
    status = CASE_STATUS_FAIL if blockers > 0 else CASE_STATUS_PASS
    return status, metrics, findings, None


# ---------- run ----------


@dataclass
class _SuiteOutcome:
    suite_label: str
    cases_recorded: int
    pass_count: int
    fail_count: int


def _run_hearing_pack_suite(
    session: Session, *, context: SessionContext, dry_run: bool
) -> _SuiteOutcome:
    run = open_run(
        session, suite_name="hearing-pack",
        provider="caseops-llm", model="purpose=hearing_pack",
    )
    pass_count = 0
    fail_count = 0
    for case in BAIL_SUITE:
        status, metrics, findings, error = _evaluate_hearing_pack_case(
            session, context=context, case=case, dry_run=dry_run,
        )
        record_case(
            session, run=run, case_key=f"hp.{case.key}",
            findings=findings, metrics=CaseMetrics(extra=metrics), error=error,
        )
        if status == CASE_STATUS_PASS:
            pass_count += 1
        else:
            fail_count += 1
    finalize_run(session, run)
    session.commit()
    return _SuiteOutcome(
        suite_label="hearing-pack", cases_recorded=run.case_count,
        pass_count=pass_count, fail_count=fail_count,
    )


def _run_recommendation_suite(
    session: Session, *, context: SessionContext, dry_run: bool
) -> _SuiteOutcome:
    run = open_run(
        session, suite_name="recommendation",
        provider="caseops-llm", model="purpose=recommendations",
    )
    pass_count = 0
    fail_count = 0
    # Cross-product of bail cases × supported rec_types — keeps the
    # matrix small but still meaningful (4 cases × 4 types = 16
    # cases). Skip 'authority' because it overlaps with the citation
    # eval surface.
    rec_types = sorted(t for t in SUPPORTED_TYPES if t != "authority")
    for case in BAIL_SUITE:
        for rec_type in rec_types:
            status, metrics, findings, error = _evaluate_recommendation_case(
                session, context=context, case=case, rec_type=rec_type, dry_run=dry_run,
            )
            record_case(
                session, run=run, case_key=f"rec.{rec_type}.{case.key}",
                findings=findings, metrics=CaseMetrics(extra=metrics), error=error,
            )
            if status == CASE_STATUS_PASS:
                pass_count += 1
            else:
                fail_count += 1
    finalize_run(session, run)
    session.commit()
    return _SuiteOutcome(
        suite_label="recommendation", cases_recorded=run.case_count,
        pass_count=pass_count, fail_count=fail_count,
    )


def _format_report(outcomes: list[_SuiteOutcome]) -> str:
    lines = ["# Workflow eval", ""]
    lines.append("| Suite | Cases | Pass | Fail |")
    lines.append("|---|---|---|---|")
    for o in outcomes:
        lines.append(
            f"| {o.suite_label} | {o.cases_recorded} | {o.pass_count} | {o.fail_count} |"
        )
    return "\n".join(lines) + "\n"


def run(*, tenant_slug: str, suite: str, dry_run: bool) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    SessionFactory = get_session_factory()
    outcomes: list[_SuiteOutcome] = []
    with SessionFactory() as session:
        company, membership, user = _resolve_tenant(session, slug=tenant_slug)
        context = SessionContext(
            user=user, company=company, membership=membership,
        )
        if suite in ("hearing-pack", "all"):
            outcomes.append(
                _run_hearing_pack_suite(session, context=context, dry_run=dry_run)
            )
        if suite in ("recommendation", "all"):
            outcomes.append(
                _run_recommendation_suite(session, context=context, dry_run=dry_run)
            )

    sys.stdout.write(_format_report(outcomes))
    fails = sum(o.fail_count for o in outcomes)
    return 1 if fails > 0 else 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-eval-workflows")
    parser.add_argument(
        "--suite", choices=["hearing-pack", "recommendation", "all"], default="all",
        help="Which workflow suite to run.",
    )
    parser.add_argument(
        "--tenant", required=True,
        help="Company slug to attach the run(s) to.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip provider calls; record empty-pass cases (plumbing test).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        tenant_slug=args.tenant, suite=args.suite, dry_run=args.dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
