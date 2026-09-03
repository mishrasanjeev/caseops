# Corpus ingestion runbook

Operator-facing guide for loading and re-embedding the shared Indian
authority corpus. Tracks Sprint G in
[`docs/WORK_TO_BE_DONE.md`](../WORK_TO_BE_DONE.md) §4.2.

## 0. Prerequisites

- Docker Postgres 17 + pgvector running. In this repo the dev compose
  file publishes Postgres on `127.0.0.1:15432` (native Postgres
  services own 5432/5433). Alembic migration `20260417_0003` has to
  be applied so `embedding_vector vector(1024)` exists.
- Python 3.13 + `uv` from the repo root.
- Disk headroom: 500 MB soft cap per scope is the default; lift with
  `CASEOPS_CORPUS_INGEST_MAX_WORKDIR_MB`. A full 10-year × 5-HC + SC
  ingestion temporarily touches a few tens of GB even with streaming.
- Embedding backend configured:

  | Provider                    | `CASEOPS_EMBEDDING_PROVIDER` | Notes                                                                                                        |
  | --------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------ |
  | Mock (offline, default)     | `mock`                       | Deterministic; CI-safe; wrong for production retrieval.                                                      |
  | fastembed (BGE-small)       | `fastembed`                  | `uv sync --extra embeddings`; first run downloads ~250 MB. Dev/offline fallback, not the production default. |
  | Voyage (voyage-4-large)     | `voyage`                     | `CASEOPS_EMBEDDING_API_KEY=…` required. Current production standard on GCP.                                  |
  | Gemini (text-embedding-005) | `gemini`                     | `CASEOPS_EMBEDDING_API_KEY=…`. General-purpose alternative, not the current production default.              |

  All four providers write into the same `vector(1024)` column — a
  switch between them is a re-embedding, not a re-ingestion.

## 1. Ingest — streaming from public S3

The CLI downloads a batch (default 25 PDFs / 1 tarball), ingests it,
deletes the files, and moves on. Canonical-key dedup means re-running
the same year is a no-op.

```bash
# Supreme Court tarballs, one year at a time (each tar is 200-400 MB).
uv run caseops-ingest-corpus --court sc --year 2023 --from-s3 -v

# Supreme Court, 10 years in one go. Use --years with a range or list.
uv run caseops-ingest-corpus --court sc --years 2015-2024 --from-s3 -v

# High Court, one jurisdiction × one year (quick trial).
uv run caseops-ingest-corpus --court hc --year 2023 --from-s3 \
  --hc-courts delhi --limit 50 -v

# High Court, the five target jurisdictions × 10 years.
# ~440k docs; plan for multiple days on CPU, hours on a modern GPU.
uv run caseops-ingest-corpus --court hc --years 2015-2024 --from-s3 \
  --hc-courts delhi,bombay,karnataka,madras,telangana -v
```

Useful flags:

| Flag                 | Default                 | Purpose                                                                     |
| -------------------- | ----------------------- | --------------------------------------------------------------------------- |
| `--limit N`          | off                     | Cap per year; good for smoke tests.                                         |
| `--batch-size N`     | from settings           | How many PDFs per streaming batch (HC) or chunk size per iteration.         |
| `--max-workdir-mb N` | 500                     | Soft cap on disk used by the streaming temp dir.                            |
| `--keep`             | off                     | Don't delete PDFs after ingesting (useful for forensics).                   |
| `--temp-root PATH`   | `tempfile.gettempdir()` | Override the workdir root (e.g. point at a fast SSD).                       |
| `--hc-courts names`  | —                       | Comma list — only ingest these HCs. See `HC_COURT_CATALOG` for valid names. |
| `-v`                 | —                       | Progress-per-scope to stdout.                                               |

## 2. Re-embed — model swap without re-ingesting

Text and chunking survive a model swap. Only the vector changes. Run:

```bash
# Pick the new model, then reembed.
export CASEOPS_EMBEDDING_PROVIDER=voyage   # or fastembed / gemini
export CASEOPS_EMBEDDING_MODEL=voyage-4-large
export CASEOPS_EMBEDDING_API_KEY=...       # if the provider needs one

uv run caseops-ingest-corpus --reembed -v
```

- Scans chunks whose `embedding_model` does not match the current
  provider's model; rerunning is idempotent.
- `--force` recomputes every chunk regardless.
- `--batch-size N` (default 64) controls chunks per provider call.
- Keyset-paginated by chunk id, so commits inside the loop don't
  cause rows to be skipped.

### 2.1 Authority-metadata extraction safety

The scheduled metadata extractor treats provider credit exhaustion as a
process-wide stop, not as 800,000 independent document errors. It keeps at
most `--concurrency` calls in flight, records the failed provider call, drains
only that bounded window, and exits non-zero:

