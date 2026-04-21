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

## North-star rule — best quality, no dummy or incorrect rows

> Prefer a smaller clean corpus to a larger noisy one. If a doc / chunk /
> header can only be produced from placeholder or malformed data, **SKIP
> IT**. Do not save a degraded row "just to have coverage". Quality
> trumps scope. Always.

Enforcement in this pipeline:

- Title-chunk header builder returns `""` (→ skip embed) when the only
  available signal is a citation-only title AND parties_json is empty.
- Layer 2 on malformed JSON: raise + skip, NEVER partial-save.
- OCR-garbage gate at ingest: reject chunks with `(cid:\d+)` density > 1%
  or > 20% control / non-BMP glyph density.
- `--min-chars 4000` floor is non-negotiable.
- Non-English docs must be tagged `language=non_en` so retrieval can
  filter. Do not embed them as if they were English.
- Do NOT run title-chunk backfill before Layer 2 — the header would be
  built from the placeholder title. Per-bucket order matters.
- A missing row is recoverable (`structured_version IS NULL` tells you).
  A dummy row is invisible poison. Err towards missing.

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

## Title hygiene is upstream of every retrieval fix

Learned on 2026-04-21 (sc-2023 stuck at 4.17/5 for a week of algorithm work):
PDF page headers leak into `title` during extraction — e.g.
`"DHARWAD BENCH"`, `"BENCH AT AURANGABAD"`, `"IN THE HIGH COURT OF
KARNATAKA"`. These strings:

- Pass every naive gate (non-empty, latin, no `(cid:XX)` markers).
- Get embedded into the title-chunk header as if they were case names.
- Collapse hundreds of docs onto near-identical embedding coordinates.
- Get fed back into the probe as `_build_query(title)` → 287 docs share
  the seed query `"DHARWAD BENCH"` → recall@10 for those samples is
  structurally 1/287.

**Dashboards lie in this state.** Probe rating is stuck in the low 4s and
every retrieval-side fix (prefilters, rerank, normalisers, query
expansion) moves it by noise because the failure isn't in retrieval.

### Detection — run after every ingest bucket

```sql
SELECT count(*), 'bench_placeholder' AS pattern FROM authority_documents
  WHERE title ~* '^(DHARWAD|AURANGABAD|JODHPUR|KOZHIKODE|NAGPUR|MADURAI|LUCKNOW|INDORE|GWALIOR|RANCHI|JABALPUR|GUWAHATI|SHILLONG|IMPHAL|AIZAWL|KOHIMA|GANGTOK|ITANAGAR) BEN ?CH$'
     OR title ~* '^BENCH AT [A-Z]+$'
UNION ALL
SELECT count(*), 'court_header' FROM authority_documents
  WHERE title ~* '^IN THE (HIGH|SUPREME) COURT'
UNION ALL
SELECT count(*), 'too_short' FROM authority_documents
  WHERE length(title) < 12
UNION ALL
SELECT count(*), 'non_latin' FROM authority_documents
  WHERE title ~ '[\u0900-\u097F\u0A00-\u0A7F\u0B80-\u0BFF\u0C00-\u0C7F\u0D00-\u0D7F]'
UNION ALL
SELECT count(*), 'cid_marker' FROM authority_documents
  WHERE title ~ '\(cid:[0-9]+\)';
```

**> 1% of bucket flagged = STOP**. Do not ship retrieval fixes on a
corpus with a dirty title tail; fix the titles first.

### Title-validation predicate (write at ingest, re-check at probe)

A Layer-2-extracted title is a valid case-name seed iff it matches at
least ONE of:

1. Party separator with proper nouns on each side — regex
   `\b\w{3,}\s+(v\.?|vs\.?|versus|and)\s+\w{3,}\b` (case-insensitive).
2. Neutral citation / case reference — one of `\[\d{4}\]`, `\bSCC\b`,
   `\bAIR\b`, `\bINSC\b`, `\bDHC\b`, `\bSCR\b`, `\d{4}[a-z:]{3,}\d+`.
