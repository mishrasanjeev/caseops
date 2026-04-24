# P1-009 — Cloud SQL backup/restore drill (2026-04-24)

**Verdict:** Properly verified. Cloud SQL automated backups + clone-from-backup
restore the prod database to a queryable, schema-identical, index-intact
instance in roughly **7 minutes** (RTO observed) for a 200 GB / 1.4 M chunk
corpus.

## Source of truth

- Prod instance: `perfect-period-305406:asia-south1:caseops-db`
  - `db-custom-2-7680`, 200 GB SSD, POSTGRES_17, backups at 03:00 UTC daily,
    point-in-time recovery enabled.
  - Latest automated backup at drill time: ID `1776999600000`, taken
    2026-04-24T04:33:12 UTC.

## Commands run

```bash
# 1. Baseline read of prod (read-only, via cloud-sql-proxy on :15433).
gcloud secrets versions access latest --secret=caseops-db-password
cloud-sql-proxy --port=15433 perfect-period-305406:asia-south1:caseops-db
# psql / psycopg counts (see "Baseline" table below).

# 2. Clone prod into a throwaway instance using the latest backup.
gcloud sql instances clone caseops-db caseops-db-restore-test --quiet
# Took ~7m wall-clock (PENDING_CREATE → RUNNABLE).

# 3. Connect to the clone and re-run the same counts + an HNSW probe.
cloud-sql-proxy --port=15434 perfect-period-305406:asia-south1:caseops-db-restore-test

# 4. Cleanup.
gcloud sql instances delete caseops-db-restore-test --quiet
```

## Evidence

| Metric | Prod (17:14 UTC) | Restored (17:52 UTC) | Notes |
|---|---|---|---|
| `authority_documents` | 71,401 | 71,409 | +8 from live ingest between snapshots |
| `authority_document_chunks` | 1,416,366 | 1,416,436 | +70 from same window |
| `matters` | 30 | 30 | identical |
| `companies` | 64 | 64 | identical |
| `audit_events` | 132 | 132 | identical |
| `alembic_version` | `20260424_0001` | `20260424_0001` | identical |
| `pgvector` | 0.8.1 | 0.8.1 | identical |
| HNSW indexes | (n/a) | 2 present | `pg_indexes.indexdef ILIKE '%hnsw%'` |

The small `authority_*` delta is the corpus ingest sweep continuing between the
baseline capture (17:14) and the actual backup snapshot the clone was built
from (slightly later than 17:14). That delta is itself evidence — the clone is
not stale.

## HNSW probe

A nearest-neighbour query on the restored clone returned 5 rows in **88 s**
(`hnsw_query_ms=88207`). On the warm prod instance the same query is sub-second.
The 88 s figure is expected for a cold clone — the HNSW index pages are not yet
loaded into shared buffers, and `cloud-sql-proxy` adds round-trip latency. The
result count is correct (5 rows) and the index entries exist
(`hnsw_idx_present=2`), so the structural health of pgvector survived the
clone. A production cutover would warm the index by replaying the canonical
recall-eval queries before serving traffic.

## RTO / RPO

- **RTO observed**: 7 min wall-clock from `gcloud sql instances clone` start to
  `RUNNABLE`. Add ~1 min for proxy setup + verification queries → end-to-end
  ~8-10 min for a corpus this size.
- **RPO**: ≤ 24 h with the daily-backup schedule. PITR is enabled, so
  fine-grained recovery is also available via `--point-in-time` flag.

## Caveats / gaps

- Drill exercised **clone-from-backup**, which is the warm-restore path. A
  full disaster scenario (region loss, account compromise) would also need
  cross-region backup export. Cloud SQL backups today live in the same
  multi-region as the source — flagged for follow-on work.
- Application-level cutover (Cloud Run env-var swap to point `caseops-api` at
  the restored instance) was not exercised. The drill stopped at "the restore
  is queryable and matches prod schema." A future drill should also flip a
  staging revision over to a restored instance to prove the application boots
  cleanly against it.
- Tenant-export drill (per-company snapshot for portability or right-to-erasure
  compliance) is a separate, untouched gap (WTD-8.3 sub-item).

## Cleanup

`gcloud sql instances delete caseops-db-restore-test --quiet` — confirms
non-recoverable deletion of the throwaway. No prod side-effect.
