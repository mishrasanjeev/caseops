---
name: corpus-ingest
description: Use this skill whenever the user asks to ingest, embed, populate, backfill, or improve quality of the CaseOps authority corpus (Supreme Court / High Court judgments) in Postgres/pgvector on GCP. Also use when the user asks for a retrieval quality probe or a 0-5 rating on the embedded vectors. Enforces the correct per-bucket pipeline (ingest → Layer-2 metadata → title-chunk embed → quality probe) that prevents the "placeholder title poisons embeddings" failure mode.
version: 1.0.0
user-invocable: false
license: Internal. Captures lessons from 2026-04-19 SC/HC sweep.
---

# Corpus-ingest skill

When the user asks for anything matching "ingest / embed / populate / backfill /
re-embed / improve data quality" against the CaseOps authority corpus (SC, HC,
or any future court), **follow this pipeline exactly**. Skipping a step or
reordering costs real money (Voyage + Anthropic spend) and drops retrieval
quality below the starting bar. This was learned the hard way on 2026-04-19 —
see `memory/feedback_vector_embedding_pipeline.md` for the incident.

## The ONE pipeline — per bucket (a "bucket" is one court-year, e.g. sc-2023 or hc-delhi-2024)

```
1. INGEST         caseops-ingest-corpus --from-s3 --court <c> --year <y> --min-chars 4000 --limit 2000
2. LAYER 2        caseops-backfill-corpus-quality --stage structured --budget-usd 30
3. TITLE CHUNK    python -m caseops_api.scripts.backfill_title_chunks --batch-size 32
4. PROBE          caseops-eval-hnsw-recall --tenant aster-demo --sample-size 30 --k 10 --seed 42
5. RATE           Report X.Y / 5 using the rubric below. If the rating dropped
                  bucket-over-bucket: STOP. Diagnose before running the next bucket.
```

**Never batch Layer 2 at the end of a multi-bucket sweep.** Ingest uses Voyage;
Layer 2 uses Anthropic. No API contention. Running Layer 2 per-bucket means
every title-chunk is embedded from REAL case-name metadata instead of
filename-derived placeholders like `"2024_2_231_238_EN.pdf"`. The title-chunk
is the single biggest recall lever for case-name queries — it MUST be seeded
from good metadata.

## Required env for every ingest command

```bash
export DB_PW=$(gcloud secrets versions access latest --secret=caseops-db-password)
export VOYAGE_KEY=$(gcloud secrets versions access latest --secret=caseops-voyage-api-key)
export ANTHROPIC_KEY=$(gcloud secrets versions access latest --secret=caseops-anthropic-api-key)

export CASEOPS_DATABASE_URL="postgresql+psycopg://caseops:${DB_PW}@127.0.0.1:25432/caseops"
export CASEOPS_EMBEDDING_PROVIDER=voyage
export CASEOPS_EMBEDDING_MODEL=voyage-4-large
export CASEOPS_EMBEDDING_DIMENSIONS=1024
export CASEOPS_EMBEDDING_API_KEY="$VOYAGE_KEY"
export CASEOPS_LLM_PROVIDER=anthropic
export CASEOPS_LLM_MODEL=claude-haiku-4-5-20251001
export CASEOPS_LLM_API_KEY="$ANTHROPIC_KEY"
export CASEOPS_RERANK_ENABLED=true        # probe AND prod must have this
export CASEOPS_RERANK_BACKEND=fastembed
export PYTHONUNBUFFERED=1
```

