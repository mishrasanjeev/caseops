# Ram Batch 3: Draft Recovery And Client Editing

## October 23 Portable Dependency Closure Correction

First patched source3a61aeae failed Security39848276097 in two jobs/three steps:
native workspace inventory and host/musl license inventories. All identify the
missing required `@img/sharp-wasm32 -> @emnapi/runtime` edge. This is incomplete
lock data,not an unapproved license. No audit/license policy is loosened. Its
full frontend08 completed1879P/242files with stable source,not release GO.
Docker05 had not started; there is no interrupted native replacement to hide.

We accepted npm11's rewrite after inspecting version pins and audit results but
without executing all platform-closure commands first. That missed its deletion
of the previously complete portable runtime/peer entries. A clean isolated
rewrite and an explicit WASM-target rewrite also reproduced the omissions,so
do not claim that an installed Windows node_modules tree alone caused them.
The Sharp WASM package declares no CPU/OS exclusion; its required runtime is
not optional merely because the parent is optional. Inspect actual metadata.

Restore exactly the two unchanged canonical `@emnapi/runtime@1.11.3` and
`@emnapi/core@1.11.1` records from the last complete main lock; verify both
registry integrities,MIT labels and dependency metadata. No other lock records
change in that correction. Native logical npm inventory then exits0. Two new
actual-lock assertions reproduce2F/4P on3a61's graph before repair. Require
their GREEN,physical clean install,strict audit,and real logical/host/pruned-musl
license gates before the next committed full Docker/CI/browser replacement.
Earlier Security and frontend results stay source-bound historical evidence.

## October 23 Security Replacement, Not Deployed

Full canonical local Docker88 completed3376 PostgreSQL passes/10128 phases,
640 browser cases=630passed/10explicit skips,zero retries/errors; all seven
changed journeys pass. Complete frontend1875P and hosted candidate CI05 are
retained. PR554 merged to366686f6 with the identical accepted tree. Main
Security39841340297 then reported critical Next advisories absent from the
earlier audit. Parent stopped the exact owned deployment tree and cancelled
both Cloud Builds before post-build migrations or traffic routing. API/web
remain92f162b4. Original acceptance and cancelled deployment evidence remain
separate; neither is patched-source or production certification.

Next16.4.1 is the official minimal patched16.x release for
GHSA-2464-fhr4-w9xw, GHSA-p3m5-59mp-jv5r and GHSA-673q-mjm6-r5xr.
The patch itself was publishedOctober14; advisory-database entries were
publishedOctober22. Existing sharp0.35.5 does not eliminate the need to patch
the other affected paths. Do not substitute a reachability guess for upgrade.
Also pin matching Vitest/coverage4.1.12 to remove the prior moderate mocker
advisories. No new ESLint stack or unrelated React upgrade is introduced.
The final candidate uses the current stable Next16.4.2,which includes16.4.1
and the vendor's subsequent compiler fixes; registry metadata and the official
October15 release agree. Vitest stays on its explicitly maintained V4 channel
for this security release rather than introducing a separate test-harness major
migration. The earlier GREEN01/audit01 used Next16.4.1 and are component history;
the final16.4.2 graph requires its own install,unit,type,build and whole gates.

`apps/web/lib/dependency-security-20261023.test.ts` asserts both workspace
manifests and every locked Next compiler/runtime and Vitest tool copy. Corrected
RED02 collected four failures on the old graph; GREEN01 passes all four with
the new graph. RED01 used the wrong cwd and collected zero, so it is incomplete,
not a reproduction. npm10's lock-generation Arborist error is retained;
canonical npm11.6.2 generated the new graph without force/legacy-peer flags.
Fresh strict lock audit reports zero findings, not whole-product security proof.

Permanent learning: external advisory data can change while an immutable
candidate is undergoing hours of acceptance. Required current-main Security
must be checked before cloud work and after builds, not inferred from an old
PR scan. Add fail-closed exact-source job checks and regress their complete
existing deploy callers before freezing replacement Docker/CI. Both workbook
production verdicts stay Inconclusive pending actual live replay.

