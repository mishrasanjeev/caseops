"""Durable ingest watchdog.

Probes the newest corpus activity on caseops-db. If the most recent ingest,
embedding, or Layer-2 metadata activity is older than STALE_THRESHOLD_SEC
(default 2h), issues a reset on the ingest VM so its boot-time @reboot cron can
relaunch the screen sweeps.

Runs as a Cloud Run Job, triggered by Cloud Scheduler every 15 min. This
replaces the session-scoped CronCreate watchdog that vanished whenever the
Claude session ended.
"""

from __future__ import annotations

import os
import sys
import time

import psycopg
from google.cloud import compute_v1  # type: ignore[attr-defined]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


PROJECT = os.environ.get("PROJECT", "perfect-period-305406")
ZONE = os.environ.get("ZONE", "asia-south1-c")
INSTANCE = os.environ.get("INSTANCE", "caseops-ingest-vm")
STALE_THRESHOLD_SEC = _env_int("STALE_THRESHOLD_SEC", 7200)
RESET_COOLDOWN_SEC = _env_int("RESET_COOLDOWN_SEC", 1800)


def _db_url() -> str:
    raw = os.environ["CASEOPS_DATABASE_URL"]
    return raw.replace("postgresql+psycopg://", "postgresql://", 1)


def _latest_activity() -> tuple[str | None, int | None]:
    with psycopg.connect(_db_url(), connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH activity(source, activity_at) AS (
                SELECT 'authority_documents.ingested_at', MAX(ingested_at)
                FROM authority_documents
                UNION ALL
                SELECT 'authority_document_chunks.embedded_at', MAX(embedded_at)
                FROM authority_document_chunks
                UNION ALL
                SELECT 'model_runs.metadata_extract', MAX(created_at)
                FROM model_runs
                WHERE purpose = 'metadata_extract'
                UNION ALL
                SELECT 'voyage_usage.ingest', MAX(created_at)
                FROM voyage_usage
                WHERE purpose = 'ingest'
            )
            SELECT source, EXTRACT(EPOCH FROM (now() - activity_at))::int
            FROM activity
            WHERE activity_at IS NOT NULL
            ORDER BY activity_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if not row:
        return None, None
    return row[0], row[1]


def _stale_seconds() -> int | None:
    _, stale = _latest_activity()
    return stale


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
    activity_source, stale = _latest_activity()
    print(
        f"activity_source={activity_source} stale_sec={stale} "
        f"threshold={STALE_THRESHOLD_SEC}",
        flush=True,
    )

    if stale is None:
        print("no_data — corpus empty, nothing to do", flush=True)
        return 0

    if stale <= STALE_THRESHOLD_SEC:
        print("ok", flush=True)
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
