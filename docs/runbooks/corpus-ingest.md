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

  | Provider | `CASEOPS_EMBEDDING_PROVIDER` | Notes |
  | --- | --- | --- |
  | Mock (offline, default) | `mock` | Deterministic; CI-safe; wrong for production retrieval. |
  | fastembed (BGE-small) | `fastembed` | `uv sync --extra embeddings`; first run downloads ~250 MB. |
  | Voyage (voyage-3-law) | `voyage` | `CASEOPS_EMBEDDING_API_KEY=…` required. Legal-tuned; paid. |
  | Gemini (text-embedding-005) | `gemini` | `CASEOPS_EMBEDDING_API_KEY=…`. Pairs with the Gemini LLM provider. |

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

| Flag | Default | Purpose |
| --- | --- | --- |
| `--limit N` | off | Cap per year; good for smoke tests. |
| `--batch-size N` | from settings | How many PDFs per streaming batch (HC) or chunk size per iteration. |
| `--max-workdir-mb N` | 500 | Soft cap on disk used by the streaming temp dir. |
| `--keep` | off | Don't delete PDFs after ingesting (useful for forensics). |
| `--temp-root PATH` | `tempfile.gettempdir()` | Override the workdir root (e.g. point at a fast SSD). |
| `--hc-courts names` | — | Comma list — only ingest these HCs. See `HC_COURT_CATALOG` for valid names. |
| `-v` | — | Progress-per-scope to stdout. |

## 2. Re-embed — model swap without re-ingesting

Text and chunking survive a model swap. Only the vector changes. Run:

```bash
# Pick the new model, then reembed.
export CASEOPS_EMBEDDING_PROVIDER=voyage   # or fastembed / gemini
export CASEOPS_EMBEDDING_MODEL=voyage-3-law
export CASEOPS_EMBEDDING_API_KEY=...       # if the provider needs one

uv run caseops-ingest-corpus --reembed -v
```

- Scans chunks whose `embedding_model` does not match the current
  provider's model; rerunning is idempotent.
- `--force` recomputes every chunk regardless.
- `--batch-size N` (default 64) controls chunks per provider call.
- Keyset-paginated by chunk id, so commits inside the loop don't
  cause rows to be skipped.

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

Before the first paying customer, run a fixed 50-query legal-eval
set and record recall@10 and p95 retrieval latency. If recall is
below 0.5, try either:

1. A stronger embedding model (e.g. `voyage-3-law`), or
2. A cross-encoder reranker (§4.2 Remaining).

Measurements belong in this runbook — update the "Bench runs" table
below when a run completes.

### Bench runs

| Date | Provider + model | Corpus size | Recall@10 | p95 latency | Notes |
| --- | --- | --- | --- | --- | --- |
| _(none recorded yet — add one after first `--reembed`)_ | | | | | |

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