The complete15-module affected deploy/workflow gate now collects1206 cases:
1205passed,one POSIX-only mount assertion skipped on Windows,3617 phases,
exact collection/JUnit/source joins and natural process completion. Ruff and
Bash syntax pass. The new helper rejects current366's failed Security push
and old92's newer failed schedule; its historical successful push's actual
eight-job field validation passes separately,not as current-main admission.
The initial focused run had two invalid synthetic positive timelines; preserve
them and the corrected complete replacement rather than weakening timeline
checks. Final16.4.2 baselineGREEN02,webTSC02,E2ETSC02 and strict audit02 pass.
These are pre-freeze components. Fresh committed full frontend,Docker,CI and
exact-serving production verification remain required.

Official release and advisories:
- https://github.com/vercel/next.js/releases/tag/v16.4.2
- https://github.com/vercel/next.js/releases/tag/v16.4.1
- https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw
- https://github.com/vercel/next.js/security/advisories/GHSA-p3m5-59mp-jv5r
- https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr

## Latest Release Gate Correction

Hosted CI04 at81005522 failed the independent production invocation inventory:
the workflow correctly owned17 roles, but the historical ordered expectation
still listed14. Add the three Batch3 roles without removing native evidence,
order or missing-role checks. The complete evidence, verification-workflow,
trusted-checkout and Batch3 fixture modules now pass324 cases/972 phases,
zero skips, with natural completion and324 JUnit cases. Preserve the original
CI failure and the superseded full Docker03 partial results, not a green claim.
Fresh committed-candidate Docker, CI and deployed acceptance remain required.
The adjacent audit also exposed generic native evidence accepting legitimate
skips for the new mandatory positive roles. Separate exact project/file/title
contracts now require one actual passed zero-retry attempt in both production
capture and independent final validation. Full-envelope RED60F/11P becomes
complete GREEN259P, including71 new cases and33 nested native Node cases.
The old172-case tester union and other roles' legitimate skips are unchanged.
Historical provider UAT explicitly selects its legacy QA project rather than
implicitly inheriting new exact-release projects. Its missing-scope RED is
retained. Independent real Playwright collection now proves the original172
and the separate exact three Batch3 cases (five unit assertions); each bounded
collection keeps the original eight-second limit. The first six-project
combined collection exceeded that bound; split the actual work rather than
raising it. Normal web compilation07 passes. Full final-source gates remain.
The exact prior full frontend run06 passed1874 cases across241 files with
stable whole inputs; its retained duplicate-title multiplicities are not
independent source-case IDs. Neither component result is production evidence.

## Source And Classification

The supplied `CaseOps_Bugs (3).xlsx` contains two populated issues, Bug Sheet
rows2/3. The source hash is
`9343973e38a062d94de391f8c7a32a1e1bf661c82ccf09d2072cd33f0ea58c63`.
Its reported dates say October23 while acquisition is October22; retain that
discrepancy rather than altering the source. BUG001's remarks repeat client-edit
wording and are not an additional draft requirement. No credentials belong in
the summary or repository.

- B3-001 / sourceBUG001: approval with zero verified citations is a required
  legal-safety rejection, not a defect to bypass. The usable recovery workflow
  still needs acceptance: current UI offers known-ineligible approval, gives
  generic recovery copy and does not expose the existing regeneration focus
  input. Classify the safety behavior separately from the UX gap. Current
  citation verification proves catalogue existence, not proposition correctness.
- B3-002 / sourceBUG002: confirmed UI gap. The authorized update API exists,
  but the client profile has no edit control after creation or KYC. Supply a
  prefilled contact/address editor and preserve client identity, KYC evidence,
  matter associations, audit and capability/tenant fences. Changing only the
  creation-form promise is not a fix.

## Reopen Analysis And Our Verification Failures

The first local happy path did not cover a positive draft becoming ineligible
in another tab. The server stayed safe while the browser displayed stale
approval eligibility. That was insufficient coverage, not a reason to weaken
the safety rejection. Reproduce rejected mutation, fresh-read recovery and
subsequent success on both Matter drafting and the adjacent IP pleading path.

We also ran a workflow subset before the complete independent evidence module,
so an obsolete role inventory was discovered late in hosted CI. Runtime Vitest
did not catch unsupported component-test locator options that normal web
TypeScript rejects. These preventable gate-order mistakes caused repeated
full-run replacements. Complete affected contract modules, actual project
collection and normal web compilation must precede the long frozen gate.

