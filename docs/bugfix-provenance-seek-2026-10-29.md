# Full-Key Import Provenance Seek

Status: Partially fixed / release NO-GO pending complete replacement acceptance.
Ownership: IPLF-030B/037, UJ-04, IP15-018, NFT-005 and SEC-003/004.

## Actual Failure And Prior Gap

Source13d086312e18f3a1f94f9f970faa40647fa3d89d CI40823363939 has one real
PostgreSQL20/24 failure. Complete shard evidence contains145cases/435phases,
144passed/1failed/0skipped. The downstream aggregate fails its expected shard
guard; Playwright is unexecuted. Security8/8 and Advanced3/3 are separate from
the failed CI. Independent CodeQL retains five reviewed test-only warnings,
not zero annotations.

test_minimal_page_query_count_is_page_bounded_and_ignores_retained_history
retains all five EXPLAIN plans before failing. Query2's import-row PK visits
200rows. The audit node chooses ix_audit_events_company_id and records
(1returned+406filtered)*200loops=81400visits. Total81600 exceeds the unchanged
4*201+16=820cap. This is the oracle's recorded metric from per-loop averages,
not an independently measured per-tuple executor counter or production timing.

The earlier full-key index and company/action-prefix retirement covered one
access path, not every alternative planner choice. Index presence, analyzed
success and a later passing replay could not prove the required fresh-state
work bound. Keep both actual old failures and this correction as history.

## Narrow Repair

Only imported_proof_expression changes. Seek the first audit key >= the desired
tenant/action/type/source-row/docket tuple, in the existing composite-index
order, with LIMIT1. Outside that fence require exact equality of every field.
A different successor must remain false. Duplicates do not multiply candidates;
missing/null/foreign/mixed records preserve the existing EXISTS meaning.

Keep both indexes, all source-row length/identity/tenant checks, current-version
scope, manual-date precedence, JSON/date validation and the canonical Python
reader unchanged. No migration, planner override, production ANALYZE, raised
work cap, deadline extension, audit rewrite or legal-source relaxation is added.
The existing access-proof implementation supplies the query pattern, but a
LIMIT or index name alone still cannot prove physical work.

## Reproduction And Regression

The new test_ip_provenance_seek_20261029.py contains five cases. Two exercise
SQLite/PostgreSQL parity for every predicate, source tenant, absent row/audit,
unrelated successors, null target/docket, exact duplicate and mixed audits,
foreign scope, reader parity and unchanged retained audit values. Three use
the actual small201-import/200-row export workload under fresh, stale-empty
and analyzed statistics, retaining valid/ready/live catalogue and statistics
receipts. Statistics controls are confined to each owned isolated database;
the fresh and stale cases must pass without refreshed statistics.

RED runs against unchanged product198ae6df9d004996c81835574274c42acdc708e3112cbcd599aaa41659895b7c:
all3cases/9phases completed, fresh/stale calls fail81600>820, analyzed passes,
all setup/teardown passes. Actual pytest exit1 is negative proof, not acceptance.
Both complete failures and failed runtime remain preserved.

Fresh independent GREEN completes17passed/51phases: all new5, the full unchanged
source-proof parity4 and full original export8. An explicit final empty pytest
mark expression includes SQLite rather than silently inheriting the native
helper's PostgreSQL-only filter. Actual collection, phases, JUnit, source
before/after and31retained files reconcile, without skips or retries.

Six complete plan receipts pass unchanged bounds. Fresh/stale/analyzed and
the original failed200-row query use200PK+200full-key visits=400, below820.
The one-row continuation uses2. Both retained-width controls use106/106/102
against228 for their three provenance-bearing queries. All five audit fields
remain checked outside the LIMIT. The complete original semantic module keeps
manual overrides and malformed-JSON parity, not only a simplified positive.

Product SHA4041604c240aca77bc547bf78a4a4804a79ddbfa0c9c4a1d8253a323347a9bdf;
unchanged Python oracleb0f190c4f3bb081b0c35b89695b1944d70f6179da01ee5d13156248988f7b9a3.
Evidence in the primary workspace outputs/fix-561-20261026/portfolio-export-worker/
ci-mrh-failure-20261029-01: failed-shard-reconciliation-01.json,
provenance-red-01/reconciliation.json and provenance-green-01/reconciliation.json.
GREEN receipt SHA86c491cfb1379528ce8fa770b1cab742ce59a36f7a23bf1d5e589f37c592e3f7.

## Release Boundary

Docker18 on13D was deliberately interrupted after its first whole group passed
438cases/1314phases and all retained bytes were verified. The remaining3061
native and640browser cases did not execute. Its outer launcher exit0 is not
acceptance. Preserve this incomplete boundary and require a complete fresh
candidate Docker run, current-head CI/Security/independent CodeQL, canonical
main/tree proof, guarded exact-SHA deployment, full live E2E and private cadence.

The committed portfolio journey must still produce the exact51-row CSV,
matching source/hash/authentication proof and unchanged<=15second duration at
both1280px and393px on the new serving SHA. These local components do not close
IP15-018, #561/#564 or any legal/provider/consent/MFA/native dependency. Both
actual original workbooks remain INTERIM07/NO-GO pending real release results.
