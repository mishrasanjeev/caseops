# Private projection shadow cleanup race - 2026-09-05 permanent learnings

## Incident verdict

Exact-release production Playwright exposed a valid stop-ship defect while
disposing a Matter. The lifecycle endpoint returned HTTP 500 and the Matter
transition rolled back. The request log and correlated API stack showed
SQLAlchemy `StaleDataError` for `private_index_projections`, not an automatic
Matter reopen and not private-index corruption.

The same production run also lost one successful foreign-associate transaction
response. Cloud Run proved that request committed once and returned HTTP 201 in
188 ms. That failure was an ambiguous client transport reset and must not be
handled by replaying the mutation.

## Exact root cause

1. A Matter disposal acquired the authoritative lifecycle locks and enqueued a
   private projection event against the active generation.
2. Event application selected matching projections from every generation,
   including an unreadable building shadow.
3. Concurrent maintenance failure cleanup deleted that shadow's committed
   partial projection rows, as it is required to do.
4. The lifecycle ORM session still held the deleted shadow projection and tried
   to tombstone it. SQLAlchemy expected two updates, PostgreSQL matched one, and
   `StaleDataError` rolled back the complete Matter disposal transaction.

The mistake was treating physical tombstoning of shadow rows as the security
fence. Shadow generations are never readable. Their correct fence is the
access/tombstone epoch captured by the rebuild, which makes stale writes and
verification fail before activation.

## Correctness boundary

- Ordinary source, access, lifecycle, and tombstone events update only the
  active generation ID captured on the immutable event.
- Building and ready shadows receive the new security epochs. Ready manifests
  are invalidated and stale workers cannot verify or activate.
- Failed-shadow cleanup may continue deleting partial unreadable rows in bounded
  transactions without racing ORM updates in an interactive lifecycle request.
- Tenant-wide data disposition remains stronger: every active, retired, and
  shadow generation is neutralized with a set-based update, followed by the
  existing zero-live-content invariant. It does not retain ORM instances that a
  concurrent cleanup can make stale.
- Matter status, `is_active`, lifecycle version, private event, tombstone, child
  neutralization, and audit rows still commit atomically.

## Regression proof

`test_matter_disposal_survives_concurrent_failed_shadow_cleanup_on_postgres`
forces the production ordering on real PostgreSQL. A lifecycle session loads its
active projection while another session locks the shadow generation, deletes its
projection, marks the shadow failed, and commits. With the old all-generations
query the test reproduces `StaleDataError` (`expected to update 2 row(s); 1 were
matched`). With generation scoping restored, the same overlap commits disposal,
tombstones the active projection, applies one event, and leaves zero shadow
projections.

Unit regressions separately prove that an ordinary event tombstones the active
projection while invalidating the shadow epoch, and that tenant disposition
neutralizes both active and shadow content.

The foreign-associate acceptance helper performs exactly one mutation POST. On
`ECONNRESET` or socket hang-up it reads the authoritative workspace, requires
exactly one event matching transaction kind, reason, and row-version before/after,
and fetches a successor by server-owned ID when applicable. Missing or ambiguous
evidence remains a test failure; the POST is never replayed.

## Release boundary

Repository tests are not production closure. The correction must pass the clean
Docker PostgreSQL/pgvector and Playwright inventory, merge through canonical CI,
deploy the exact current `origin/main`, pass the same production lifecycle
journey, and complete one quiescent maintenance rebuild followed by a second
clean no-rebuild cadence with no blocker.