3. Party-role label — `Petitioner`, `Respondent`, `Appellant`,
   `Applicant`, `Accused`, `Complainant` as a standalone word.
4. ≥ 3 distinct proper-noun tokens NOT in the bench-header stopword set
   (same list as the SQL detector above plus `BENCH`, `AT`, `CIRCUIT`,
   `HIGH`, `COURT`, `SUPREME`, `STATE`, `UNION`, `OF`, `INDIA`).

### Fallback chain when the predicate fails

Apply at ingest time (before the row is written) AND at title-chunk
refresh time (before a new header is embedded):

```
raw_title → predicate → if pass: keep
                     → if fail: try `case_reference` → predicate
                              → if fail: try first entry of
                                  `parties_json` → predicate
                              → if fail: SKIP the title-chunk
                                  embedding entirely and mark
                                  `title_needs_reextract = true`
```

**Never save a degraded title string as the canonical title.** A missing
title is recoverable; a placeholder title is invisible poison (see the
north-star rule at the top of this skill).

### Probe must skip, not measure, garbage-titled docs

`caseops-eval-hnsw-recall`'s `_sample_probes` must apply the
title-validation predicate to each candidate. Docs that fail the
predicate are skipped (not added to the sample) and the skip count is
reported alongside the rating:

```
rating: 4.83/5 (recall@10=96.7 %, MRR=0.902, rank=1.18)
skipped: 3/33 (bench_placeholder=2, too_short=1)
```

If `skipped / total > 10%`: the probe is measuring a shrunken sample
and the rating is unreliable. Schedule a Layer-2 re-extract pass on the
skipped docs with the targeted prompt below.

### Targeted Layer-2 re-extract prompt for bench-placeholder docs

```
Extract the case name from this judgment's first 3 pages.

Rules:
- Do NOT return the page header, bench name alone, or court name alone.
  Strings like "DHARWAD BENCH", "BENCH AT AURANGABAD",
  "IN THE HIGH COURT OF KARNATAKA" are NEVER valid case names.
- A valid case name has two parties separated by "v." / "vs." / "versus"
  / "and", OR a neutral citation, OR at least three distinctive
  proper-noun tokens.
- If the first 3 pages do not contain the case name (continuation
  pages, translation covers, procedural orders), return the JSON
  literal `null`. Do not invent.

Return a JSON object: {"title": "<case name or null>"}.
```

Run on the subset flagged by the SQL detector; do NOT re-extract the
whole bucket.

### Principle

In any pipeline where stage N writes a field that stage N+1 trusts to
be semantically meaningful, "field is non-empty" is NEVER sufficient;
the predicate stage N+1 actually needs must be enforced at the write,
or reasserted at the read. Prefer the former: fail early, fail at the
source.

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
- Use Sonnet for Layer 2 on huge docs. Sonnet returns malformed JSON at
  >~45k chars output — use `--force-tier haiku` until `corpus_structured`
  adds a tolerant JSON repair path.
- Run the per-bucket retry loop with no timeout ceiling. Cloud SQL drops
  long-running client connections; treat that as retryable, not terminal.

## Final tested recipe — reliably reaches 4.8+/5

Tested 2026-04-19/20 on the CaseOps prod corpus. **Do not deviate from
this recipe without running an HNSW probe first.**

### Setup (once per session)

```bash
# 1. Proxy on port 25432 (5432/5433 blocked on Sanjeev's Windows box).
cloud-sql-proxy --port 25432 perfect-period-305406:asia-south1:caseops-db &

# 2. Export the env block. Reuse for ingest / Layer 2 / probe / backfill.
export DB_PW=$(gcloud secrets versions access latest --secret=caseops-db-password)
export VOYAGE_KEY=$(gcloud secrets versions access latest --secret=caseops-voyage-api-key)
export ANTHROPIC_KEY=$(gcloud secrets versions access latest --secret=caseops-anthropic-api-key)
export CASEOPS_DATABASE_URL="postgresql+psycopg://caseops:${DB_PW}@127.0.0.1:25432/caseops"
export CASEOPS_EMBEDDING_PROVIDER=voyage
export CASEOPS_EMBEDDING_MODEL=voyage-4-large
export CASEOPS_EMBEDDING_DIMENSIONS=1024
export CASEOPS_EMBEDDING_API_KEY="$VOYAGE_KEY"
export CASEOPS_LLM_PROVIDER=anthropic
export CASEOPS_LLM_MODEL=claude-haiku-4-5-20251001    # Haiku for Layer 2 reliability
export CASEOPS_LLM_API_KEY="$ANTHROPIC_KEY"
export CASEOPS_RERANK_ENABLED=true
export CASEOPS_RERANK_BACKEND=fastembed
export PYTHONUNBUFFERED=1
```

