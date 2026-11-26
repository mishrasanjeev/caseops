# Statute vector index: production backfill and verification

Feature: section-level vector retrieval over verified statute text (PRD J05/M04,
MOD-TS-017, US-010/US-011; tests FT-117..FT-122, NFT-026, SEC-034). Migration
`20261126_0101` adds `statute_section_chunks`. Until this runbook is executed,
production behaves exactly as before: research answers find a statute section
only by an exact reference in the question or a section cited by a retrieved
judgment.

Nothing in the code calls a paid provider on its own. The index is built by an
operator-run job, like the judgment title-chunk backfill.

## What runs where

| Step | Runs | External call |
| --- | --- | --- |
| Seed verified statute text | `caseops-seed-statutes` job (already part of `scripts/deploy-prod.sh`) | none |
| Build or refresh the index | `python -m caseops_api.scripts.embed_statute_sections` (operator) | Voyage `voyage-4-large`, `input_type=document` |
| Research answer retrieval | API, research answer background job | one Voyage query embedding per answer (`input_type=query`), skipped when the index is empty |
| Reranking | API process, local fastembed cross-encoder when `CASEOPS_RERANK_ENABLED=true` | none |
| Benchmark | `python -m caseops_api.scripts.eval_statute_retrieval` (operator) | one Voyage query embedding per question (two with `--calibrate`) |

## Index contract

- Only sections that pass `services/statute_selection.py` (verified official or
  licensed text, enacted or reviewed historical repeal, official publisher,
  source hash and version, checked section link) are chunked.
- Chunks are verbatim slices of `section_text`, cut at sub-section, clause,
  proviso, Explanation and Illustration boundaries, at most 1,500 characters.
- Each chunk stores `statute_id`, `section_number`, `section_label`,
  `source_sha256`, `source_version`, `exact_source_version`, the chunker
  version, the SHA-256 of the exact embedded text, the model and the
  dimensions.
- A re-run embeds only sections whose text, label, Act name, source identity,
  chunking rule or embedding model changed, and deletes chunks of sections that
  are no longer selectable (retired, quarantined, withheld, unverified). Each
  batch commits on its own; an interrupted run resumes by running it again.
- Retrieval re-checks selectability and the section's current `source_sha256`
  and `source_version` on every read, so a stale chunk is never returned even
  before the job runs again.

## Cost estimate (measured offline on the current release bundle)

`--dry-run` against a database seeded from the current release bundle
(23 Acts, 5,020 selectable sections):

```
statute index: mode=dry-run ... selectable_sections=5020 to_embed_sections=5020
to_embed_chunks=7198 estimated_tokens=1708561
```

