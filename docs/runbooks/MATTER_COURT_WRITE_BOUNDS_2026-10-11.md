# Court Write Bounds And Release Investigation

## Scope And Verdict

J08/M08/US-023/FT-042/043, M02 authority and SEC-003/004. Release **NO-GO**
until the complete replacement Docker, CI, canonical main and exact live
journeys pass. The prior native lock timeout is **Inconclusive**. A separate
broad-hydration defect can be reproduced and bounded without claiming it is the
sole cause of that timeout.

## Historical Failure

The prior session recorded Docker R2 on `665f2b19`: 2,261/2,262 PostgreSQL
passes, one 55P03 in `text-mutation-manual_sync`, all setup/teardown and native
completion reconciled. No browser phase ran. Its SQL trace showed the competing
worker waiting on Company; the holder was idle in transaction and resumed
within 18 ms of the snapshot. A later client-side trace gap was about 2.54 s.
That filtered trace omitted ordinary SELECT/ORM work and did not measure server
duration or establish a deadlock cycle. Hosted Linux CI passed the exact case.
Neither fact closes the native failure or attributes its cause.

The old checkout and final temporary reports are absent on recovery. One original
native SQL journal survives in pytest storage, independently read and copied to
`.tmp/recovered-docker-r2/failed-compliance-manual-sync-native-sql.jsonl`.
Original/copy SHA-256:
`1cc97fb78c03919fa17c08bf318acaa712d4e4d28f69a21c9b81963463ab61be`.
It proves the directed wait, 55P03, completed contenders and empty cleanup
activity/locks, not full-suite counts. Preserve the recorded failed checkpoint
and obtain fresh structured acceptance; never relabel it as green.

Fresh original/counterpart unchanged-source replay passed 2/2, all six phases,
two JUnit identities, no skip/failure and both exits 0:
`.tmp/recovery-original-lock-r1`. That narrow pass does not establish the cause
of the earlier failure or certify the full candidate.

## Source Defect And Narrow Correction

`_get_matter_model` locks a bare Matter, checks current access, then eagerly loads
all relationships for a general workspace DTO. Manual court-order create,
update and court-sync import use only scalar parent fields plus their own
targeted queries; they should not load unrelated retained tasks, notes,
hearings, orders, sync history, attachments/chunks and billing children while
Company/actor/Matter locks are held.

The source correction adds `load_locked_children=True` by default, with only
those three writers opting out. Ordinary reads and other locked callers retain
their existing hydration contract. Company-first locking, actor capability,
current ACL, terminal lifecycle, compliance extraction, notification, audit,
source deduplication and post-commit DTO behavior must remain unchanged.

## Regression Contract

The fresh PostgreSQL regression must exercise actual writes with 1 and 501
unrelated historical rows per retained model, bound every SQL statement and ORM
materialization in the locked getter, retain byte-equivalent historical values,
and assert the durable new order/import and downstream effects. A default
locked-read control must still hydrate its children. Keep the existing 2-second
lock and 10-second statement budgets; do not add transport retries or a larger
wait budget. Reconcile all collected identities and setup/call/teardown phases.
Run both complete historical concurrency modules beside the new file.

Retained recovery attempts: `.tmp/court-write-recovery-red-r1` has zero collection
and exit 4 from a malformed JUnit argument; r2 has four setup skips because the
fixture's actual `CASEOPS_TEST_POSTGRES_URL` was not set. r3 has a genuine update
hydration failure and a passing default-reader control, but create/import stop
on invalid test assertions for nonpersisted Matter flags and nonexistent
notification fields. Those assertions are corrected to the real read DTO and
redacted intent metadata; r3 is incomplete reproduction for those two writers.

Corrected r4 independently reproduced all three intended hydration failures
after actual writes, replay where supported, retained-history hashes and denial
fences completed. Four collected/JUnit identities, 12 phases, three call
failures, one reader control pass, successful setup/teardown, zero skips and
both exits 1 are retained in `.tmp/court-write-recovery-red-r4`.

The source correction passed all **68 cases** across the new file (4), complete
participant-fence file (53) and complete document-finalizer file (11).
`.tmp/court-write-recovery-green-r1` independently reconciles 204 successful
phases, 68 JUnit identities, zero skipped/missing/failed cases and both exits 0.
The three write getters decreased from 16/17 queries to **2**, with zero unrelated
history ORM loads. Complete write query counts at 1 and 501 histories are
identical: create 160, update 28/replay 24, import 118/replay 71. Default shared
and exclusive readers still hydrate all retained children. Current ACL,
cross-tenant and stale-active lifecycle rejection, Company-first locks, retained
history and real compliance/notification/audit outcomes passed. The separate
earlier 55P03 cause remains Inconclusive; this bounded source defect is only
**Partially fixed**, pending complete Docker and exact-production replay.

History fixtures use different source/date/reference values. The separate
`_find_existing_imported_order` same-identity collision scan remains open pending
a reviewed bound and production volume evidence. Do not guess legal identifier
normalization or silently truncate candidates to satisfy this regression.

## Production Boundary

No production write, provider reconfiguration or deploy has occurred. Local
work-bound improvements are not production certification. Require fresh images,
complete PostgreSQL/migration/catalogue/browser acceptance, green candidate CI,
canonical-main identity, guarded deployment and the same exact-serving dated
browser journeys. Paid providers remain excluded from automated tests.
