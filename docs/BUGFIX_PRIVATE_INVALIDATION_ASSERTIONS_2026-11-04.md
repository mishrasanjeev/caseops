# Private invalidation test mutations outside assertions

Three existing tests invoked `_apply_private_invalidation` inside an assertion.
That helper constructs and executes UPDATE statements and synchronizes cached
ORM state. Assertion evaluation must not own those effects.

The three calls now assign their results before the existing equality checks.
This covers the saved-output savepoint case and both streaming cases that
exercise row-count and recursive-autoflush behavior. Every argument, expected
result, later assertion, fixture and test identity is preserved.

This follows the existing private-retrieval/IPLF-066 coverage for M02, M08,
M13, M14 and NFT-005. The source and test contract is documented in
`PRD_COVERAGE_MOD_TS_2026-04-20.md`, October 30 Private Invalidation Coverage.

Validation on the isolated checkout based on main
`bdd1480699222712475372690334659088629429`:

- Both complete affected files were selected with `-m 'not postgres'`:
  **7 passed, 21 passed setup/call/teardown phases, zero skips or failures**.
  Two PostgreSQL parameter cases were explicitly deselected and remain
  unverified on this candidate until the PostgreSQL gate runs.
- The journal and JUnit contain the same seven case identities and outcomes.
- A retained AST comparison reconstructs each original assertion by joining
  only its new assignment and comparison. Both whole-file ASTs then equal
  their canonical base-tree versions. All three effectful assertion calls
  were removed and all other executable syntax was retained.
- The local run used a fresh short SQLite temporary root and the accepted
  API162 environment without installing dependencies or using the shared
  PostgreSQL service. The native result was `7 passed, 2 deselected` in
  27.93 seconds; its 43 dependency deprecation warnings are retained.

Local evidence is under `outputs/mac-release-closure-20261103/` in the original
agent workspace, subdirectory `private-invalidation-assertion-fix01`:
`native-events.jsonl`, `junit.xml`, both raw pytest streams and
`RECONCILIATION.json`. The first post-run reader mistakenly used the API139
configuration-file length for API162; it is retained as a failed reader.
The corrected data-only reader takes the exact API162 pin from its accepted
provenance packet and does not rerun the tests.

Verdict: **Partially fixed**. The isolated non-PostgreSQL checks passed;
the two PostgreSQL cases and fresh candidate CI remain pending. This is a
test-code repair, not a new claim about production private-retrieval behavior
or closure of the broader competitive-gap programme.
