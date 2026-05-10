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
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import text

from caseops_api.db.session import get_session_factory
from caseops_api.scripts.authority_metadata_batch import DEFAULT_BATCH_MODEL
from caseops_api.services.corpus_ingest import HC_COURT_CATALOG


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
    language: str = "any"
    limit: int = 10000
    shard_size: int = 5000
    court_key: str | None = None


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
    openai_cap_usd: float = 500.0
    voyage_cap_usd: float = 75.0
    dirty_title_rate_cap: float = 0.01
    quarantine_rate_cap: float = 0.10
    target_rating: float = 4.8
    red_rating: float = 4.0
    max_recovery_attempts: int = 2
    recover_below_target: bool = False


@dataclass(frozen=True)
class BucketClassification:
    state: BucketState
    rating: float
    reason: str


@dataclass(frozen=True)
class BucketLedgerStatus:
    terminal_state: BucketState | None = None
    terminal_reason: str | None = None
    import_completed: bool = False
    title_refreshed: bool = False
    imported_document_ids: tuple[str, ...] = ()

    @property
    def is_terminal(self) -> bool:
        return self.terminal_state in {
            BucketState.ACCEPTED,
            BucketState.ACCEPTED_WITH_CAVEAT,
            BucketState.RECOVERY_REQUIRED,
        }


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
            BucketState.RECOVERY_REQUIRED,
            rating,
            "bucket rating below red-line minimum; queued for recovery",
        )
    if (
        policy.recover_below_target
        and recovery_attempts < policy.max_recovery_attempts
    ):
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


def _slug(value: str) -> str:
    value = value.lower().replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _hc_display_to_key() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, meta in HC_COURT_CATALOG.items():
        mapping.setdefault(str(meta["display"]), key)
    return mapping


