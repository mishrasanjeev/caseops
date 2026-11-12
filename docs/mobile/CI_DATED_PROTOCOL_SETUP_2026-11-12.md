# Dated PostgreSQL setup and CI timeout — 2026-11-12

J20/M22 release verification remains **Inconclusive** and release **NO-GO**.
This is test infrastructure work; it earns no Android or iOS native case credit.

## Original CI evidence

Main CI run43242669428 on c8dd5c2ff94b165da3a3104c87df7d6aa1e2f93c
was canceled. PostgreSQL shard3/32 reached its unchanged12-minute job limit.
Artifact13956228709 (SHA-256
f748e8ce05b954dd1e4eb45fbc874e1a7bfbf8d68dc1bc995ec5f839f93d97d6)
retains41 complete passing cases of127 selected;86 are unexecuted.
The aggregate PostgreSQL check then failed and browser projects were skipped;
the Playwright aggregate correctly failed rather than certifying absent reports.
The complete52-job observation is retained outside Git at
`native-release-20261111-ZzEIol4V/ci-c8dd-main-complete-jobs-02.json`.
A faulthandler stack sampled migration traversal; that single observation does
not prove a SQLAlchemy hang.

Reported phases for the41 completed cases sum to430.537 seconds. Two
compliance-tail fixtures spent42.992 and39.815 seconds in setup. Source
inspection independently establishes that each protocol/tail fixture created an
empty database and replayed the whole migration history to its dated boundary.
No production query or test assertion is removed by this change.

## Candidate

Two session templates are each built from template0, at the exact fixed
20260928_0001 and20261010_0002 boundaries. Moving head and any other revision
are refused before database IO. The actual revision and empty companies table
are verified, connections are closed and ALLOW_CONNECTIONS is disabled.

Every test still receives its own physical PostgreSQL clone through the
canonical acknowledged-creation owner. Document protocol tests reflect their
actual old table before the unchanged forward migration to20261010_0002.
Compliance tail tests start at their exact pre-protocol boundary. Current-head
ancestry, frozen worker bytes, concurrency barriers, native DDL, forward,
downgrade, recovery and refusal assertions remain unchanged. Per-test mapper,
engine, history-listener and settings cleanup remain. The canonical database
owner now also proves exact database absence after its acknowledged DROP,
including body failures. The separate historical_database rehearsal is unchanged
and still replays each explicitly named revision from template0.

New tests compare the actual columns, indexes, constraints, triggers, functions,
revision and full semantic alias catalogue against an independently migrated
fresh database. That historical alias migration generates UUIDs and timestamps,
so those generated values are compared exactly between clones and after
interrupted-clone recovery; all stable catalogue fields are compared across
independent migrations. Complete alias rows, native IDs and timestamps remain
in the clone oracle. Templates reject connections; failed clone data/DDL cannot
contaminate a sibling or subsequent clone; the shared source database remains
unchanged. A first candidate incorrectly equated independently generated alias
IDs and failed those two new assertions. That145-case failed run and all its
143 passing siblings remain separate evidence.

## Actual PostgreSQL verification

A fresh read-only source snapshot binds base commit
e8086e0a700da8bdb66b197ce1a51c16e8ac5159 and the exact four changed test files.
Its current API runtime source is unchanged from the c8dd image; no production
application code is substituted. Exact pinned pure-Python pytest9.0.3,
pluggy1.6.0 and iniconfig2.3.0 are independently staged for Linux execution.
The worker has no provider keys or external network and uses a fresh, uniquely
owned source database on the isolated test PostgreSQL server.

The complete changed modules passed with435 passing setup/call/teardown phases,
zero failures or skips and an independently observed native exit0:

- test_postgres_http_fixture.py:10 cases.
- test_document_execution_protocol_20261010_postgres.py:61 cases.
- test_compliance_tail_protocol_20261010_postgres.py:74 cases.

The total145 cases finished in261.903 seconds under the unchanged720-second
outer bound, without timeout or OOM. Every fixture database and the owned source
database were removed and their absence verified; all original database names
and PostgreSQL server identity remained unchanged. Stopped diagnostic workers
and immutable source/report snapshots remain retained for inspection.
Earlier setup failures (wrong public configuration lookup and absent receipt
source SHA) are retained separately; neither launched pytest.

Outside-Git proof is
`native-release-20261111-ZzEIol4V/verified-e808-and-dated-protocol-02/proof.json`;
native journals/JUnit/runtime exit and frozen file hashes are referenced there.
The original failed CI artifact and first failed145-case candidate are retained.

The separate20-command source gate on the committed Android logout correction
also passed:686 mobile, TypeScript,1703 harness passes plus two unchanged
Windows-only skips,422 Python cases in all17 requested modules. Complete
current CI on the next pushed revision, replacement native platform suites,
distribution signing and store submission remain required.
