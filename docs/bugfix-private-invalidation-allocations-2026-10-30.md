# Private Invalidation Allocation Bound

## Scope And Verdict

**Partially fixed / NO-GO pending full replacement release.** This adjacent
#561/#564/PR567 blocker belongs to existing private retrieval/IPLF-066, Matter/IP
lifecycle, M02/M08/M13/M14, NFT-005 and tenant/access security. App, native
read-through storage/migration0008 and MacBook acceptance remain separate.

## Observed Failure

Frozen EB109EC Docker24 child02 completed440 identities/1320phases with439
passed calls and one failed call. Its original10,001projection/10,000output
test measured6.7003345s against the unchanged5s lock budget. Passive evidence
records11critical cursor intervals totaling1.7319516s and81overlapping GC
intervals totaling4.7826358s. One generation2 collection took4.7423339s and
collected203,100objects. This proves overlap, not every allocation's origin,
a server-wait cause or the explanation of older historical delays.

The old atomic UPDATE still buffered its complete returned source list and
ORM fetch-synchronization identities. Saved-output synchronization returned
all affected IDs even with an empty cache. Bounded SQL count did not bound
Python materialization. Keep the failed run failed. Interrupted child03 has
16passed calls/49phases and no completion; all640browsers were unexecuted.

## Repair And Regressions

Raw-table Core updates retain exact atomic predicates and assignments. A
shared helper consumes narrow RETURNING metadata in100-row batches, counts
consumed rows and retains distinct source pairs. Only actual returned IDs
synchronize resident ORM objects. When no sources/resident IDs are needed,
use rowcount without RETURNING. This bounds SQLAlchemy Row batches, not native
driver/database buffering, distinct source count or every resident object.

Committed values plus flag_dirty preserve nested rollback expiry before and
after flush, without per-row SQL. Autoflush respects no_autoflush and recursive
flush protection. Results close on success/failure; errors propagate under
caller-owned transactions. No source SELECT/UPDATE race, new lock order,
commit, retry, GC policy, timeout or weakened predicate was introduced.

Fresh independently migrated focused03 completes all10selected modules:
275passed cases/825phases,0skip/retry/nonpass,167retained files verified and
source equality. Inventory:5streaming,4SQLite/PG savepoint,1original large,
9foundation,32workflow,27actor-safety,32actor-lock,2authority-lock,162client-
authority and1later-manifest cases. The large case passes all original
count/SQL/private-byte/persistence/replay assertions at1.8983929s. Its extra
assertions cover expired cached outputs, retained prior locks and untouched
cached projections. New contracts cover raw Core targets, bounded batches,
returned-ID coherence, unnecessary RETURNING, error closure and autoflush.

Preserve focused01's subnet refusal and focused02's262passed/4call-failed/
8setup-error result. Four new fixture updates omitted required tombstone/lock
timestamps/reasons; eight setup errors rejected the auxiliary environment.
Its database name also needed the existing exact owned-native format.
Correct only those fixture/setup inputs, not constraints or safety guards.
Those12failures are not product reproductions. focused03 replaces all274old
identities and adds one autoflush contract, not a passing subset.

Evidence: outputs/fix-561-20261026/portfolio-export-worker/
docker24-private-event-diagnosis/focused03/results/reconciliation.json SHA256
bed1ee5142c9528f83e2595e19a6b71bfaa1e6c41dfb5c2f8e06350412514a81.
Final large-event receipt SHA256
c3ff0f3a44b252721bca9f65066bb239b4e17d2ef4b88309f30e8ed82eaa7762.

## Closure Gates

Component proof is not whole-release latency or production acceptance. Require
complete fresh frozen Docker, green exact-head hosted gates, protected main
merge with accepted-tree equality, guarded deployment and exact-release full
production verification. Preserve desktop/mobile15s/51-CSV-data-row D29,
later clean private cadences and guarded scheduler recovery. Update both
original workbooks only from actual results. Legal review, unknown Matter,
old Calendar consent, owner MFA, provider/GBA and MacBook holds stay open.