Finally, receipt presence alone cannot certify a mandatory positive journey.
Require its exact case and one actual passed attempt, not a skip or expected
failure, without changing legitimate historical skips. Preserve every failed
or interrupted run and never promote an older component pass to current
production acceptance. No persisted automatic Matter reopening is established
by this report; contact editing must not change lifecycle or verified KYC.

## Product Mapping

Drafting: J07/M06, US-017/018/021, FT-027..030, MOD-TS-008/012.
Client management: J12/M11, US-034/035/037,
FT-044..046/049, MOD-TS-009/013. No paid-provider or legal-verification policy
change is authorized. Keep current administration/enquiry release certification
on its frozen source while the independent batch is implemented.

## Required Proof

| ID | Boundary |
| --- | --- |
| B3-DRAFT-01 | Current zero-citation revision keeps approval unavailable with persistent reason and server422 defense. |
| B3-DRAFT-02 | Recovery opens current Matter source context and exposes bounded regeneration focus using the existing contract. |
| B3-DRAFT-03 | Real local deterministic regeneration makes a new version; only the latest verified count enables approval, with reload persistence. |
| B3-DRAFT-04 | Older positive versions cannot authorize a latest zero-citation version. |
| B3-DRAFT-05 | Permissions, finalized/filed/served immutability and provider failures remain fail-closed; no automated paid calls. |
| B3-DRAFT-06 | Desktop and mobile actions fit the available work area; stale/error feedback is actionable. |
| B3-CLIENT-01 | Real existing client can open a prefilled editor with clients:edit. |
| B3-CLIENT-02 | Contact/address update and explicit clearing persist after profile/list reload. |
| B3-CLIENT-03 | Verified KYC evidence, identity, relationships and audits survive contact edits unchanged. |
| B3-CLIENT-04 | Unauthorized/cross-tenant/archived paths remain unavailable or reject without mutation. |
| B3-CLIENT-05 | Validation and failure retain user input and expose the actual safe problem. |
| B3-CLIENT-06 | Desktop/mobile keyboard and visible actions work, without hidden or zero-width controls. |

## Current Verdict

Docker02 at9045 stopped during the web build, before native/browser execution:
13 new component role locators used Playwright's unsupported exact option in
Testing Library. Vitest accepted it at runtime but the web compiler correctly
rejected it. Use anchored accessible-name matchers, retain all failed build
errors, and require the normal web type-check before the replacement Docker
gate. E2E TypeScript alone did not cover these component test inputs. Concurrent
coverage05 will be source-unstable after this correction and cannot certify it.

The adjacent IP pleading workflow had the same rejected-stale-tab recovery gap,
and its approval control treated missing validation as sufficient. The page now
awaits list/deep-link refresh after rejection and requires successful, idle,
positive validation bound to the exact current version. Failed reads remain
unavailable. Component RED8F/5P became13P; the existing IPLF-046B browser journey
now binds the actual422, a single rejected approval, refreshed zero-citation
revision4 and local mock recovery before later filing/serving. It remains one
desktop-collected journey, not a separate mobile or production acceptance.

The clock correction's complete SQLite module passed58 cases. Its PostgreSQL
sibling58 plus full client module47 passed105 cases/315phases/0skips with exact
collection/JUnit joins and stable API source. These are component results, not
the next candidate's full3376-node PostgreSQL gate. The earlier full Docker01
was intentionally interrupted as superseded and cannot certify the replacement.

The next hosted e01 run exposed a fixed-fixture/real-JWT clock mismatch in all
four named-report pagination kinds. Cursor expiry at13:34:56UTC was correctly
enforced; this is not a reason to extend production TTL or disable verification.
All four call failures have complete passing setup/teardown envelopes. A local
four-case RED reproduced them. The test-owned decode clock is now scoped to
report cursors only, with seven new expiry/signature/audience/required-claim
cases imported into the PostgreSQL sibling. No production authentication clock
was changed. The selected fixture calls are serial; its temporary JWT-module
clock patch is process-global and must not be extended to concurrent unrelated
authentication without separate isolation proof. The two CodeQL
redundant-json-import notes were removed at source, not
dismissed. Replacement full CI/Docker admission is still pending.

