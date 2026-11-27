"""CLI: statute retrieval benchmark (FT-122) — recall@k, MRR and rank.

Runs every benchmark question through the same ``search_statute_sections``
call research answers use, against the configured database and embedding
provider, and reports the corpus-quality rubric line::

    rating: X.Y/5 (recall@10=NN.N%, MRR=0.YYY, rank=Z.ZZ)

Questions carry no section number, so they measure the semantic path; a
question is skipped when none of its expected sections is selectable in the
database (for example an Act whose verified edition is not loaded yet).
Negative questions have no statutory answer and must return no statute; the
false-positive rate checks the similarity floor. ``--calibrate`` adds the
similarity of each expected hit and of the closest neighbour of each negative,
with the floor disabled, so the floor can be confirmed on the production model.

Only a run on the production provider (``voyage-4-large``) with the production
reranker is a production rating. Any other model's numbers exercise the
pipeline and are labelled as such.

Usage::

    python -m caseops_api.scripts.eval_statute_retrieval
    python -m caseops_api.scripts.eval_statute_retrieval --k 10 --calibrate --json-out out.json

Semantic retrieval is evaluated even while
``CASEOPS_STATUTE_SEMANTIC_RETRIEVAL_ENABLED`` is off for the live service, so
the benchmark can gate enabling it. Set ``CASEOPS_RERANK_ENABLED`` and
``CASEOPS_RERANK_BACKEND`` to the live API service's values so the rating
reflects production ranking.

Read-only: no writes to the database. Each question costs one query embedding.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import StatuteSection
from caseops_api.db.session import get_session_factory
from caseops_api.services.embeddings import EmbeddingProvider, build_provider
from caseops_api.services.statute_selection import selectable_statute_section_sql
from caseops_api.services.statute_vectors import (
    min_similarity_for,
    search_statute_sections,
    semantic_retrieval_enabled,
)

BENCHMARK_PATH = Path(__file__).resolve().parent / "statute_retrieval_benchmark.json"
PRODUCTION_MODEL = "voyage-4-large"
# Corpus-quality rubric (.codex/skills/corpus-ingest/SKILL.md):
# (rating, minimum recall@10, minimum MRR, maximum mean rank).
_RUBRIC = (
    (5.0, 0.95, 0.90, 1.2),
    (4.8, 0.93, 0.88, 1.2),
    (4.5, 0.90, 0.85, 1.25),
    (4.0, 0.85, 0.75, 1.5),
    (3.5, 0.75, 0.70, None),
    (3.0, 0.70, None, None),
)


def rating(recall: float, mrr: float, mean_rank: float) -> float:
    for score, min_recall, min_mrr, max_rank in _RUBRIC:
        if recall < min_recall:
            continue
        if min_mrr is not None and mrr < min_mrr:
            continue
        if max_rank is not None and mean_rank > max_rank:
            continue
        return score
    return 2.5


@dataclass
class QueryResult:
    id: str
    statute_id: str
    query: str
    expected: list[str]
    rank: int
    top: list[str]
    expected_similarity: float | None = None


@dataclass
class Report:
    model: str
    k: int
    floor: float
    rerank: str
    evaluated: int = 0
    skipped: int = 0
    recall: float = 0.0
    mrr: float = 0.0
    mean_rank: float = 0.0
    results: list[QueryResult] = field(default_factory=list)
    per_act: dict[str, list[int]] = field(default_factory=dict)
    negatives: int = 0
    negative_false_positives: int = 0
    negative_top_similarity: list[float] = field(default_factory=list)
    income_tax_extension_queries: int = 0
    live_semantic_setting: bool = False

    @property
    def rating(self) -> float:
        return rating(self.recall, self.mrr, self.mean_rank) if self.evaluated else 0.0


def load_benchmark(path: Path | None = None) -> dict:
    return json.loads((path or BENCHMARK_PATH).read_text(encoding="utf-8"))


def _selectable_keys(session: Session) -> set[tuple[str, str]]:
    return set(
        session.execute(
            select(StatuteSection.statute_id, StatuteSection.section_number).where(
                selectable_statute_section_sql()
            )
        ).tuples()
    )


def evaluate(
    session: Session,
    benchmark: dict,
    *,
    k: int = 10,
    embedder: EmbeddingProvider | None = None,
    calibrate: bool = False,
) -> Report:
    embedder = embedder or build_provider()
    report = Report(
        model=embedder.model,
        k=k,
        floor=min_similarity_for(embedder.model),
        rerank=os.environ.get("CASEOPS_RERANK_ENABLED", "false") or "false",
        live_semantic_setting=semantic_retrieval_enabled(),
        income_tax_extension_queries=len(
            benchmark.get("income_tax_extension", {}).get("queries", [])
        ),
    )
    selectable = _selectable_keys(session)
    per_act: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    reciprocal = 0.0
    found_ranks: list[int] = []
    for item in benchmark["queries"]:
        expected = {(item["statute_id"], number) for number in item["expected"]}
        if not expected & selectable:
            report.skipped += 1
            continue
        hits = search_statute_sections(
            session, item["query"], limit=k, embedder=embedder, semantic=True
        )
        keys = [(hit.statute.id, hit.section.section_number) for hit in hits]
        rank = next((index for index, key in enumerate(keys, start=1) if key in expected), 0)
        result = QueryResult(
            id=item["id"],
            statute_id=item["statute_id"],
            query=item["query"],
            expected=item["expected"],
            rank=rank,
            top=[f"{statute_id} {number}" for statute_id, number in keys[:3]],
        )
        if calibrate:
            pool = search_statute_sections(
                session,
                item["query"],
                limit=50,
                embedder=embedder,
                min_similarity=-1.0,
                semantic=True,
            )
            result.expected_similarity = next(
                (
                    hit.similarity
                    for hit in pool
                    if (hit.statute.id, hit.section.section_number) in expected
                ),
                None,
            )
        report.results.append(result)
        report.evaluated += 1
        per_act[item["statute_id"]][0] += 1
        if rank:
            per_act[item["statute_id"]][1] += 1
            reciprocal += 1.0 / rank
            found_ranks.append(rank)
        session.rollback()
    for negative in benchmark.get("negatives", []):
        report.negatives += 1
        if search_statute_sections(
            session, negative["query"], limit=k, embedder=embedder, semantic=True
        ):
            report.negative_false_positives += 1
        if calibrate:
            pool = search_statute_sections(
                session,
                negative["query"],
                limit=1,
                embedder=embedder,
                min_similarity=-1.0,
                semantic=True,
            )
            if pool and pool[0].similarity is not None:
                report.negative_top_similarity.append(pool[0].similarity)
        session.rollback()
    if report.evaluated:
        report.recall = len(found_ranks) / report.evaluated
        report.mrr = reciprocal / report.evaluated
    report.mean_rank = sum(found_ranks) / len(found_ranks) if found_ranks else 0.0
    report.per_act = dict(per_act)
    return report


def format_report(report: Report) -> str:
    lines = [
        f"# Statute retrieval benchmark (k={report.k})",
        "",
        f"model: {report.model} · rerank: {report.rerank} · similarity floor: {report.floor:.2f}"
        f" · live semantic setting: {report.live_semantic_setting}",
    ]
    if report.model != PRODUCTION_MODEL:
        lines.append(
            "OFFLINE PROVIDER: these numbers exercise the retrieval pipeline only; they are "
            "NOT a production rating."
        )
    lines += [
        "",
        f"rating: {report.rating:.1f}/5 (recall@{report.k}={100 * report.recall:.1f}%, "
        f"MRR={report.mrr:.3f}, rank={report.mean_rank:.2f})",
        f"evaluated: {report.evaluated} · skipped (expected section not selectable here): "
        f"{report.skipped}",
        f"negatives: {report.negatives} · returned a statute: {report.negative_false_positives}",
        f"income-tax extension queries: {report.income_tax_extension_queries}",
        "",
        "## Per Act (found / evaluated)",
    ]
    for act, (evaluated, found) in sorted(report.per_act.items()):
        lines.append(f"- {act}: {found}/{evaluated}")
    expected_similarities = sorted(
        result.expected_similarity
        for result in report.results
        if result.expected_similarity is not None
    )
    if expected_similarities or report.negative_top_similarity:
        lines += ["", "## Calibration (floor disabled)"]
        if expected_similarities:
            lines.append(
                f"- expected-hit similarity: min={expected_similarities[0]:.3f} "
                f"median={expected_similarities[len(expected_similarities) // 2]:.3f} "
                f"(present in pool for {len(expected_similarities)}/{report.evaluated})"
            )
        if report.negative_top_similarity:
            lines.append(
                f"- negative closest-neighbour similarity: max="
                f"{max(report.negative_top_similarity):.3f}"
            )
    misses = [result for result in report.results if not result.rank][:15]
    lines += ["", "## Misses (first 15)"]
    lines += [
        f"- {result.id} ({result.statute_id} {', '.join(result.expected)}): top={result.top}"
        for result in misses
    ] or ["_no misses_"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--benchmark", type=Path, default=None)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    with get_session_factory()() as session:
        report = evaluate(
            session, load_benchmark(args.benchmark), k=args.k, calibrate=args.calibrate
        )
    sys.stdout.write(format_report(report))
    if args.json_out is not None:
        args.json_out.write_text(
            json.dumps({**asdict(report), "rating": report.rating}, indent=2), encoding="utf-8"
        )
    return 0 if report.evaluated else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