### Per-bucket exact sequence (copy-paste)

```bash
LABEL="sc-2024"   # or hc-delhi-2024, etc.
COURT="sc"
YEAR="2024"
HC_COURTS=""       # set to e.g. "delhi" for HC buckets

# 1. INGEST (Voyage embeddings; 10-30 min per bucket)
uv run --no-sync python -m caseops_api.scripts.ingest_corpus \
  --from-s3 --court "$COURT" $([ -n "$HC_COURTS" ] && echo "--hc-courts $HC_COURTS") \
  --year "$YEAR" --min-chars 4000 --limit 2000

# 2. LAYER 2 (Haiku only — Sonnet has a JSON-parse defect on huge docs)
uv run --no-sync python -m caseops_api.scripts.backfill_corpus_quality \
  --stage structured --force-tier haiku --budget-usd 30

# 3. TITLE CHUNKS (new docs, idempotent via chunk_role='metadata')
uv run --no-sync python -m caseops_api.scripts.backfill_title_chunks \
  --batch-size 32

# 4. TITLE CHUNK REFRESH (rebuild with Layer-2-improved metadata)
uv run --no-sync python -m caseops_api.scripts.backfill_title_chunks \
  --batch-size 32 --refresh

# 5. PROBE and RATE
uv run --no-sync python -m caseops_api.scripts.eval_hnsw_recall \
  --tenant aster-demo --sample-size 30 --k 10 --seed 42
# Report as: "rating: X.Y/5 (recall@10=NN.N%, MRR=0.YYY, rank=Z.ZZ)"
```

### Decision tree at each bucket boundary

- **Rating improved**: proceed to next bucket.
- **Rating flat (±0.1)**: proceed.
- **Rating dropped >0.2**: STOP. Check in this order:
  1. Layer 2 succeeded on the bucket? (check `structured_version` counts)
  2. Rerank flag still on? (verify `CASEOPS_RERANK_ENABLED=true`)
  3. Probe seed pinned to 42?
  4. OCR / cross-lingual contamination in top-10 misses?

### Known-broken docs (skip these)

- `129b3e0a-d448-436a-8a11-dc876f5b12f1` — malformed JSON on Sonnet AND Haiku at >45k chars output. Skip until `corpus_structured._tolerant_json_loads` can repair this class.

### Levers in priority order when stuck at 4.0-4.5

1. Ensure title-chunk **refresh** ran AFTER Layer 2 — the commonest omission.
2. Parties-JSON pre-filter at retrieval (exact-match before vector).
3. ~~Query expansion via Haiku~~ — **TESTED AND KILLED** on 2026-04-20. Net-negative (recall@10 90% → 63%) because Haiku hallucinates party names on ambiguous / OCR-garbage / docket-number queries. Do not re-enable without a case-name-classifier gate in front.
4. OCR garbage gate at ingest (reject `(cid:\d+)` density > 1%).
5. Language filter at retrieval (`WHERE language='en'`).
6. Postgres connection retry wrapper — mitigated on GCE VM (same-region Cloud SQL).

### Spend guard-rails

- After every 5 buckets, probe budget + chunk ratio. If Voyage burns > $2/1k docs, stop and audit chunks-per-doc.
- If Anthropic > 50% of $450 cap before SC is done, drop Layer 2 to `--budget-usd 15` per bucket.
