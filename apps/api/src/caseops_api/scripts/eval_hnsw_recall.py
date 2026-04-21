"""CLI: HNSW recall@k benchmark — does retrieval find a doc by its own essence?

Sprint 11 follow-up to ``eval_citations`` (which uses hand-curated
queries and substring matching). This benchmark is *runtime-grounded*:
sample N docs from the corpus, build a query from each doc's own
title, search the index, and check whether that exact doc appears
in the top-k results. No ground-truth list needed — the corpus
self-evaluates.

What it measures:

- ``recall@k``: percentage of sampled docs that appeared in their own
  top-k retrieval results. A high number means "the index can find
  a doc when handed a clue from the doc itself" — the floor of any
  retrieval claim.
- ``MRR`` (mean reciprocal rank): average of 1/rank for found docs,
  0 for missed. Sensitive to *where* in the top-k the doc landed.
- ``mean_found_rank``: average rank among found docs. Diagnostic for
  re-rank tuning.

Compares cleanly across runs as the corpus grows: a recall@10 of
0.72 today vs 0.81 next week is a real signal about index quality,
not noise from picking different landmark queries.

Usage::

    uv run caseops-eval-hnsw-recall --tenant <slug>
    uv run caseops-eval-hnsw-recall --tenant <slug> --sample-size 50 --k 10
    uv run caseops-eval-hnsw-recall --tenant <slug> --dry-run

No LLM tokens. No write to authority tables. Safe to re-run.
"""
from __future__ import annotations

import argparse
import logging
import random
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    Company,
    CompanyMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.authorities import AuthoritySearchRequest
from caseops_api.services.authorities import search_authorities
from caseops_api.services.corpus_title_validation import (
    title_is_case_name as _title_is_case_name,
)
from caseops_api.services.draft_validators import DraftFinding
from caseops_api.services.evaluation import (
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    CaseMetrics,
    finalize_run,
    open_run,
    record_case,
)
from caseops_api.services.identity import SessionContext

logger = logging.getLogger("caseops.eval.hnsw")

# Stripped from titles when building a query — they're meta-noise that
# the index already filters out. Keeping them inflates the query
# length without informing retrieval.
_TITLE_NOISE_RE = re.compile(
    r"\b(in the|hon'?ble|supreme court|high court|of india|"
    r"versus|v\.|vs\.|case no\.?|petition|appeal|civil|criminal)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^A-Za-z0-9\s]+")


@dataclass(frozen=True)
class _Probe:
    document_id: str
    title: str
    query: str


def _build_query(title: str) -> str:
    """Reduce a doc title to a 6-10 word retrieval query.

    Strategy: strip noise + punctuation, dedupe whitespace, take the
    first 10 words. Falls back to the raw title slice if the cleaned
    version is too short to be useful (<3 words)."""
    cleaned = _TITLE_NOISE_RE.sub(" ", title or "")
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    words = [w for w in cleaned.split() if len(w) >= 2]
    if len(words) < 3:
        # Fall back to the raw title — better noise than empty query.
        return (title or "").strip()[:120] or "judgment"
    return " ".join(words[:10])


def _expand_query_via_haiku(query: str) -> str:
    """Ask Haiku to expand a short case-name query with procedural context.

    Short queries like "Wahid State Govt of NCT of Delhi" carry little
    semantic signal for Voyage. A Haiku rewrite expanding to include a
    clean v./versus marker, likely procedural posture (bail, SLP,
    criminal appeal, writ petition), and typical court terms gives the
    cosine search much richer matching targets. Returns the original
    query on any failure.
    """
    from caseops_api.services.llm import LLMMessage, build_provider

    try:
        llm = build_provider()
    except Exception:  # noqa: BLE001
        return query

    prompt = (
        "You rewrite Indian-law case-name queries for vector retrieval. "
        "Return ONE LINE ONLY, 20-35 words, no preamble, no quotes, no "
        "explanation. Add: a clean ' v. ' between parties, likely procedural "
        "posture (bail / SLP / criminal appeal / writ petition / quashing / "
        "anticipatory bail / compensation / 482 CrPC), and the court (Supreme "
        "Court of India / High Court).\n\nInput: " + query + "\n\nRewrite:"
    )
    try:
        result = llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=80,
        )
    except Exception:  # noqa: BLE001
        return query

    # Haiku sometimes prefaces with "Rewrite:" or "Sure! ..." — strip the
    # first chatty line if present.
    text = (result.text or "").strip().strip('"').strip("`").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return query
    expanded = lines[-1]  # take the last non-empty line — chatter first, content last
    # Drop leading labels the model sometimes emits.
    for prefix in ("Rewrite:", "Output:", "Expanded:", "Query:"):
        if expanded.startswith(prefix):
            expanded = expanded[len(prefix):].strip()
    expanded = expanded.strip('"').strip("`").strip()
    # Strict validation — reject chatty / preamble / too-short / too-long responses.
    # 290-char hard ceiling stays under the AuthoritySearchRequest 300-char limit.
    if (
        not expanded
        or len(expanded) > 290
        or len(expanded.split()) < 6
        or len(expanded) < max(len(query) + 10, 30)
    ):
        return query
    return expanded


