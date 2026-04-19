"""CLI: citation-quality eval — does retrieval find the right authority?

Sprint 11 (BG-034 follow-up). Drafting eval measures the *output*;
this measures the *input retrieval* that drafting depends on. A
clean draft on garbage retrieval is still a wrong draft.

Usage::

    uv run caseops-eval-citations --tenant <slug>
    uv run caseops-eval-citations --tenant <slug> --dry-run

What it does:

1. Loads a curated seed of (query, expected_substrings) pairs
   covering common Indian legal queries (bail / quashing / NI Act /
   arbitration / writ).
2. For each pair, calls ``search_authority_catalog`` and computes:
   - ``hit@k``: did ANY top-k result's title or case_reference
     contain ANY expected substring? (Recall@k for the case-name
     class. Set-based; tolerant of corpus drift.)
   - ``structural_pass``: returned >=1 result, scores monotonically
     non-increasing, top result's snippet contains at least one
     query term.
3. Records an ``EvaluationCase`` per query (status=fail when
   ``hit@5`` is false OR structural checks fail).
4. ``finalize_run`` rolls per-case counts + emits a markdown
   report. Useful as a regression gate after corpus / embedding
   changes.

No LLM tokens consumed — this exercises only retrieval. Safe to
run as often as you like.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.authorities import AuthoritySearchRequest
from caseops_api.services.authorities import search_authorities
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
from caseops_api.services.identity import SessionContext

logger = logging.getLogger("caseops.eval.citations")


@dataclass(frozen=True)
class CitationCase:
    """One retrieval probe.

    ``expected_substrings`` is OR-ed: if ANY substring matches the
    title / case_reference of ANY top-k result, the probe is a hit.
    Substrings are case-insensitive. Keep them generic enough to
    survive title-cleanup churn (e.g. ``"section 482"`` not the exact
    formatted variant).
    """

    key: str
    query: str
    expected_substrings: tuple[str, ...]
    forum_level: str | None = None  # None = all forums

    def query_terms(self) -> list[str]:
        # Word-tokenize for the snippet check. Stopwords are kept —
        # short queries shouldn't be reduced to the empty set.
        return [t.lower() for t in self.query.split() if len(t) >= 3]


# Seed set is deliberately small + canonical. Each query is one a
# CaseOps user has plausibly typed; each expected_substring is a
# fragment we'd hope shows up in titles / case refs of relevant
# Indian-law judgments. Misses are signal — they say "the corpus or
# retrieval is missing this lane".
CITATION_SEEDS: tuple[CitationCase, ...] = (
    CitationCase(
        key="bail-triple-test",
        query="anticipatory bail triple test parity custody",
        expected_substrings=("bail", "anticipatory"),
        forum_level="supreme_court",
    ),
    CitationCase(
        key="quashing-482",
        query="quashing FIR inherent powers high court Section 482",
        expected_substrings=("482", "quash"),
    ),
    CitationCase(
        key="ni-act-138",
        query="dishonour of cheque presumption Section 138 NI Act",
        expected_substrings=("138", "ni act", "negotiable"),
    ),
    CitationCase(
        key="arbitration-s34",
        query="arbitration award patent illegality scope of Section 34",
        expected_substrings=("arbitration", "section 34"),
    ),
    CitationCase(
        key="writ-mandamus",
        query="writ of mandamus public duty principles",
        expected_substrings=("mandamus", "writ"),
    ),
    CitationCase(
        key="498a-cruelty",
        query="matrimonial cruelty Section 498A IPC dowry",
        expected_substrings=("498a", "cruelty"),
    ),
    CitationCase(
        key="bnss-bail",
        query="bail under BNSS Section 483 grounds for grant",
        expected_substrings=("bnss", "483", "bail"),
    ),
    CitationCase(
        key="article-14",
        query="Article 14 reasonable classification equal protection",
        expected_substrings=("article 14", "classification", "equal"),
    ),
    CitationCase(
        key="specific-performance",
        query="specific performance Section 16 Specific Relief Act",
        expected_substrings=("specific performance", "section 16"),
    ),
    CitationCase(
        key="property-attachment-pmla",
        query="provisional attachment of proceeds of crime PMLA",
        expected_substrings=("pmla", "attachment", "proceeds of crime"),
    ),
)


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


def _evaluate_case(
    session: Session,
    *,
    context: SessionContext,
    case: CitationCase,
    limit: int,
) -> tuple[str, dict[str, int | float | bool | str], list[DraftFinding], str | None]:
    """Run one retrieval probe; return (status, metrics, findings, error)."""
    payload = AuthoritySearchRequest(
        query=case.query,
        limit=limit,
        forum_level=case.forum_level,
    )
    try:
        response = search_authorities(session, context=context, payload=payload)
    except Exception as exc:  # noqa: BLE001
        return CASE_STATUS_ERROR, {}, [], repr(exc)

    results = response.results
    findings: list[DraftFinding] = []

    if not results:
        findings.append(
            DraftFinding(
                code="empty_retrieval",
                severity="blocker",
                message=f"no results for query {case.query!r}",
            )
        )

    # Substring hit-rate: which expected_substrings matched at top-k.
    expected_lower = tuple(s.lower() for s in case.expected_substrings)
    hit_at_k: dict[int, bool] = {1: False, 3: False, 5: False}
    first_hit_rank = 0
    for rank, r in enumerate(results, start=1):
        haystack = " ".join(
            (r.title or ""),
        ).lower()
        # Include case_reference + summary to widen the match surface
        # — title cleanup may have stripped the docket no.
        haystack = " ".join([
            (r.title or "").lower(),
            (r.case_reference or "").lower(),
            (r.summary or "").lower(),
        ])
        matched = any(needle in haystack for needle in expected_lower)
        if matched and first_hit_rank == 0:
            first_hit_rank = rank
        for k in (1, 3, 5):
            if rank <= k and matched:
                hit_at_k[k] = True

    # Structural: scores non-increasing, top snippet contains at
    # least one query term.
    scores_monotonic = all(
        results[i].score <= results[i - 1].score for i in range(1, len(results))
    )
    if not scores_monotonic:
        findings.append(
            DraftFinding(
                code="scores_not_monotonic",
                severity="warning",
                message="result scores are not non-increasing — re-rank slipped",
            )
        )
    snippet_terms = case.query_terms()
    snippet_overlap = False
    if results:
        top_snippet = (results[0].snippet or "").lower()
        snippet_overlap = any(t in top_snippet for t in snippet_terms)
    if results and not snippet_overlap:
        findings.append(
            DraftFinding(
                code="snippet_no_query_terms",
                severity="warning",
                message="top result snippet shares no >=3-char term with the query",
            )
        )
    # Hit@5 is the gate. Anything missing it is a fail (citation
    # eval's whole point).
    if not hit_at_k[5]:
        findings.append(
            DraftFinding(
                code="no_expected_match_top5",
                severity="blocker",
                message=(
                    f"none of {list(case.expected_substrings)} matched any of "
                    f"top-5 result titles / refs / summaries"
                ),
            )
        )

    metrics: dict[str, int | float | bool | str] = {
        "result_count": len(results),
        "hit_at_1": hit_at_k[1],
        "hit_at_3": hit_at_k[3],
        "hit_at_5": hit_at_k[5],
        "first_hit_rank": first_hit_rank,
        "scores_monotonic": scores_monotonic,
        "snippet_overlaps_query": snippet_overlap,
        "top_score": float(results[0].score) if results else 0.0,
        "forum_level": case.forum_level or "any",
    }
    blockers = sum(1 for f in findings if f.severity == "blocker")
    status = CASE_STATUS_FAIL if blockers > 0 else CASE_STATUS_PASS
    return status, metrics, findings, None


def _format_report(run, per_case: list[tuple[CitationCase, str, dict]]) -> str:
    lines: list[str] = []
    lines.append(f"# Citation-quality eval — {run.suite_name}")
    lines.append("")
    lines.append(
        f"Provider: `{run.provider}` · Model: `{run.model}` · "
        f"Cases: {run.case_count} · Pass: {run.pass_count} · Fail: {run.fail_count}"
    )
    lines.append("")
    # Aggregate hit rates.
    total = max(len(per_case), 1)
    hit1 = sum(1 for _, _, m in per_case if m.get("hit_at_1"))
    hit3 = sum(1 for _, _, m in per_case if m.get("hit_at_3"))
    hit5 = sum(1 for _, _, m in per_case if m.get("hit_at_5"))
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- **hit@1**: {hit1}/{total} ({100*hit1/total:.1f} %)")
    lines.append(f"- **hit@3**: {hit3}/{total} ({100*hit3/total:.1f} %)")
    lines.append(f"- **hit@5**: {hit5}/{total} ({100*hit5/total:.1f} %)")
    lines.append("")
    lines.append("## Per-case")
    lines.append("")
    lines.append("| Key | Status | hit@1 | hit@3 | hit@5 | first | snippet | results |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for case, status, m in per_case:
        lines.append(
            f"| `{case.key}` | {status} | "
            f"{'✓' if m.get('hit_at_1') else '✗'} | "
            f"{'✓' if m.get('hit_at_3') else '✗'} | "
            f"{'✓' if m.get('hit_at_5') else '✗'} | "
            f"{m.get('first_hit_rank', 0)} | "
            f"{'✓' if m.get('snippet_overlaps_query') else '✗'} | "
            f"{m.get('result_count', 0)} |"
        )
    return "\n".join(lines) + "\n"


def run(
    *,
    tenant_slug: str,
    limit: int,
    dry_run: bool,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        company, membership, user = _resolve_tenant(session, slug=tenant_slug)
        context = SessionContext(
            user=user,
            company=company,
            membership=membership,
        )
        run_row = open_run(
            session,
            suite_name="citation-quality",
            provider="caseops-authority-search-v2",
            model="hybrid-pgvector-bm25",
        )

        per_case: list[tuple[CitationCase, str, dict]] = []
        for case in CITATION_SEEDS:
            if dry_run:
                status, metrics, findings, error = (
                    CASE_STATUS_PASS, {"dry_run": True}, [], None,
                )
            else:
                status, metrics, findings, error = _evaluate_case(
                    session, context=context, case=case, limit=limit,
                )
            record_case(
                session,
                run=run_row,
                case_key=case.key,
                findings=findings,
                metrics=CaseMetrics(extra=metrics),
                error=error,
            )
            per_case.append((case, status, metrics))

        finalize_run(session, run_row)
        # Always commit — "dry-run" means "skip retrieval calls", not
        # "drop the audit record". A dry-run produces a valid (empty
        # cases) EvaluationRun so the harness plumbing is testable.
        session.commit()

    sys.stdout.write(_format_report(run_row, per_case))
    # Non-zero exit when any case failed — useful for CI gating.
    return 1 if run_row.fail_count > 0 else 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-eval-citations")
    parser.add_argument(
        "--tenant", required=True,
        help="Company slug to attach the run to (any tenant works).",
    )
    parser.add_argument(
        "--limit", type=int, default=5, choices=range(1, 11),
        help="Top-k retrieval depth (1..10). Default 5.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip retrieval; record empty-pass cases (used for plumbing tests).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        tenant_slug=args.tenant, limit=args.limit, dry_run=args.dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
