# Corpus duplicate cleanup approval checkpoint - 2026-05-19

## Findings

This checkpoint is a docs-only approval artifact for a future separate cleanup
PR. It records the approvals and evidence that must exist before any cleanup
execution is considered for the two exact-content duplicate loser candidates.

No approvals have been granted yet. This document authorizes no cleanup,
deletion, dependency repointing, index creation, migration, ingest, backfill, or
embedding job.

## Evidence Chain

- Read-only duplicate audit:
  `docs/runbooks/corpus-duplicate-readonly-audit-2026-05-18.md`
- Read-only metadata extract:
  `docs/runbooks/corpus-duplicate-metadata-extract-2026-05-18.md`
- Exact-content approval planning packet:
  `docs/runbooks/corpus-duplicate-exact-content-cleanup-approval-packet-2026-05-18.md`
- No-execution approval checklist:
  `docs/runbooks/corpus-duplicate-cleanup-no-execution-approval-checklist-2026-05-18.md`
- Offline planner design:
  `docs/runbooks/corpus-duplicate-exact-content-cleanup-planner-design-2026-05-19.md`
- Offline planner:
  `scripts/corpus_duplicate_cleanup_planner.py`

The latest merged planner PR was `#59`, merge commit
`77f0c64af89c29115827478c472fd7fd32d33be4`.

## Scope Boundary

The only automatic-cleanup review scope is the two exact-content loser
candidates below. All values are bounded metadata already present in merged
reports.

| Source reference | Loser candidate id | Keeper candidate id | Text hash | Characters | Chunks / embedded / metadata | Chunk dependency rows | Bounded title |
| --- | --- | --- | --- | ---: | --- | ---: | --- |
| `DLHC010128692024_1_2024-12-23.pdf` | `8c8eafd3-b75e-4b24-993a-e68a483485bc` | `f791ca94-9198-4448-a16c-81ec27ed8fc7` | `7343caaca1dca196a527c67174b89520` | 301860 | `138 / 138 / 0` | 138 | `CONT.CAS(C) 647/2024` |
| `DLHC010253692023_1_2025-01-13.pdf` | `5b79de0a-5a2e-4354-8347-f5ecd94af211` | `200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8` | `c36ce20558296cc83b64171f0a55ec28` | 2272 | `2 / 2 / 1` | 2 | `Kapil Bhati v. Jyoti Choudhary & Anr.` |

Current evidence records `140` chunk dependency rows for exact-content loser
candidates. Every other checked FK-backed and semantic/non-FK dependency count
was `0` in the metadata extract.

## Quarantined Groups

The four same-source_reference/different-content groups remain quarantined.
They are not cleanup candidates and must not be included in any exact-content
cleanup approval.

| Source reference | Rows | Distinct text hashes | Character range |
| --- | ---: | ---: | --- |
| `DLHC010026412024_1_2025-01-13.pdf` | 2 | 2 | `6037-7153` |
| `DLHC010087382023_1_2025-01-13.pdf` | 2 | 2 | `4212-4221` |
| `DLHC010146102023_1_2023-05-30.pdf` | 2 | 2 | `23865-23865` |
| `DLHC010146112023_1_2023-05-30.pdf` | 2 | 2 | `23865-23865` |

These groups require separate legal/content disposition before any future
dedupe hardening can rely on source_reference uniqueness.

## Required Sign-Offs

No sign-off has been granted by this checkpoint. A future cleanup PR must
include explicit approval evidence for every gate below.

| Gate | Required confirmation | Current status |
| --- | --- | --- |
| Legal/content | Confirms the two exact-content loser rows are true duplicates and that there is no content-retention concern. | Missing |
| Database | Confirms dependency inventory, transaction safety, lock expectations, rollback mechanics, and backup posture. | Missing |
| Engineering | Confirms planner/tool behavior, tests, fixed candidate scope, and no broadened cleanup surface. | Missing |
| Product | Confirms search, corpus, recommendation, analytics, citation, and user-visible impact is acceptable. | Missing |
| Operations | Confirms approved run window, monitoring owner, rollback operator, and incident plan. | Missing |

All five gates must be complete before any production cleanup execution is
authorized.

## Required Evidence Before Future Cleanup Execution

A future separate cleanup PR/runbook execution must include:

- fresh read-only dry-run evidence from the approved environment;
- fresh dependency validation for every loser candidate;
- exact loser-to-keeper map matching the approved candidate IDs;
- rollback and audit plan reviewed by database, engineering, and operations;
- post-cleanup verification plan for duplicate counts, dependency counts,
  chunk counts, and semantic dependency counts;
- explicit production execution approval from legal/content, database,
  engineering, product, and operations.

Stale evidence from the 2026-05-18 audit chain cannot by itself authorize a
production cleanup.

## Hard Stop Conditions

Stop before opening or approving a write-capable cleanup PR if any of the
following is true:

- any required sign-off is missing or stale;
- candidate IDs differ from the approved exact-content candidate set;
- text hashes differ within either exact-content group;
- source or source_reference values no longer match within a candidate group;
- fresh dependency validation shows new non-zero FK-backed or semantic
  dependencies without an approved handling plan;
- any same-ref/different-content group is included in cleanup scope;
- rollback, audit, monitoring, or incident ownership is incomplete.

## Index And Uniqueness Hardening Boundary

No index, uniqueness constraint, or migration hardening can happen until after
cleanup verification is complete and separately approved. Hardening must remain
outside any future cleanup execution unless a later approval explicitly covers
that separate scope.

## No-Authorization Statement

This checkpoint performs no cleanup and grants no approval. It is only the
approval readiness inventory for a future separate cleanup PR and runbook
execution.

This document intentionally excludes SQL snippets, cleanup scripts, application
code, deployment paths, release signoff documents, migration files, index
definitions, production execution instructions, secrets, DB URLs, credentials,
full judgment text, OCR text, full document text, source payloads, and large
source excerpts.