Adjacent stale-tab approval was separately reproduced after the initial Docker
pass: the server correctly rejected a now-zero-citation current revision, but
the page retained its old positive revision. A new component case failed before
the correction, then the complete three-page selection passed38 cases. Approval
failure now awaits a fresh query read, without replaying the mutation. The same
dated local browser journeys additionally require the actual browser approval
POST to return422 exactly once, current revision3 to replace stale revision2,
no approval audit for that rejection, and later review/finalization at revision6.
Those strengthened browser assertions require a fresh Docker replay; the old
six-case DAB pass is retained only for its earlier code and four-version scope.

The prior retained candidate is PR554/dabd6704. All6 new local Docker journeys
passed on fresh exact-SHA API/web images:4client/2draft,4desktop/2real mobile,
no skips/retries. Native/progress/JSON/JUnit identities reconcile exactly in
`docker-preflight-03/RECONCILIATION.json`. This is scoped browser acceptance,
not the full3369-node canonical local PostgreSQL gate or a deployed outcome.

Complete frontend coverage03 passed1864/1864,0pending, unchanged thresholds,
with all source/configuration readers frozen. Complete workflow/fixture-source
modules passed97/97. Preserve coverage02's1/1864 failure: it read an intermediate
root production configuration (117 instead of116 tester cases) excluded by its
older narrow source guard. The separate Batch3 projects preserve the original
partitions. Full03 includes root configuration/test inputs in its source guard.

CI554 is currently NO-GO for a separate secret-scan harness cleanup regression:
53P/1F, scanning not executed. A successful removal acknowledgement did not
prove the exact owned container was absent. Preserve the original failure and
require a permanent bounded absence fix, real-client regression and fresh green
security checks, never a blind rerun or exclusion.

The cleanup correction now verifies actual absence after every removal result
under one30-second total budget. All40 fake-boundary cases and the two original
real timeout/interruption cases pass;13 actual owned containers were separately
confirmed absent. Preserve the complete native Windows module's56P/11SARIF
permission errors as failed evidence. The replacement Linux Security gate and
actual nonempty tree/history scans are still required; no full scan is claimed.

The production fixture is a clearly labelled synthetic client/Matter inside
test-legal, prepared in5 bounded authenticated writes and read back with its
audit and retained fingerprint. It certifies no real identity, sends no email
and calls no provider. No GBA or existing client/draft was mutated. Its exact
IDs/fingerprint are non-secret CI variables. Production UI acceptance still
requires the admitted serving release; no source-tree or fixture-creation pass
is a live feature pass.

Component acceptance:37 passed across the three client/draft page modules.
Complete client native acceptance:47 passed,141 setup/call/teardown phases,
including9 new PostgreSQL contact cases and9 SQLite siblings; source was stable,
with no skipped cases. Evidence is retained in `outputs/bugs-3-20261022` under
the primary workspace, not committed with confidential runtime artefacts.

Full frontend coverage01 passed1864 cases with unchanged thresholds on the
pre-browser candidate. Actual Docker preflight01 collected6 but did not execute
them because its caller had not created the native reporter directory. Preserve
it as incomplete infrastructure evidence. Replacement preflight02 executed all6:
2passed (mobile contact persistence and independent permission/tenant/archive
negatives),4failed. Desktop contact/fault tests incorrectly used the host's
touchscreen capability to select Playwright tap; select the configured project
hasTouch instead. Both drafting cases exposed the actual20px Matter-context
link target; increase its visible target, keep the24px geometry assertion and
replay the complete six-case inventory. These failures are not green acceptance
and the earlier frontend proof does not cover the subsequent class change.

Bounded read-only production metadata at API92f162b4 shows the screenshot Matter
has a differently titled current draft with5 catalogue citations at revision2
and0 at revision1. Two other retained Appeal Memoranda are accessible, one
finalized with1 citation and one draft with3. They are not the pictured draft
and were not modified. The exact screenshot's failed approval is not recreated
by those records. No automatic Matter reopening is established by that metadata.

Both outcomes remain Inconclusive for deployed acceptance. Source inspection,
fixture tests, a submitted PR and an older release do not prove production.
Record exact intended/collected browser identities, no skips/retries, local
Docker image identity, CI, merged main and the serving API/web revision before
changing the workbook verdict. No silent Matter reopening is established by
this workbook; investigate the persisted lifecycle audit rather than assuming it.