- Full first build: about 1.7 million input tokens (heuristic of 4 characters
  per token; Voyage's own tokenizer may differ by roughly 20%). Multiply by the
  current `voyage-4-large` price per million tokens before approving the run.
- Later runs embed only changed sections. Adding the Income-tax Act edition
  adds its own sections only; run `--dry-run` after it is seeded for its
  figure.
- Per research answer: one extra query embedding (under 150 tokens).
- Storage: the offline build used 117 MB for 7,198 chunks, including a 56 MB
  HNSW index (JSON copy of each vector plus the pgvector column, the same
  layout as `authority_document_chunks`).

## Production backfill (release owner)

Run only after the release that contains migration `20261126_0101` is deployed
and its `caseops-seed-statutes` execution has finished. Use the same
workstation or VM setup as the judgment title-chunk backfill
(`.codex/skills/corpus-ingest/SKILL.md`): Cloud SQL Auth Proxy on port 25432
and the production embedding environment.

```bash
cloud-sql-proxy --port 25432 perfect-period-305406:asia-south1:caseops-db &
export DB_PW=$(gcloud secrets versions access latest --secret=caseops-db-password)
export CASEOPS_DATABASE_URL="postgresql+psycopg://caseops:${DB_PW}@127.0.0.1:25432/caseops"
export CASEOPS_EMBEDDING_PROVIDER=voyage
export CASEOPS_EMBEDDING_MODEL=voyage-4-large
export CASEOPS_EMBEDDING_DIMENSIONS=1024
export CASEOPS_EMBEDDING_API_KEY=$(gcloud secrets versions access latest --secret=caseops-voyage-api-key)
export CASEOPS_RERANK_ENABLED=true
export CASEOPS_RERANK_BACKEND=fastembed
export PYTHONUTF8=1 PYTHONUNBUFFERED=1
cd apps/api   # checkout of the deployed commit

# 1. Confirm the schema and the work to do. Writes nothing, calls no provider.
uv run --no-sync python -m caseops_api.scripts.embed_statute_sections --dry-run

# 2. Trial: 20 sections, then check the rows (step 4).
uv run --no-sync python -m caseops_api.scripts.embed_statute_sections --limit 20

# 3. Full sync. Exit code 1 means errors or a budget stop; re-run to resume.
uv run --no-sync python -m caseops_api.scripts.embed_statute_sections

# 3b. Re-run: must report embedded_sections=0 and up_to_date=<selectable_sections>.
uv run --no-sync python -m caseops_api.scripts.embed_statute_sections --dry-run
```

`stop_reason=ai_money_budget_denied` means the AI money budget refused further
spend; nothing is half-written, and the next run continues. The Voyage daily
cap in `services/voyage_usage.py` also applies.

A Cloud Run job is not provided on purpose: production jobs are governed by
`infra/cloudrun/scheduler-inventory.json`. To run this as a job instead, add an
inventory entry (image digest, `python -m
caseops_api.scripts.embed_statute_sections`, the embedding env above, secrets
`CASEOPS_DATABASE_URL`, `CASEOPS_AUTH_SECRET`, `CASEOPS_EMBEDDING_API_KEY`)
through the usual inventory review first.

## Verification (release owner)

4. Row checks (read-only SQL through the proxy):

```sql
-- Every chunk belongs to a selectable section and matches its source identity.
SELECT count(*) AS chunks,
       count(*) FILTER (WHERE c.embedding_vector IS NULL) AS missing_vectors,
       count(*) FILTER (WHERE c.source_sha256 <> s.source_sha256
                          OR c.source_version <> s.source_version) AS stale,
       count(*) FILTER (WHERE substr(s.section_text, c.char_start + 1,
                                     c.char_end - c.char_start) <> c.content) AS not_verbatim,
       count(DISTINCT c.embedding_model) AS models
FROM statute_section_chunks c JOIN statute_sections s ON s.id = c.section_id;
-- Expected: missing_vectors = 0, stale = 0, not_verbatim = 0, models = 1.

SELECT s.verification_status, count(DISTINCT s.id)
FROM statute_section_chunks c JOIN statute_sections s ON s.id = c.section_id
GROUP BY 1;
-- Expected: only verified_official / verified_licensed.
```

5. Benchmark on the production provider with reranking on:

```bash
uv run --no-sync python -m caseops_api.scripts.eval_statute_retrieval --calibrate --json-out statute-benchmark.json
```

Report the printed line, for example
`rating: X.Y/5 (recall@10=NN.N%, MRR=0.YYY, rank=Z.ZZ)`, with the negatives
line and the calibration block. The slice is production-ready only at 4.8+/5
(PRD 12.4) with zero negatives returning a statute.

6. Similarity floor. `services/statute_vectors.py` uses a provisional floor of
0.30 for `voyage-4-large`. The calibration block prints the minimum and median
similarity of expected hits and the maximum similarity of the closest
neighbour of each negative question. Confirm the floor sits above the negative
maximum and below most expected hits. If it does not, change
`_MIN_SIMILARITY_BY_MODEL` in a reviewed PR and re-run step 5; do not call the
slice production-ready before that.

7. End-user check: in Research, ask a paraphrased question that names no
section (for example "presumption that the holder received the cheque for a
debt") and confirm a statute source with the matching section, verified text
and source link appears, and that the Section 138 benchmark question still
lists Section 138 first.

## Rollback

The index is derived data. To stop semantic statute retrieval without a
deploy, delete the rows (`DELETE FROM statute_section_chunks;`); research falls
back to exact references and judgment-cited sections. Rebuild later with step
3. The migration is restore-forward only: its downgrade refuses before any DDL,
like the research-answers revision below it.

## After each statute seed

Any release that changes verified statute text, labels or verification state
needs step 3 (it embeds only the changes) and step 4. Until it runs, changed
sections are excluded from semantic retrieval by the read-time source check,
and their exact references keep working.

## Income-tax Act extension

When the Income-tax Act edition lands in the release bundle, run steps 1-4,
then move reviewed questions into `queries` in
`apps/api/src/caseops_api/scripts/statute_retrieval_benchmark.json` (see its
`income_tax_extension` block) and repeat step 5.
