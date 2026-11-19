# November 17 production verification follow-up

Status: **Partially implemented / Inconclusive; NO-GO for complete release certification.**

## Exact deployed release and retained failure

PRs612,621 and623 have merged. The canonical retry deployed
`acff6c866bb7734e6ca3c3705b19b7f2392cb38f`; API revision
`caseops-api-00526-78v` and web revision `caseops-web-00501-576` serve100% latest
untagged traffic. Public release identity, health, scanner, edge, backup,
migration, worker activation and index checks passed. Document processing,
court sync and18:00 case tracking resumed through the canonical guards.
Private projection maintenance remains paused pending complete production QA
and the existing two-clean-execution recovery guard.

[Production dispatch44011493757](https://github.com/mishrasanjeev/caseops/actions/runs/44011493757)
failed its first tester partition:101 cases,84 passed,13 skipped and four
failed. These are separate outcomes; the partition and release are not green.
[Retained native artifact14297698983](https://github.com/mishrasanjeev/caseops/actions/runs/44011493757/artifacts/14297698983)
binds the exact source, configuration, zero retries and failure locations.
The other production partitions were still running when this note was added.

All four failures are the desktop/phone Registry and patent-family reference
checks in `tests/e2e/ram-2026-11-14-prod.spec.ts`. Their errors locate the
`prepareTester` production tenant refusal at the original
`tests/e2e/support/ram-bugs4.ts:231`. The job log records
`CASEOPS_RAM_PROD_SLUG=caseops-qa`; that helper permits only `test-legal`.
The tests failed before authenticating or opening the reference pages.
Their subsequent UI assertions remain unverified, not failed product behavior.

## Account binding repair

Existing J08/M08 owns these read-only reference journeys. Keep every test name,
UI assertion and deadline. Move the four reference cases from the QA-bot
project into the existing serialized reporting project and its second
invocation. Preserve the unchanged helper and existing workflow credentials.
The reviewed partitions become97/18/6/40/15; their complete176-case
semantic union and all original51 dated identities are unchanged. Independent
Python and frontend contracts must prove every literal identity and role,
with an actual zero-retry pass required for each reference. No account,
entitlement or production password is created, reset or broadened. Local
execution retains its fresh owned tenant and local-only setup.

An earlier explicit-purpose credential-binding alternative passed10 focused
VM controls after its negative baseline, but does not satisfy the current
release instruction to use the existing serialized role. Preserve that
alternative externally; its interrupted complete API attempt is incomplete,
and its new helper/test are not part of the final change.79 focused Python
identity, partition and positive-receipt controls pass after the role move.
The first frontend inventory replay timed out during native discovery;
34 cases passed and15 hook-dependent cases remain unverified. The initial
wrong-cwd invocation discovered no tests and is retained separately.
No collection or preparation deadline is widened. Complete source, frontend,
CI and exact-serving production replay remain required.

## Next.js dependency repair

The fresh root npm audit flags Next16.4.2 for
[GHSA-mfr8-8qww-v76h](https://github.com/vercel/next.js/security/advisories/GHSA-mfr8-8qww-v76h).
The maintainer describes root-parameter cache disclosure when application code
combines `use cache` with `unstable_cache()`, and identifies16.4.5 as patched.
No matching cache API usage was found in the first-party web source; that
observation does not waive the affected dependency or certify every possible
runtime path. Existing CI's high/critical threshold explains why a moderate
advisory can coexist with passing earlier source checks.

Pin current stable Next16.4.6, reconcile all locked and installed Next/compiler
identities, and retain the actual MIT package attribution shipped by the full
production `node_modules` copy. The version-specific native TLS worker fixture
must exercise the new installed runtime with its original verification and
deadlines. Keep existing license exceptions and TLS policy unchanged.
The targeted install reports zero vulnerabilities; fresh complete security,
platform-installed license, type/build/Docker and deployed workflow evidence
remain necessary. Registry provenance and the original failing audit are
retained separately in the operator's release evidence.

The exact1079-byte MIT license also ships as a public notice and a retained
source copy, independently pinned to upstream commit
`54b876b6b161b0ecda19562eb264bec637e60d6d` and SHA-256
`ee765244e2d59f5234d474f62e0766fa0c8b99af967fdd4c0cb8dcb0c76ea224`.
The public catalog now has12 components/15 notices; the native upload contract
requires74 exact material paths. Existing exception registries are unchanged.

The first native upload replay retained12 passes/one failure from a missed
operator-count consumer (`58 != 57`). After reconciling that separate count,
all13 native discovery, builder-input and exclusion controls pass in205.447s.
The image's independent hash-bound retained-source inventory must also include
the new base-policy MIT material:57 retained files/58 total operator records.
Its original19 reviewed exception entries remain unchanged.

The complete packaging contract also reproduced a pre-existing Windows JSON
decoding error: default cp1252 mangles the Node notice while both original and
current UTF-8 JSON match the unchanged pinned public/source bytes. Make every
text read in that contract explicitly UTF-8. A physical child regression owns
its non-UTF-8 locale, verifies its actual UTF-8 flag is off, and calls the real
Node notice guard; its original failing result retains those runtime facts.
No process-global locale patch, text normalization or fingerprint change is used.

The pinned npm11 producer regenerated the original382-entry lock in a fresh
owned stage. All10 Next/env/compiler identities retain the image's root
layout at16.4.6. The sole unrelated metadata difference removes `dev: true`
from optional Darwin-only `fsevents@2.3.2`; its version, integrity, MIT terms,
platform, engines and install-script flag are unchanged. This exact difference
is retained and reviewed separately from runtime identity changes.

Windows npm-tool preparation retained two incomplete attempts: an unsafe
inherited temporary-directory write scope was refused, and a later private
preparation exceeded its unchanged30-second budget. The fresh private lock
producer did complete under that budget. These are preparation outcomes,
not dependency-audit verdicts or proof of a repaired Windows timing issue.
The web dependency installation follows its canonical `npm ci` path;
the separately changed native TLS fixture still needs actual consumer proof.

## Other acceptance limits

The earlier complete Windows attempt retained803 passes/one failure among804
executed cases: an IP import resume exceeded the unchanged90-second limit.
The remaining3398 native cases and Windows browser inventory were not run.
A later276-case prefix passed, but did not establish the original cause or
complete that Windows gate. Preserve both scopes and the original failure.

The November15 format-generation desktop/phone journeys are deliberately
synthetic and loopback-only. Their source-CI passes do not establish production
model quality, legal accuracy or filing readiness. Do not put those fixtures
into the production inventory or count them as live production acceptance.

## Later production partition failure

The same dispatch's second reporting partition completed9 passes and
two failures, both IP18 saved-view POST assertions at line167 on desktop
and phone. Exact revision00526 request logs show409 for both requests.
The later Notes22 case itself passed; its whole-document guard rejected
the failed partition, which does not erase that row-specific pass.
Calendar readiness and the other completed sibling journeys retain their
own passing evidence. Saved-view quota/name-conflict diagnosis is pending;
do not delete retained data, raise the50-view limit or call later export
assertions verified. Artifact14302073924 retains the full native report.
A second private mobile dependency preparation also exceeded its original
30-second deadline; native TLS consumer proof remains incomplete.

## Completed November17 run and PR624

Production44011493757 completed with three failed browser groups. Batch5 desktop
retains5 passes/2 failures: original contract controls and retained draft PDF
parity. Its mobile invocation was never reached. The source's privacy-preserving
native error redaction retained the failing line but discarded the phase text.
Add a failure annotation containing only the existing local phase label or HTTP
status, preserving error redaction, failure status, every original assertion,
deadline and the read-only record fences. This is diagnostic coverage, not a
fix or successful replay of either reported record.

The independent production database check ran exactly once as
`caseops-release623-read-20261117-01-gcbxh` on the exact serving API image.
PostgreSQL confirmed `transaction_read_only=on`; the transaction rolled back,
with zero business mutations. At06:21UTC, the reporting membership owns exactly50
saved views, meeting the existing quota that refused both IP18 creates.48 names
match the historical automated fixture shape; that shape alone does not grant
deletion authority. No view, draft, contract, attachment or account was changed.
The original contract has its indexed PDF and populated editor metadata. The
draft remains finalized, revision2, on the independently pinned version/body
hash with2 verified citations. Those data facts do not prove the browser paths
or explain their remaining failure. Retain the full exact image/job receipt in
the operator evidence, without publishing private source text or credentials.

PR624 source76c8d0ce passes all3182 frontend tests across311 files, strict web
and E2E compilation, build, native upload, Linux/Windows dependency audits and
mobile source gates. The actual Next page-data Worker TLS test passes with the
new installed runtime, retaining certificate and hostname rejection controls;
the earlier local npm preparation failures remain incomplete local evidence.
This is source/CI proof, not native device or owner sign-in acceptance.

CI44028393260/shard7 retains1481 passes/2 failures/714 explicit skips. Two old
exact configuration assertions omitted the newly routed reference-file constant.
Reconcile all three affected assertions, preserving the exact role guards,
credential/release checks and complete semantic inventory. The complete repaired
workflow module then passes271 cases on Windows in513.82s. New complete CI,
remaining source/native/browser gates and exact-serving QA remain required.

CI's independent shard6 also retains1878 passes/5 failures/186 explicit skips:
five missing-file regressions still asserted the old reporting-role total51.
Retain that negative baseline and require55 total, exactly51 original cases and
exactly4 reference cases before the unchanged missing-file rejection oracle.
The complete repaired evidence and Batch5 wiring modules pass886 cases without
failures/skips on Windows in1349.64s, using a fresh short owned temporary root.
The follow-up's E2E TypeScript and changed API lint also pass. These complete
module results do not complete the earlier interrupted whole Windows gate.

Exact-serving HTTP logs show the retained contract preview and all five draft
PDF requests returned200 during Batch5. That rules out an HTTP refusal for those
specific calls, not a rendering, byte-parity or browser-boundary failure. The
new phase-only diagnostics preserve native privacy redaction and all original
browser assertions so the replay can locate the remaining boundary precisely.

Read-only execution`caseops-release623-read-20261117-02-gxv6v` additionally
verified two old synthetic view candidates against exact filters/columns,
personal ownership, unchanged version1, original53-row committed imports and
creation audits. Exact row backups are retained in operator evidence. Deleting
these existing saved preferences is pending an explicit owner decision; no
candidate, other saved view or legal record has been changed.

## Failure-phase annotation contracts

HEAD48 CI retains3179 frontend passes/3 failures from the old annotation
expectations. The negative version/body drift journeys must now emit exactly
the fixed failure phase while still rejecting before render/export and making
zero writes. Their positive counterpart must still emit exactly one bounded
successful receipt only after all final source/read-only assertions. Two new
independent AST controls reject unbounded phase inputs in both helpers; only
the reviewed literal phase labels and observed HTTP status may be recorded.
The complete focused module passes10 tests, and component/E2E compilation pass.

The complete frozen Windows frontend run on48 retains3170 passes/5 failures and
7 unverified hook-skipped cases across3182 tests/311 files. Source hashes for
every tracked repository input, exact changed paths and empty untracked/dirty
sets remain unchanged. Three failures match CI's annotation expectations; the
other two are a native ZIP/QR/accessibility worker constructor timeout and the
default-client TLS test's existing15-second whole-test timeout. The App source
inventory's native15-second collection timeout prevented its7 later assertions.
These are independent failures; do not attribute them to the annotation change.

A serial maximum-one-worker diagnostic retains64 passes/4 failures/7 unverified
cases across75 tests in176.82s. It does not establish the original cause or clear
the Windows metadata/worker/TLS boundaries. All constructor and test deadlines,
real TLS verification, exact inventories and assertions remain unchanged.
No replacement full Docker gate has started. Native startup profiling and a
complete replacement frontend run remain required before that expensive gate.

## Windows harness follow-up and approved IP18 cleanup

Head6967 completes its five GitHub workflows successfully, including all3184
Linux frontend cases/311files. Its frozen Windows replacement retains3181
passes/three native failures, with unchanged source and deadlines. These are
not a green complete Windows inventory. Subsequent source-bound diagnostics
retain their own failed counts and phases; do not rerun unchanged timing races
or treat system-load observations as a proven historical cause.

Native diagnostics expose sequential OS startup costs, an OpenSSL preparation
timeout and a browser-startup timeout. The candidate uses fresh P-256 test
certificates, finite independent controls, and a test-local cancellation scope
that joins physical child closure. It rejects a late successful exit rather
than accepting a delayed timer. Two cancellation controls and11 owned-view
cleanup controls pass in a39-case run retaining36passes/three failures. The
original8-second Node child,5-second OpenSSL/browser/test and15-second
whole-invocation/test budgets remain unchanged. The offline worker retains all
three real ZIP/QR/accessibility cases and now uses its Playwright-managed
browser and one controlled offline profile; privacy, no-paid headers and actual
rendered-pixel/hostname/CA assertions remain enforced. Complete replacement
source/platform gates remain pending.

Add an independent Windows frontend CI job with the same pinned Node22.23.4,
reviewed host trust setup, component/E2E typechecks, whole coverage command,
coverage thresholds and the existing Windows one-hour whole-suite window. Preserve the Linux web/build
and Docker gates. Native failure stages and trust timing evidence are retained
as synthetic JSON only. A hosted Windows pass must name that actual runner;
it cannot rewrite the earlier workstation failures or certify an unrun Docker
inventory. Current component/E2E compilation passes before the latest small
process-helper refactor and must be replayed on the final source.

The owner explicitly approved removing exactly two old IP18 preferences on
November17. One exact-serving operation at13:52UTC deleted only the reviewed
IDs beginning537c0410 and8646711c. A fresh separate-connection readback proves the
other48 complete saved-view snapshots and the original import/creation-audit
snapshots unchanged. Two canonical SYSTEM audit events document the operation,
with no reporting-user impersonation. Exact backups and execution/log receipts
are retained in operator evidence; the one-use job definition was removed and
its absence verified. No legal record or other saved preference was changed.

The IP18 journey now records only its own201-acknowledged canonical view ID,
removes that one preference in independent cleanup, and rereads the complete
unchanged sibling response. Original workflow failures take precedence over
separately retained cleanup failures. Existing240-second workflow and export
budgets,50-view product limit, API authorization and all UI/CSV/continuation
assertions remain unchanged. Add the helper to the exact builder COPY,
Docker/gcloud allowlists and deploy dirty-input closure. Reconcile independent
closure and inventory tests before freezing a long gate. The next full
frontend inventory is3198cases/312files; the browser journey identities remain
unchanged. New complete CI, native/Docker and exact-serving production QA are
still required before merge/deploy certification or guarded scheduler resume.

The final child timer also deducts synchronous constructor time from its
original absolute budget. Raw bounded synthetic stage lines are retained
inside valid JSON, so a partial final line cannot replace the primary native
failure with a diagnostic decoder exception. These final source changes
supersede the first Windows-CI candidate; no earlier pass is transferred.

The first hosted Windows candidate1a80 retains20 trust passes,8 native loader
passes and11 owned-view cleanup passes. Its three originally failing checks
therefore passed on that actual isolated Windows runner, not the workstation.
The newly added15-minute overall Windows job ceiling interrupted the complete
coverage invocation; no full Windows pass is claimed. The replacement new job
uses the existing3600-second Windows whole-suite window, including its own
provisioning. Existing Linux CI remains15minutes, and every original native,
OpenSSL, per-test, interactive and production deadline remains unchanged.

The first candidate additionally fails the committed-change governance review
and an independent CI trust-action count. The reviewed map adds only the
builder-only/test-cleanup note; canonical render/validate passes, and the
compiled projection differs only in its document fingerprint and projection
identity. Every other AST node, schema/class and policy value is unchanged.
The map change check initially still refuses while that review is uncommitted;
it must pass on the committed replacement. The independent complete workflow
inventory now requires20 setup sites and206 Node commands with all nine trust
outputs. A local mobile inventory invocation is setup-incomplete because the
candidate has no installed mobile parser dependency; fresh complete hosted
source-gate evidence remains required. Native upload-context tests pass all13
cases in591.484s; focused workflow/closure checks pass61cases in137.75s. Correct
API-project Ruff passes; earlier wrong-root lint invocations remain separate
operator evidence and do not authorize unrelated fixture edits.

Head37 Linux frontend retains3196passes/one loader failure: the new persistent
browser fixture's setup hit its original five-second deadline. Preserve the
original non-Windows Playwright page/headless-shell fixture path, while keeping
the separately verified Windows persistent profile. All three real native
cases, zero retries/skips and existing deadlines remain required.

The local head37 complete frontend attempt is interrupted: its control session
is unavailable, its completion receipt/native whole report are absent, and
read-only process inspection finds no remaining candidate-owned runner. Do
not infer a whole pass from the retained prefix. It also records Windows
0xC0000142 process-initialization exits, distinct from actual policy refusal.
No owned orphan browser was proven and no unrelated process was stopped.
The pinned runtime subsequently returns its correct version with exit0; that
diagnostic does not clear the interrupted test run or establish its cause.

Require each startup negative to show the genuine policy message/exit1 or
the exact Node CA-option conflict/exit9. A process that never initialized,
was killed or failed for another reason cannot count as security proof. Add
a regression for the observed initialization code and unrelated refusals;
the next complete frontend inventory is3198cases/312files. Final component,
native/full source, CI, Docker and production replay remain pending.

The complete final local native selection passes40/40 across its three files
in17.64s, including actual CA/hostname/marker checks, three native browser
journeys and the new initialization-failure negative oracle. This focused
result is not a complete frontend or release pass; final source replay follows.
Head37 hosted Windows completes3196passes/one setup failure: the metadata
interceptor requires the candidate-owned API Python executable, which the new
frontend-only runner had not provisioned. Prepare only a stdlib venv with the
already accepted Python3.13.14; retain the original one-second marker fixture
deadline and zero external/Docker requests. Pin the actual observed supported
`windows-2025-vs2026` image label. The separate complete browser-caller inventory
must admit this one Windows job while keeping every old Linux job restricted
to literal ubuntu24.04, rejecting floating/dynamic and cross-platform labels.

The complete workflow replay09 retains258passes/37failures: every failure
uses Windows locale decoding for a UTF-8 workflow source. Read the module's
source/fixture text explicitly as UTF-8; do not remove valid source characters
or hide the earlier failures with a process-wide encoding flag. Replay the
complete295-case two-module inventory on the corrected source.

## November 18 replacement candidate and retained local browser failure

At head9a89d2f6 the complete hosted checks pass, including3198 frontend
tests on both Windows and Linux. The complete local Windows PostgreSQL gate
passes4202 tests and12606 phases in eight naturally completed groups, with
unchanged source, retained native reports and independently verified cleanup.
The original90-second projection case passes in25.263seconds. This current
result does not establish the cause of its earlier latency failure.

The following local desktop shard retains360passes,8 declared skips and one
failure: `app-spine.spec.ts`, "every top-level nav destination renders a real
page". Its Admin heading misses the unchanged15-second assertion while the
workspace loading fallback remains visible. The canonical gate stops there;
the second359-case desktop shard and64-case mobile inventory are unverified
locally. Preserve the full failed gate and original trace, screenshot, video
and error context. Twenty-six finite controlled probes do not reproduce the
stall, including original navigation, delayed font delivery, delayed prefetch
and CPU-throttled controls. Its historical cause remains **Inconclusive**;
these probes are diagnostics, not a replacement release pass.

An adjacent verification defect is independently reproduced: standalone
Playwright API contexts do not inherit a browser fixture's no-paid marker.
All four app-spine constructors now use `createNoPaidApiContext` from the
existing cost-controls helper. A real owned loopback receiver retains the
original missing-marker control and verifies marked successful requests,
failed requests and an explicit retry, payload/authentication preservation,
independent contexts and no automatic retries. Both new unit cases pass.
This is a test-isolation repair; it is **not** a proven cause or repair of the
Admin stall and is not evidence of a paid call in the isolated local stack.
All navigation assertions, ordering, deadlines and production controls remain
unchanged. The expected replacement frontend inventory is3200cases/313files.

The replacement candidate requires complete component/E2E compilation,
dependency and source-closure checks, current-head CI and a fresh full frozen
Docker gate. Complete combined-main CI must precede deployment. Production QA
must then pass on the exact serving release, followed by two later clean,
serial projection executions (second rebuild_count0) and guarded scheduler
resume. Until those proofs exist the release remains **NO-GO** and projection
maintenance remains paused. Earlier failed and interrupted reports stay
retained; no passing prefix or diagnostic probe supersedes a whole gate.

The next b28 candidate is rejected by newly reviewed picomatch advisory data.
Its failed security/mobile checks are retained and its expensive CI was
superseded. The private source backport, exact installer compatibility repair,
native controls, failed attempts and outstanding final gates are recorded in
[the November18 security handoff](picomatch-security-2026-11-18.md).
This does not close the earlier local navigation or production findings.

## November18 Docker04: three new local failures, replacement required

Exact source7c6c02a39c3c82da1866b0a2e138d2c6ea4b20d5 ran from
05:10:04UTC to09:32:40UTC. All4202 PostgreSQL cases/12606 phases passed
naturally in eight groups. Desktop shard1 completed361 passes/eight skips;
shard2 completed351 passes/five skips/three failures. Both native exits,
standard and redacted-native JSON, XML, discovery identities and retained
artifact hashes are preserved. There were no retries or flaky cases.
The64 mobile cases were unexecuted after the second shard rejection. The
outer verifier exited1/completed=false with unchanged source/main and clean
inputs. Exact-project container/volume/network absence is independently
verified. The failed04 source/worktree remains unchanged.

The journal failure is `ram-2026-10-31-watch.spec.ts:359`. Its recorded entry
exists, but after the profile is paused its final original15-second half-
viewport assertion observes ratio0. The profile badge is confirmed immediately
while the old intake count can remain1 until the background read returns0.
This source-level race can remove the obsolete form and shift the entry;
its exact timing in the original viewport failure remains an inference.
The component control proves the stale gate, not the native geometry. Do not
increase the viewport deadline, lower its ratio or add another scroll to hide
the original failure. The candidate obtains the count from the same canonical
actor-visible intake predicate under existing writer/context locks, constructs
the complete status response before commit, and updates count/profile together.
It does not subtract from a partial profile list. Quota-paused profiles retain
their existing eligibility. The API response adds only a nonnegative derived
count; OpenAPI is regenerated, with no migration or storage owner change.

Both `ram-2026-11-07-assistant` journeys fail at fixture validate(IndexError),
before browser assertions. The exact inspected Windows filename is supplied
as __file__ inside Linux, where Path.parents[3] has no such ancestor. Only
after the existing core proves an owned Docker interpreter/database does the
adapter translate virtual main/module filenames to/app/tests/e2e/support.
Host filename/source identity, input bytes, namespace fences, no-model policy
and physical interpreter budget remain unchanged. Actual-wrapper tests retain
three red assertions, including the IndexError, and pass all five after repair.

Current scoped evidence in the operator's merge161001 directory:

- `pr624-docker04-failed-scope05.json`: complete failed-desktop scope,4202
  PostgreSQL pass, retained artifact bytes and exact-project absence. Earlier
  auxiliary reader refusals are separate: report grouping/schema, six native
  title redactions and Windows260-300character retained paths. The reader
  uses extended-length paths and one descriptor per retained byte/hash check;
  it never skips, rewrites, copies or deletes an artifact to obtain acceptance.
- `pr624-file-identity-red01.log` and `-green01.log`: three failures/two
  passes before repair, five passes after. Host and owned Windows/POSIX paths,
  module/main ownership, stdin and compile-before-execution refusal are covered.
- `pr624-intake-count-red01.xml` is invalid fixture setup for its first
  scenario (duplicate bootstrap slug), not a reproduced count defect.
  Corrected `-red02.xml` reaches the missing status count; its rollback hook
  is not yet implemented. `-green01.xml` passes both SQLite scenarios.
- `pr624-browser-focused01.json`: all92 cases in the three complete affected
  frontend files pass. Two cases prove cache success with bounded observer
  notification still pending, deliver inside act and restore/clear the client.
- `pr624-watch-old-ui-control01.json`: the exact old page implementation
  fails both new availability cases (other23 cases excluded from this negative
  control). The fixed page is restored byte-for-byte. This is not a full gate.
- `pr624-watch-complete01.xml`: all68 selected SQLite/API cases and two
  subtests pass, with five explicitly deselected PostgreSQL cases. A fresh,
  short owned Windows temporary root is used. It is not PostgreSQL acceptance.

These are uncommitted repair-candidate observations, not deployed proof or
closure. Verdict remains **Partially fixed / Inconclusive; NO-GO**. Still due:
complete affected PostgreSQL/browser replay, actual component/E2E/mobile
compilation, frozen complete frontend, fresh source/native/security/audits and
exact-head CI/separate alert verdict, full replacement Docker inventory and
cleanup, independent review, combined-main checks, canonical deployment and
full exact-serving production QA. Original Batch5 production failures remain
unresolved until that replay. Projection cadence requires the latest successful
mutation-capable QA plus two later clean serial executions, second rebuild0,
through the guarded resume command; no direct scheduler resume.


## November19 — PR624 merged and deployed; complete production acceptance remains failed

PR624 is merged as `e56437b8672d89e5eeb2a1642be4e759c3c6d2ef`.
Its four combined-main workflows passed all70 jobs; full local Docker07 passed
4204 PostgreSQL cases and792 browser cases (778 passes,14 declared skips).
The three original Windows failures have complete replacement frontend proof:
3210 tests across313 files, with component compilation and source-group order.
Canonical deployment completed November19 at02:47UTC. API00527-9tj and
web00502-zn4 serve100% untagged traffic; public33-case QA and native Android
app-link/compatibility probes passed. These are scoped passes, not full release
certification or private device/Mac sign-in acceptance.

Exact-serving production run44446805801 is **FAILED / NO-GO for complete
certification**. Its13 other completed jobs pass. Independent original-source
native reconciliation validates20 successful invocations:476 cases,459 passes,
17 explicit skips. Ten of the11 production counterparts to main's declared
skips passed; the historical owner-Matter case remains skipped/unverified.
Batch5 desktop has4 passes and3 failures; its phone invocation was never run.
The final evidence job is skipped. Earlier failures remain retained.

| Actual failed desktop journey | Evidence and bounded diagnosis | Current verdict |
| --- | --- | --- |
| AI-TEAM-01 membership/audited lead journey |120046ms timeout; final cleanup location does not identify its original body boundary. Two later observation-only diagnostics pass the body; no historical cause is asserted. | Inconclusive until complete canonical replacement acceptance |
| B5-CON-005/006/009 original contract preview | Original HTTP200/marker precede CDP `response.body()` refusal. Fixed-step diagnostics identify `No data found for resource`; source-byte/pixel checks were not reached. This does not establish a product rendering defect. | Inconclusive; test observer repair under verification |
| BUG001 retained draft PDF parity | Diagnostic confirms every render/download/reload/whole-DTO check precedes final safety refusal. Counters:1 violation,0 mutations,1 login,0 native downloads,0 passive exports. The refused normalized path is exactly `/api/teams/`, the existing tenant team-list read from the Matter header. | Inconclusive; exact read-dependency repair under verification |

Observation-only diagnostic runs44464522436 and44465040030 use a source distinct
from servinge564 and cannot certify a release. Their safe receipts retain no
private response bodies, DOM, media, credentials or tokens. The repair preserves
the exact original UI-triggered preview status/transport marker, single fetch,
retained source size/SHA and visible canvas/pixel assertions. A bounded clone of
that same browser fetch supplies digest metadata in memory when CDP has discarded
the streamed body. It never substitutes a second API GET or changes application
stream bytes. Fifteen observer controls include actual offline-browser proof,
wrong-source bytes, duplicate admission, body bounds, stream failure and the
unchanged ten-second deadline. The draft boundary adds only the marked team-list
read; team writes, other team records and unmarked reads remain refused.

Current focused evidence:45 frontend cases pass, including the real offline
browser; actual web component compilation passes. Original thirteen upload
closure checks pass; the new independent closure control and all complete
replacement/source/CI/deployed desktop+phone gates remain due. Every new unit
and its root helper must be committed and included in the builder COPY closure,
both cloud/context allowlists and the deploy dirty-input fence.

Projection cadence remains **PAUSED**. Document-processing, court-sync and18:00
case-tracking schedules are enabled. Resume requires a successful complete
exact-serving canonical QA run, then two later clean serial maintenance
executions with the second rebuild count0 and the guarded inventory command.
No direct projection resume is allowed. Owner/provider credentials/consents,
Mac/APK sign-in and approved governed-renewal fixture configuration remain
explicitly unverified; no synthetic legal approvals or identity substitutions.

PR625 independent review found an overlapping-observer failure-latch defect in
the first candidate. The controlled negative test retained a complete status
where duplicate refusal must remain failed. The corrected observer preserves
that refusal while the first fetch resolves, never substitutes a second GET,
and cancels only its owned cloned reader. All45 focused cases pass. The native
offline control now uses the public browser-server process handle, verifies
native exit0 and exact owned temporary-profile ENOENT after close. An attempted
cleanup of the earlier synthetic profile was rejected by automatic policy before
execution; that scratch remains retained, not falsely recorded as removed.
