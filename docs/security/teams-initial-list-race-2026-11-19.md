# Teams creation during the initial list read — 19 November 2026

Verdict: **Partially fixed**. Journey J14, module M13, stories US-040,
tests FT-059/FT-061 and AI-TEAM-01. This is a separate reproducible defect;
the historical production 120-second failure has no proven root cause.

The New team control is available while the first list request is pending.
React Query coalesces invalidation with that request when it has no cached
data. If creation commits before the older empty snapshot arrives, the UI
can show the success toast and then omit the newly created team. The actual
unchanged page fails the new original regression (one native failure).

After acknowledged creation, cancel only the outstanding Teams list read,
then perform the existing invalidation. No write is replayed. Rejected
creation leaves the original read and form intact. Member and delete actions
require an already loaded row; background refetch is independently covered.

Six new component cases cover the original race, old success/error ordering,
rejected creation, failed recovery with read-only retry and background refetch.
Nine transport-fixture cases retain real response bytes, authentication,
request-owned no-paid marking, TLS and finite deadlines with no retries.
The existing desktop and phone journey now holds one real pre-create GET,
proves a distinct post-create GET and visible row, then releases the exact
older bytes. Every existing membership, stale conflict, audit, reload and
cleanup assertion remains. Browser cases and their 120-second budget are
unchanged. Real browser execution is pending.

Focused Windows verification: 56 cases passed across five modules, component
and E2E TypeScript compilation passed. The intentional short-timeout control
proves cleanup settles the actual mutation and leaves the next form clean.
Disabling cleanup independently reproduces a pending mutation and stale
callback. The first control parser failed because native JSON replaces the
timeout message with STACK_TRACE_ERROR; retained console evidence proves
the exact 50ms timeout. The corrected verifier reuses that positive run and
executes only the missing negative control. Neither intentional failure is
a product failure or a full-suite pass.

External retained evidence: C:/Users/mishr/.codex/merge161001/
team-initial-read-baseline01-*, team-fixture-focused01-*,
team-timeout-isolation01-* and team-timeout-isolation02-*.

Privacy diagnostics add four finite Teams route classes, without IDs, query
values, bodies or credentials. The independent native reporter contract rises
from 42 to 43 cases. The real response helper is included explicitly in the
builder COPY closure, both upload allowlists and deployment dirty-input fence;
the complete upload-context suite passes 15 cases. Complete offline deployment
rehearsal, full frontend, build, local browser, CI, deployed forced-race and
full production verification remain pending. No production closure claimed.

Main 3b1f9953cf07c137b68ae52923b78b14041e6a9b is already deployed after PR625.
Its separate full production QA run44519464549 failed in the Registry journey.
Its current Batch5 Contract/Draft results passed independently. The
private projection scheduler remains paused until all required QA and the
canonical two clean post-QA maintenance executions pass. Ordinary successful
production Teams checks without this forced race cannot close this defect.

## Complete Windows run and QR transport repair

The first complete frozen run executed all3242 cases/316 files:3241 passed,
one failed, zero skips/todo. The independent complete identity comparison
matches all prior3226 plus16 new cases, including all18 reviewed checkout
title relocations. All51 source cases finished first; all Teams cases passed.
The unrelated existing native offline QR test exceeded its unchanged5-second
budget while overlapping the full API rehearsal. CPU was sampled at64%
later in that same full run, not at the exact QR failure. Its worker retains ZIP/a11y passes
and the exact QR timeout. This failed whole run remains failed evidence.

J14/M14/US-040/042, FT-060/061, PRA-09: the real QR helper previously passed
262144 boxed pixel numbers through the browser protocol on each decode.
Transfer the same256x256 RGBA bytes as chunked binary/base64, decode them
back to bytes in Node and call the same actual jsQR library. Keep exact URL,
issuer/account/secret/algorithm/digits/period validation and both independent
pixel decodes, mismatch/blank negatives, real ZIP and a11y checks. No media
is persisted by the helper, no external QR service is used, and neither the
5-second test,5-second browser startup nor15-second child budget is changed.

Scratch-only new-transport native3/3 passes retain exact original assertions
and budgets. An earlier scratch run failed import setup before collection;
that failure remains distinct. The complete integrated replacement passes
all3242 cases/316 files with zero failures/skips/todo, both compile checks0,
all51 source cases first and exact original identities retained. Actual nested
ZIP/QR/a11y checks pass within their unchanged budgets. The complete affected
Windows deployment/source rehearsal passes1699 cases (1694 passes/five unchanged
POSIX-only skips), with unchanged source. These passes predate the additional
Registry repair; complete replacement gates for the combined candidate remain
required. See registry-link-settlement-2026-11-19.md for its separate evidence.
Real local forced Teams desktop and phone both pass, production build passes,
and owned service ports are absent after cleanup. These are local proofs;
neither production Teams forced-race nor private owner MFA is certified.

## Combined candidate verification

After the Registry repair, the serial Windows replacement passes3248/316 with
zero failures/skips/todo, canonical npm launcher and both compile checks0.
Every prior3226 identity plus16 Teams/diagnostic cases and six Registry cases
is retained; all18 named checkout-title translations and seven unchanged
canonical source inputs reconcile. All51 source checks run first. The actual
three native ZIP/QR/accessibility journeys pass with original5s/15s limits.

The failed concurrent run remains failed, including its125 unstarted cases,
15 setup-blocked cases and native-worker timeout. The API rehearsal's3000s
runner timeout remains incomplete: observed process exit0 without final JUnit
is not completion proof. Fresh whole API CI/native1699-case reconciliation and
platform complements are required before merge. Serial admission changed only
owned-gate overlap; no test deadline, worker count, retry or source was changed
between the failed and passing frontend attempts. Full CI, exact serving-release
production verification and guarded projection resume remain pending. Evidence:
team-frontend05-complete-verdict01.json and
team-affected-source03-final-disposition01.json in the external evidence folder.