| Exit code | Meaning                       | Operator action                                                                            |
| --------- | ----------------------------- | ------------------------------------------------------------------------------------------ |
| `0`       | Requested sweep completed     | Review counters and normal evidence.                                                       |
| `2`       | Daily spend cap reached       | Review the cap and spend before another run.                                               |
| `3`       | Provider credits exhausted    | Keep the schedule paused; restore credits and run the canary below.                        |
| `4`       | Provider canary failed closed | Keep the schedule paused; no eligible row or no successful provider completion was proved. |

On 2026-08-14, execution `caseops-extract-authority-metadata-wv2b7` was
cancelled after repeatedly receiving OpenAI `credit_balance_exhausted` while
walking an 803,139-document backlog. The daily scheduler was paused. Do not
resume it merely because a new image was deployed: first prove the configured
secret and provider account with one document on the current job image.
The checked-in scheduler inventory intentionally declares this scheduler
`PAUSED`; standard deployment must preserve that state until the reviewed
restart change described below.

```bash
gcloud run jobs execute caseops-extract-authority-metadata \
  --region=asia-south1 \
  --project=perfect-period-305406 \
  --args="-m,caseops_api.scripts.extract_authority_metadata,--provider-canary" \
  --wait
```

`--provider-canary` ignores broader limit/concurrency/force options, selects
one metadata-missing document with at least 200 text characters, and forces
`--limit=1 --concurrency=1`. The canary passes only when all of these are true:

- the Cloud Run execution exits `0`;
- the final log reports `processed=1`, `submitted=1`, `llm_err=0`, and
  `parse_err=0`; and
- a new `metadata_extract` `ModelRun` has `status=ok` for the configured live
  provider/model.

A successful one-document canary does **not** authorize an untracked direct
resume. In a reviewed canonical change, flip only the authority job's
`desired_state` in `infra/cloudrun/scheduler-inventory.json` from `PAUSED` to
`ENABLED`, then deploy/reconcile that exact revision. The reconciler performs
the resume and verifies state plus the canonical 43,200-second task timeout.
An emergency direct `gcloud scheduler jobs resume` is temporary drift and must
be followed immediately by the same reviewed inventory change and reconcile.

If the canary reports exit code `2`, `3`, or `4`, leave the scheduler paused.
Never launch the full backlog as a provider-health probe.

## 3. Verification

```bash
# Total documents + chunks + which model each chunk is on.
docker exec caseops-postgres-1 psql -U caseops -d caseops -c "
  SELECT forum_level, court_name, COUNT(*) FROM authority_documents
  GROUP BY forum_level, court_name ORDER BY 1, 2;
  SELECT embedding_model, COUNT(*) FROM authority_document_chunks
  GROUP BY embedding_model;
  SELECT COUNT(*) AS with_vector FROM authority_document_chunks
  WHERE embedding_vector IS NOT NULL;
"
```

A production-ready state is: every row has `embedding_vector NOT NULL`
and all rows share a single `embedding_model`. Mixed models means a
re-embed was interrupted — rerun `--reembed`.

## 4. Quality gate (pre-pilot)

Before calling any corpus slice production-ready, run a fixed 50-query legal
eval set and record recall@10 and p95 retrieval latency. Current production
truth assumes **Voyage `voyage-4-large`**, OpenAI-backed metadata cleanup
where needed, and reranking enabled. If the slice fails the 4.8+/5 quality bar
or recall is below the agreed target, try either:

1. A stronger or better-benchmarked embedding model/path, or
2. A cross-encoder reranker (§4.2 Remaining).

Measurements belong in this runbook — update the "Bench runs" table
below when a run completes.

### Bench runs

| Date                                                    | Provider + model | Corpus size | Recall@10 | p95 latency | Notes |
| ------------------------------------------------------- | ---------------- | ----------- | --------- | ----------- | ----- |
| _(none recorded yet — add one after first `--reembed`)_ |                  |             |           |             |       |

## 5. Known footguns

- **Port 5432 conflict.** Native Postgres services on Windows take
  5432 / 5433; the docker Postgres is published on `15432`. All
  examples above assume that.
- **First-time fastembed cold start.** Downloads ~250 MB of ONNX on
  first call. Warm up the container before timing anything.
- **Model swap, same corpus, wrong target.** If you export the wrong
  `CASEOPS_EMBEDDING_MODEL`, `--reembed` will happily rewrite every
  row. Run `--reembed --limit 1` first to sanity-check the model
  identifier printed in the summary.
- **Dual stacks on one DB.** SC tarballs and HC PDFs both land in the
  same `authority_documents` table. If you ingest a different
  jurisdiction into a dev DB you had populated for tests, the test
  suite's cross-tenant assertions still hold because the data is
  shared-public anyway.
