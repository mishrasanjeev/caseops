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


# Seed suites. Chosen to cover the four drafting surfaces a typical
# Indian litigation practice produces most of — regular bail,
# anticipatory bail, quashing petitions, civil review applications,
# and arbitration submissions. Each case is deliberately varied so
# the drafter's prompt-hardening is exercised against distinct
# legal-fact patterns, not just one template filled four times.
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
        key="bail.regular.bombay.pmla",
        matter_title="Regular bail — Nitin Shah — PMLA",
        matter_code="EVAL-BAIL-004",
        client_name="Nitin Shah",
        opposing_party="Enforcement Directorate",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Bombay High Court",
        description=(
            "ECIR/MBZO/09/2025. Offences under PMLA s.3/s.4. Applicant "
            "in custody for 90+ days. Twin conditions under PMLA s.45 "
            "engaged. Predicate offence is BNS s.318."
        ),
        focus_note=(
            "Draft a regular bail application. Address the twin "
            "conditions under PMLA s.45, prolonged custody, the proviso "
            "for women/sick/infirm if applicable, and whether the "
            "prosecution has made out a prima facie case. Cite only "
            "retrieved authorities."
        ),
    ),
    EvalCase(
        key="bail.regular.madras.ndps",
        matter_title="Regular bail — Suresh Kumar — NDPS commercial qty",
        matter_code="EVAL-BAIL-005",
        client_name="Suresh Kumar",
        opposing_party="Narcotics Control Bureau",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Madras High Court",
        description=(
            "Crime No. 89/2025. Offences under NDPS ss.8(c) r/w 20(b)(ii)"
            "(C)/22(c). Commercial quantity alleged. Applicant in "
            "custody for 120+ days; chargesheet filed 80 days ago."
        ),
        focus_note=(
            "Draft a regular bail application. Address NDPS s.37 twin "
            "conditions, the presumption under NDPS s.35, prolonged "
            "custody, and delay in trial. Cite retrieved authorities only."
        ),
    ),
)


ANTICIPATORY_BAIL_SUITE: tuple[EvalCase, ...] = (
    EvalCase(
        key="bail.anticipatory.delhi.economic",
        matter_title="Anticipatory bail — Arjun Mehta — economic offence",
        matter_code="EVAL-ABAIL-001",
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
    EvalCase(
        key="bail.anticipatory.delhi.dowry",
        matter_title="Anticipatory bail — Rohit Sharma — BNS s.85 cruelty",
        matter_code="EVAL-ABAIL-002",
        client_name="Rohit Sharma",
        opposing_party="State of NCT of Delhi",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "FIR No. 312/2025 P.S. Model Town. Offences under BNS s.85 "
            "(cruelty) and s.80 (dowry death threat). Applicant is the "
            "estranged husband; multiple false allegations from matrimonial "
            "dispute. Applicant's parents (aged 70+) are co-accused."
        ),
        focus_note=(
            "Draft an anticipatory bail application under BNSS s.482. "
            "Ground on the matrimonial-dispute background, age of "
            "co-accused parents, absence of specific allegations, and "
            "applicant's cooperation history. Cite only retrieved authorities."
        ),
    ),
    EvalCase(
        key="bail.anticipatory.bombay.medical",
        matter_title="Anticipatory bail — Dr. Kavita Rao — medical negligence",
        matter_code="EVAL-ABAIL-003",
        client_name="Dr. Kavita Rao",
        opposing_party="State of Maharashtra",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Bombay High Court",
        description=(
            "Complaint pending investigation. Offence alleged under BNS "
            "s.106(1) (causing death by negligence). Applicant is the "
            "treating obstetrician; post-partum haemorrhage death. "
            "Medical board opinion not yet sought."
        ),
        focus_note=(
            "Draft an anticipatory bail application. Argue the Jacob "
            "Mathew / Martin D'Souza safeguards — prosecution of doctors "
            "needs a medical board opinion before arrest. Cite only "
            "retrieved authorities."
        ),
    ),
)


