# IP pleading validate latency, 2026-09-28: root cause and fix

Source: finding of 2026-09-27. `GET
/api/ip/dockets/{docket}/proceedings/{proceeding}/drafts/{draft}/validate` on
`caseops-api` (project `perfect-period-305406`, region `asia-south1`,
`containerConcurrency: 1`, service minimum 4) took a near-constant 4.6 s.

## Symptom

Cloud Run request logs, 2026-08-29 to 2026-09-27: 160 validate `GET`s (158
`200`, two `409`) and 121 CORS preflights.

| Week starting | Requests | p50 | p90 |
| --- | --- | --- | --- |
| 2026-08-24 | 20 | 1.77 s | 2.28 s |
| 2026-08-31 | 49 | 4.60 s | 4.73 s |
| 2026-09-07 | 33 | 4.65 s | 4.74 s |
| 2026-09-14 | 31 | 4.66 s | 5.24 s |
| 2026-09-21 | 27 | 4.66 s | 7.28 s |

Since 2026-09-14 the fastest request took 4.18 s. Without the seven requests
above 6 s (cold starts and queueing), p50 is 4.65 s and p90 4.77 s. The time
was flat across drafts and revisions: a fixed cost per request.

## Root cause

`validate_ip_draft` rechecks every cited authority against the public corpus
(`services/ip_draft_validation.py`, `_authority_findings`):

```sql
SELECT ... FROM authority_documents
WHERE id IN (...) OR neutral_citation IN (...) OR case_reference IN (...)
```

`id` has its primary key and `case_reference` has
`ix_authority_documents_case_reference`. `neutral_citation` had only the
trigram GIN expression index `ix_authority_documents_citation_trgm`, which
cannot serve equality. PostgreSQL can combine an `OR` through indexes only
when every branch has one, so it read the whole table on every validate.
Production runs on `caseops-db` (`db-custom-1-3840`: 1 vCPU, 3.75 GB, PD-SSD)
and the corpus exceeds 800K documents, so that heap cannot stay in memory.

The request issues 12 statements. The rest of validation (proceeding,
identifiers, deadlines, document versions) was already bounded and makes no
provider or model calls. The same `OR` also runs in:

- `services/drafting.py` `_verify_version_citations`, on every draft
  generation and edit;
- `services/hearing_packs.py`, when a hearing pack checks its citations;
- `services/appeal_strength.py`, once per citation missing from the bench
  context (`neutral_citation = ... OR case_reference = ...`).

## Fix

Revision `20260928_0001` adds `ix_authority_documents_neutral_citation`, a
B-tree on `authority_documents (neutral_citation)`, declared on the ORM column
as well:

- `CREATE INDEX CONCURRENTLY IF NOT EXISTS` in an autocommit block, because
  ingestion writes this table continuously.
- An interrupted build leaves an invalid index. The upgrade drops only that
  artifact (`DROP INDEX CONCURRENTLY`) and rebuilds it, then refuses to
  continue unless `pg_index.indisvalid` is true.
- The downgrade drops the index inside Alembic's transaction, so a later
  restore-forward refusal rolls it back.

Validation semantics are unchanged: same query, same findings, same
fail-closed `citation.source_lost` and `citation.none_verified` blockers.
Nothing in the request path changed.

## Measurements

Local PostgreSQL 17, 800,000 authority rows (1,250 MB heap), one validate of
a grounded notice, three runs per phase. All phases issue 12 statements and
return the same findings.

| Phase | Request | Citation lookup |
| --- | --- | --- |
| Index present | 33-41 ms | 1.6-1.9 ms |
| Index dropped (the old schema) | 342-369 ms | 305-330 ms |
| Index rebuilt concurrently | 36-37 ms | 1.5-1.8 ms |

A separate `EXPLAIN (ANALYZE, BUFFERS)` of the validation lookup and of the
draft citation verifier, on the same 800,000-row shape, read 160,000 blocks
through a sequential scan without the index. With it, each read 25 blocks
through a `BitmapOr` of the primary key, `ix_authority_documents_case_reference`
and the new index.

The concurrent build over those 800,000 rows took 2.8 s and produced a valid
25 MB index. Production migrations run with a 900 s statement budget and a
5 s lock budget. The concurrent build's snapshot waits count against the lock
budget, the same exposure as `20260912_0001` on this table.

## Verification

- `tests/test_20260928_pleading_validation_bounded.py` (SQLite) validates a
  real grounded notice, then widens its revision to 31 citations: 20 neutral
  citations, 6 case references, 2 authority IDs and 2 citations the corpus no
  longer holds. Both validations issue the same number of statements. The
  second still reports exactly one `citation.source_lost` blocker naming the
  two lost citations, and `can_approve` stays false. `EXPLAIN QUERY PLAN` of
  the captured lookup must not scan `authority_documents` and must use the new
  index. The file also checks the migration source contract and that the
  migrated schema carries the index.
- `tests/test_20260928_pleading_validation_bounded_postgres.py`:
  - the same journey on PostgreSQL;
  - the captured lookup after 60,000 filler authorities, with no manual
    `ANALYZE`: `EXPLAIN (ANALYZE, BUFFERS)` must show no sequential scan of
    `authority_documents`, must use the new index, and must read at most 64
    blocks from a table more than twenty times that size;
  - an interrupted concurrent build (a real invalid index from a failed
    unique build), then two upgrades: the index is valid and not unique, and
    every row is kept. The downgrade's drop rolls back with its transaction;
  - a disposable database at head with retained bulk-update history:
    downgrading to `20260920_0001` is refused twice by `20260924_0001`, and
    each time the head revision, the retained row and the complete index
    inventory are unchanged. Without a refusal, downgrading to
    `20260925_0001` removes the index and upgrading to head restores the
    identical inventory. A deliberately unsafe downgrade (a concurrent drop
    in an autocommit block) fails this test because the refusal can no
    longer restore the index;
  - the index is valid at head.
- Reproduction on the unfixed commit `da0b28aa`, in a separate checkout whose
  imported `caseops_api` module path was verified: the SQLite plan scans
  `authority_documents`, and PostgreSQL shows a sequential scan. The new tests
  pass on the fixed commit.
- The 11 existing PostgreSQL rehearsals that downgrade from head pass against
  the new head. In the first local run one of them,
  `test_patent_family_pg_persistence_tenant_constraints_and_atomic_rollback`,
  failed while connecting to `127.0.0.1:5432/caseops`: the run set
  `CASEOPS_TEST_POSTGRES_URL` but not `CASEOPS_DATABASE_URL`, which
  `alembic/env.py` reads and CI sets to the same database. That was a setup
  error, not a result; the replay with CI's pairing passed.
- 16 related SQLite files: the new regression, pleading drafting and its
  legal fixture pack, drafting studio, authority search indexes, hearing packs,
  appeal strength, citations, draft validators, index health, migration safety,
  migration preflight, data-class projection and its gate, authorities, and
  bulk updates. The JUnit record has 214 unique cases from all 16 files: 213
  passed, and one PostgreSQL-only test was skipped by its marker.
- Governance: the map's schema and ORM index fingerprints, its rendered view
  and the runtime data-class projection were regenerated. `generate` also
  replaced the reviewed purpose of `matter_bulk_update_operations` with its
  generic text; the reviewed text was restored. All 13 CI validators pass,
  including both `check-change` gates. Legal-hold and data-class suites,
  including the PostgreSQL legal-hold regressions: 52 passed.
- Docker acceptance, including the dated pleading-validation journey whose
  workspace must settle `aria-busy`, and exact-release production
  verification are recorded on the pull request.