def _sample_probes(
    session: Session, *, sample_size: int, seed: int
) -> tuple[list[_Probe], dict[str, int]]:
    """Return ``(probes, skip_reasons)``.

    ``skip_reasons`` tags why a doc was excluded from the probe sample
    — almost always a title-validation failure (bench placeholder, OCR
    gibberish, too-short, non-Latin). Surfaced in the report so
    operators see the data-quality tail explicitly and don't mistake a
    shrunken sample for a retrieval regression. See
    ``memory/feedback_title_validation_legal_corpus.md`` for why this
    gate exists.
    """
    # Pull every Layer-2 doc id + title in one shot — the result set
    # is bounded (~14K rows × ~300 bytes) so loading into memory is
    # fine. Random sampling here is more honest than ``ORDER BY
    # random()`` because Postgres' random() ordering is biased on
    # large tables under HNSW indexes.
    stmt = (
        select(AuthorityDocument.id, AuthorityDocument.title)
        .where(AuthorityDocument.structured_version.is_not(None))
        .where(AuthorityDocument.title.is_not(None))
    )
    candidates = list(session.execute(stmt).all())
    if not candidates:
        return [], {}
    rng = random.Random(seed)
    # Over-sample so we still land ``sample_size`` good probes after
    # filtering out bench-placeholder / non-Latin / OCR-garbage titles.
    # 3x is enough to cover the ~10-15 % rejection rate we see on SC/HC
    # 2023 buckets without degrading probe-selection variance.
    overshoot = min(sample_size * 3, len(candidates))
    pool = rng.sample(candidates, k=overshoot)
    probes: list[_Probe] = []
    skip_reasons: dict[str, int] = {}
    for doc_id, title in pool:
        ok, reason = _title_is_case_name(title or "")
        if not ok:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        query = _build_query(title or "")
        if not query.strip():
            skip_reasons["empty_query"] = skip_reasons.get("empty_query", 0) + 1
            continue
        probes.append(_Probe(document_id=doc_id, title=title or "", query=query))
        if len(probes) >= sample_size:
            break
    return probes, skip_reasons


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


def _evaluate_probe(
    session: Session,
    *,
    context: SessionContext,
    probe: _Probe,
    k: int,
) -> tuple[str, dict[str, object], list[DraftFinding]]:
    payload = AuthoritySearchRequest(query=probe.query, limit=k)
    response = search_authorities(session, context=context, payload=payload)
    rank = 0
    for i, r in enumerate(response.results, start=1):
        if r.authority_document_id == probe.document_id:
            rank = i
            break
    found = rank > 0
    findings: list[DraftFinding] = []
    if not found:
        findings.append(
            DraftFinding(
                code="self_lookup_miss",
                severity="blocker",
                message=(
                    f"doc {probe.document_id} did not appear in its own "
                    f"top-{k} for query {probe.query!r}"
                ),
            )
        )
    metrics: dict[str, object] = {
        "rank": rank,
        "found": found,
        "result_count": len(response.results),
        "query": probe.query[:200],
        "title": probe.title[:200],
    }
    status = CASE_STATUS_PASS if found else CASE_STATUS_FAIL
    return status, metrics, findings


def _format_report(
    run,
    results: list[tuple[_Probe, str, dict[str, object]]],
    *,
    k: int,
    skip_reasons: dict[str, int] | None = None,
) -> str:
    total = max(len(results), 1)
    found = [m for _, _, m in results if m.get("found")]
    found_count = len(found)
    ranks_found = [int(m["rank"]) for m in found]
    found_at_5 = sum(1 for r in ranks_found if r <= 5)
    found_at_10 = sum(1 for r in ranks_found if r <= 10)
    mrr = sum(1.0 / r for r in ranks_found) / total if ranks_found else 0.0
    mean_rank = sum(ranks_found) / len(ranks_found) if ranks_found else 0.0

    lines: list[str] = []
    lines.append(f"# HNSW recall@{k} benchmark — {run.suite_name}")
    lines.append("")
    lines.append(
        f"Provider: `{run.provider}` · Model: `{run.model}` · "
        f"Sample size: {run.case_count} · Pass: {run.pass_count} · Fail: {run.fail_count}"
    )
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- **recall@{k}**: {found_count}/{total} ({100*found_count/total:.1f} %)")
    lines.append(f"- **recall@5**: {found_at_5}/{total} ({100*found_at_5/total:.1f} %)")
    lines.append(f"- **recall@10**: {found_at_10}/{total} ({100*found_at_10/total:.1f} %)")
    lines.append(f"- **MRR**: {mrr:.3f}")
    lines.append(f"- **mean rank (when found)**: {mean_rank:.2f}")
    if skip_reasons:
        skip_total = sum(skip_reasons.values())
        lines.append("")
        lines.append("## Skipped (title-validation)")
        lines.append("")
        lines.append(
            f"- **skipped**: {skip_total} (docs whose `title` failed the "
            "case-name predicate and were excluded from the probe sample)"
        )
        for reason, count in sorted(skip_reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"  - `{reason}`: {count}")
    lines.append("")
    lines.append("## Misses (first 10)")
    lines.append("")
    misses = [(p, m) for p, _, m in results if not m.get("found")][:10]
    if not misses:
        lines.append("_no misses_")
    else:
        for p, m in misses:
            lines.append(f"- **{p.title[:80]}** — query: `{m.get('query', '')[:120]}`")
    return "\n".join(lines) + "\n"


