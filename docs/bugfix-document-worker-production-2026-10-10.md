# Durable Document Execution And Production Certification - 2026-10-10

## Current Verdict

**NO-GO.** #527 is **Not fixed** on the serving production release
`3dbf364d9834316d181d4a52b2e9b4c7bee431b4`. PR528 and PR522 are merged;
API `caseops-api-00488-5sd` and web `caseops-web-00465-sk6` serve that exact
revision with one untagged latest-only 100% traffic entry each. PR529's
security-only repair is now merged onto canonical main
`dfda0eb3ee3d109f86092962a08d125878b24932`; it is not a newly deployed API/web
release. Fresh October 10 GitHub main-ref readback finds no open code-scanning
alerts. Draft license PR531's file-read-race finding is also fixed without
dismissal, but 19 actual license-policy rejections still prevent its merge.
The earlier "not deployed" checkpoints are history, not current serving truth.

This scope maps to existing US-001/M02/M03/M08/M13/M14/UJ36/UJ61 release
journeys and J19/M21/US-063/SEC-031 public discovery and evidence controls.
It adds no legal-source approval, consent or commercial commitment.

## Exact Failed Evidence

[Production verification 38036444501](https://github.com/mishrasanjeev/caseops/actions/runs/38036444501)
attempt 1 completed all six serial shards: **341 identities, 320 pass,
18 unverified skips and three failures**, without retries, missing identities,
native mismatches or global errors. The readback retains original JSON/XML,
ordered collections, incremental attempts, progress and all 64 native digests.
Main independently rehashed all **2,936** sealed files with zero mismatches.
Evidence seal SHA256:
`7aa7e4013ba81817c81e67aba0f28aec1009924a67aca8c01de57fe00c385b8f`.

| Journey | Actual response on API 00488-5sd | Corroborating SQL |
| --- | --- | --- |
| Notice sent attachment, spec line 173 | POST attachment 503 at 08:46:53 UTC, 5.047 seconds | Company NO KEY UPDATE lock timeout at 08:46:58 UTC |
| Patent parties, spec line 59 | POST patent application 503 at 08:56:27 UTC, 5.066 seconds | Company NO KEY UPDATE lock timeout at 08:56:32 UTC |
| Patent priorities, spec line 57 | POST patent application 503 at 08:58:14 UTC, 5.048 seconds | Company NO KEY UPDATE lock timeout at 08:58:19 UTC |

The temporal/route/revision evidence strongly corroborates one shared lock
mechanism. Historical holders, request IDs, problem bodies and a direct
HTTP-to-SQL-process linkage were not captured; do not invent those identities
or attribute the historical lock to a particular uncaptured worker.

A fresh unchanged Notice diagnostic passes **2/2** on 3dbf, not a waiver of
the failed full dispatch. A read-only observer subsequently captures document
private-projection finalization idle in transaction after the browser journey,
up to **5.786345 seconds**, while Cloud Run uses request-based CPU throttling.
This establishes an unsafe execution boundary; attribution of the original
historical holder remains an inference. All 90 observer samples are read-only,
bounded and complete; receipt SHA256:
`bb55c9455b0ddab60ea105034fb62b86e3bd4a535e3b169422c61335cf557d53`.

Read-only queue inspection at 10:03 UTC finds **11 processing jobs** whose
oldest enqueue age is approximately 154 days and **three queued jobs** whose
oldest age is approximately 92 days. No Contract/IP pending group is returned.
This is actual missing crash-recovery evidence, not a fabricated incident.
Receipt SHA256:
`fd75e16b1968dd70d9853a00533f4fa6dc717b40f32799d781af50a53434e19a`.

## Repair In Progress

**Partially implemented; candidate verification is Inconclusive.** Relocate
execution of the existing durable DocumentProcessingJob queue from production
Starlette after-response tasks to an independent, exact-image document worker.
Do not introduce a second domain workflow or an ad hoc in-memory queue.
Production never falls back inline after a denied/timed-out wake-up. Admission
is committed before the bounded no-override job wake; the API owns no database
transaction during external transport. A minute cadence recovers missed wakes.

Atomic claims, bounded stale recovery and attempt-fenced finalization must
prevent overlapping workers or a reclaimed old attempt from persisting output.
Release the database transaction before parsing/provider I/O, then reacquire
current parent lifecycle, membership/access, source provenance and Company-first
private-generation authority before final persistence. Retain every existing
security fence and the 5,000-ms lock budget. Unknown legacy jobs are no-paid;
new jobs persist and restore the authoritative automated-request marker.

The documents-only worker must not poll courts, generate case summaries,
automatically replay failed jobs, run migrations or call billable providers for
automated work. Scheduler/IAM/image/readback and release draining require native
regressions. Preserve request-based API billing, capacity, scanner and deadlines.

The Notice browser contract now requires all three exact uploaded attachments
to finish indexing, have completed jobs and extracted content, and survive a
page reload. Mutation retries remain forbidden. Bounded sanitized network/API
diagnostics must retain decisive failed writes instead of navigation floods,
without raw response bodies, URLs, record IDs, credentials or personal data.

Provisional Main targeted replay r3 completes **246 pass/one unverified
POSIX-only skip** among 247 identities, with 740 setup/call/teardown records and
a session-finished receipt. Source formatting overlapped that run, so it is
provisional, not frozen release proof. Earlier r1/r2 failures remain preserved.
Fresh final-source collection, migration/claims PostgreSQL races, full Docker,
browser, build and hosted CI gates still precede a normal PR merge and guarded
exact-main deployment. Full production replay and two later clean private
maintenance executions precede certification and private cadence resume.

Fresh full Main r10 completes **392 passes and one unverified POSIX-only
skip**, with 393 ordered identities, 1,178 incremental phases and a matching
session-finished/JUnit receipt. The Windows skip is not coverage of an
exec-disabled POSIX filesystem. The document and court
dispatchers release read-only transactions before bounded Google Jobs wakes;
missing wakes never fall back to production after-response execution. The
complete deployment-script suite is included in this scoped result. A later
runtime-bound replacement r11 completes **196 passes / 588 phases**, zero
skips/errors, with exact collection and native result agreement.
Agent PostgreSQL evidence is scoped to its exact committed inputs, not yet
proof of the integrated final image. Database rolling-writer fences and the
legacy-to-independent-worker handoff remain under implementation/review.

Main r13 completes **415 passes / one unverified POSIX-only skip**, with
416 ordered identities, 1,247 incremental phases and matching final JUnit.
The later r14 runtime-control replacement completes **221 passes / 663 phases**,
zero skips/failures, identical collection/execution identities and unchanged
before/after source pins. It rejects both desired and resolved traffic drift
and service-level manual scaling. These results do not replace broad
PostgreSQL, final-image Docker or production acceptance.

The actual frozen 3dbf worker commits indexing before a separate compliance
transaction. Fencing its document-job receipt alone cannot reject that tail.
An explicit root-run persistence protocol is required across manual, current
worker and court callers; no legacy auto-stamp, physical-stop claim or provider
cancellation is implied. Its migration/counterproof remains pending.

The first all-historical native stop probe is **Inconclusive**: 8,624 read-only
Monitoring requests, zero mutations, then a bounded timeout. Its failed
receipt and unchanged before/after source hashes are retained under
`.tmp/worker-stop-native-r1`. Cloud Run metrics expire after six weeks; missing
old series are not zero instances. Requiring every retained historical
revision's expired telemetry cannot produce a usable release gate. A bounded,
primary-source-backed read-only r2 classification now reconciles all 487
retired revisions with **106 native measured zero results** and **381 explicit
platform-contract inferences**, using 106 Monitoring requests and zero writes.
Receipt SHA256:
`f927fabd4ac4284f1bbe496aa482ad085d779bca82911905ff0a0eaa63db3bef`.
Expired history is not assigned fabricated zeros. The inference requires
stable untagged/unreferenced retirement, no effective minimum allocation,
automatic scaling and request-based CPU. The retained r2 receipt used an
unsupported timeout/idle/shutdown arithmetic premise and is **not final proof**.
The corrected source records historical autoscale retirement as an operational
inference only, not a physical execution deadline or missing-metric zero.
It cannot release earlier locks or cancel already-issued provider work; the
independent compliance-tail barrier is required before legacy persistence is
fenced. A fresh corrected native preflight is still required. The captured
currently serving prior revision must always have
positive native active/idle zero evidence after routing, even on a resumed
rollout. No revision deletion, credential rotation or admission enablement
has been performed as a waiver.

Corrected read-only r3 completes with **105 native measured zeros and 382
explicit operational-retirement inferences** among all 487 retired revisions,
105 Monitoring requests and zero writes. The moving six-week retention boundary
accounts for the cohort change; missing series still never become zeros.
Its receipt explicitly denies physical-stop proof for expired history and
records the compliance-tail barrier as unverified. Source pins match before
and after; receipt SHA256:
`c1d0091b8d03af46d615648114d3a65b0d4d4bd267e98d0585e79767d45867c5`.

## Security And External Boundaries

All 28 original code-scanning alerts are actually fixed, not dismissed.
PR529's actual hosted CI, Security and CodeQL attempts are successful; all three
fresh PR SARIF reports have zero results, errors and warnings. Main independently
rehashed 3,260 sealed evidence files with zero mismatches. The earlier 25 Python
note findings belong to retained historical evidence, not these new reports.
This is exact-tree scanner evidence, not a blanket security certificate.

The old secret scan examined zero commits/bytes. Its merged replacement retains
the unchanged reviewed exception policy and passes all 38 native controls,
including real offline Gitleaks fixtures. Hosted scanning actually examines
2,680 tracked files and all four changed commits, including merge resolutions.
The accepted hosted merge tree `9837fcabf8e8a4d89b399bc79e50193444b783cb`
matches canonical main's merge tree. No worker repair is certified by this
security-only result.

The inherited license artifact is still `{}`: four bytes and zero packages.
The original draft at `6cb037ab` exposed 20 rejections. Its replacement
`3616820e` corrects SPDX OR evaluation and descriptor-bound JSON reading,
passing **140/140 native and hosted controls**, zero skips. It reconciles
200 runtime locations / 166 package-version identities with **19 actual policy
rejections and zero inventory errors**. Local inventory includes 42 optional
lock-only locations; hosted inventory includes 37. OFL, LGPL, MIT-0 and Zlib
remain unapproved under the unchanged allowlist, not vulnerabilities or green
license certification. All three fresh CodeQL SARIF reports have zero results;
alert 534 is fixed, not dismissed. Main independently rehashed all 95 sealed
license evidence files with zero mismatches; manifest SHA256:
`6e2cba1ca476e8901f351395613974e4dcc1f215ee1af713a9c6b4edc858f748`.
Hosted Security fails on the real policy rejections. PR531 remains draft,
unmerged and not production-certified; #530 stays open.

#515 has 40/40 exact-release public-content passes, with closure deferred to
the replacement certified release. Stronger mobile/desktop persona/pilot
assertions additionally complete a **23/23** native local public-content
diagnostic, without retries or missing identities. It reads the retained
Docker image `a968c614` whose public source tree matches serving `3dbf364d`;
it is not new-image acceptance or a fresh 40-case production result.
Reconciliation receipt: `.tmp/public-pilot-docker-diagnostic-r1-reconciliation.json`.
#513's privacy-first lead admission keeps
GA4/client telemetry disabled; sender/privacy/retention consent is still open.
#521's crawl-policy correction is deployed, but Google-reported noindex
exclusion is not proved. Fresh owner-authorized Search Console readback on
October 10 still reports `/sign-in` indexed though blocked by robots, with the
last crawl September 22 at 02:08:14. No crawl, sitemap or validation submission
was repeated. Calendar's automatic candidate passes; actual human
Google consent remains unverified. Previously owner-kept provider/legal identity,
Workspace, sender, merchant and license dependencies stay open. Never count
synthetic production leads, paid automated probes or skipped consent as proof.

## Permanent Learning

A green deploy, zero open alerts or one successful replay cannot certify a
failed full production inventory. Request-based Cloud Run must not do database
finalization after its response; a durable admission alone also needs atomic
claims, bounded expiry and stale-attempt rejection. Persist automated no-paid
policy across execution boundaries. Preserve failed evidence and identify
uncaptured causality as unknown. A green scanner that examined zero bytes is a
coverage failure, and bounded diagnostics must prioritize failed mutations.
An empty license inventory is equally incomplete; report actual policy
rejections rather than silently electing new terms. Expired monitoring evidence
cannot certify a stopped process and must not turn into an unbounded polling
loop or an impossible historical release requirement.

Official runtime basis: [Cloud Run general tips](https://docs.cloud.google.com/run/docs/tips/general),
[billing settings](https://docs.cloud.google.com/run/docs/configuring/billing-settings),
and [Jobs run API](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs/run).
