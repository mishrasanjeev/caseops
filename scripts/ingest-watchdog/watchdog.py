"""Durable ingest watchdog.

Probes corpus activity on caseops-db. If the corpus has no recent ingest,
metadata, or title-chunk activity for longer than STALE_THRESHOLD_SEC
(default 2h), issues a reset on the ingest VM so its boot-time @reboot
cron can relaunch the screen sweeps.

Runs as a Cloud Run Job, triggered by Cloud Scheduler every 15 min. This
replaces the session-scoped CronCreate watchdog that vanished whenever the
Claude session ended.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

import psycopg
from google.cloud import compute_v1  # type: ignore[attr-defined]


def _env_map() -> dict[str, str]:
    """Return watchdog config with a repair path for a known bad deploy.

    On 2026-05-18 the Cloud Run Job had a single env var shaped like:
    ``PROJECT=perfect-period-305406 ZONE=... INSTANCE=...``. That made the
    Compute API project name invalid and every reset attempt failed. Keep the
    normal env path, but also parse accidentally-packed KEY=VALUE tokens so a
    redeployed image can self-heal even before the job env is corrected.
    """
    values = dict(os.environ)
    packed = values.get("PROJECT", "")
    if " " not in packed or "=" not in packed:
        return values

    tokens = packed.split()
    if tokens:
        values["PROJECT"] = tokens[0]
    for token in tokens[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key and value:
            values.setdefault(key, value)
    return values


_ENV = _env_map()
PROJECT = _ENV.get("PROJECT", "perfect-period-305406")
ZONE = _ENV.get("ZONE", "asia-south1-c")
INSTANCE = _ENV.get("INSTANCE", "caseops-ingest-vm")
STALE_THRESHOLD_SEC = int(_ENV.get("STALE_THRESHOLD_SEC") or 7200)
RESET_COOLDOWN_SEC = int(_ENV.get("RESET_COOLDOWN_SEC") or 1800)


def _db_url() -> str:
    raw = os.environ["CASEOPS_DATABASE_URL"]
    return raw.replace("postgresql+psycopg://", "postgresql://", 1)


@dataclass(frozen=True)
class ActivitySnapshot:
    ingest_stale_sec: int | None
    activity_stale_sec: int | None
    doc_count: int
    chunk_count: int
    structured_doc_count: int
    embedded_chunk_count: int
    metadata_chunk_count: int
    ingestion_run_count: int


def _activity_snapshot() -> ActivitySnapshot:
    with psycopg.connect(_db_url(), connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH doc AS (
                SELECT
                    COUNT(*)::int AS doc_count,
                    COUNT(*) FILTER (
                        WHERE structured_version IS NOT NULL
                    )::int AS structured_doc_count,
                    MAX(ingested_at) AS max_ingested_at,
                    MAX(updated_at) AS max_doc_updated_at
                FROM authority_documents
            ),
            chunk AS (
                SELECT
                    COUNT(*)::int AS chunk_count,
                    COUNT(*) FILTER (
                        WHERE embedding_model IS NOT NULL
                    )::int AS embedded_chunk_count,
                    COUNT(*) FILTER (
                        WHERE chunk_role = 'metadata'
                    )::int AS metadata_chunk_count,
                    MAX(created_at) AS max_chunk_created_at,
                    MAX(embedded_at) AS max_chunk_embedded_at
                FROM authority_document_chunks
            ),
            run AS (
                SELECT
                    COUNT(*)::int AS ingestion_run_count,
                    MAX(completed_at) AS max_ingestion_run_completed_at
                FROM authority_ingestion_runs
                WHERE adapter_name = 'corpus-ingest'
            ),
            activity AS (
                SELECT
                    doc.*,
                    chunk.*,
                    run.*,
                    GREATEST(
                        COALESCE(max_ingested_at, TIMESTAMPTZ 'epoch'),
                        COALESCE(max_doc_updated_at, TIMESTAMPTZ 'epoch'),
                        COALESCE(max_chunk_created_at, TIMESTAMPTZ 'epoch'),
                        COALESCE(max_chunk_embedded_at, TIMESTAMPTZ 'epoch'),
                        COALESCE(max_ingestion_run_completed_at, TIMESTAMPTZ 'epoch')
                    ) AS latest_activity_at
                FROM doc CROSS JOIN chunk CROSS JOIN run
            )
            SELECT
                CASE
                    WHEN max_ingested_at IS NULL THEN NULL
                    ELSE EXTRACT(EPOCH FROM (now() - max_ingested_at))::int
                END AS ingest_stale_sec,
                CASE
                    WHEN latest_activity_at = TIMESTAMPTZ 'epoch' THEN NULL
                    ELSE EXTRACT(EPOCH FROM (now() - latest_activity_at))::int
                END AS activity_stale_sec,
                doc_count,
                chunk_count,
                structured_doc_count,
                embedded_chunk_count,
                metadata_chunk_count,
                ingestion_run_count
            FROM activity
            """
        )
        row = cur.fetchone()
    if row is None:
        return ActivitySnapshot(None, None, 0, 0, 0, 0, 0, 0)
    return ActivitySnapshot(*row)