QUASHING_SUITE: tuple[EvalCase, ...] = (
    EvalCase(
        key="quashing.delhi.matrimonial_498a",
        matter_title="Quashing — Vikram Malhotra — s.498A (BNS s.85) FIR",
        matter_code="EVAL-QUASH-001",
        client_name="Vikram Malhotra",
        opposing_party="State of NCT of Delhi",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "FIR No. 408/2024 P.S. Dwarka. Offence under BNS s.85 + s.115"
            "(2). Parties have amicably settled through mediation; "
            "compromise deed dated 2025-09-01. Wife supports quashing."
        ),
        focus_note=(
            "Draft a quashing petition under BNSS s.528 / Art. 226. "
            "Anchor on the settlement, Gian Singh / Narinder Singh "
            "framework for matrimonial compromises, and the absence of "
            "societal harm. Cite only retrieved authorities."
        ),
    ),
    EvalCase(
        key="quashing.delhi.ni_138",
        matter_title="Quashing — Rakesh Industries — NI Act s.138 summons",
        matter_code="EVAL-QUASH-002",
        client_name="Rakesh Industries Pvt Ltd",
        opposing_party="Chawla Traders",
        practice_area="commercial",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "Complaint Case No. 1205/2025 at Patiala House Courts. "
            "Summons issued under NI Act s.138 against the company and "
            "its non-executive director. No cheque was signed by the "
            "director; no statutory notice served on her personally."
        ),
        focus_note=(
            "Draft a quashing petition seeking to drop the non-executive "
            "director. Anchor on the Aneeta Hada / SMS Pharma / Pooja "
            "Ravinder Devidasani line of authority on vicarious liability "
            "under NI Act s.141. Cite only retrieved authorities."
        ),
    ),
    EvalCase(
        key="quashing.bombay.cheating_civil_dispute",
        matter_title="Quashing — Sanjay Enterprises — cheating overlay on civil dispute",
        matter_code="EVAL-QUASH-003",
        client_name="Sanjay Enterprises",
        opposing_party="State of Maharashtra",
        practice_area="commercial",
        forum_level="high_court",
        court_name="Bombay High Court",
        description=(
            "FIR No. 77/2025 P.S. BKC. Offences under BNS ss.318/319. "
            "Genesis is a commercial dispute over supply of industrial "
            "chemicals — contract interpretation issue. Civil suit "
            "pending at Commercial Court for the same transaction."
        ),
        focus_note=(
            "Draft a quashing petition. Anchor on the Bhajan Lal / "
            "Indian Oil / V.Y. Jose line that criminalising commercial "
            "disputes is an abuse of process. Cite only retrieved authorities."
        ),
    ),
)


CIVIL_REVIEW_SUITE: tuple[EvalCase, ...] = (
    EvalCase(
        key="review.delhi.commercial_decree",
        matter_title="Review — Tilak Construction — commercial suit decree",
        matter_code="EVAL-REVIEW-001",
        client_name="Tilak Construction Pvt Ltd",
        opposing_party="Sunrise Builders",
        practice_area="commercial",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "CS(COMM) 204/2023 decreed on 2025-10-12. Applicant has "
            "discovered two critical invoices dated 2023 that could not "
            "be produced at trial despite reasonable diligence. Error "
            "apparent on the face of record in paragraph 37 of the "
            "judgment (misapplication of limitation)."
        ),
        focus_note=(
            "Draft a review application under O.47 r.1 CPC. Address the "
            "three grounds — newly discovered evidence with reasonable "
            "diligence, error apparent on the face of record, and any "
            "sufficient reason. Cite only retrieved authorities."
        ),
    ),
    EvalCase(
        key="review.sc.limitation_condonation",
        matter_title="Review — Jyoti Singh — SC review with delay condonation",
        matter_code="EVAL-REVIEW-002",
        client_name="Jyoti Singh",
        opposing_party="Union of India",
        practice_area="constitutional",
        forum_level="supreme_court",
        court_name="Supreme Court of India",
        description=(
            "SC judgment dated 2025-05-18 in WP(C) 1234/2024. Review "
            "filed 47 days after the judgment. Delay of 17 days beyond "
            "the 30-day limitation under SC Rules Order XLVII r.1. "
            "Reason: applicant's counsel was hospitalised."
        ),
        focus_note=(
            "Draft a review petition with a simultaneous delay-condonation "
            "application under Art. 137 and SC Rules. Address why "
            "'sufficient cause' is made out. Cite only retrieved authorities."
        ),
    ),
    EvalCase(
        key="review.bombay.execution_order",
        matter_title="Review — Arun Chopra — error apparent in execution order",
        matter_code="EVAL-REVIEW-003",
        client_name="Arun Chopra",
        opposing_party="Bank of India",
        practice_area="civil",
        forum_level="high_court",
        court_name="Bombay High Court",
        description=(
            "Execution Application 156/2024. Order dated 2025-09-02 "
            "attached applicant's residential flat despite it being "
            "exempt under CPC s.60(1)(ccc) as the principal dwelling. "
            "Error apparent on the face of record."
        ),
        focus_note=(
            "Draft a review application under O.47 r.1 CPC targeting the "
            "execution order. Ground on the statutory exemption being "
            "overlooked — a classic 'error apparent'. Cite only retrieved "
            "authorities."
        ),
    ),
)