def autonomous_sweep_plan() -> list[BucketPlan]:
    """Full approved SC/HC source-year sweep plan, newest first.

    The plan scopes by corpus/source year, not decision-date year. That is the
    proven production shape for the current authority corpus because many
    imported rows have null or mismatched decision dates.
    """
    buckets: list[BucketPlan] = []
    for year in range(2025, 1989, -1):
        buckets.append(
            BucketPlan(
                label=f"supreme-court-{year}",
                forum_level="supreme_court",
                court_name="Supreme Court of India",
                source_year=year,
                language="any",
            )
        )

    display_to_key = _hc_display_to_key()
    priority = [
        "Delhi High Court",
        "Bombay High Court",
        "Karnataka High Court",
        "Madras High Court",
        "Telangana High Court",
    ]
    remaining = sorted(display for display in display_to_key if display not in priority)
    for court_name in [*priority, *remaining]:
        court_key = display_to_key[court_name]
        for year in range(2025, 1989, -1):
            buckets.append(
                BucketPlan(
                    label=f"{_slug(court_name)}-{year}",
                    forum_level="high_court",
                    court_name=court_name,
                    source_year=year,
                    language="any",
                    court_key=court_key,
                )
            )
    return buckets


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
            court_name="Supreme Court of India",
            source_year=2024,
            language="non_english",
            limit=100,
        ),
        BucketPlan(
            label="sc-non-en-2023",
            forum_level="supreme_court",
            court_name="Supreme Court of India",
            source_year=2023,
            language="non_english",
            limit=100,
        ),
        BucketPlan(
            label="sc-non-en-2022",
            forum_level="supreme_court",
            court_name="Supreme Court of India",
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
        allow_s3_ingest: bool = True,
        global_eval_every: int = 5,
    ) -> None:
        self.base_dir = base_dir
        self.tenant_slug = tenant_slug
        self.policy = policy
        self.dry_run = dry_run
        self.poll_seconds = poll_seconds
        self.allow_s3_ingest = allow_s3_ingest
        self.global_eval_every = global_eval_every
        self.ledger_path = base_dir / "controller-ledger.jsonl"
        self.lock_path = base_dir / "controller.lock"
        self.started_at = datetime.now(UTC)
        self.openai_estimated_usd = 0.0

    def event(self, payload: dict[str, Any]) -> None:
        append_jsonl(self.ledger_path, payload)

    def run_command(
        self,
        args: list[str],
        *,
        output_path: Path | None = None,
        check: bool = True,
    ) -> str:
        self.event({"event": "command", "dry_run": self.dry_run, "args": args})
        if self.dry_run:
            return ""
        result = subprocess.run(args, check=False, text=True, capture_output=True)
        output = result.stdout + result.stderr
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output, encoding="utf-8")
        if check and result.returncode != 0:
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

    def _json_from_output(self, output: str) -> dict[str, Any]:
        start = output.find("{")
        end = output.rfind("}")
        if start < 0 or end < start:
            raise ValueError(f"command did not emit JSON: {output[-1000:]}")
        return json.loads(output[start : end + 1])

    def _bucket_dir(self, bucket: BucketPlan) -> Path:
        return self.base_dir / bucket.label

    def _language_for_eval(self, language: str) -> str:
        if language == "english":
            return "en"
        if language == "non_english":
            return "non_en"
        return "any"

    def bucket_ledger_status(self, bucket: BucketPlan) -> BucketLedgerStatus:
        """Read prior controller progress for resume-safe bucket handling."""
        if not self.ledger_path.exists():
            return BucketLedgerStatus()

        terminal_state: BucketState | None = None
        terminal_reason: str | None = None
        import_completed = False
        title_refreshed = False
        imported_ids: list[str] = []
        seen_ids: set[str] = set()
        bucket_path_fragment = f"/{bucket.label}/"

        with self.ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("bucket") == bucket.label:
                    if event.get("event") == "bucket_classified":
                        try:
                            state = BucketState(str(event.get("classification")))
                        except ValueError:
                            state = None
                        if state is not None:
                            terminal_state = state
                            terminal_reason = str(event.get("reason") or "")
                    elif event.get("event") == "import_result":
                        import_completed = bool(event.get("errors") in (None, []))
                    elif event.get("event") == "title_refresh_result":
                        title_refreshed = True

                if event.get("event") == "imported":
                    source_file = str(event.get("source_file") or "").replace("\\", "/")
                    document_id = event.get("document_id")
                    if (
                        bucket_path_fragment in source_file
                        and isinstance(document_id, str)
                        and document_id not in seen_ids
                    ):
                        seen_ids.add(document_id)
                        imported_ids.append(document_id)

        return BucketLedgerStatus(
            terminal_state=terminal_state,
            terminal_reason=terminal_reason,
            import_completed=import_completed,
            title_refreshed=title_refreshed,
            imported_document_ids=tuple(imported_ids),
        )

    def _coverage_sql(self) -> str:
        return """
WITH docs AS (
  SELECT
    d.id,
    d.structured_version,
    CASE
      WHEN d.source_reference ~ '(?:^|/)([0-9]{4})_' THEN
        substring(d.source_reference from '(?:^|/)([0-9]{4})_')::int
      WHEN d.source_reference ~ '_([0-9]{4})-[0-9]{2}-[0-9]{2}(?:\\.pdf)?$' THEN
        substring(d.source_reference from '_([0-9]{4})-[0-9]{2}-[0-9]{2}(?:\\.pdf)?$')::int
      WHEN d.decision_date IS NOT NULL THEN extract(year from d.decision_date)::int
      ELSE NULL
    END AS doc_year
  FROM authority_documents d
  WHERE d.forum_level = :forum_level
    AND (
      cast(:court_name as varchar) IS NULL
      OR d.court_name = cast(:court_name as varchar)
    )
),
bucket_docs AS (
  SELECT * FROM docs WHERE doc_year = cast(:source_year as integer)
)
SELECT
  count(*) AS docs,
  count(*) FILTER (WHERE structured_version IS NOT NULL) AS structured_docs,
  count(*) FILTER (WHERE structured_version IS NULL) AS pending_docs
FROM bucket_docs
"""

    def _hygiene_sql(self) -> str:
        return """
WITH docs AS (
  SELECT
    d.id,
    d.structured_version,
    CASE
      WHEN d.source_reference ~ '(?:^|/)([0-9]{4})_' THEN
        substring(d.source_reference from '(?:^|/)([0-9]{4})_')::int
      WHEN d.source_reference ~ '_([0-9]{4})-[0-9]{2}-[0-9]{2}(?:\\.pdf)?$' THEN
        substring(d.source_reference from '_([0-9]{4})-[0-9]{2}-[0-9]{2}(?:\\.pdf)?$')::int
      WHEN d.decision_date IS NOT NULL THEN extract(year from d.decision_date)::int
      ELSE NULL
    END AS doc_year
  FROM authority_documents d
  WHERE d.forum_level = :forum_level
    AND (
      cast(:court_name as varchar) IS NULL
      OR d.court_name = cast(:court_name as varchar)
    )
),
bucket_docs AS (
  SELECT * FROM docs WHERE doc_year = cast(:source_year as integer)
),
bucket_chunks AS (
  SELECT c.*
  FROM authority_document_chunks c
  JOIN bucket_docs d ON d.id = c.authority_document_id
)
SELECT
  (SELECT count(*) FROM bucket_docs) AS docs,
  (SELECT count(*) FROM bucket_docs WHERE structured_version IS NOT NULL) AS structured_docs,
  (SELECT count(*) FROM bucket_chunks WHERE chunk_role = 'metadata') AS metadata_chunks,
  (
    SELECT count(*) FROM bucket_chunks
    WHERE chunk_role = 'metadata'
      AND (
        content ~ :cid_re
        OR content ~ :indic_re
        OR content ~* :procedural_re
      )
  ) AS dirty_metadata_chunks,
  (
    SELECT count(*) FROM authority_document_chunks
    WHERE embedding_json IS NULL OR embedding_model IS NULL OR embedded_at IS NULL
  ) AS unembedded_chunks_global,
  (
    SELECT count(*) FROM bucket_chunks
    WHERE embedding_json IS NULL OR embedding_model IS NULL OR embedded_at IS NULL
  ) AS unembedded_chunks_in_bucket,
  (
    SELECT count(*) FROM authority_document_chunks
    WHERE embedding_json IS NOT NULL
      AND (
        embedding_model IS DISTINCT FROM 'voyage-4-large'
        OR embedding_dimensions IS DISTINCT FROM 1024
      )
  ) AS embedding_drift_chunks_global
"""

    def bucket_coverage(self, bucket: BucketPlan) -> dict[str, int]:
        session_factory = get_session_factory()
        with session_factory() as session:
            row = session.execute(
                text(self._coverage_sql()),
                {
                    "forum_level": bucket.forum_level,
                    "court_name": bucket.court_name,
                    "source_year": bucket.source_year,
                },
            ).mappings().one()
        return {key: int(row[key] or 0) for key in ("docs", "structured_docs", "pending_docs")}

    def read_hygiene(self, bucket: BucketPlan) -> HygieneMetrics:
        session_factory = get_session_factory()
        with session_factory() as session:
            row = session.execute(
                text(self._hygiene_sql()),
                {
                    "forum_level": bucket.forum_level,
                    "court_name": bucket.court_name,
                    "source_year": bucket.source_year,
                    "cid_re": r"\(cid:[0-9]+\)",
                    "indic_re": (
                        r"[\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F"
                        r"\u0A80-\u0AFF\u0B00-\u0B7F\u0B80-\u0BFF"
                        r"\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F]"
                    ),
                    "procedural_re": (
                        r"(^|\n)\s*[\(\[]?\s*(via\s+video[-\s]?conferencing|"
                        r"date\s+of\s+(judg(e)?ment|order|decision)|"
                        r"signature\s+not\s+verified)"
                    ),
                },
            ).mappings().one()
        return HygieneMetrics(
            docs=int(row["docs"] or 0),
            structured_docs=int(row["structured_docs"] or 0),
            dirty_metadata_chunks=int(row["dirty_metadata_chunks"] or 0),
            unembedded_chunks_global=int(row["unembedded_chunks_global"] or 0),
            unembedded_chunks_in_bucket=int(row["unembedded_chunks_in_bucket"] or 0),
            embedding_drift_chunks_global=int(row["embedding_drift_chunks_global"] or 0),
            metadata_chunks=int(row["metadata_chunks"] or 0),
        )

    def voyage_spend_since_start(self) -> float:
        session_factory = get_session_factory()
        with session_factory() as session:
            value = session.execute(
                text(
                    "SELECT coalesce(sum(cost_usd), 0) FROM voyage_usage "
                    "WHERE created_at >= :started_at AND status = 'ok'"
                ),
                {"started_at": self.started_at},
            ).scalar_one()
        return float(value or 0.0)

    def maybe_ingest_missing(self, bucket: BucketPlan, coverage: dict[str, int]) -> None:
        if not self.allow_s3_ingest or coverage["docs"] > 0:
            return
        self.event({
            "event": "state",
            "bucket": bucket.label,
            "state": BucketState.INGESTING,
            "reason": "no DB coverage for source-year bucket",
        })
        args = self._python_module(
            "caseops_api.scripts.ingest_corpus",
            "--from-s3",
            "--year",
            str(bucket.source_year),
            "--min-chars",
            "4000",
            "--limit",
            str(bucket.limit),
            "-v",
        )
        if bucket.forum_level == "supreme_court":
            args.extend(["--court", "sc"])
        else:
            args.extend(["--court", "hc"])
            if bucket.court_key:
                args.extend(["--hc-courts", bucket.court_key])
        self.run_command(args, output_path=self._bucket_dir(bucket) / "ingest.log")

    def export_bucket(self, bucket: BucketPlan) -> dict[str, Any]:
        bucket_dir = self._bucket_dir(bucket)
        manifest_dir = bucket_dir / "batch"
        common = [
            "--output-dir",
            str(manifest_dir),
            "--ledger",
            str(self.ledger_path),
            "--model",
            DEFAULT_BATCH_MODEL,
            "--forum-level",
            bucket.forum_level,
            "--year-range",
            f"{bucket.source_year}-{bucket.source_year}",
            "--language",
            bucket.language,
            "--limit",
            str(bucket.limit),
            "--shard-size",
            str(bucket.shard_size),
        ]
        if bucket.court_name:
            common.extend(["--court-name", bucket.court_name])
        dry = self.run_command(
            self._python_module(
                "caseops_api.scripts.export_authority_metadata_batch",
                *common,
                "--dry-run",
            ),
            output_path=bucket_dir / "export_dry_run.json",
        )
        dry_result = self._json_from_output(dry)
        estimate = float(dry_result.get("estimated_cost_usd") or 0.0)
        if self.openai_estimated_usd + estimate > self.policy.openai_cap_usd:
            raise RuntimeError(
                "OpenAI cap would be exceeded: "
                f"${self.openai_estimated_usd + estimate:.2f} > ${self.policy.openai_cap_usd:.2f}"
            )
        if int(dry_result.get("exported_requests") or 0) == 0:
            return dry_result
        output = self.run_command(
            self._python_module("caseops_api.scripts.export_authority_metadata_batch", *common),
            output_path=bucket_dir / "export.json",
        )
        result = self._json_from_output(output)
        self.openai_estimated_usd += float(result.get("estimated_cost_usd") or 0.0)
        return result

    def submit_bucket(self, bucket: BucketPlan, manifest_path: Path) -> dict[str, Any]:
        output = self.run_command(
            self._python_module(
                "caseops_api.scripts.submit_authority_metadata_batch",
                str(manifest_path),
                "--ledger",
                str(self.ledger_path),
            ),
            output_path=self._bucket_dir(bucket) / "submit.json",
        )
        return self._json_from_output(output)

    def monitor_bucket_until_done(self, bucket: BucketPlan, manifest_path: Path) -> dict[str, Any]:
        bucket_dir = self._bucket_dir(bucket)
        while True:
            output = self.run_command(
                self._python_module(
                    "caseops_api.scripts.monitor_authority_metadata_batch",
                    "--manifest",
                    str(manifest_path),
                    "--ledger",
                    str(self.ledger_path),
                    "--output-dir",
                    str(bucket_dir / "results"),
                    "--download-completed",
                ),
                output_path=bucket_dir / "monitor.json",
            )
            result = self._json_from_output(output)
            batches = result.get("batches") or []
            statuses = {str(item.get("status")) for item in batches}
            self.event({
                "event": "batch_status",
                "bucket": bucket.label,
                "statuses": sorted(statuses),
                "batches": batches,
            })
            if statuses <= {"completed"} and batches:
                return result
            if statuses & {"failed", "expired", "cancelled", "cancelling"}:
                raise RuntimeError(f"OpenAI Batch terminal failure for {bucket.label}: {statuses}")
            time.sleep(self.poll_seconds)

    def import_bucket(self, bucket: BucketPlan, manifest_path: Path) -> dict[str, Any]:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output_paths = [
            str(shard["output_path"])
            for shard in manifest.get("shards", [])
            if shard.get("output_path")
        ]
        if not output_paths:
            raise RuntimeError(f"completed manifest has no output_path values: {manifest_path}")
        output = self.run_command(
            self._python_module(
                "caseops_api.scripts.import_authority_metadata_batch",
                *output_paths,
                "--ledger",
                str(self.ledger_path),
                "--quarantine",
                str(self._bucket_dir(bucket) / "quarantine.jsonl"),
                "--commit-batch-size",
                "250",
            ),
            output_path=self._bucket_dir(bucket) / "import.json",
            check=False,
        )
        result = self._json_from_output(output)
        total = (
            int(result.get("imported") or 0)
            + int(result.get("skipped") or 0)
            + int(result.get("quarantined") or 0)
        )
        quarantined = int(result.get("quarantined") or 0)
        if total and quarantined / total > self.policy.quarantine_rate_cap:
            raise RuntimeError(
                f"quarantine rate {quarantined / total:.2%} exceeds cap for {bucket.label}"
            )
        return result

    def refresh_title_chunks(
        self,
        bucket: BucketPlan,
        *,
        document_ids: tuple[str, ...] = (),
    ) -> str:
        args = self._python_module(
            "caseops_api.scripts.backfill_title_chunks",
            "--refresh",
            "--batch-size",
            "32",
            "--forum-level",
            bucket.forum_level,
            "--year",
            str(bucket.source_year),
            "-v",
        )
        if bucket.court_name:
            args.extend(["--court-name", bucket.court_name])
        if document_ids:
            ids_path = self._bucket_dir(bucket) / "imported_document_ids.txt"
            ids_path.parent.mkdir(parents=True, exist_ok=True)
            ids_path.write_text("\n".join(document_ids) + "\n", encoding="utf-8")
            args.extend(["--ids-file", str(ids_path)])
        return self.run_command(args, output_path=self._bucket_dir(bucket) / "title_refresh.log")

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
        args.extend(["--language", self._language_for_eval(bucket.language)])
        report = self.run_command(args, output_path=bucket_dir / "eval.txt")
        return parse_eval_report(report)

    def evaluate_global(self) -> EvalMetrics:
        output = self.run_command(
            self._python_module(
                "caseops_api.scripts.eval_hnsw_recall",
                "--tenant",
                self.tenant_slug,
                "--sample-size",
                "30",
                "--k",
                "10",
                "--seed",
                "42",
            ),
            output_path=self.base_dir / "global_eval.txt",
        )
        metrics = parse_eval_report(output)
        rating = score_rating(metrics)
        self.event({
            "event": "global_eval",
            "rating": rating,
            "metrics": asdict(metrics),
        })
        if rating < self.policy.red_rating:
            raise RuntimeError(f"global rating below hard stop: {rating}")
        return metrics

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
        if classification.state == BucketState.RECOVERY_REQUIRED:
            self.event({
                "event": "recovery_queued",
                "bucket": bucket.label,
                "reason": classification.reason,
                "rating": classification.rating,
                "hygiene": asdict(hygiene),
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

    def finish_imported_bucket(
        self,
        bucket: BucketPlan,
        *,
        status: BucketLedgerStatus,
    ) -> BucketClassification:
        document_ids = status.imported_document_ids
        if not status.title_refreshed:
            self.event({
                "event": "state",
                "bucket": bucket.label,
                "state": BucketState.TITLE_CHUNK_REFRESH,
                "resume": status.import_completed,
                "document_ids": len(document_ids),
            })
            title_output = self.refresh_title_chunks(bucket, document_ids=document_ids)
            self.event({
                "event": "title_refresh_result",
                "bucket": bucket.label,
                "output_tail": title_output[-1000:],
                "document_ids": len(document_ids),
            })

        self.event({
            "event": "state",
            "bucket": bucket.label,
            "state": BucketState.HNSW_PROBE,
            "resume": status.import_completed,
        })
        hygiene = self.read_hygiene(bucket)
        voyage_spend = self.voyage_spend_since_start()
        if voyage_spend > self.policy.voyage_cap_usd:
            raise RuntimeError(
                f"Voyage cap exceeded: ${voyage_spend:.2f} > ${self.policy.voyage_cap_usd:.2f}"
            )
        metrics = self.evaluate_bucket(bucket)
        classification = self.mark_bucket(
            bucket,
            metrics=metrics,
            hygiene=hygiene,
            recovery_attempts=self.policy.max_recovery_attempts,
        )
        if classification.state in {BucketState.PAUSED_FOR_HUMAN, BucketState.FAILED}:
            raise RuntimeError(f"bucket hard stop: {bucket.label}: {classification.reason}")
        return classification

    def process_bucket(self, bucket: BucketPlan) -> BucketClassification | None:
        bucket_dir = self._bucket_dir(bucket)
        bucket_dir.mkdir(parents=True, exist_ok=True)
        status = self.bucket_ledger_status(bucket)
        if status.is_terminal:
            self.event({
                "event": "bucket_skipped_terminal",
                "bucket": bucket.label,
                "state": status.terminal_state,
                "reason": status.terminal_reason,
            })
            return None
        if status.import_completed:
            self.event({
                "event": "bucket_resumed_after_import",
                "bucket": bucket.label,
                "title_refreshed": status.title_refreshed,
                "document_ids": len(status.imported_document_ids),
            })
            return self.finish_imported_bucket(bucket, status=status)

        self.event({"event": "state", "bucket": bucket.label, "state": BucketState.PLANNED})
        coverage = self.bucket_coverage(bucket)
        self.event({"event": "coverage", "bucket": bucket.label, **coverage})
        self.maybe_ingest_missing(bucket, coverage)
        export_result = self.export_bucket(bucket)
        exported = int(export_result.get("exported_requests") or 0)
        if exported == 0:
            hygiene = self.read_hygiene(bucket)
            self.event({
                "event": "bucket_skipped_no_pending",
                "bucket": bucket.label,
                "hygiene": asdict(hygiene),
            })
            return None

        self.event({
            "event": "state",
            "bucket": bucket.label,
            "state": BucketState.LAYER2_STRUCTURING,
            "exported_requests": exported,
            "estimated_cost_usd": export_result.get("estimated_cost_usd"),
        })
        manifest_path = Path(str(export_result["output_dir"])) / "manifest.json"
        self.submit_bucket(bucket, manifest_path)
        self.monitor_bucket_until_done(bucket, manifest_path)
        import_result = self.import_bucket(bucket, manifest_path)
        self.event({"event": "import_result", "bucket": bucket.label, **import_result})
        status = self.bucket_ledger_status(bucket)
        return self.finish_imported_bucket(bucket, status=status)

    def run(self, buckets: list[BucketPlan]) -> int:
        acquire_lock(self.lock_path)
        self.event({
            "event": "controller_started",
            "dry_run": self.dry_run,
            "policy": asdict(self.policy),
            "bucket_count": len(buckets),
            "first_bucket": asdict(buckets[0]) if buckets else None,
            "last_bucket": asdict(buckets[-1]) if buckets else None,
        })
        try:
            if self.dry_run:
                for bucket in buckets:
                    self.event({
                        "event": "state",
                        "bucket": bucket.label,
                        "state": BucketState.PLANNED,
                    })
                self.event({
                    "event": "controller_finished",
                    "status": "planned",
                    "completed_buckets": 0,
                })
                return 0

            completed = 0
            for bucket in buckets:
                classification = self.process_bucket(bucket)
                if classification is not None:
                    completed += 1
                if completed and completed % self.global_eval_every == 0:
                    self.evaluate_global()
            self.evaluate_global()
            self.event({
                "event": "controller_finished",
                "status": "completed",
                "completed_buckets": completed,
                "openai_estimated_usd": round(self.openai_estimated_usd, 6),
                "voyage_spend_usd": round(self.voyage_spend_since_start(), 6),
            })
            return 0
        except Exception as exc:
            self.event({
                "event": "controller_paused",
                "status": "paused_for_human",
                "error": str(exc),
                "openai_estimated_usd": round(self.openai_estimated_usd, 6),
            })
            raise
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
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run the full SC/HC 2025-1990 sweep plan.",
    )
    parser.add_argument("--openai-cap-usd", type=float, default=500.0)
    parser.add_argument("--voyage-cap-usd", type=float, default=75.0)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--global-eval-every", type=int, default=5)
    parser.add_argument("--no-s3-ingest", action="store_true")
    parser.add_argument("--recover-below-target", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    plan = autonomous_sweep_plan() if args.sweep else _load_plan(args.plan)
    controller = CorpusController(
        base_dir=args.base_dir,
        tenant_slug=args.tenant,
        policy=StopLinePolicy(
            openai_cap_usd=args.openai_cap_usd,
            voyage_cap_usd=args.voyage_cap_usd,
            recover_below_target=args.recover_below_target,
        ),
        dry_run=args.dry_run,
        poll_seconds=args.poll_seconds,
        allow_s3_ingest=not args.no_s3_ingest,
        global_eval_every=args.global_eval_every,
    )
    return controller.run(plan)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
