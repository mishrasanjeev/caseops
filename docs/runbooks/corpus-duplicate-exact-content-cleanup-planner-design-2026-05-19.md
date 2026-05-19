# Corpus duplicate exact-content cleanup planner design - 2026-05-19

## Findings

This milestone adds a non-executing offline planner for the two hc-delhi
exact-content duplicate loser candidates identified by the merged evidence
chain. It does not run production cleanup, modify data, repoint dependencies,
add indexes or migrations, run ingest/backfill/embedding jobs, or expose full
text/source payloads.

The four same-source_reference/different-content groups remain quarantined and
are rejected by the planner.

## Source Of Truth

- Read-only duplicate audit:
  `docs/runbooks/corpus-duplicate-readonly-audit-2026-05-18.md`
- Metadata extract:
  `docs/runbooks/corpus-duplicate-metadata-extract-2026-05-18.md`
- Exact-content approval packet:
  `docs/runbooks/corpus-duplicate-exact-content-cleanup-approval-packet-2026-05-18.md`
- No-execution approval checklist:
  `docs/runbooks/corpus-duplicate-cleanup-no-execution-approval-checklist-2026-05-18.md`

## Design Decision

Use an explicit JSON metadata packet as the only input and emit a bounded JSON
plan as output. The planner is intentionally outside the API runtime and has no
database client, production connection handling, credential discovery, SQL
execution, migration behavior, or cleanup execution path.

The planner is scoped to the current four exact-content candidate rows:

| Source reference | Keeper candidate | Loser candidate |
| --- | --- | --- |
| `DLHC010128692024_1_2024-12-23.pdf` | `f791ca94-9198-4448-a16c-81ec27ed8fc7` | `8c8eafd3-b75e-4b24-993a-e68a483485bc` |
| `DLHC010253692023_1_2025-01-13.pdf` | `200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8` | `5b79de0a-5a2e-4354-8347-f5ecd94af211` |

Any future cleanup still requires a separate approved cleanup PR, a fresh
read-only dry-run close to the execution window, and explicit legal/content,
database, engineering, product, and operations approvals.

## Planner Behavior

Script:

- `scripts/corpus_duplicate_cleanup_planner.py`

The planner:

- requires `--input` with explicit offline metadata;
- optionally writes a local JSON dry-run plan with `--output`;
- emits no executable write SQL;
- opens no database connection;
- reads no environment variables or credentials;
- hard-stops unless the candidate ids exactly match the source evidence;
- hard-stops on same-ref/different-content inputs;
- requires a complete dependency inventory for every row;
- requires approval gate metadata for legal/content, database, engineering,
  product, and operations;
- requires rollback and audit plan metadata;
- includes only bounded ids, source references, text hashes, counts, timestamps,
  titles, and dependency counts.

## Required Input Metadata

The offline input packet must include:

- source report references;
- source snapshot timestamp and environment label;
- approval gate placeholders for legal/content, database, engineering,
  product, and operations;
- rollback plan summary;
- audit plan summary;
- quarantined group and row counts;
- the four approved exact-content candidate ids;
- two exact-content groups with one keeper candidate and one loser candidate
  each;
- per-row source, source_reference, text hash, character count, chunk counts,
  structured metadata signal, bounded title, updated timestamp, and dependency
  counts.

Forbidden input fields include full `document_text`, OCR text, full judgment
text, source payloads, database URLs, credentials, tenant/matter payloads, and
large free-text values.

## Output Plan

The output plan is a dry-run artifact only. It contains:

- keeper-to-loser mapping for the two exact-content groups;
- future dependency repoint plan by dependency column and row count;
- bounded row metadata for review;
- aggregate loser and dependency counts;
- quarantine status for the four same-ref/different-content groups;
- non-execution flags showing cleanup is not authorized and production
  connection handling is unsupported.

The plan is not an execution artifact and cannot authorize production cleanup.

## Guardrails

The planner fails closed unless all of the following are true:

- every row in a group has the same source and source_reference;
- every row in a group has the same text hash;
- all row ids are from the approved exact-content candidate set;
- no quarantined same-ref/different-content row id is present;
- every row has all required FK-backed and semantic dependency counts;
- approval gate metadata is present;
- rollback and audit plan metadata is present;
- bounded titles and metadata strings stay within configured limits.

## Tests

Tests are in:

- `scripts/test_corpus_duplicate_cleanup_planner.py`

Coverage includes:

- exact-content loser-to-keeper plan generation from fixture metadata;
- rejection of same-ref/different-content input;
- rejection of missing dependency inventory;
- rejection of missing approval metadata;
- rejection of full-text payload fields;
- verification that no write-capable SQL statements are emitted;
- verification that no production connection or default credential path is used.

## Residual Risks

- The planner uses merged audit evidence as a fixed candidate allow-list. A
  future cleanup PR must refresh the dry-run against the approved snapshot or
  read-only transaction before any write-capable work is considered.
- Dependency counts can change after the metadata extract. Fresh dependency
  validation remains mandatory.
- The planner can describe a future dependency repoint plan, but it does not
  prove lock behavior, transaction sizing, rollback mechanics, or post-check
  queries.
- Manual-review groups remain unresolved and must stay excluded until
  legal/content disposition is complete.

## No-Execution Statement

This milestone creates only planning mechanics and tests. It performs no
cleanup, modifies no production data, runs no production queries, repoints no
dependencies, creates no indexes or migrations, and authorizes no future
cleanup.
