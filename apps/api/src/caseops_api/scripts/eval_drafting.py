"""CLI: run the bail-drafting flight and record an EvaluationRun.

Usage::

    uv run caseops-eval-drafting --suite bail --tenant <slug>
    uv run caseops-eval-drafting --suite bail --tenant <slug> --dry-run

What it does:

1. Loads a seed set of legal briefs (hard-coded bail scenarios for
   v1 — gold-dataset collection is operator work, BG-035).
2. For each case, creates (or reuses) a matter + draft in the
   target tenant, calls ``generate_draft_version``, runs the
   post-generation ``draft_validators`` over the output, and
   records an ``EvaluationCase`` row.
3. When every case has run, calls ``finalize_run`` to stamp
   aggregate metrics and emit a one-page markdown report to stdout
   (redirect to a file with ``> report.md``).

This is Sprint 11's BG-034: "build a real evaluation harness" — the
scaffolding that turns "we think the output is good" into a
persistable, auditable number. The gold-standard expert-drafted
baseline (BG-035) still needs operator legwork; once a firm reviews
the recorded bodies and attaches a grade, the same EvaluationRun
becomes a pair for the drafter-vs-expert claim.

Provider routing: drafting goes through whatever ``purpose=drafting``
is configured to — typically Opus in prod. The CLI deliberately does
NOT force a provider so the eval measures the production pipeline,
not a one-off fixture.
"""
from __future__ import annotations

import argparse
import json
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
    Draft,
    DraftType,
    Matter,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.draft_validators import run_validators
from caseops_api.services.drafting import (
    create_draft,
    generate_draft_version,
)
from caseops_api.services.evaluation import (
    CASE_STATUS_ERROR,
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    CaseMetrics,
    finalize_run,
    open_run,
    record_case,
)
from caseops_api.services.identity import SessionContext

logger = logging.getLogger("caseops.eval")


@dataclass(frozen=True)
class EvalCase:
    key: str
    matter_title: str
    matter_code: str
    client_name: str
    opposing_party: str
    practice_area: str
    forum_level: str
    court_name: str
    description: str
    focus_note: str


# Hard-coded bail suite. Three scenarios chosen to exercise the three
# prompt-hardening vectors we know about: statute selection
# (BNSS vs BNS), parity argument, custody-duration ground.
BAIL_SUITE: tuple[EvalCase, ...] = (
    EvalCase(
        key="bail.regular.delhi.cheating",
        matter_title="Regular bail — Rahul Verma — cheating under BNS",
        matter_code="EVAL-BAIL-001",
        client_name="Rahul Verma",
        opposing_party="State of NCT of Delhi",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "FIR No. 145/2025 P.S. Connaught Place. Offences under BNS "
            "ss.318, 319, 336, 340. Applicant in judicial custody for "
            "60+ days; chargesheet not yet filed. Co-accused Ajay Gupta "
            "already on bail on identical footing."
        ),
        focus_note=(
            "Draft a regular bail application under BNSS s.483. "
            "Address the triple-test (flight risk, tampering, repetition), "
            "parity with co-accused already on bail, prolonged custody "
            "without chargesheet, and the applicant's undertakings. "
            "Cite only authorities in the retrieved context."
        ),
    ),
    EvalCase(
        key="bail.regular.delhi.forgery",
        matter_title="Regular bail — Meera Iyer — forgery",
        matter_code="EVAL-BAIL-002",
        client_name="Meera Iyer",
        opposing_party="State of NCT of Delhi",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "FIR No. 201/2025 P.S. Saket. Offences under BNS ss.336, 340. "
            "First-time accused; 45 days in custody. Investigation "
            "complete. No co-accused."
        ),
        focus_note=(
            "Draft a regular bail application under BNSS s.483. "
            "Ground the argument on custody duration, first-time-offender "
            "status, and satisfaction of the triple-test. Use only "
            "the retrieved authorities."
        ),
    ),
    EvalCase(
        key="bail.anticipatory.delhi.economic",
        matter_title="Anticipatory bail — Arjun Mehta — economic offence",
        matter_code="EVAL-BAIL-003",
        client_name="Arjun Mehta",
        opposing_party="State of NCT of Delhi",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "No FIR yet; complainant has issued a summons under BNSS. "
            "Alleged offence: cheating under BNS s.318. Applicant "
            "apprehends arrest."
        ),
        focus_note=(
            "Draft an anticipatory bail application under BNSS s.482 "
            "(equivalent to CrPC s.438). Ground on absence of flight "
            "risk, willingness to join investigation, and the economic "
            "nature of the allegation. Cite only retrieved authorities."
        ),
    ),
)


