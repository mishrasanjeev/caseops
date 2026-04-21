# SC-2023 retrieval-quality investigation — 2026-04-21

## Context

The 2026-04-20 HNSW probe on the SC-2023 bucket landed at **4.17 / 5**:

- recall@10 = **83.3 %** (25 / 30 queries pass)
- MRR and rank ladders otherwise healthy
- Target: **4.8+ / 5**

The gap is not in the embedding quality itself — the 25 passing queries
land with strong cosine margins. The five misses cluster on query-side
shape mismatches that the corpus DOES contain but that the query
embedding fails to locate because the surface form differs.

## The five misses and the hypothesis per miss

| # | Miss query                                              | Hypothesis                                                                                                               | Fix side   |
|---|---------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|------------|
| 1 | `2022 15 827`                                           | Pure-numeric citation. No alpha content → Voyage vector drifts toward random-numeric neighbours.                         | Query-side |
| 2 | `DHARWAD BENCH`                                         | All-caps bench-name query. Corpus embeds `Dharwad` (Title Case) in title-chunks; caps-only collide with statute codes.   | Query-side |
| 3 | `[2019] 1 S.C.R. 1001`                                  | SC reporter citation with punctuation. Corpus stores `2019 1 SCR 1001`; brackets + dots embed to a different cluster.    | Query-side |
| 4 | `[2021] 1 S.C.R. 694`                                   | Same shape as #3.                                                                                                        | Query-side |
| 5 | `ਐਮ/ਐਸ ਏਪੈਕਸ ਲੈਬੋਰੇਟਰੀਜ਼ ਪ੍ਰਾਈਵੇਟ ਿਲਿਮਟੇਡ` (Punjabi)  | Gurmukhi party name. Voyage multilingual encodes the script, but the corpus was ingested on English-translated headings. | Query-side |

All five are addressable by rewriting the query before embedding. No
re-ingest, no re-embed, no change to the HNSW index config.

## What this branch ships

Three normalisers in
`apps/api/src/caseops_api/services/retrieval_normalisers.py`:

1. **`normalise_citation_query(q)`** — detects bracketed SC reporter
   citations (`[2019] 1 S.C.R. 1001`) and pure-numeric citations
   (`2022 15 827` with zero alpha content), returns the corpus-shaped
   variants (`2019 1 SCR 1001`, `[2019] 1 SCR 1001`, `(2019) 1 SCR 1001`,
   etc.) with the original query always included and deduplicated.
2. **`normalise_bench_query(q)`** — collapses all-caps bench / court / HC
   queries (≤ 4 tokens) to their Title-Case stem, dropping the
   `BENCH` / `COURT` / `HC` suffix. Returns None for mixed-case or
   topical queries so the caller falls through.
3. **`is_non_english_script(q)`** — detects Indic scripts (Devanagari,
   Bengali, Tamil, Telugu, Kannada, Gurmukhi) when ≥ 30 % of alphabetic
   code points fall in those ranges. Drives the optional
   `translate_query_to_english(q)` path, which wraps
   `services/llm.build_provider("metadata_extract")` with a 40-token
   translation prompt. Guarded by
   `settings.retrieval_non_english_translate` (default **OFF**) — opt
   in once the probe confirms the variant beats the raw query.

Wired in `apps/api/src/caseops_api/services/authorities.py` inside
`search_authority_catalog`: the query is expanded to variants BEFORE the
HNSW prefilter call, each variant is embedded + searched independently,
and the per-variant top-k lists are unioned in order. The downstream
lexical re-score and reranker paths are unchanged. Gated by
`settings.retrieval_query_normalisers_enabled` (default **ON**).

Two new settings flags in
`apps/api/src/caseops_api/core/settings.py`:

- `retrieval_query_normalisers_enabled: bool = True`
- `retrieval_non_english_translate: bool = False`

## How to verify

Run the HNSW recall probe against the same 30-query SC-2023 sample with
the same seed:

```
apps/api/.venv/Scripts/python.exe -m caseops_api.scripts.eval_hnsw_recall --tenant aster-demo --sample-size 30 --k 10 --seed 42
```

Then fill in the "after" column below.

## Results

| Metric      | Before (2026-04-20) | After (post-fix) | Target |
|-------------|---------------------|------------------|--------|
| recall@10   | 83.3 % (25 / 30)    |                  | 95 %+  |
| MRR         |                     |                  | 0.85+  |
| mean rank   |                     |                  | ≤ 2    |
| Rating      | 4.17 / 5            |                  | 4.8+   |

## Out of scope for this branch

- Re-ingest / re-embed of the SC-2023 bucket. None of the five misses
  points at an embedding-quality defect; the corpus content is correct.
- HNSW index tuning (`ef_search`, `m`, `ef_construction`). No evidence
  these are the bottleneck for the remaining misses.
- Layer-2 metadata changes. The Layer-2 extraction ran clean on
  SC-2023 (4.7 / 5 extraction sample, which is a DIFFERENT signal from
  retrieval and must not be used to rate retrieval — see
  `feedback_retrieval_quality_eval.md`).