ARBITRATION_SUITE: tuple[EvalCase, ...] = (
    EvalCase(
        key="arbitration.s34.delhi.patent_illegality",
        matter_title="§34 challenge — Bharat Infrastructure — patent illegality",
        matter_code="EVAL-ARB-001",
        client_name="Bharat Infrastructure Ltd",
        opposing_party="NHAI",
        practice_area="commercial",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "Domestic arbitral award dated 2025-07-14 under the Arbitration "
            "& Conciliation Act, 1996. Tribunal granted damages in excess "
            "of the contractual cap (s.11.3 of the EPC contract). "
            "Applicant alleges patent illegality and violation of most "
            "basic notions of morality and justice."
        ),
        focus_note=(
            "Draft a petition under A&C Act s.34 challenging the award. "
            "Anchor on patent illegality as explained in ONGC v. Saw "
            "Pipes / Associate Builders / Ssangyong / Delhi Airport "
            "Metro. Cite only retrieved authorities."
        ),
    ),
    EvalCase(
        key="arbitration.s11.bombay.appointment",
        matter_title="§11 appointment — Aster Logistics — arbitrator appointment",
        matter_code="EVAL-ARB-002",
        client_name="Aster Logistics Pvt Ltd",
        opposing_party="Gateway Terminals India",
        practice_area="commercial",
        forum_level="high_court",
        court_name="Bombay High Court",
        description=(
            "Dispute under a service agreement dated 2023-04-11 with "
            "s.15 arbitration clause (seat: Mumbai, MCIA rules). "
            "Respondent failed to appoint its arbitrator within 30 days "
            "of notice. Applicant seeks appointment under A&C Act s.11."
        ),
        focus_note=(
            "Draft a s.11 application. Address existence of the "
            "arbitration agreement, accrual of the cause of action, the "
            "prima facie standard post Vidya Drolia / NN Global, and the "
            "seat/venue split. Cite only retrieved authorities."
        ),
    ),
)


SUITES: dict[str, tuple[EvalCase, ...]] = {
    "bail": BAIL_SUITE,
    "anticipatory_bail": ANTICIPATORY_BAIL_SUITE,
    "quashing": QUASHING_SUITE,
    "civil_review": CIVIL_REVIEW_SUITE,
    "arbitration": ARBITRATION_SUITE,
}


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


def _resolve_suite(suite_key: str) -> tuple[str, tuple[EvalCase, ...]]:
    """Expand the ``--suite`` argument. ``all`` concatenates every
    suite in a deterministic order; unknown suites raise."""
    if suite_key == "all":
        cases: list[EvalCase] = []
        for name in ("bail", "anticipatory_bail", "quashing", "civil_review", "arbitration"):
            cases.extend(SUITES[name])
        return ("all", tuple(cases))
    if suite_key not in SUITES:
        raise SystemExit(
            f"unknown suite {suite_key!r}; valid: "
            f"{', '.join(sorted(SUITES))}, all"
        )
    return (suite_key, SUITES[suite_key])