def run(
    *,
    tenant_slug: str,
    sample_size: int,
    k: int,
    seed: int,
    dry_run: bool,
    expand_query: bool = False,
    fail_on_miss: bool = False,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        company, membership, user = _resolve_tenant(session, slug=tenant_slug)
        context = SessionContext(
            user=user, company=company, membership=membership,
        )

        run_row = open_run(
            session, suite_name="hnsw-recall",
            provider="caseops-authority-search-v2", model=f"k={k}",
        )

        skip_reasons: dict[str, int] = {}
        if dry_run:
            probes: list[_Probe] = []
        else:
            probes, skip_reasons = _sample_probes(
                session, sample_size=sample_size, seed=seed,
            )
            if expand_query and probes:
                expanded: list[_Probe] = []
                for p in probes:
                    new_q = _expand_query_via_haiku(p.query)
                    if new_q != p.query:
                        logging.info(
                            "query-expansion: %r -> %r", p.query, new_q[:140]
                        )
                    expanded.append(
                        _Probe(document_id=p.document_id, title=p.title, query=new_q)
                    )
                probes = expanded
        if not probes and not dry_run:
            sys.stderr.write(
                "no Layer-2 docs (structured_version IS NOT NULL) to sample. "
                "Run the structured backfill first, then re-run this benchmark.\n"
            )
            finalize_run(session, run_row)
            session.commit()
            return 1

        results: list[tuple[_Probe, str, dict[str, object]]] = []
        for probe in probes:
            status, metrics, findings = _evaluate_probe(
                session, context=context, probe=probe, k=k,
            )
            record_case(
                session, run=run_row, case_key=f"hnsw.{probe.document_id}",
                findings=findings, metrics=CaseMetrics(extra=metrics),
            )
            results.append((probe, status, metrics))

        finalize_run(session, run_row)
        session.commit()

    sys.stdout.write(
        _format_report(run_row, results, k=k, skip_reasons=skip_reasons)
    )
    # 2026-04-21 BUG: the sweep orchestrator was halting on valid
    # 83.3 % recall runs because this CLI previously returned 1 on ANY
    # miss. That's wrong for a metrics eval — every real run has
    # some misses, and the caller should gate on the PRINTED rating
    # number, not on the exit code. Successful evaluation → exit 0.
    # Callers that want the strict "every probe must pass" mode can
    # opt in with --fail-on-miss.
    if fail_on_miss and run_row.fail_count > 0:
        return 1
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-eval-hnsw-recall")
    parser.add_argument(
        "--tenant", required=True,
        help="Company slug to attach the run to.",
    )
    parser.add_argument(
        "--sample-size", type=int, default=30,
        help="Number of docs to sample from the Layer-2 corpus (default 30).",
    )
    parser.add_argument(
        "--k", type=int, default=10, choices=range(1, 11),
        help="Top-k retrieval depth (1..10). Default 10.",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed for reproducible sampling. Default 42.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip retrieval; record empty run (plumbing test).",
    )
    parser.add_argument(
        "--expand-query", action="store_true",
        help=(
            "Send each probe's stripped query through Haiku for expansion "
            "before embedding. Tests whether LLM-side query expansion is a "
            "quality lever. Adds ~0.5s + a few hundred tokens per probe."
        ),
    )
    parser.add_argument(
        "--fail-on-miss", action="store_true",
        help=(
            "Exit 1 when any probe misses. Default: exit 0 on a "
            "successful eval run regardless of per-query misses — the "
            "rating lives in the printed report, not the exit code. "
            "Turn this on for strict CI gating."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        tenant_slug=args.tenant, sample_size=args.sample_size, k=args.k,
        seed=args.seed, dry_run=args.dry_run, expand_query=args.expand_query,
        fail_on_miss=args.fail_on_miss,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
