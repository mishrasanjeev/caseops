# Database ownership journal CI regression — 2026-11-13

Verdict: **Partially fixed**. The complete changed offline module passes;
replacement hosted CI and the native mobile release remain unverified.

Required CI run 43286760507, API coverage shard 13/13, job 131422315007
failed two database-journal tests. Its downloaded artifact 13978821660 has
SHA-256 `ec74a7b804a70944446667553d9732aa11f7ada721c0d9c03a701cff4f22f170`.
The native JUnit contains 1,417 cases: 860 passed, 555 skipped, two failed.
Neither the failed shard nor its skipped cases count as complete acceptance.

The canonical temporary-database owner verifies `pg_database` after receiving
the DROP acknowledgement. The two offline journal tests used a database
double that implemented creation and removal but omitted `Connection.scalar`.
That missing method raised `AttributeError` during cleanup, including while
handling an intended journal acknowledgement failure. The canonical fixture
and its independent absence check are unchanged.

The double now maintains separate created and dropped identities, checks the
exact absence statement and bind, and returns its retained database state.
Both success paths assert that the absence read occurred. Two added controls
prove that an acknowledged DROP with a still-present database or a lost
absence observation remains a failure. Unknown CREATE outcomes still retain
their intent without replay or speculative removal. Invalid journal files
still refuse creation.

The unchanged 25-case module reproduced the exact two hosted failures in an
isolated, network-disabled Linux ARM64 API image with Python 3.13.18. The
replacement complete module passes 27 cases and all 81 native pytest phases,
with JUnit and the independent process receipt agreeing on exit zero. Ruff
passes. Docker filesystem bytes and inodes were measured before this run.
These are offline fixture contracts, not actual PostgreSQL DDL or app-device
acceptance. The earlier missing-source and prelaunch attempts are preserved
separately and receive no passing credit.

Evidence remains outside Git under
`native-release-20261111-ZzEIol4V/ci-api13-journal-reconciliation-03.json`,
with the failed hosted artifact, local red and green reports and exact source
digests retained alongside it. Fresh hosted CI must still cover the entire
selected shard. No retry, time-budget change, production authorization change,
native test completion, distribution artifact or store upload is claimed.
