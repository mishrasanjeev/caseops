# Web Fixture Cleanup

Verdict: Partially fixed; whole release acceptance pending.
Ownership: NFT-005 and local-only fixture isolation, adjacent IPLF-063B setup.
This is web Playwright tooling, not native Android/iOS or production runtime.

## Retained Failure

Full Docker21 on82c8dc551163a95e7d81daa682e623f6cbcc1c91 ended naturally/reaped1
before image/main-regression phases. Full Node TAP/JUnit has18cases:16passed,
two failures, no skips. The selected isolated venv's psycopg probe exceeded
the original10s limit at driver stage; oversized-output rejection then hit
EBUSY removing its owned temporary directory after the child-close boundary.
Both complete failures, exact source-before/after equality and failed scratch
bytes are preserved. The remaining57fixture checks, expected3514main native
cases and640browser cases were unexecuted, not green.

Historical receipt under outputs/fix-561-20261026/portfolio-export-worker/
docker21-web-cleanup-fix-01/historical-docker21/reconciliation.json:
SHA2567c28dad94fe64c81ee5e4849a78285ff93c9873278cf604d29356949914909e0.

## Narrow Tooling Change

After the existing real child-close and owned-root checks, delegate removal
to awaited Node promises.rm with maxRetries4 and retryDelay100. Exhausted
errors still propagate. This is native filesystem backoff, not an application,
provider, mutation or fixture-child retry. The configured linear backoff is
bounded per native removal path; it is not a promised global recursive-delete
wall-time limit. No deadline, kill/reap assertion or source/tenant guard changes.

One deterministic new process test checks the exact root/options, closed
single-child invariant, propagation of exhausted EBUSY, awaiting the removal
promise and actual successful deletion. It delegates to the real filesystem
after releasing its test gate, restores the mock, and does not run the child
again. It tests the API contract, not Node's internal retry timing algorithm.
All original18process identities remain in order; counts become19/51/6=76.
Controller expectations change only to match the real added process case.
Support entitlement helper and shared OAuth supervisor remain byte-identical.

## Actual Verification

The complete canonical fixture entry point passed all76cases on pinned
Node22.14:19process,51SQLite,6controller; zero skips/retries/failures. Exact
inventories/JUnit/Python phases, source snapshots and all three owned phase
trees reconcile. The original10s child/15s test limits and negative protocol,
sanitization, no-late-write, SQLite parity and scope guards remain exercised.
Full browser TypeScript checking on the same pinned runtime also passed.

Receipt:fixture-green-reconciliation-02/reconciliation.json,
SHA256a486748a0fe15a85b4442869070eae075c964d76ef64ab490315c8842ce84b17.
The first post-run reader used a nonexistent helper name and failed without
altering reports. Corrected read-only reconciliation used the actual canonical
reconcile_sqlite function; fixture tests were not rerun to hide that reader error.

Three separate driver observations are diagnostic only. The first profiled
and second unprofiled observations exceeded their execution allowance; a
later isolated selected-venv observation completed in1.301s with no API import.
The real unchanged driver test then passed in2.074s inside the76-case run.
Neither a later pass nor import-time output establishes the original timing
cause, filesystem holder or host/GC explanation. No dependency, runtime, driver,
OS/antivirus/priority, cache policy or shared native tool was changed.

The product writer hashes are unchanged from GREEN46/138. A new clean committed
full Docker/native/browser inventory, current CI/Security/CodeQL, protected
main/tree proof, guarded exact-SHA deployment and complete live verification
remain required. No production or workbook status is promoted by this fixture
component; MacBook app and owner/legal/provider/consent holds stay separate.
