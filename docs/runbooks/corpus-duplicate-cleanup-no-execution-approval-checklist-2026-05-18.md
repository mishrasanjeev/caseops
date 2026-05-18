# Corpus duplicate cleanup no-execution approval checklist - 2026-05-18

## Findings

This checklist defines the approval gates and evidence required before any
future corpus duplicate cleanup can be proposed. It is a no-execution artifact:
it performs no cleanup, authorizes no cleanup, and contains no production write
path.

## Source Audit Reference

- Source audit report:
  `docs/runbooks/corpus-duplicate-readonly-audit-2026-05-18.md`
- Manual-review packet:
  `docs/runbooks/corpus-duplicate-manual-review-packet-2026-05-18.md`
- Exact-content approval packet:
  `docs/runbooks/corpus-duplicate-exact-content-cleanup-approval-packet-2026-05-18.md`
- Source query inventory:
  `scripts/corpus-duplicate-audit-readonly.sql`
- Audit environment: `production-primary-readonly-transaction`
- Audit timestamp: `2026-05-18T15:37:53.041112Z`

## Non-Execution Boundary

This milestone does not:

- modify production data;
- perform duplicate cleanup;
- remap dependencies;
- add unique indexes, constraints, or migrations;
- run corpus ingest, backfill, or embedding jobs;
- change application code;
- touch deploy paths or release signoff documents;
- expose full text, OCR text, source payloads, DB URLs, credentials, or large
  source excerpts.

## Approval Gates

| Gate | Required approval evidence |
| --- | --- |
| Legal/content | Written disposition for all four same-ref/different-content groups, including whether each row pair is duplicate, distinct, corrected, or source-ambiguous |
| Database | Approved transaction plan, lock expectations, timeout settings, rollback mechanics, and post-check queries |
| Engineering | Approved keeper/loser map, dependency behavior, idempotency plan, and test/dry-run evidence |
| Product | Approval for any user-visible corpus, recommendation, analytics, prediction, citation, or annotation impact |
| Operations | Approved environment, execution window, operator, monitoring plan, and rollback owner |

All gates must be complete before a write-capable cleanup PR is opened.

## Required Future Dry-Run Evidence

A future dry-run packet must be generated from an approved replica, snapshot, or
read-only transaction and include only bounded metadata:

- current duplicate summary counts;
- exact-content keeper/loser map with current row ids;
- exclusion list for same-ref/different-content groups;
- per-loser FK-backed dependency counts;
- per-loser semantic/non-FK dependency counts;
- per-loser chunk counts and embedded chunk counts;
- structured metadata presence/version;
- bounded title hygiene flags;
- timestamps needed to validate deterministic keeper selection;
- checks proving no full text, OCR text, source payloads, secrets, or connection
  details were captured.

The dry-run must be refreshed close to the requested execution window. Stale
audit results cannot authorize production writes.

## Future Cleanup PR Requirements

Any future write-capable cleanup PR must be separate from this milestone and
must include:

- the approved dry-run packet and approval signoffs;
- exact keeper and loser ids;
- dependency remapping or cascade behavior documented per dependency;
- explicit exclusion of unresolved manual-review groups;
- transaction script reviewed by database and engineering owners;
- rollback script or restore plan reviewed by database and operations owners;
- pre-check, post-check, and audit queries;
- statement timeout, lock timeout, and batch sizing;
- dry-run and rollback rehearsal evidence from a non-production clone or
  approved snapshot;
- confirmation that no index or uniqueness hardening is bundled unless it has a
  separate approved plan.

## Rollback And Audit Requirements

Before any future write:

- capture the approved snapshot identifier or backup reference;
- record the exact commit, operator, environment label, and execution timestamp;
- export the pre-write keeper/loser/dependency map to an access-controlled
  artifact;
- define a rollback path for row restoration or snapshot restore;
- define post-write verification queries for duplicate counts, dependency
  counts, chunk counts, and semantic dependency counts;
- record final audit results without secrets or full text.

## Stop Conditions

Stop before any future cleanup if:

- any manual-review group lacks legal/content disposition;
- exact-content hashes changed since the source audit;
- new FK-backed or semantic dependencies appear without an approved plan;
- the keeper-selection policy changes without approval;
- production access cannot enforce a controlled transaction and rollback plan;
- required approvals are missing or stale.

## Final No-Authorization Statement

This checklist is not permission to run cleanup. It only defines the evidence
and approvals required before a separate future cleanup PR can be considered.