Cloud SQL Auth proxy must be running on port **25432** (workstation ports
5432/5433 are blocked on Sanjeev's Windows box):

```bash
cloud-sql-proxy --port 25432 perfect-period-305406:asia-south1:caseops-db &
```

## Non-negotiable quality gates

Never disable these; they are the reason the pipeline works.

1. **`--min-chars 4000`** at ingest — skips 1-page procedural orders that are
   noise without signal. Without this, corpus explodes with stay/listing
   orders that compete in top-K for every query.
2. **`canonical_key` sha256 dedup** (court|year|filename|size) — inherent to
   `persist_judgment`. Never bypass. Re-ingestion of the same PDF must skip.
3. **No `--keep` flag** — each PDF/TAR is unlinked the moment its chunks are
   upserted. See `feedback_ingest_disk_hygiene.md`.
4. **Voyage `input_type`** — `"document"` at ingest (wired in
   `services/embeddings.py::VoyageProvider`), `"query"` at retrieval. A new
   codepath that drops `input_type` silently loses 5-15 pp recall.
5. **Reranker ON for probe and prod** — `CASEOPS_RERANK_ENABLED=true` +
   `CASEOPS_RERANK_BACKEND=fastembed`. Lifts MRR +0.1 and mean rank -0.7
   even without changing recall@10. Verified on prod 2026-04-19.
6. **Probe seed pinned to 42** — same 30 sample docs across probes so the
   delta is meaningful.

## Parallelism rules

- Voyage (ingest + title-chunk) and Anthropic (Layer 2) run on distinct APIs.
  They CAN and SHOULD run in parallel. Different buckets serially, but
  within one bucket the three backend calls do not contend.
- HuggingFace tokenizer fetches are slow (unauth rate limit). First Voyage
  call warms the tokenizer in `~/.cache/huggingface/`; set `HF_TOKEN` for
  long runs.
- Do NOT invoke `caseops-*` CLI scripts in parallel with an active ingest —
  uv's venv Scripts dir gets file-locked on Windows. Use
  `uv run --no-sync python -m caseops_api.scripts.<module>` instead of the
  CLI wrapper when there's concurrent work.

## 0-5 rating rubric (retrieval, not extraction)

Measure via `caseops-eval-hnsw-recall --sample-size 30 --k 10 --seed 42` with
rerank ON. **Never** rate from Layer-2 extraction sampling — that measures
metadata quality, not retrieval. They diverge wildly (4.7 extraction /
2.5 retrieval, 2026-04-19).

- **5.0** — recall@10 ≥ 0.95, MRR ≥ 0.9, mean rank ≤ 1.2, zero noise in top-10
- **4.8** — recall@10 ≥ 0.93, MRR ≥ 0.88, mean rank ≤ 1.2  *(target)*
- **4.5** — recall@10 ≥ 0.90, MRR ≥ 0.85, mean rank ≤ 1.25
- **4.0** — recall@10 ≥ 0.85, MRR ≥ 0.75, mean rank ≤ 1.5
- **3.5** — recall@10 ≥ 0.75, MRR ≥ 0.70; signal-to-noise degraded
- **3.0** — recall@10 ≥ 0.70; cross-lingual siblings / noise in top-10
- **2.5 or below** — broken; stop ingesting, investigate

Report after every bucket as: `rating: X.Y/5 (recall@10=NN.N%, MRR=0.YYY, rank=Z.ZZ)`.
A drop bucket-over-bucket → STOP and diagnose.

## Levers to move from 4.0 → 4.8+

Ordered by impact per dollar:

1. **Complete Layer 2 on every doc BEFORE its title-chunk is embedded.**
   Stuck misses in every probe are case-name queries on Layer-2-NULL docs.
2. **Title-chunk refresh after Layer 2** —
   `caseops-backfill-title-chunks --refresh` drops existing
   `chunk_role='metadata'` chunks and rebuilds from current metadata.
   Needed whenever titles get richer.
3. **Parties-JSON pre-filter** — for case-name queries, exact-match
   `parties_json @> '[...]'` BEFORE vector search. Bypasses the hard
   proper-noun queries entirely. Not yet implemented.
4. **Query expansion (Haiku)** — thin queries like
   `"Rajan The State of Haryana"` rewritten to
   `"Rajan v. State of Haryana criminal appeal SLP"` before embedding.
   Not yet implemented.
5. **OCR-garbage gate** — reject chunks with `(cid:\d+)` density > 1%
   before embedding. Older SC PDFs (1950s-70s) and some HC scans have this.
   Not yet implemented; currently the pipeline silently embeds garbage.
6. **Language filter** — `WHERE language='en'` at retrieval. Removes the
   multilingual siblings Voyage pulls in. Not yet implemented.

When the user says "target 4.8+", levers 1-3 are on the critical path.

## Autonomous sweep

The sweep script at `tmp/sweep.sh` chains buckets per the pipeline above for
SC 2025 → 1980 descending and HC 2025 → 2010 × top-5 courts (delhi, bombay,
karnataka, madras, telangana). State file: `tmp/sweep_state.txt`. Per-bucket
logs: `tmp/ingest_buckets/<label>.log`.

Relaunch for a fresh run:

```bash
bash /c/Users/mishr/caseops/tmp/sweep.sh
```

## Anti-patterns — do NOT do these

- Batch Layer 2 at the end of a multi-bucket sweep.
- Rate the corpus from Layer-2 extraction samples rather than an HNSW probe.
- Probe only at session start and end — miss the drop trajectory.
- Forget `get_settings.cache_clear()` in test fixtures when overriding
  `CASEOPS_DATABASE_URL` — tests hit prod via cached settings.
- Ask the user questions when they've told you to run autonomously. Execute,
  report quality ratings on the 15-min cadence, surface failures, move on.