def _record_prompt_fixture(
    session: Session,
    *,
    context: SessionContext,
    case: EvalCase,
    output_dir: str,
) -> None:
    """Write a per-case fixture with the matter context + retrieved
    authorities — no LLM call. Useful for Sprint 12 expert-baseline work:
    a human lawyer reads the same context and writes their own draft,
    which becomes the comparison baseline.

    Persists the matter row (idempotent via matter_code) so retrieval
    can run against the real Matter ORM shape, then dumps the prompt
    payload to disk. The LLM is not called.
    """
    import os

    from caseops_api.services.drafting import _retrieve_for_draft

    os.makedirs(output_dir, exist_ok=True)

    matter = _ensure_matter(session, context=context, case=case)
    session.commit()

    try:
        candidates = _retrieve_for_draft(
            session, matter=matter, focus_note=case.focus_note
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieval failed for %s: %r", case.key, exc)
        candidates = []

    payload = {
        "case_key": case.key,
        "matter": {
            "id": matter.id,
            "matter_code": matter.matter_code,
            "title": matter.title,
            "client_name": matter.client_name,
            "opposing_party": matter.opposing_party,
            "practice_area": matter.practice_area,
            "forum_level": matter.forum_level,
            "court_name": matter.court_name,
            "description": matter.description,
        },
        "focus_note": case.focus_note,
        "retrieved_authorities": [
            {
                "id": getattr(c, "id", None),
                "title": getattr(c, "title", None),
                "case_reference": getattr(c, "case_reference", None),
                "neutral_citation": getattr(c, "neutral_citation", None),
                "court_name": getattr(c, "court_name", None),
                "decision_date": (
                    c.decision_date.isoformat()
                    if getattr(c, "decision_date", None) else None
                ),
                "summary": getattr(c, "summary", None) or "",
            }
            for c in candidates
        ],
    }
    out_path = os.path.join(output_dir, f"{case.key}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    sys.stdout.write(f"wrote {out_path}\n")


def run(
    *,
    suite: str,
    tenant_slug: str,
    dry_run: bool,
    git_sha: str | None,
    record_prompts: str | None = None,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    resolved_suite, cases = _resolve_suite(suite)

    from caseops_api.core.settings import get_settings

    settings = get_settings()
    provider = settings.llm_provider
    model = (
        getattr(settings, "llm_model_drafting", None)
        or settings.llm_model
    )

    # Record-prompts mode is session-only — no run is opened, no DB
    # rows are written. Dumps a JSON fixture per case with matter
    # context + retrieved authorities for offline expert-baseline work.
    if record_prompts:
        Session = get_session_factory()
        with Session() as session:
            company, membership, user = _load_tenant(session, slug=tenant_slug)
            context = SessionContext(
                company=company, user=user, membership=membership
            )
            for case in cases:
                logger.info("recording prompt fixture for %s", case.key)
                _record_prompt_fixture(
                    session,
                    context=context,
                    case=case,
                    output_dir=record_prompts,
                )
        return 0

    Session = get_session_factory()
    recorded_cases: list = []
    with Session() as session:
        company, membership, user = _load_tenant(session, slug=tenant_slug)
        context = SessionContext(company=company, user=user, membership=membership)
        run_row = open_run(
            session,
            suite_name=f"drafting.{resolved_suite}",
            provider=provider,
            model=model,
            git_sha=git_sha,
        )
        session.commit()

        for case in cases:
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
    parser.add_argument(
        "--suite",
        default="bail",
        choices=[
            "bail",
            "anticipatory_bail",
            "quashing",
            "civil_review",
            "arbitration",
            "all",
        ],
        help="Which seed suite to run. 'all' concatenates every suite.",
    )
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
        "--record-prompts",
        default=None,
        metavar="DIR",
        help=(
            "Write per-case JSON fixtures (matter context + retrieved "
            "authorities) to DIR and exit. No LLM calls, no DB writes "
            "beyond the read. Useful for the Sprint 12 expert-baseline "
            "protocol — a human lawyer reads the fixture and drafts "
            "their version for comparison."
        ),
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
        record_prompts=args.record_prompts,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
