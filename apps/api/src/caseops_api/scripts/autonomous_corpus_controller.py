"""Autonomous, fail-closed controller for authority corpus Batch backfill.

The controller intentionally composes the existing corpus scripts instead of
duplicating their data logic. It owns the operational policy: one broad lock,
durable JSONL ledger events, per-bucket state transitions, budget caps, quality
classification, and stop-line checks.

It is safe to run with ``--dry-run`` for planning. Paid boundaries are still the
existing OpenAI Batch submit script and Voyage title/eval embedding calls.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class BucketState(StrEnum):
    PLANNED = "planned"
    INGESTING = "ingesting"
    LAYER2_STRUCTURING = "layer2_structuring"
    TITLE_CHUNK_REFRESH = "title_chunk_refresh"
    EMBEDDING_VERIFICATION = "embedding_verification"
    HNSW_PROBE = "hnsw_probe"
    RECOVERY_REQUIRED = "recovery_required"
    ACCEPTED = "accepted"
    ACCEPTED_WITH_CAVEAT = "accepted_with_caveat"
    PAUSED_FOR_HUMAN = "paused_for_human"
    FAILED = "failed"


@dataclass(frozen=True)
class BucketPlan:
    label: str
    forum_level: str
    court_name: str | None
    source_year: int
    language: str = "english"
    limit: int = 5000
    shard_size: int = 5000


@dataclass(frozen=True)
class EvalMetrics:
    recall_at_10: float
    mrr: float
    mean_rank: float
    pass_count: int
    total_count: int


@dataclass(frozen=True)
class HygieneMetrics:
    docs: int = 0
    structured_docs: int = 0
    dirty_metadata_chunks: int = 0
    unembedded_chunks_global: int = 0
    unembedded_chunks_in_bucket: int = 0
    embedding_drift_chunks_global: int = 0
    metadata_chunks: int = 0

    @property
    def dirty_rate(self) -> float:
        return 0.0 if self.docs <= 0 else self.dirty_metadata_chunks / self.docs


@dataclass(frozen=True)
class StopLinePolicy:
    openai_cap_usd: float = 75.0
    voyage_cap_usd: float = 10.0
    dirty_title_rate_cap: float = 0.01
    quarantine_rate_cap: float = 0.10
    target_rating: float = 4.8
    red_rating: float = 4.0
    max_recovery_attempts: int = 2


@dataclass(frozen=True)
class BucketClassification:
    state: BucketState
    rating: float
    reason: str


_RECALL_RE = re.compile(r"\*\*recall@10\*\*:\s*(\d+)/(\d+)\s*\(([\d.]+)\s*%")
_MRR_RE = re.compile(r"\*\*MRR\*\*:\s*([\d.]+)")
_RANK_RE = re.compile(r"\*\*mean rank \(when found\)\*\*:\s*([\d.]+)")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"created_at": utc_now_iso(), **payload}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def acquire_lock(lock_path: Path) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"controller lock already exists: {lock_path}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"pid": os.getpid(), "created_at": utc_now_iso()}))


def release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return


def score_rating(metrics: EvalMetrics) -> float:
    recall = metrics.recall_at_10
    mrr = metrics.mrr
    rank = metrics.mean_rank
    if recall >= 0.95 and mrr >= 0.90 and rank <= 1.20:
        return 5.0
    if recall >= 0.93 and mrr >= 0.88 and rank <= 1.20:
        return 4.8
    if recall >= 0.90 and mrr >= 0.85 and rank <= 1.25:
        return 4.5
    if recall >= 0.85 and mrr >= 0.75 and rank <= 1.50:
        return 4.0
    if recall >= 0.75 and mrr >= 0.70:
        return 3.5
    if recall >= 0.70:
        return 3.0
    return 2.5


def parse_eval_report(report: str) -> EvalMetrics:
    recall_matches = _RECALL_RE.findall(report)
    if not recall_matches:
        raise ValueError("could not parse recall@10 from eval report")
    passed, total, pct = recall_matches[-1]
    mrr_match = _MRR_RE.search(report)
    rank_match = _RANK_RE.search(report)
    if not mrr_match or not rank_match:
        raise ValueError("could not parse MRR/mean rank from eval report")
    return EvalMetrics(
        recall_at_10=float(pct) / 100.0,
        mrr=float(mrr_match.group(1)),
        mean_rank=float(rank_match.group(1)),
        pass_count=int(passed),
        total_count=int(total),
    )


def classify_bucket(
    *,
    metrics: EvalMetrics,
    hygiene: HygieneMetrics,
    policy: StopLinePolicy,
    recovery_attempts: int,
) -> BucketClassification:
    rating = score_rating(metrics)
    if hygiene.unembedded_chunks_global > 0 or hygiene.unembedded_chunks_in_bucket > 0:
        return BucketClassification(
            BucketState.PAUSED_FOR_HUMAN,
            rating,
            "unembedded chunks detected",
        )
    if hygiene.embedding_drift_chunks_global > 0:
        return BucketClassification(
            BucketState.PAUSED_FOR_HUMAN,
            rating,
            "embedding provider/model drift detected",
        )
    if hygiene.dirty_rate > policy.dirty_title_rate_cap:
        return BucketClassification(
            BucketState.RECOVERY_REQUIRED,
            rating,
            f"dirty metadata rate {hygiene.dirty_rate:.2%} exceeds cap",
        )
    if rating >= policy.target_rating:
        return BucketClassification(BucketState.ACCEPTED, rating, "target quality met")
    if rating < policy.red_rating:
        return BucketClassification(
            BucketState.PAUSED_FOR_HUMAN,
            rating,
            "rating below red-line minimum",
        )
    if recovery_attempts < policy.max_recovery_attempts:
        return BucketClassification(
            BucketState.RECOVERY_REQUIRED,
            rating,
            "below target; targeted recovery still available",
        )
    return BucketClassification(
        BucketState.ACCEPTED_WITH_CAVEAT,
        rating,
        "clean bucket remains below target after targeted recovery attempts",
    )


def default_wave3_plan() -> list[BucketPlan]:
    return [
        BucketPlan(
            label="delhi-hc-remaining-2026",
            forum_level="high_court",
            court_name="Delhi High Court",
            source_year=2026,
            language="english",
            limit=10,
        ),
        BucketPlan(
            label="sc-non-en-2024",
            forum_level="supreme_court",
            court_name=None,
            source_year=2024,
            language="non_english",
            limit=100,
        ),
        BucketPlan(
            label="sc-non-en-2023",
            forum_level="supreme_court",
            court_name=None,
            source_year=2023,
            language="non_english",
            limit=100,
        ),
        BucketPlan(
            label="sc-non-en-2022",
            forum_level="supreme_court",
            court_name=None,
            source_year=2022,
            language="non_english",
            limit=250,
        ),
    ]


class CorpusController:
    def __init__(
        self,
        *,
        base_dir: Path,
        tenant_slug: str,
        policy: StopLinePolicy,
        dry_run: bool,
        poll_seconds: int = 300,
    ) -> None:
        self.base_dir = base_dir
        self.tenant_slug = tenant_slug
        self.policy = policy
        self.dry_run = dry_run
        self.poll_seconds = poll_seconds
        self.ledger_path = base_dir / "controller-ledger.jsonl"
        self.lock_path = base_dir / "controller.lock"

    def event(self, payload: dict[str, Any]) -> None:
        append_jsonl(self.ledger_path, payload)

    def run_command(self, args: list[str], *, output_path: Path | None = None) -> str:
        self.event({"event": "command", "dry_run": self.dry_run, "args": args})
        if self.dry_run:
            return ""
        result = subprocess.run(args, check=False, text=True, capture_output=True)
        output = result.stdout + result.stderr
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output, encoding="utf-8")
        if result.returncode != 0:
            self.event({
                "event": "command_failed",
                "returncode": result.returncode,
                "args": args,
                "output_tail": output[-4000:],
            })
            raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}")
        return output

    def _python_module(self, module: str, *extra: str) -> list[str]:
        return [sys.executable, "-m", module, *extra]

    def recover_bucket(self, bucket: BucketPlan, *, attempt: int) -> None:
        bucket_dir = self.base_dir / bucket.label
        self.event({
            "event": "state",
            "bucket": bucket.label,
            "state": BucketState.RECOVERY_REQUIRED,
            "attempt": attempt,
        })
        base_args = [
            "--refresh",
            "--batch-size",
            "32",
            "--forum-level",
            bucket.forum_level,
            "--year",
            str(bucket.source_year),
        ]
        if bucket.court_name:
            base_args.extend(["--court-name", bucket.court_name])
        # Two narrow passes: invalid canonical titles and already-poisoned metadata chunks.
        for mode in ("--invalid-titles-only", "--dirty-metadata-only"):
            self.run_command(
                self._python_module(
                    "caseops_api.scripts.backfill_title_chunks",
                    *base_args,
                    mode,
                ),
                output_path=bucket_dir / f"recovery_{attempt}_{mode.strip('-')}.log",
            )

    def evaluate_bucket(self, bucket: BucketPlan) -> EvalMetrics:
        bucket_dir = self.base_dir / bucket.label
        args = self._python_module(
            "caseops_api.scripts.eval_hnsw_recall",
            "--tenant",
            self.tenant_slug,
            "--sample-size",
            "30",
            "--k",
            "10",
            "--seed",
            "42",
            "--forum-level",
            bucket.forum_level,
            "--source-year",
            str(bucket.source_year),
        )
        if bucket.court_name:
            args.extend(["--court-name", bucket.court_name])
        if bucket.language == "english":
            args.extend(["--language", "en"])
        elif bucket.language == "non_english":
            args.extend(["--language", "non_en"])
        report = self.run_command(args, output_path=bucket_dir / "eval.txt")
        return parse_eval_report(report)

    def mark_bucket(
        self,
        bucket: BucketPlan,
        *,
        metrics: EvalMetrics,
        hygiene: HygieneMetrics,
        recovery_attempts: int,
    ) -> BucketClassification:
        classification = classify_bucket(
            metrics=metrics,
            hygiene=hygiene,
            policy=self.policy,
            recovery_attempts=recovery_attempts,
        )
        self.event({
            "event": "bucket_classified",
            "bucket": bucket.label,
            "classification": classification.state,
            "rating": classification.rating,
            "reason": classification.reason,
            "metrics": asdict(metrics),
            "hygiene": asdict(hygiene),
            "recovery_attempts": recovery_attempts,
        })
        return classification

    def run_recovery_until_classified(
        self,
        bucket: BucketPlan,
        *,
        initial_metrics: EvalMetrics,
        hygiene: HygieneMetrics,
    ) -> BucketClassification:
        metrics = initial_metrics
        attempts = 0
        classification = self.mark_bucket(
            bucket,
            metrics=metrics,
            hygiene=hygiene,
            recovery_attempts=attempts,
        )
        while (
            classification.state == BucketState.RECOVERY_REQUIRED
            and attempts < self.policy.max_recovery_attempts
        ):
            attempts += 1
            self.recover_bucket(bucket, attempt=attempts)
            metrics = self.evaluate_bucket(bucket)
            classification = self.mark_bucket(
                bucket,
                metrics=metrics,
                hygiene=hygiene,
                recovery_attempts=attempts,
            )
        return classification

    def run(self, buckets: list[BucketPlan]) -> int:
        acquire_lock(self.lock_path)
        self.event({
            "event": "controller_started",
            "dry_run": self.dry_run,
            "policy": asdict(self.policy),
            "buckets": [asdict(bucket) for bucket in buckets],
        })
        try:
            # This script intentionally exposes the lock/state/reporting spine.
            # Paid export/submit/import orchestration is done by the existing
            # Batch scripts and VM run helpers until this controller graduates
            # from dry-run proof to scheduler-owned operation.
            for bucket in buckets:
                self.event({
                    "event": "state",
                    "bucket": bucket.label,
                    "state": BucketState.PLANNED,
                })
            self.event({"event": "controller_finished", "status": "planned"})
            return 0
        finally:
            release_lock(self.lock_path)


def _load_plan(path: Path | None) -> list[BucketPlan]:
    if path is None:
        return default_wave3_plan()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [BucketPlan(**item) for item in raw]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-autonomous-corpus-controller")
    parser.add_argument("--base-dir", type=Path, default=Path(".tmp/corpus-controller"))
    parser.add_argument("--tenant", default="aster-demo")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--openai-cap-usd", type=float, default=75.0)
    parser.add_argument("--voyage-cap-usd", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    controller = CorpusController(
        base_dir=args.base_dir,
        tenant_slug=args.tenant,
        policy=StopLinePolicy(
            openai_cap_usd=args.openai_cap_usd,
            voyage_cap_usd=args.voyage_cap_usd,
        ),
        dry_run=args.dry_run,
    )
    return controller.run(_load_plan(args.plan))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
