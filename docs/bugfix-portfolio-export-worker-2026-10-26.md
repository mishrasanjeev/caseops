# Portfolio Export Worker Recovery

Ownership: IPLF-030B/037, UJ-04-NORMAL/EXC-02/EXC-03, IP15-018,
J08/M08, NFT-005 and SEC-003/004. This follows the exact-release failure found
while certifying the deployed verification-header repair #561.

## Actual Baseline

Canonical/live f49b274e2098cdbd0284e505c2eb5fc363b820d2 passed full local Docker
and protected main CI/Security/CodeQL. Exact production QA40323857026 is RED:
414 actual of417 intended,395passed/18explicit skips/1failure. The last three
dated Batch3 invocations did not run. Signed closure correctly did not publish.

IP18 1280px created one51-row export. Its persisted worker ran16.502seconds,
exceeding the unchanged15-second contract; the artifact ultimately completed.
POST202 finished in0.921seconds before work, on a request-based CPU-throttled
service. Status reads were successful and mostly reached other instances.
Individual SQL/GCS stage attribution has not been proved. Do not label this
test drift, data corruption, a missing header or a billable provider failure.

The worker uses post-response BackgroundTasks, unlike existing production
document dispatch. It also lacks an atomic duplicate claim, expiry recovery
and stale-finalizer fence. Preview and execution unnecessarily hydrate display
data and repeated full-scope statistics. Those are independently inspected
code findings, not invented production profiler results.

## Repair Boundary

- Keep the existing durable job/admission and explicit failed-job retry.
- Local-only BackgroundTasks remain a deterministic development mechanism.
- Production admits an exact-body dedicated-HMAC Cloud Tasks callback before
  returning202. The warm synchronous HTTP handler executes off the event loop
  and acknowledges only a durable terminal result. It returns conflict for a
  current competing worker; status GETs remain read-only.
- Transport is bounded and non-retrying. An uncertain queue acknowledgment
  never replays the browser enqueue. Scheduled bounded fallback recovers the
  durable database record, not another legal record or provider call.
- New protocol1 jobs use atomic claims with bounded expiry and ownership-fenced
  publication. Rolling old writers retain protocol0. Never reclaim an old
  running row whose original executor has no ownership fence.
- Admission caps only current protocol1 work. Retained protocol0 jobs are
  separately reported and unchanged, so abandoned old work cannot permanently
  block a fresh bounded queue or be adopted by an unfenced executor.
- Release database transactions before queue/storage transport; freshly check
  current membership, IP capability, source visibility/lifecycle and claim
  before publication. Active membership alone is not current IP permission.
- Commit an immutable tenant/job/attempt receipt with the claim, including its
  deterministic planned object key and lease expiry. Link failed/completed
  outcomes to that attempt. A plan is not proof of upload. Receipts survive
  expiry, retry, token clearing and lost acknowledgements; they do not authorize
  deleting an uncertain published object or introduce a new retention rule.
- Share canonical scoped selection/date proof, preserve HMAC manifests and
  exact CSV values. Three-column export must not load unrelated display history.
- Do not alter request-based billing, warm capacity, legal verification or the
  accepted15-second completion gate. Cloud Tasks is not a timing guarantee;
  its actual serving-release journey must still pass.

## Required Regression

EXW-01: exact preview manifest/row-limit/truncation and CSV output,1/51/201/401rows.
EXW-02: deep retained history cannot grow three-column hydration; query bounds.
EXW-03: simultaneous delivery, crash/expiry, stale finalizer, completed replay,
and no implicit replay of a terminal failure.
EXW-04: revocation/source/lifecycle change during storage rejects publication;
no database transaction or parent lock spans network transport.
EXW-05: missing/stale/tampered HMAC, wrong body/secret, app/admin JWT and CSRF
boundaries; positive request stays active through completion and is off-loop.
EXW-06: dispatch timeout/denial/lost acknowledgment, bounded fallback and actual
Cloud Tasks constructor; no production BackgroundTask or mutation retry.
EXW-07: old insert after migration remains protocol0, upgrade/downgrade from
fresh databases, repeat upgrade, and no legacy-running claim takeover.
EXW-08: unchanged IP18 desktop/mobile, source IDs, single enqueue,15seconds and
all51 CSV records; full intended local/production inventories, not a file filter.
EXW-09: complete deployment rehearsal intercepts both exact-scope worker-helper
phases offline, parses actual API environment/key references into helper readback,
and retains named main-drift/denial gates before routing and certification.

## Reopen And Verification Lessons

The initial local export gate could not prove Cloud Run's post-response CPU
behavior. The exact-release production run correctly exposed that gap; neither
an eventual artifact nor a longer test timeout would fix it. The worker now has
an explicit request-owned execution boundary, but only its actual serving
production replay can establish the completion outcome.

The first focused repair selection also omitted the full deployment fake
harness. Dedicated queue-helper tests passed while that harness forwarded the
new helper into unintended real code and later guard assertions became
unreachable. The repaired rehearsal validates both exact helper invocations,
uses network-disabled execution and named main fences, and preserves earlier
failed/interrupted evidence. It is not enough to assert that the deploy script
contains a helper name or to rerun only the first failing test.

Verdict: Not fixed until complete source, Docker, CI, deployment and exact
production replacement evidence pass. Keep every failed receipt. The live
private scheduler stays under the canonical guard; any interim manual clean
maintenance is not post-successful-QA resume evidence.

Primary guidance:
[Cloud Run background execution](https://docs.cloud.google.com/run/docs/tips/general),
[Cloud Tasks asynchronous HTTP workers](https://docs.cloud.google.com/run/docs/triggering/using-tasks),
[duplicate/delayed delivery](https://docs.cloud.google.com/tasks/docs/common-pitfalls).