def _load_tenant(
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


def _ensure_draft(
    session: Session, *, context: SessionContext, matter: Matter, case: EvalCase
) -> Draft:
    existing = session.scalar(
        select(Draft).where(
            Draft.matter_id == matter.id,
            Draft.title == case.matter_title,
        )
    )
    if existing is not None:
        return existing
    return create_draft(
        session,
        context=context,
        matter_id=matter.id,
        title=case.matter_title,
        draft_type=DraftType.OTHER,
    )


def _evaluate_case(
    session: Session,
    *,
    context: SessionContext,
    case: EvalCase,
    dry_run: bool,
) -> tuple[str, int, int, int, str, str | None]:
    """Return (status, body_chars, verified_cites, blocker_count, warning_count,
    error_text). Also writes a draft version when not dry-run."""
    if dry_run:
        return (CASE_STATUS_PASS, 0, 0, 0, 0, None)
    matter = _ensure_matter(session, context=context, case=case)
    draft = _ensure_draft(session, context=context, matter=matter, case=case)
    try:
        updated = generate_draft_version(
            session,
            context=context,
            matter_id=matter.id,
            draft_id=draft.id,
            focus_note=case.focus_note,
        )
    except HTTPException as exc:
        return (
            CASE_STATUS_ERROR, 0, 0, 0, 0,
            f"HTTP {exc.status_code}: {exc.detail}",
        )
    except Exception as exc:  # noqa: BLE001
        return (CASE_STATUS_ERROR, 0, 0, 0, 0, repr(exc))

    if not updated.versions:
        return (CASE_STATUS_FAIL, 0, 0, 0, 0, "no draft version produced")
    version = max(updated.versions, key=lambda v: v.revision)
    body = version.body or ""
    try:
        citations = json.loads(version.citations_json or "[]")
    except json.JSONDecodeError:
        citations = []
    findings = run_validators(body, citations)
    blockers = sum(1 for f in findings if f.severity == "blocker")
    warnings = sum(1 for f in findings if f.severity == "warning")
    if blockers > 0:
        status_label = CASE_STATUS_FAIL
    else:
        status_label = CASE_STATUS_PASS
    return (
        status_label,
        len(body),
        int(version.verified_citation_count or 0),
        blockers,
        warnings,
        None,
    )


def _format_report(run, cases: Iterable) -> str:  # noqa: ANN001
    lines: list[str] = []
    lines.append(f"# Drafting eval — {run.suite_name}\n")
    lines.append(f"- run id: `{run.id}`")
    lines.append(f"- provider / model: `{run.provider} / {run.model}`")
    if run.git_sha:
        lines.append(f"- git sha: `{run.git_sha}`")
    lines.append(f"- started at: {run.started_at.isoformat()}")
    if run.completed_at:
        lines.append(f"- completed at: {run.completed_at.isoformat()}")
    lines.append(
        f"- **{run.pass_count} / {run.case_count} passed**, "
        f"{run.fail_count} failed / errored"
    )
    if run.metrics_json:
        try:
            m = json.loads(run.metrics_json)
            lines.append(
                f"- avg body chars: {m.get('avg_body_chars', 0):.0f} · "
                f"avg verified citations: {m.get('avg_verified_citations', 0):.1f} · "
                f"total blockers: {m.get('total_blockers', 0)} · "
                f"total warnings: {m.get('total_warnings', 0)}"
            )
        except json.JSONDecodeError:
            pass
    lines.append("")
    lines.append("## Case results\n")
    for case in cases:
        lines.append(f"### {case.case_key}\n")
        lines.append(
            f"- status: **{case.status}** · blockers: {case.blocker_count} · "
            f"warnings: {case.warning_count}"
        )
        lines.append(
            f"- body chars: {case.body_chars} · verified citations: "
            f"{case.verified_citation_count}"
        )
        if case.error:
            lines.append(f"- error: `{case.error}`")
        if case.findings_json:
            try:
                payload = json.loads(case.findings_json)
                findings = payload.get("findings", [])
                for f in findings:
                    lines.append(
                        f"  - `[{f['severity']}] {f['code']}` {f['message']}"
                    )
            except json.JSONDecodeError:
                pass
        lines.append("")
    return "\n".join(lines)


def run(
    *,
    suite: str,
    tenant_slug: str,
    dry_run: bool,
    git_sha: str | None,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if suite != "bail":
        raise SystemExit(f"unknown suite {suite!r}; only 'bail' is seeded for v1")

    from caseops_api.core.settings import get_settings

    settings = get_settings()
    provider = settings.llm_provider
    model = (
        getattr(settings, "llm_model_drafting", None)
        or settings.llm_model
    )

    Session = get_session_factory()
    recorded_cases: list = []
    with Session() as session:
        company, membership, user = _load_tenant(session, slug=tenant_slug)
        context = SessionContext(company=company, user=user, membership=membership)
        run_row = open_run(
            session,
            suite_name=f"drafting.{suite}",
            provider=provider,
            model=model,
            git_sha=git_sha,
        )
        session.commit()

        for case in BAIL_SUITE:
            logger.info("running case %s", case.key)
            status_label, body_chars, verified, blockers, warnings, error = (
                _evaluate_case(
                    session, context=context, case=case, dry_run=dry_run,
                )
            )
            findings_blob: list = []
            if blockers or warnings:
                # Re-run the validator solely to capture the findings list
                # for the report — the per-case record_case path wants
                # DraftFinding objects, not aggregate counts. Because the
                # underlying evaluation already ran generate_draft_version,
                # the body is available from the latest DraftVersion.
                from caseops_api.db.models import DraftVersion

                version = session.scalar(
                    select(DraftVersion)
                    .join(Draft, Draft.id == DraftVersion.draft_id)
                    .join(Matter, Matter.id == Draft.matter_id)
                    .where(
                        Matter.company_id == context.company.id,
                        Matter.matter_code == case.matter_code,
                    )
                    .order_by(DraftVersion.revision.desc())
                )
                if version is not None:
                    try:
                        cites = json.loads(version.citations_json or "[]")
                    except json.JSONDecodeError:
                        cites = []
                    findings_blob = run_validators(version.body or "", cites)

            case_row = record_case(
                session,
                run=run_row,
                case_key=case.key,
                findings=findings_blob,
                metrics=CaseMetrics(
                    body_chars=body_chars,
                    verified_citation_count=verified,
                ),
                error=error,
            )
            # Override status if record_case derived a different one.
            case_row.status = status_label
            recorded_cases.append(case_row)
            session.commit()

        finalize_run(session, run_row)
        session.commit()
        session.refresh(run_row)
        report = _format_report(run_row, recorded_cases)

    sys.stdout.write(report)
    sys.stdout.write("\n")
    # Non-zero exit when anything failed — makes CI-gating feasible.
    return 0 if run_row.fail_count == 0 else 1


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-eval-drafting")
    parser.add_argument("--suite", default="bail", choices=["bail"])
    parser.add_argument(
        "--tenant",
        required=True,
        help="Company slug to run the eval against (tenant must already exist)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the LLM calls; open + finalize a run for schema smoke.",
    )
    parser.add_argument(
        "--git-sha",
        default=None,
        help="Optional: stamp the run with the code revision being evaluated.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        suite=args.suite,
        tenant_slug=args.tenant,
        dry_run=args.dry_run,
        git_sha=args.git_sha,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