_LABEL_LAST_RESET = "watchdog-last-reset-unix"


def _seconds_since_last_watchdog_reset() -> int | None:
    """Return seconds since this watchdog last reset the VM, via a label
    sentinel we set on the instance. Returns None if no prior reset is
    recorded.

    GCE's `last_start_timestamp` only updates on stop+start, NOT on
    `instances.reset`, so it can't be used to enforce a reset cooldown.
    """
    client = compute_v1.InstancesClient()
    inst = client.get(project=PROJECT, zone=ZONE, instance=INSTANCE)
    raw = (inst.labels or {}).get(_LABEL_LAST_RESET)
    if not raw or not raw.isdigit():
        return None
    return int(time.time()) - int(raw)


def _reset_and_record() -> str:
    """Reset the VM and stamp the time on it as a label so we can enforce
    a cooldown window across watchdog runs."""
    client = compute_v1.InstancesClient()
    inst = client.get(project=PROJECT, zone=ZONE, instance=INSTANCE)
    labels = dict(inst.labels or {})
    labels[_LABEL_LAST_RESET] = str(int(time.time()))
    client.set_labels(
        project=PROJECT,
        zone=ZONE,
        instance=INSTANCE,
        instances_set_labels_request_resource=compute_v1.InstancesSetLabelsRequest(
            label_fingerprint=inst.label_fingerprint,
            labels=labels,
        ),
    )
    op = client.reset(project=PROJECT, zone=ZONE, instance=INSTANCE)
    return op.name


def main() -> int:
    snapshot = _activity_snapshot()
    print(
        "ingest_stale_sec="
        f"{snapshot.ingest_stale_sec} activity_stale_sec="
        f"{snapshot.activity_stale_sec} threshold={STALE_THRESHOLD_SEC} "
        f"docs={snapshot.doc_count} chunks={snapshot.chunk_count} "
        f"structured_docs={snapshot.structured_doc_count} "
        f"embedded_chunks={snapshot.embedded_chunk_count} "
        f"metadata_chunks={snapshot.metadata_chunk_count} "
        f"ingestion_runs={snapshot.ingestion_run_count}",
        flush=True,
    )

    if snapshot.ingest_stale_sec is None and snapshot.activity_stale_sec is None:
        print("no_data — corpus empty, nothing to do", flush=True)
        return 0

    if (
        snapshot.ingest_stale_sec is not None
        and snapshot.ingest_stale_sec <= STALE_THRESHOLD_SEC
    ):
        print("ok_recent_ingest", flush=True)
        return 0

    if (
        snapshot.activity_stale_sec is not None
        and snapshot.activity_stale_sec <= STALE_THRESHOLD_SEC
    ):
        print(
            "ok_recent_non_ingest_activity "
            "(Layer-2/title-chunk/probe phase likely active)",
            flush=True,
        )
        return 0

    since_last_reset = _seconds_since_last_watchdog_reset()
    print(f"sec_since_last_watchdog_reset={since_last_reset}", flush=True)
    if since_last_reset is not None and since_last_reset < RESET_COOLDOWN_SEC:
        print(
            f"cooldown — last reset {since_last_reset}s ago, "
            f"waiting at least {RESET_COOLDOWN_SEC}s before re-resetting",
            flush=True,
        )
        return 0

    print(f"STUCK — resetting {INSTANCE}", flush=True)
    op_name = _reset_and_record()
    print(f"reset_issued op={op_name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
