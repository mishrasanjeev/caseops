# Strict Bug Task List - 2026-04-22

## October 29 PostgreSQL Provenance Work #558

Not fixed. The unchanged API reproduced
CI shard22's820-work failure: the200-record page inspected20,400 provenance
rows under both ordinary and adverse plans. Split its required import/audit
EXISTS into independently correlated lookups, preserving exact tenant/source/
docket proof and manual-date behavior. Original bounds remain unchanged;
supplemental bitmap/proof-branch work and future per-shard full-plan retention
are included. The first candidate still failed both provenance scale checks:
20,400 versus820 and1,396 versus228 (2,741 including bitmap ownership). Its
nineteen-case run completed12passes/two failures, interrupted retained-scale
and leftfour cases unreached. No complete replacement or native pass is inferred.
A second unverified candidate adds the full tenant/source/docket proof index
and scalar point lookups; actual generic plans and eight cross-dialect migration
cases join the unchanged original bounds in the replacement proof closure.
That second candidate still failed the200-row path in allthreeprofiles, while
the retained-width/date-category case passed. The later retained-scale call
timed out before its post-fixture artifact, and sourcefacts remainedunreached.
Candidate three's actual focused run failed all three profiles: 40,400 relation
work and 41,000 owning proof work versus820. Allthreecasephases and the strict
source/runtime/cleanup/output audits completed; the product remains Not fixed.
Candidate four uses a tenant-fixed ordered tuple seek with exact policy outside
the one-row barrier, retaining the unique import-row scalar without its redundant
limit. Candidate four also failed all three actual profiles: 162,400 relation /
163,000 proof work versus820; continuation812/815 stayed within820. Source,
cleanup and typed output audits passed, with33ownedgroups closed. A diagnostic
test change now captures the exact live case's index catalog and separately
estimates index eligibility with transaction-local sort disabled. That is not
a production planner change or a repair. The completed same-case diagnostic
proved the new index present and eligible, with stale estimates choosing the
old scan/sort at8.20 over the ordered index at8.29. Candidate six subsequently failed all three profiles; candidate seven remains
unverified. Two new PostgreSQL/SQLite
wrong-successor/foreign-source cases
extend the required original27identities to29cases/87phases. Actual plans and
the complete same-source replacement remain pending; no limits are increased.
See [actual diagnosis, source scope and open verification](mobile/PG22_PROVENANCE_PLAN_REPAIR_2026-10-29.md).

## October 29 iOS Autolinking Environment #558

Partially fixed; actual Pods/native replay remains pending. Real A8 Expo
prebuild succeeded, but CocoaPods-to-Node autolinking hit four unreviewed Expo
switches. A read-only actual-constructor stop captured their names; the repaired
host admits only their finite source-defined values, preserving all trust,
owner and deadline fences. Focused2/2, tooling381/381 and the full33-module
functional inventory1,264 passed/two existing Windows skips are complete, with
zero failures/cancellations/todos and owned closure. No native pass is inferred.
See [scoped evidence and remaining work](mobile/IOS_POD_ENVIRONMENT_REPAIR_2026-10-29.md).

Current `108a2215` CI separately failed PostgreSQL shard22: the minimal portfolio
export's provenance work exceeded its unchanged `4 * 201 + 16` bound. Retain
116 passes/one failure and the complete uploaded artifact; the test wrote its
EXPLAIN plans outside that artifact's paths, so its exact historical plan was
not recovered. Reproduce the original query and retain default/adverse plans
before accepting a bounded repair. No rerun, index assumption or raised budget
closes this failure.

## October 29 Native Source Observer #558

Partially fixed; measured/native acceptance remains open. The retained 1,262-case
measured run has eight failures and exceeds its raw-output limits. Actual Node24
controller defaults were absent from the exact startup allowlist. An isolated
real-CLI baseline/candidate/changed-flag reproduction passes; the repair retains
unknown-flag fallback and native entry refusal. Reconcile every dependent source
pin and regenerate the bootstrap with exact AST/byte proof. The complete updated
functional inventory passes 1,262/1,264 with exactly two existing Windows skips,
zero failures/cancellations/todos and owned closure. This is not replacement
measured or native evidence. See
[the scoped reproduction and remaining gates](mobile/SOURCE_OBSERVER_REPAIR_2026-10-29.md).

## October 27 Export Release Projection Stop

Dependabot65 separately reports GHSA-xcq7-p3pf-p88h in the optional
OpenTelemetry API1.41.0 lock. The upstream first patch is1.45.1; align its SDK,
exporter and instrumentation0.66b1 dependencies rather than upgrading only
the incompatible API pin. Raise the optional manifest floors and regenerate
only that dependency closure. Keep the unrelated package graph fixed. Regress
manifest/lock floors and the actual patched parser's literal comma split with
large space/tab inputs, plus valid context preservation. Default installs may
honestly skip the optional parser; the all-extras CI run must execute it. No
provider, telemetry activation or audit waiver is involved.

CI40467206921/api7 failed one callback future-timestamp expectation after the
request crossed a second: the header made at now+301 was valid at actual
skew300. Complete native journal/JUnit and controlled two-clock reproduction
are retained. The original test rejects at301 and reaches its worker sentinel
at300; this is a test-clock race, not proof of authentication bypass. Freeze
only the route clock in this test, preserve the production300-second rule and
all seven unauthorized mutations, and cover exact inside/outside boundaries
plus deterministic elapsed-second transitions. The complete callback module
passes 42 cases; its one PostgreSQL case is explicitly skipped without the
database URL and still requires the canonical Docker gate. Docker05 is
incomplete before stack/product tests; its npm install subsequently completed
naturally. CI's complete 35-job result has this sole failed test shard, its
dependent aggregate failure and skipped downstream browser/staging jobs.

Follow-up local frontend02 completed1906 cases:1905 passed/one failed, no skips.
The intake invalid-code case was still showing the initial loading skeleton
before its first button assertion. A separate controlled diagnostic reproduces
that exact state with a successful query and one undelivered observer update;
it is fixture-delivery evidence, not an established production intake defect.
The unchanged seven-case intake module now explicitly delivers that boundary
inside act, preserves its invalid-code/no-API-call assertions, clears its client
and restores the scheduler in finally. No deadline or production code changed.
Full replacement frontend coverage remains required with unmodified thresholds.
Docker04 was deliberately interrupted before source editing; its retained
incremental PG journal has no session completion and is NOT acceptance.

PR565 merged as d1099288b7e61224aa06088437c7a4b207bb43b9 with accepted
Docker tree db59d73f0a3a5875ded6e8055cd6b99186883c1e. Local acceptance is
3425 PostgreSQL passes,1906 frontend passes and630 browser passes/10 skips.
The canonical deploy stopped before routing at the new queue helper's runtime
identity fence. Actual gcloud JSON projection omitted `spec.containers`
because its repeated traversal lacked `[]`; the fake supplied absent fields.
Cloud Tasks was still disabled and no dedicated worker secret existed in the
read-only diagnosis. The old serving f49 remains uncertified after QA40323857026.

Preserved RED: both pre-route and post-route constructor cases fail with the
same runtime-identity error after making the fake honor repeated projection.
Repair name/image/env traversal, retain all runtime/sidecar/ACL/main fences,
audit adjacent projections and replay the full offline deployment rehearsal.
Do not waive the guard or count the stopped attempt as production acceptance.
Issue561 and independent564 remain open until complete replacement release
evidence. The dated SEO log records today's incomplete GSC retry separately.

## October 26 Verification Marker #561

Partially fixed at the local verification-client boundary; production closure
pending. Original source sends Accept without the mandatory no-paid marker.
Retained actual request-construction/certificate/retry/CLI RED:5failed/4passed;
complete repaired module9passed. Local startup/Docker/cold diagnostic RED:5
missing-marker assertions, followed by complete5passed. No fixture error is
counted as a product reproduction. Adjacent independent verification clients
are included without weakening authentication, TLS, deadlines or provider fences.
Required final gates and stableVR561-01..05: bugfix-verification-markers-2026-10-26.md.

Serving29865557and its successful exact QA40256221597 supersede older pending
Batch3 checkpoints below:399passed/18explicit skips,zero failures/retries,
including all51datedIP/Calendar writes and49public cases. That is the earlier
release's evidence, not this new candidate's regression result. The interrupted
native Files0/2 evidence remains failed; its separate recovery is active and
the prior Android23/23receipt is not promoted to its newer HEAD.

## October 25 Native Browser Launch

Actual full-inventory attempts reached successful MFA and authorization but did
not reliably open the app. The fix requires a fresh Open CaseOps gesture after
the grant, with server-owned lifetime, no regrant, duplicate-launch fencing and
query/visibility/pagehide cleanup. Web79 passes; actual replacement native
acceptance is pending. Separate harness defects (ignored resource-ID capability,
disabled button lookup, pull-to-refresh while waiting, unknowable static session
ID and undersized evidence history) have retained diagnoses and regressions.

## October 25 Native Race And Identity Components

Actual device exploration additionally reproduced a signed-out privacy-cover
return defect and an unusable optional-policy/enrolled-user native MFA consent
path. The server fence worked; there was no MFA bypass. Typed recovery and the
existing step-up form now pass web44 and native-auth49 component checks, with
NATIVE-23 covering actual Home/return. Rebuilt Android acceptance is still required;
do not close these from source tests. See the dated native build checkpoint.

Malformed native identity and mutable identity snapshots reproduced in unit
tests before correction. Picker-origin login/lifecycle identity must survive the
OS round trip unchanged; native upload now checks that version under the real
server lock before and after I/O, including close/explicit-reopen races. Private
original downloads now emit no-store including one-byte range responses.
Component and PostgreSQL coverage passed; actual candidate Android journeys are
still pending, not fixed/deployed closure. No Matter-reopening or production
claim follows. See `mobile/MOBILE_BUILD_CHECKPOINT_2026-10-25.md`.

## October 23 IP18 Export Completion Contract

Serving875 is deployed but production39915271013 is NO-GO:414 actual cases,
395 passed/18 explicit skips/one failure, zero retries. Writer51 completed50P/1F.
Notes22 now has its required actual zero-retry pass; the three Batch3 cases were
not reached after the writer failure and remain unverified.

The sole failure is IP18 desktop at the asynchronous export completion check.
Nine exact-revision HTTP200 status reads identify jobdc9a59b7 in that test window.
Its retained job record completed51 rows in10.489420seconds. Mobile completed
in4.091519seconds. The local assertion default is15seconds; production's is10.
No failed export, missing rows or worker exception is established by this run.

Give this operation the existing accepted15-second bound independently of the
unchanged UI defaults, at most16 serial reads and a remaining-time-bounded
request timeout. Reject failed/unknown/wrong-identity or undownloadable results,
assert one original enqueue and retain all51 exact CSV record assertions. Add
deterministic deadline/terminal/transport/privacy coverage. This is a test-contract
repair, not an export-performance or background-worker durability fix. Fresh
Docker, CI and exact-main deployed replay remain required; do not rerun the old
failed release to conceal it. See BUGFIX_IP18_EXPORT_ACCEPTANCE_2026-10-23.md.

## October 23 Notes Production Role Correction

Production API/web now serve `44d3d0be39b8aac3dbd1294ea3927627ef4eb53d`
after PR555, with the identical accepted723 tree. This supersedes the earlier
security-replacement deployment checkpoint below, not its retained failures.
Exact production verification39881030365 is **NO-GO**: tester completed98 cases
(84 passed,13 skipped,one failed,zero retries). Notes22 correctly refused the
generic `caseops-qa` credentials before transport; its mutation guard requires
`test-legal`. No Notes UI failure was established. Other unfinished roles and
the three mandatory Batch3 production journeys remain unverified.

Move that single Notes case to the existing serialized legal-write project,
preserving its hard tenant guard and all172 semantic identities. Independent
partition counts become97/18/6/51, with exact Notes title/project membership
and mandatory positive native capture/validation. The unchanged neighboring
dated families have no additional concrete exclusive-tenant mismatch in the
bounded source audit. Interrupted component evidence is incomplete, not green.
Fresh complete candidate gates, protected merge, canonical deployment and
exact-release Notes execution at1280px/393px with reload/cleanup are required.
The current release stays deployed but uncertified; private-projection cadence
remains held until successful QA and the guarded clean-cadence recovery.

## October 23 Batch 3 Security Replacement

PR554 merged as366686f6 with the identical Docker-accepted88 tree. Full local
acceptance completed3376 PostgreSQL passes/10128 phases and640 browser cases:
630passed/10explicit skips,zero retries/errors; all seven changed journeys pass.
Fresh main Security39841340297 then found critical Next advisories published
to the advisory database during the long gates. Stop the release before routing:
both Cloud Builds are cancelled, parent reaped, API/web remain92f162b4. This
supersedes the earlier pending-candidate descriptions, not the production gaps.

Pin reviewed stable Next16.4.2 and matching Vitest/coverage4.1.12. Four lock regressions
fail on the old graph and pass on the patched graph; strict npm11 audit reports
zero findings locally. These are component results, not patched Docker/CI or
production certification. Add the exact-main required-Security release fence,
then require complete fresh candidate gates and live replay. Both workbook
issues remain Inconclusive on production. No citation block, KYC identity,
provider-cost boundary, scanner policy or audit threshold is weakened.

## October 22 Ram Batch 3

Two populated workbook issues, not an inferred summary total. B3-001 preserves
the correct zero-citation approval block while proving a usable current-version
recovery path. B3-002 restores actual authorized client contact/address editing
after KYC without rewriting verification or relationships. The dated batch brief
owns the full positive/negative/reload/responsive inventory. Both production
verdicts are Inconclusive pending reproduction and exact-serving Playwright;
neither the active administrator release nor an old mocked test closes them.

## October 22 Combined Release Gate Corrections

PRA-10..13 and LEAD-01..05 remain release-pending. Leads081e Docker06 failed
both mobile real journeys on PostgreSQL ENOSPC, with native3276 passing; this
is not completed browser acceptance or a demonstrated product auth defect.
Retain all original failures and replay the full combined candidate after
actual Docker filesystem recovery and new byte/inode admission checks. See
`runbooks/docker-acceptance-storage.md` for the fail-closed guard contract.

Initial combined-head hosted CI also found the compiled data-class projection
stale after the ORM addition. Render and validate the canonical projection,
preserve legal-hold enforcement, and replay the complete affected PostgreSQL
journey plus all current CI. The CodeQL test mutation is moved outside its
assertion; the historical scanner finding is reviewed at an exact synthetic
fixture fingerprint, never a rule-wide/path-wide exclusion. No component fix
or prior source result establishes current release or owner acceptance.

## October 22 Revoked Administrator Cannot Be Re-Invited

Adjacent enhancement PRA-13: Usage, Revenue and account-specific Overview
alerts currently expose only account IDs, unlike the already-named Activity
and Profit views. Add current authoritative names alongside IDs, retaining
legacy strict wire shapes, values, warning variants and pagination. No
production or cross-view visible acceptance is claimed yet.

PRA-10..12 / J14/M14: Not fixed. Serving92f162b4 and candidate081e005b
explicitly reject a revoked report grant with409; the directory lacks Resend
and Delete controls. The owner clarified that recipients never opened their
initial links. Do not invent a delivered-link defect from that incident.
Reproduce pending invite -> revoke -> same-email invite, then prove fresh
password/MFA admission and rejection of every obsolete token/session. Removal
must affect report access only, preserve User, tenant memberships and immutable
audit history, and permit authorized same-email re-admission. Regress active
and never-accepted accounts, expiry/cooldown, repeated commands, actor revocation,
cross-issuer/root/role denials and stale concurrent actions on PostgreSQL.
Original leads release gates remain separate; no new production verdict yet.

Local recovery and named-report code now exists. Complete frontend replacement
1835/1835 passes without skips; original failures remain retained. The selected
backend318P/954phases is qualified by one unselected emulator-test hash change,
not accepted as a clean whole-tree PG gate. Native issuer-boundary4P/12phases
has stable source and exact collection/JUnit joins. Verdict remains Not fixed
on production92f until this combined source is merged, deployed and replayed;
local or synthetic renderer proof must not stand in for real owner acceptance.

## October 22 Unordered Recent Matter Notes

Release-test follow-up: d72's independent web source inventory still expected
115 tester cases rather than the independently collected116 after NOTES22 was
added; total171 must become172 without weakening exact membership. Its complete
web run was1802P1F/1803, not a green gate. The local29-case browser preflight was
28P1F: server-uppercase Matter code made the new fixture's cleanup ownership
check reject its lowercase input. Title and four retained notes agree; the
overwritten body exception and unreached width proofs remain unverified. Correct
the canonical fixture acknowledgement and error preservation, retain both failed
packets, and require complete replacement unit/browser/CI/Docker/deployed gates.

Subsequent complete f83 scoped05 also ended28P1F/29. Its separate receipts prove
four-note admission/persistence/order and strict cleanup/disposal200, but failure
at the first1280px reload body decoder prevented responsive acceptance. The
catch discarded the underlying exception, so malformed server JSON is not
established. The missing initial-body/render barrier makes a prior-response race
plausible, not proven. Preserve all payload/UI/geometry assertions while binding
the new reload request and awaiting response completion; classify body transport
separately from JSON syntax. CodeQL598 is a distinct test-only unused initial
cleanupStage assignment, to correct without suppression. No runtime fix or clean
production claim follows from either failed test-harness run.

J04/M03/US-007..009/FT-011..015: exact f26 CI39696037419 PostgreSQL shard11
collected204 cases with203 passes and one failed call, all setup/teardown passed.
test_default_readers_keep_rich_workspace_dto differed only in notes;14 other DTO
fields agreed. The dependency guard is not a second failing testcase. Source
inspection confirms an unordered relationship feeding UI Recent notes slice(0,3),
which can omit the newest record. This predates the nullable-contact correction;
do not claim that change introduced it. Require a shared created_at DESC,id DESC
contract, preserved full DTO equality, deterministic ties/materialization tests
and actual desktop/mobile reload proof. Current verdict:Not fixed until complete
replacement native/Docker/CI and exact-serving browser acceptance pass.

## October 22 Rolling Public Admission Classification

LEAD-01/J19/M21/US-063: two valid REDs on SQLite and PostgreSQL prove that
successful old-column inserts after migration leave three public records false
and hidden, including converted proof. A second head upgrade does not backfill
them. Raw metadata/outbox bytes, unrelated commercial/malformed-shape exclusions,
current-protocol explicit false, index health and downgrade refusal hold. Earlier
extraction/overlay/database-readiness failures are retained as setup failures,
not reproductions. Correct only the atomic insertion-time compatibility boundary;
never retrofit email eligibility or resurrect later/current-policy exclusions.
Current verdict:Not fixed until the combined correction and full replacement
native/browser/Docker/CI/exact-production gates pass. No production incident or
data repair is inferred from this isolated pre-release reproduction.

## October 22 Retained Enrollment Readback

J14/M14/US-040/042 and J19/M21/US-063: a valid commercial enrollment with a
null contact name makes the founder page reject its entire HTTP200 enrollment
response, hiding a saved public enquiry. Storage and the actual API also permit
a null email; the frontend incorrectly required both fields to be strings.
The newer isolated Leads reader already models nullable contacts. Preserve the
incomplete commercial fixture instead of fabricating contact data or dropping
the row. Align only the retained read schema and show explicit missing labels;
new public submissions still require their validated name and email.

Original full81ec CI:633ended=615P17S1F at the earlier disabled-purpose assertion.
Complete abeb scoped28replay:27P1F, now at the real founder UI after normal fresh
bootstrap/login/me200 and successful pending/zero-attempt API readback. The
snapshot says Unable to load enrollments; later UI/reload/denial steps remain
unverified. Five new real-parser/component regressions reproduce the contract
and sibling loss, alongside nine existing passes. Current verdict:Inconclusive,
candidate correction only; full amended browser/Docker/CI and exact-production
acceptance remain required. No authentication, source, delivery or no-paid fence
was relaxed; original failures and the provenance-only root setup failure remain.

## October 21 Authenticator Setup QR

PRA-09: confirmed missing QR forces a long manual key. The original component
reproduction has one missing-image failure and two passing adjacent tests;
an earlier malformed test-root invocation collected nothing and is not proof.
Root cause: the UI implemented only the manual fallback, and its test explicitly
asserted that no image existed. That assertion preserved the missing phone-scan
journey instead of proving usable enrollment. Replace it with positive decoded
QR acceptance while retaining QR absence for anonymous/challenge sessions.
Fix only enrollment presentation: encode the existing canonical URL locally,
retain the key and preserve MFA. Independent pixel decoding and real local
enrollment must pass desktop/mobile, followed by complete release gates and
exact-serving production checks. Current verdict: Inconclusive, not deployed.

## October 21 Post-Commit Renewal Query

C24's required Security39506605978 fails nine Pillow12.3.0 findings; its
Docker15/CI results remain incomplete and cannot certify a replacement.
Pillow13, the labelled FastEmbed compatibility rebuild and shipped uv0.13.5
need complete fresh audits and actual image/inference regressions. No
workbook item is upgraded from source changes or a resolver-only success.

C23's certifi patch is not whole-image remediation: pinned web Node still
trusts the affected root on reachable HTTPS paths. Its Docker14 run was
deliberately stopped with the partial journals retained and all owned
resources cleaned up. A corrected candidate needs fresh complete gates.

Scoped follow-up: C22 `30d9ba70` passes all four original dated IP portfolio
journeys with a fresh standard-config build, zero skips/retries/errors and
stable source. The release remains NO-GO: Security39490391664 reports the
new critical certifi trust-root advisory GHSA-6q48-6c7w-9gw2. Preserve the
failure, patch the lock and rebuild all release images; do not relabel the
operator-failed Docker12 or superseded Docker13 as acceptance. See the same
evidence document below. No original workbook verdict is upgraded.

**Inconclusive / release NO-GO.** R21 main CI39465871860 collected 623 browser
cases: 605 passed, 17 explicitly skipped and one failed, with no retries. The
failed 393px imported-portfolio journey received 503 from a renewal correction.
Local replay proves the correction committed before a tracker SELECT failed
with SQLite circular CTE references. A five-stage-name diagnostic subsequently
completed all three corrections with HTTP200, but the complete journey then
failed on an offsetless notification timestamp across IST midnight. Neither
diagnostic is a clean full gate or production acceptance. Preserve both failure
artifacts; fix shared tracker/list/count identities and UTC receipt output,
without replaying committed writes or weakening the dated assertion. See
`docs/bugfix-renewal-cte-identity-2026-10-21.md`.

## October 20 Docker Evidence Ordering

**Inconclusive / release NO-GO at source freeze.** Docker10 on C20 `2948b3a6`
completed native 3,252/3,252 and desktop raw 608 passed/10 skipped, but exited 1
at its progress validator; mobile five did not run. The built-in JSON reporter
regroups tests with different fixture pools, while native collection/final
output retains declaration order. All 301 second-group unique identities,
outcomes and complete progress records match; 24 array positions differ.
The correction must use an exact identity join without weakening duplicate,
missing, source/config, outcome, native ordered-inventory or journal fences.
Retain the failed run and require fresh complete acceptance, not a fabricated
completion receipt. Details and scoped proof pointers are in
`docs/bugfix-docker-native-progress-order-2026-10-20.md`. This test-harness
defect neither reopens nor closes any original Ram/IP/Calendar verdict.

## October 20 Historical Worker Gate

Replacement local selections have completed without failures/skips: 330 cases
across five backend modules, 43 additional historical/migration/helper cases,
324 cases across the four CI-contract modules, and fresh whole-web coverage
of 1,740 cases in all 238 files. These inventories overlap and are not summed
as unique coverage. Historical reads retain real absent columns and reject
unexpected access; the report client shares the full-body deadline without
tenant refresh. Source pins and owned cleanup held. The release verdict stays
NO-GO pending fresh full committed CI/Docker and exact-production proof; see
the current evidence pointers in `docs/platform-report-admin-2026-10-20.md`.

**Inconclusive / release NO-GO.** C19 `d8ba7fb0` required CI exposes older-schema
fixtures loading the new User session-revocation column before the historical
worker boundary. A diagnostic replay retains the actual UndefinedColumn
exception; increasing a timeout would conceal the cause. The replacement
preserves the physical historical schema and frozen sources, scopes its read
column compatibility to that isolated engine and rejects unexpected new-field
access. Whole replacement CI/Docker and exact-serving browser proof remain
required. See `docs/platform-report-admin-2026-10-20.md`; no earlier failed
evidence or Ram/IP/Calendar verdict is erased or upgraded.

## October 20 Solo Report And Delegated Console

Local convergence checkpoint: the full dated console journeys passed on
desktop and Pixel 5 in `platform-pw-local-06` (2/2, no skips/retries). They are
host-only deterministic acceptance, not Docker or production proof. Retained
earlier failures led to complete replacement-link, UTC serialization,
invitation replay, MFA-retry and precise-money regressions. The final focused
client/session set is 188/188; backend console112 plus native invitation races2
is 114/114. See the exact scoped evidence and qualifications in
`docs/platform-report-admin-2026-10-20.md`. Fresh complete release gates and
production grant/setup remain open; no Ram historical verdict is upgraded.

**Not fixed on production.** The serving report on `9cf76f2b` explicitly restricts
CompanyType to law_firm and corporate_legal, while segment construction and
HTML/plain-text totals repeat that restriction. Solo accounts are omitted at
multiple layers; adding only a selector option would be incomplete. Dormant
account grouping and delegated report admins are valid enhancements. Parent
contract PRA-01..08 is recorded before implementation under J14/M14/US-040/042.
Require complete category and metric parity, rolling-cutoff evidence, profile-
less owner login audit, protected invitations/reset/MFA/revocation and fresh
desktop/mobile local-Docker plus exact-production browser proof. Do not close
these items from source code, email HTTP acceptance or an earlier candidate's
green checks. No original Ram/IP/Calendar row is upgraded by this extension.

## October 20 Governance Correction Checkpoint

At05:32 UTC C16 `94db8c27` is NO-GO: CI39373277832/job118465761974
failed the data-governance change gate for the new settings, report sender and
scheduler changes. No Docker09 run or production release was started. This
is not a Ruff diagnosis and no sibling outcome is inferred from it.

The local-only correction `a6659663` inventories the actual cross-account
SendGrid disclosure without inventing retention, residency, tenant ACLs or
delivery guarantees. Existing classes and disposition admission remain
unchanged; the new non-SQL inventory remains unreviewed and unadmitted. Existing
generators updated the map view and compiled metadata projection. All84 tests
and252 phases across seven complete governance modules passed, including the
explicit non-admission control. All12 actual committed-HEAD CI governance
commands plus scheduler validation passed against canonical origin/main. Parent
reviewed the full six-file diff, source/artifact pins, genuine red failure and
class-aware exact collection/JUnit identities. These are focused local results,
not replacement CI/Docker or production acceptance. Upcoming C17 requires all
fresh gates. Earlier failed, interrupted and unverified evidence is preserved.

## October 20 Combined Candidate Checkpoint

At 05:07 UTC the upcoming C16 combines Ram's retained fixes with the newly
requested activity-report correction. C15 Docker08 was deliberately stopped
for this scope change: 3226 intended native cases, group01 404 complete passes,
group02 218 passing three-phase cases without session completion, 2604 native
cases unobserved and all621 browser cases unstarted. No failed product phase
was observed. Parent67262 and observer46137 are reaped; both raw2975-file source
comparisons, physical archive and exact-project resource closure passed. The
run is incomplete, never acceptance or carry. C15 whole hosted CI was also
left unreconciled at its final browser job and is not C16 evidence.

The dashboard correction independently passed105 host tests/315 phases with
zero skips; parent reconciled exact collection, JUnit and raw phases. The owner
explicitly authorized removal of only the Gmail global unsubscribe; DELETE204
and subsequent GET200/empty object were verified at04:47:51 UTC. Other
suppression lists were untouched. Four-recipient daily configuration, fresh
combined Docker09, green CI, main merge and exact-release production acceptance
remain pending. Previously partial or inconclusive legal/Calendar rows are not
upgraded. Evidence: `outputs/bugs-l-20261019/docker08-c15-reconciliation-01/`
`final-closure-02/SOURCEHOLD-RELEASE.json` and
`outputs/bugs-l-20261019/activity-report-0730-implementation-01/FINAL-PROOF.json`.

## October 20 Activity Dashboard Email

**Inconclusive for production delivery.** Parent diagnosis identifies a Gmail
global unsubscribe on October 18-20, not a failed report-generation job.
The separate C15-based feature branch implements the requested four-recipient
07:30 IST configuration with bounded validation, private personalizations and
zero task retries. Neither a successful job nor the retained `sent` status
proves inbox delivery. Parent owns the explicitly authorized Gmail-only global
unsubscribe removal; this branch performs no provider/suppression operation.
Review local evidence and later targeted Docker/deployed acceptance separately
from frozen C15 release gates. See `docs/activity-report-0730-2026-10-20.md`.

## October 20 Drive Docker Release Blocker

Later C14 `dd2756f2` remains NO-GO: findings check118440204670 failed on an
unreachable `InterruptedError` handler beneath `OSError`, plus two CodeQL notes
for mixed ctypes imports and an unexplained expected empty-child exception.
Analyzer execution success is not findings closure. Docker08 was not launched.
Reorder the specific interruption handler, keep one lazy import style and
explain the no-descendant case without changing cleanup. New explicit exception
regressions and fresh full gates are required; do not carry C14 acceptance.

**Release NO-GO.** C13 hosted CI/security/CodeQL passed, but full Docker07
completed3226 native passes and then failed one nested Drive process timeout:
desktop603P/1F/10 explicit skips, four mobile cases unstarted. Historical timeout
cause remains unproven; the separate29.621-second cold diagnostic is not a
replacement gate. Parent99137 exited1/reaped and owned source/resources closed.
The narrow test-only replacement promotes existing route checks to real HTTP,
retains six pure security units under owned bounded supervision, and consumes
the existing native per-case reporter. Application/dependency/provider/security
budgets are unchanged. Fresh full gates and serving replay remain required.
See `docs/bugfix-drive-docker-boundary-2026-10-20.md`; do not relabel the failed
gate or Ram's unknown historical evidence as fixed.

## October 20 Dependency Security Release Blocker

**Implemented and focused-tested in replacement source, not fixed in the
serving release; full gates remain pending.** C12 `d7aec233` required Security run39298948341/job118218732094
failed strict pip-audit on locked aiohttp3.14.3. Three distinct upstream
advisories identify3.14.4 as patched. This is a real dependency finding, not
an audit outage, severity-policy exception or demonstrated production exploit.
The direct dependency and Voyage import path both retain the affected package.

The replacement is aiohttp3.14.4 and its required yarl1.25.1 companion, with
only the aiohttp declared floor raised. All other lock records are unchanged.
The complete three-module focused run passed69 cases/207 setup/call/teardown
phases, zero skips/errors, with matching ordered collection and JUnit. It proves
real native SDK/client compatibility and the genuinely shared Secure-cookie
cached-path boundary; the same test bytes retain the old-version cookie RED.
Final-source strict audits covered162 registry-lock packages and138 Windows
default/dev installed packages, zero findings/skips/missing identities. Final
proof SHA2563ead6498e6cce6b7012b70ea3a41483fa5723cea81f685b4bd1225fa6e667592.
This is source-only acceptance, not Linux CI or production acceptance. All
fresh required CI and canonical Docker07 plus exact-serving replay remain required.
No dependency exception, legal-source, provider-cost or release fence changes.
See `docs/bugfix-aiohttp-security-2026-10-20.md`.

C12 canonical Docker06 was operator-superseded after its build and canonical
native collection, before any test phase. All3226 native identities and618
browser cases remain incomplete. Canonical cleanup completed and parent91987
reaped exit1; the missing aggregate journal follows the explicit driver stop,
not a diagnosed product failure. All2970 raw source hashes matched twice and
owned resources/readers closed. Sourcehold release seal:
`362323205a68e7c3ed79cfa67695df39203c7745a6f0553a6882c25c81724dc3`.
Fresh C12 raw CodeQL0/0/0 and current-ref open0 do not clear Security failure.

## October 19 Browser Runner Compatibility

**Implemented in workflow/test source; release NO-GO pending fresh complete
gates.** C11 `a5cc8301` CI39285487552 job118189765017 failed Chromium install
on the observed ubuntu-26.04 image20261012.163.1 with locked Playwright1.60.0.
Hosted browser execution was zero. Completed sibling metadata is33 successful
jobs/one known failure/one skip, Security8/8 successful; separate CodeQL native
SARIF0/0/0 and current-PR open0 do not make the required browser gate pass.

Pin only six browser jobs in CI, production/manual/scheduled verification and
release verification to ubuntu-24.04. Preserve every other workflow field,
dependency, budget, install/runtime/no-paid/source fence and scheduled-step
digest. The guard now discovers all yml/yaml workflows, including shared-step
consumers; real filesystem controls fail under the old three-file loader.
Both complete targeted modules passed92 cases/276 phases, zero skips/errors.
A real Ubuntu24.04.4/Node22.14.0/lockedSDK1.60 Chromium smoke passed with network
none. It predates only the final test-helper delta; immutable runtime inputs
are proven equal, not relabelled as final-tree application acceptance.

The optional five-module Windows audit was deliberately narrowed, not passed:
599 collected,302 passed/one existing skip/one interrupted/295 unexecuted,
909 phases with no failed phase. Its full prefix remains retained. The complete
five-file inventory is now601 after the two filesystem controls and remains
required in fresh full CI. Full replacement canonical acceptance remains mandatory;
there is no coverage waiver or native carry. Focused receipt SHA256:
`a2ec9120655b619d1a4fb7bf7385c4bf7063b96ab8d87c2f99294a100fb2e52d`.

C11 Docker05 was separately operator-superseded:404 complete-group cases/1212
phases plus402 interrupted-group calls/1206 phases without group completion,
2420 unexecuted identities and all618 browser cases unstarted. No failed native
phase was observed. Parent60685 reaped naturally after canonical cleanup;
source/resource/reader closure seal26e82e7e2ce9934d80ce3e5de1a213a7d713399dc6539b3b16565a97649339a5
resolves the earlier pending-reap note. No production release is claimed.

## October 19 Leftover Verification Imports

**Corrected in test source; release NO-GO pending fresh complete gates.**
C10 `1610d300` has three exact-current-ref CodeQL alerts587-589 for unused
`noPaidProviderHeaders` imports after the fixture-header replacement. Actual
SARIF counts are Python0 / JavaScript-TypeScript3 / Actions0. A successful
analysis/check or an empty unscoped alert response did not clear those findings.
The earlier13-file source review missed them; its limited GO cannot override
the actual detector. No runtime exploit or credential exposure is established.

Remove only those three unused names; retain the used IP-controls import,
all five scoped transport fixtures and every no-paid marker. The independent
real TypeScript semantic comparison of C8/C10 covers all13 changed paths and
finds only those three introduced unused diagnostics. Five existing unrelated
baseline diagnostics are recorded, not suppressed or silently called clean.
After the removals,142 units/six modules, both TypeScript checks and13 real
wire cases passed;618 standard discovery identities remain unchanged.

Docker04 was operator-superseded, not passed:1211 completed-group cases/3633
phases,135 further passed calls with an interrupted group and no completion,
1879 unexecuted identities and one partial identity; all618 browser cases were
unstarted. No failed native test phases were observed. The missing aggregate
journal followed the explicit driver stop, not a product reproduction.
Retained final proof SHA256:
`cff0714c0e308f12c0828285fc37ae326a02e073313303a3cf49f0ce32d3a014`.
Focused correction receipt SHA256:
`8f3e81b391be16bddbfbaf17c36e22a99b91ec199a89b60b7980a20c4bf1c2dd`.
Require fresh exact-source CodeQL clearance and full unchanged canonical05;
there is no native carry, detector waiver, main merge or production acceptance.

## October 19 Web Builder Closure Correction

**Implemented in build/test source; release NO-GO.** C9 `862b9cee`
canonical Docker03 failed web TypeScript with TS2307 and its TS7006 cascade:
the real static unit import's public identity helper was absent from the
explicit builder/context closure. Native and browser execution were both zero.
Host typechecks and focused units had not proved the Docker input boundary.
Preserve the full failed proof; do not transfer C8 native results.

Add only the exact helper to the builder COPY and both root ignore allowlists.
The existing standard-discovered closure contract retains runner exclusion,
strict typechecking and narrow direct/transitive inputs. Two complete RED calls
identify the missing input. Replacement22 cases/66 phases, all142 units across
the intended six modules, both TypeScript checks and a real fresh web image
build passed on the captured dirty source. That image used a source fingerprint,
not an invented release SHA. No application/provider/legal behavior changed.

Focused receipt: `outputs/bugs-l-20261019/web-builder-closure-c10-01/RECONCILED.json`,
SHA256 `622c55ca80f9ec77e2206a38b269877688c46033de2e138ad044aea17e264ecc`.
Full canonical replacement, green exact-source CI, main merge, deployment and
exact-serving acceptance remain required. The abandoned alternate supplied no
accepted carry results. See the dated transport postmortem below.

## October 19 Public Identity Transport Correction

**Implemented in test source; release NO-GO pending complete replacement
gates.** C8 hosted CI passed, but local Docker02 completed native3226 cases /
9678 phases and then failed one IP15 1281px setup public-web identity GET.
Desktop results were590 passed /1 error /10 skipped;4 mobile cases did not run.
The application assertions in that failed case were not reached. Preserve the
failed run; its historical reset cause remains Inconclusive.

Actual wire tests prove that IP15's marker-only spec option replaces the
config's loopback close policy. Public identity reads now use credential-free
per-endpoint contexts, the existing origin-scoped headers and fatal exact-SHA
checks with no redirects or retries. New contexts still share a socket pool.
All five workspace consumers preserve their resolved baseURL policy; adjacent
notice/patent readers share the same public helper. No product/API/native,
legal-source, entitlement, dependency or execution-script contract changed.

Parent's final combined E2E/web typechecks passed. The full six-module unit
replacement passed142/142, including the unchanged four inventory assertions
within their existing8-second child bound. Earlier133P/four-unexecuted evidence
and the isolated ETIMEDOUT remain; the original exception was not retained and
no cache-cause conclusion is established. Thirteen real wire regressions pass;
standard collection is618 cases, retaining all original605 identities. These
are not full application or production acceptance. See
`docs/bugfix-ip15-public-identity-transport-2026-10-19.md`.

## October 19 SQL Read Oracle Correction

**Partially fixed in test source / release NO-GO.** C7 `d5ecdab2`
CI39212375169 completed with four failed cases: hydration on SQLite/PostgreSQL,
missing retained-scale initial SQL and missing dense-history category_counts.
All16 specialist plans passed; this is a confirmed SQL-observer defect, not an
established production regression. Actual retained RED proves three typed
SELECTs, the third starting WITH ... AS MATERIALIZED. C8 changes tests only:
extract the exact existing AST guard, preserve its alias, reject nested DML/text,
and repair six adjacent collectors without cap increases. 29 compiler/unit cases,72 focused PostgreSQL cases/216 phases and79
focused SQLite cases/237 phases passed in separate completed runs. These are
not full release acceptance; fresh complete gates remain pending. Keep all failed phases
and operator-superseded C7 Docker evidence. See
`docs/bugfix-sql-read-oracles-2026-10-19.md`; older entries below are history.

## October 19 BUG-008 Import Review

Release **NO-GO**: later source-identical specialist CI failed2109 >2048;
valid ordered PostgreSQL RED confirms2346 >2048. Earlier fixture failures
remain separate, not product reproductions. Candidate canonical active-team
SQL is shared per statement; full replacement gates remain pending. PR546 is
draft. See `docs/bugfix-ip-statement-team-plan-2026-10-19.md`.

**Inconclusive pending committed exact-serving production proof.** Candidate
source implements the bounded review/recovery UX. Mixed historical
missing-context report and confirmed raw-warning UX. Serving9cf already stages
135 valid/three blank rows; the retained committed job created zero and skipped
135 duplicates. Parent desktop/mobile read-only diagnostic confirms raw notes,
not a backend failure or committed acceptance. Separate notes from issues and
refresh saved originals; preserve expiry, context, draft and image fences.
Evidence and adjacent paths: `docs/bugfix-ip-import-recovery-2026-10-19.md`.

## October 19 Specialist Docket Work

**Partially fixed in source / release NO-GO.** Merged401d1615 equals C5, but
Docker15 failed the10k specialist query work390055>2048. The retained plan shows
52 tenant-index loops removing7487 rows per loop. The repair seeks one ordered
PK row before exact-identity/tenant/current policy checks. Complete native25/75
passes, four plans1000-1485, two compile guards pass; full replacement gates and
deployed list acceptance remain pending. Preserve the original failure, the
18P/1F shape baseline and the19P/6F new-test UUID expectation failure separately.
No production verdict is upgraded from scoped results. See
`docs/bugfix-specialist-docket-seek-2026-10-19.md`.

## October 19 CI Correction

C4 `ce938d24` is additionally blocked by CodeQL alert586
(`py/side-effect-in-assert`) in the compile-only history-work oracle. The call
constructs a SQLAlchemy DELETE AST; it does not execute a deletion. Capture the
statement before asserting its rejection, with the same oracle and no scanner
suppression. Docker14 was deliberately stopped after346 passed calls and1,037
passed setup/call/teardown prefix phases; no completion event or native failure
was recorded. The rest of its3,208-case inventory and all605 browser tests are
unverified. Preserve this incomplete run and its operator cancellation attempts.
The replacement candidate still requires fresh complete release gates.

**Scoped correction verified / release NO-GO.** C3ed13138d CI39173686953 failed the
compiled governance projection check and seven retained historical compliance
tail call phases while a new concurrent index waited behind a frozen legacy
transaction. Regenerate the projection and machine-check it before Docker;
install the exact historical fence during the pause, then prove the complete
captured-head upgrade after join without raw-row changes. No migration budget,
negative baseline or 55000 rejection is weakened. Docker13 was operator-stopped
after401 complete cases plus142 prefix cases; its remainder/browser inventory
is incomplete. Fresh affected-file, full Docker/CI/main/live/cadence gates are
required. Serving9cf and both workbooks56/23 remain unchanged. See
`docs/bugfix-document-workspace-snapshot-2026-10-18.md`.

Whole affected module74P/222 phases and genuine baseline02 expected RED2 now
pass their intended contracts, source/cleanup sealed26125c6550f3424c. Actual
CI preflight17/17 and adjacent Docker guard104 controls also pass. Retain the
operator-incomplete first attempt and invalid guarded baseline01; full release
gates and original legal/Calendar/history dependencies remain open.

## October 18 Document Snapshot Failure

C3's required trusted company scope precedes ranking and latest-only
materialization. Its original59 native cases/177 phases passed the assertions
executed, with15 actual plans retained, but the total-work oracle omitted Bitmap
Index Scan children and missed nested opaque TextualSelect DML. Actual typed
helper SQL is read-only; no product mutation is inferred. Reported24,580 was an
undercount, not proof of33,028. Corrected RED6 completed3P/3F across18 phases:
foreign-default work40,998/40,999>33,028. Raw Job work16,387<=16,514, rank
input8,193 and latest16 remain valid. Ordered six-key index EMPTY/RETAINED modes
each completed3P/3F and12 plans (24 plans/36 phases total), insufficient
receipt0a0e6608cf906b80; exact evidence is in the bug doc below. Both LIMIT
variants failed3P/3F. The narrow company/type index passed both six-case timings,
default16,418 and worst adverse24,612<=33,028, exact DTOs preserved. Causal
receipt087c2764140591d9 is not migration or full native acceptance. The separate
native result follows. C2 failures stay retained;
full candidate/main/deployed gates remain required; scoped proof is recorded below.
Serving P is still failed, private cadence PAUSED, manual-IP grant unreplayed
and workbooks56/23 unchanged. Original work budgets are not waived.
Actual101/303 completed82P/19F, including32 migration and10 legacy passes.
Eighteen HTTP setup paths failed under long Windows temp storage; one upload
barrier remains unclassified because its Future exception was not surfaced.
Retain7e79a3fd failed history and require full short-root replay with four
diagnostic controls, unchanged20-second barriers and all original identities.
The complete replacement now passes105/315, zero skips/retries/errors, with
all15 plans,32 migration and10 legacy cases passed. Receipt99f2c417488ae98b
retains the actual frozen source and cleanup. Old101/UNKNOWN history remains;
full Docker, green candidate/main CI and exact-live/cadence proof still gate release.

**Partially fixed in source / NO-GO.** Serving9cf production39143613520 has
385P/1F/18 unverified skips; all50 mandatory dated and47 public cases pass.
The remaining Matter393 index assertion is not a durable-loss diagnosis:
later read-only metadata is correct and its original tuple member is redacted.
Two controlled PostgreSQL HTTP REDs establish torn source/receipt reads under
READ COMMITTED; ten adjacent controls pass. The shared snapshot and IP response
correction still need full replacement native, Docker, CI and live acceptance,
then guarded maintenance/resume. Retain earlier test-assumption failures and
historical evidence; do not replay the manual-IP grant or close legal/consent/
writer/reopening dependencies. See
`docs/bugfix-document-workspace-snapshot-2026-10-18.md`.
The complete scoped replacement passes50 native cases/150 phases, with no
skip/retry/error or source drift; prior failed attempts remain retained. This
is not production closure and does not authorize private-cadence resume.

## October 18 Exact-Serving Tracker And Calendar Failure

**Partially fixed / NO-GO.** PR542 serves `ee351e0c`, but production39042539115
completed383 passed/3 failed/18 explicit skips. The dated partition was47/50
passed, with two first-page tracker failures and one mobile month-chip failure.
Tracker data is present; observed retained-volume requests exceeded the visible
budget. Native1345-record RED measured1.39MB count SQL/29.11seconds execution;
scoped GREEN stages authorized current source facts once, retaining exact counts
and50+1identities at0.63-1.67second HTTP reads. Frontend superseded reads now
receive their cancellation signal. The family API's missing five shared filters
also have seven passing route/validation/OpenAPI cases. Fullfrontend1529passes,
typechecks and build are source-only proof. A later unchanged Calendar2/2 pass does not explain
the original failure. Require complete replacement Docker/CI/live acceptance,
then guarded maintenance/cadence; keep private scheduling paused meanwhile.
Do not upgrade source, consent, verified-date writer or historical Matter gaps.
See `docs/BUGFIX_IP_TRACKER_PRODUCTION_SCALE_2026-10-17.md` for retained proof.

## October 17 IP Calendar Remaining Rows

**Partially fixed / new acceptance pending.** Current main/API/web6af has
production38989524122 and guarded maintenance acceptance; older29d recovery
entries below remain history. Ten open workbook rows overlap source-data,
external Calendar, full hearing/reminder, actual dismissal and tracker
filter/view/export/paging outcomes. New fixes require fresh Docker and deployed
Playwright proof. No genuine reviewed source, external consent or historical
Matter identity may be invented to upgrade a verdict. See
`docs/BUGFIX_IP_CALENDAR_OPEN_ITEMS_2026-10-17.md` for the exact inventory.

## October 17 Private Resume Identity

**Partially fixed / NO-GO.** Serving29d passed production38942699099:
11 required jobs,378 pass/18 skip/zero fail or retry,all42 dated. Both later
maintenance runs were clean (7 candidates;3 then0 rebuilds). Resume65074 still
failed before mutation on two doubled GitHub matrix names; private cadence
remains PAUSED. Candidate exact-role matching and matrix-derived names have
scoped regression proof only, not new whole Docker or production acceptance.
See `docs/bugfix-prod-verification-job-identity-2026-10-17.md`.

## October 16 Production Certification Budget

**Partially fixed / NO-GO.** API/web599defc3 contains merged PR539 with green
full local Docker/current-main gates. Production38888165664's tester native
inventory is complete115=102 pass/13 skip/zero fail or retry, but its whole job
was cancelled for exceeding38 minutes. The remaining production inventory is
not inferred from that pass. The replacement isolates complete catalogue cases
and bounds initial metric-maturity waiting without changing test bodies,
deadlines, retries, provider isolation, grants or stop-proof requirements.
See `docs/bugfix-prod-verification-budget-2026-10-16.md`; LIFE13-01 is unchanged.

## October 15 IP Controls And Renewal Tracker

Seven new populated bug rows and the new renewal specification are under
reproduction, not deployed closure. IP15-001..022 retain source-aware selectors,
container-responsive forms, independent persisted date edits, recurring daily
in-app delivery, idempotence, recovery and lifecycle/access negatives.
See `docs/BUGFIX_IP_RENEWAL_TRACKER_2026-10-15.md`. Earlier ecb acceptance is
baseline only. Historical unidentified Matter reopening remains Inconclusive.

## October 15 Production Replay And Candidate Recovery

**Partially fixed / NO-GO.** API/web0c82fbb0 is deployed and four dated production
document/contract cases pass. In38693611994 the tester still exhausted its budget,
six October13 cases never ran, Review met a legacy-worker epoch change, and Notice
failed after successful indexing because a received reply filter also hid Sent.
The candidate fixes coordination and the scoped filter while preserving shared
search, full inventories, deadlines, provider isolation and source/access fences.
See `docs/bugfix-qa-quiescence-2026-10-15.md`. Exact new production replay remains
required. The grant is already applied once; LIFE13-01 remains Inconclusive.

PR538 CI38716637035 subsequently fails one Calendar browser journey while its
other33 jobs and all current language scans pass. Trace data proves the test
opened all-events rather than overflow, not duplicate hearings. J08/M08 dated
keyboard acceptance now synchronizes modal removal/focus restoration and checks
exact named dialogs and subsets. Fresh joined gates and both widths remain
required; see the candidate document for the retained failure and limits.

## October 15 Worker Environment Acceptance

**Partially fixed / NO-GO.** API/web serve62243583 and the one-time test-legal
manual-IP grant is applied. Production38660900422 retains four index failures,
one Notice indexing failure and an interrupted tester invocation; the six
October13 cases did not run. Real cloud string1 is rejected by integer-Literal
worker settings before claims. The focused strict document/court parser fix
has212 passes and offline actual-image startup proof, not deployed closure.
Fresh joined gates/live replay remain; private cadence stays held. LIFE13-01
is Inconclusive. See `docs/RELEASE_RECOVERY_IP_CALENDAR_2026-10-14.md`.

## October 14 Serving Release Recovery

**Partially fixed / NO-GO.** PR535 merged and API/web serve09d79527, not a
completed certification. Native CI budget exhaustion and Windows cloud argument
transport require fresh joined proof. The grant was not attempted; the discarded
historical command's cause is unknown. LIFE13-01 stays Inconclusive. See
`docs/RELEASE_RECOVERY_IP_CALENDAR_2026-10-14.md`; older checkpoints are history.

## October 13 Canonical Release Checkpoint

October14 dfa full Docker is NO-GO: 2,996 native passes/one work-bound failure,
8,991 phases; all556 browser cases unexecuted. A separately labelled retained
plan isolates repeated global Team scans, not the bounded docket lookup. The
26f97222 shared IP membership-first correction has166 scoped native passes,
144 SQLite passes and60 exact native supplements; max page work1,279 under
unchanged2,048/128/5s bounds. All failed scopes remain retained. Fresh joined
gates, canonical merge, guarded release and live replay are pending; production
is3dbf, the QA grant is unexecuted and historical reopening is Inconclusive.
See `docs/BUGFIX_IP_CALENDAR_2026-10-13.md` for cause and proof limitations.

The new participant-observation correction has114 scoped native passes/342
phases, preserving105 original identities and111 assertions under unchanged
deadlines/GC/security. Real admission and delayed-preflight controls supplement,
not replace, the failed40e8 hosted evidence. Complete amended-source gates and
exact live acceptance remain pending; no deployed closure or QA grant is claimed.

October14 fresh40e8 CI is NO-GO despite19 prerequisite passes and clean secret
scans. The web gate fails two offline readiness fixtures after a required
timezone read; the a446 local correction has a complete204-file/1,323-pass
frontend replacement, not hosted closure. Native shard3 has373 passes and one
missed directed-wait deadline; its final snapshot contains the expected edge,
and its process-wide GC timing is retained without thread/cause overclaim.
Complete deterministic native and final-source release gates remain required.
The independent099 specialist module passes19 cases with measured executor
bounds; that scoped proof does not accept the joined release. Production is
still3dbf and the approved QA grant is unexecuted. See the October13 bug document.

October14 native gate: frozen655 has2,957 native passes and one genuine5s
specialist-list timeout; its556 browser cases did not execute. The parent join,
not its indexed grant probes, materialized the authorized docket set. The
PostgreSQL per-candidate lookup correction preserves all access/lifecycle
predicates and adds actual executor-work proof. Fresh complete native replay,
joined Docker/CI/CodeQL and deployed acceptance remain required; no old proof
transfers. Adjacent ordinary joins remain audit candidates, not demonstrated
defects. The query bound currently targets the reported alternating-visibility
first-page fixture. Production is still3dbf and the QA grant remains unexecuted.

October14 acceptance correction: J08/M08/US-022..025/FT-042..043 and
FT-078..082 retain non-hearing stable ties and actual loaded hearing navigation.
UJ-02/04/26 and IPLF-037 require recipient-readable delivered renewal content,
not only a queued/delivered status. The complete local content RED has two
failures plus two history passes on3f639af0; current read-path closure is pending.
The QA grant remains approved but unexecuted. Canonical audit ownership is
restored with219 scoped passes across seven complete modules; fresh joined
CI/CodeQL/Docker/main/deploy/live gates remain required. Production remains3dbf,
canonical main30e, historical reopening cause Inconclusive. These scoped results
do not certify the final joined release. See the October13 bug document.

The earlier four-PR batch is merged as main
`30e7229368de013123e9a48db2b19230829ddac2`, tree
`88cf5e4c9a59ea8ad721e69cf2efe7784e5081e0`, identical to accepted `51ecde9c`.
Its complete workstation Docker gate has 2,898 native passes and 540 browser
passes plus ten explicit skips, natural exit zero and sealed artifact/cleanup
reconciliation. Candidate CI/Security/CodeQL passed. Main Security and CodeQL
passed; main CI38399405530 also completed successfully. This supersedes earlier merge/local-gate
checkpoints below, not their retained failed evidence. Production is still
`3dbf364d`; no new deployed closure or scheduler resume is claimed.

The October 13 IP/Calendar scope is draft PR535, with subsequent acceptance
corrections under review and fresh whole-candidate gates required. Actual
production preview reproduces native Excel datetime upload 500 on serving
3dbf, request `ip-native-date-prod-7a0ae37155884f198720b24eda3006b8`; native
baseline establishes JSON serialization cause. Scoped corrections remain
Partially fixed pending fresh Docker/full CI and exact-production browser
replay. Historical reopening cause remains Inconclusive. See
`docs/BUGFIX_IP_CALENDAR_2026-10-13.md` and
`docs/RELEASE_PR533_ACCEPTANCE_2026-10-13.md`.

October14 QA readiness checkpoint: the owner approved one non-billable manual-IP
grant for test-legal only under existing M14/US-041 and IP workspace ownership.
Read-only production inspection finds one manual_active grandfathered_free
subscription with no IP override. The one-shot control preserves plan/status,
other entitlements, providers, configuration and GBA; consumed replay cannot
regrant after revocation. No production grant has executed. Scoped operator
coverage has39 SQLite and29 PostgreSQL passes, and the four governance modules
have47 passes. These do not certify the joined release. Fresh final-source
Docker/CI, canonical merge, guarded execution and exact live browser replay
remain required. The historical unidentified reopening remains Inconclusive.
See `docs/runbooks/test-legal-manual-ip-qa-grant.md` for the operator procedure.

## October 13 IP And Calendar Specifications

New owner scope is tracked separately in `docs/BUGFIX_IP_CALENDAR_2026-10-13.md`.
Calendar overflow is a confirmed dead plain-text div; prior coverage checked
presence only. Court metadata/time was omitted and title-only order ignored
the catalog. Corrections have 16 page, 13 API and two real PostgreSQL passes,
but Docker and deployed dated browser acceptance remain pending: **Partially
fixed**, not closed. IP upload's historical transport cause and historical
Matter reopening remain **Inconclusive**. A bounded production read finds seven
recent disposed records still disposed, not proof about every prior incident.
The earlier frozen #533 gate cannot certify new source bytes.

## October 12 Combined Fixes

October 13 passive evidence checkpoint: **Partially fixed / NO-GO**. faff CI's
native teardown correctly rejects a 512-cell GC-recorder overflow. The bounded
observer correction passes 37 complete affected PostgreSQL tests/111 phases,
including the original 514-phase fixture and fail-closed maximum controls.
Skipped initial setup stays incomplete; full fresh CI/Docker and deployed proof
remain required. `docs/RELEASE_PR533_ACCEPTANCE_2026-10-13.md` records evidence.

October 13 PostgreSQL strategy checkpoint: BUG-004 is **Not fixed** on actual
Docker ba, despite green hosted CI and native acceptance. The request returns
500 at the read-only provider boundary after shared authority retrieval emits
unproven SQL forms. Correct those forms, keep caller writes/index bounds/source
rules protected, and replay the actual PostgreSQL and dated browser boundaries.
Three serial cases/four mobile cases remain unexecuted; no deployed closure.
Full evidence: `docs/RELEASE_PR533_ACCEPTANCE_2026-10-13.md`.

The new structured-read correction is **Partially fixed**: 42 real PostgreSQL
and 299 adjacent unit passes cover the actual session/HTTP and protected-write
boundaries. Original dated Docker and exact-release production replay remain
required before any deployed bug closure.

October13 Windows artifact checkpoint: **Partially fixed / NO-GO**. ce hosted
CI is green and fresh Docker native has 2,854 passes, but retention failed after
272 browser passes/one skip; 277 cases remain unexecuted. The real report's
forward-slash Windows path becomes an invalid extended path, not a true reparse
point. Correct normalization and retain all safety fences; 50 offline Windows
controls pass. Complete amended-tree Docker and live replay remain required.
Evidence and preserved failures: `docs/RELEASE_PR533_ACCEPTANCE_2026-10-13.md`.

October13 browser checkpoint: contract mobile navigation is **Not fixed**
in the accepted source/live surface. Complete6fc CI reproduced a393px Playbook
tab covered by the Obligations panel (532 pass/17 skip/one failure). Root and
stronger regression are recorded in `docs/RELEASE_PR533_ACCEPTANCE_2026-10-13.md`.
Current source correction is not closure before full Docker/CI/live replay.

October13 final-candidate checkpoint: **Partially fixed / NO-GO**, not deployed.
The complete dd7 local native run has one global recovery assertion failure;
its full evidence is retained and product attribution is not presumed.
Prepared CI artifact and decoder clarity corrections have focused full-module
proof, not whole-release or live proof. See
`docs/RELEASE_PR533_ACCEPTANCE_2026-10-13.md`; browser acceptance is still unrun.

Replacement-freeze proof: **Partially fixed**, pending full release. Current
runner has51 unit and252 native passes, covering every one of the84 prior
failed identities without shortening stored names. Full hardening scope is
341 passes/one unchanged Windows skip. Bounded future/journal evidence has24
unit and127 selected passes (103 PG-marked/24 pure); the historical blocker cause stays
Inconclusive. All failed evidence remains retained; no deployed-fix closure.

October13 IST: **Partially fixed/NO-GO**, not deployed.4eda's hosted API gates
are green, but a complete native shard has one missing-blocker failure without
its SQL/PID/future evidence; root cause is **Inconclusive**. Local Docker's
first357-case child is complete RED (273/84), with82 path failures and two
Inconclusive observer failures. The second child is interrupted; no browser
execution occurred. Short native runtime/verified long-path retention and
failure-outcome diagnostics are under correction, not accepted. Preserve all
failed/interrupted evidence and require fresh full exact-candidate gates.

Candidate-freeze note: malformed `row_number(1)` has a retained classifier RED
and a narrow zero-argument correction; the complete current four-module replay
passes175 cases/525 phases with zero skips. Both interrupted mixed inventories
(4,329 and1,749 cases) require complete exact-candidate CI/Docker replacement;
their passing prefixes are not accepted. Verdict stays **Partially fixed**.

20:20 UTC: **Partially fixed/NO-GO**, not deployed. All37 hosted failed API
calls are individually reconciled. The authenticated accounting replacement
passes its whole8-case module without weakening the unowned-call fence.
Native identity correction passes126 cases/378 phases and the original
20/500-recipient bounds; the failed observer wrapper remains failed evidence,
separately reconciled from retained COMMIT logs. Driver/deployment scope has
327 passes and one unchanged Windows POSIX-policy skip. Interrupted broad
coverage remains incomplete; fresh full exact-head CI/Docker/live Playwright
must replace it. No fixed product verdict follows from these focused proofs.

19:17 UTC: release remains **Inconclusive/NO-GO**, with no production change.
The shared provenance guard introduced strategy false positives despite561
focused passes. All35 hosted failures and a complete48 local RED are retained;
exact timeout configuration and pure row-number reads now have a narrow source
correction and48 local passes, **Partially fixed** pending all seven consumers
and fresh full gates. Current native compliance timing failure remains
**Inconclusive** for its GC allocation trigger; prompt release preceded a
measured1.8158s GC pause under the still-held transaction. Fixture email identity
is **Partially fixed** pending deterministic native persistence/500-recipient
replay; its constraint failure is not a notification-product reproduction.

18:49 UTC: contract AI remains **Partially fixed** pending full release.
Twenty current native/strict-schema/wire-cap controls and all 134 unit cases
pass; source-only review and byte-identical public OpenAPI are reconciled.
Unknown fields are rejected by all eight private models rather than silently
discarded into empty success. Full amended Docker/CI and exact-live browser
proof remain required; all earlier failures retain their original verdicts.

18:24 UTC: four contract AI actions are **Partially fixed**, not deployed.
Owned transaction-free transport and fresh source/access/policy persistence
passed the prior 474-case focused scope; the subsequent rejected-completion
accounting amendment requires its own fresh native SDK/complete-scope proof.
Two responsive dated browser journeys are standard-discovered, not executed.
Frozen3e full Docker ended with 2,631 passes/two native failures and no browser
run. The original lock-timeout and private-invalidation delay remain
**Inconclusive**; bounded passive timing retains every original assertion and
deadline. Preserve all failed evidence and require fresh exact-source Docker,
green CI, canonical merge and production Playwright before any fixed verdict.

Resumed October 12 IST: court preparation is **Partially fixed** with complete
24-case native proof and independent review; two-SQL getters, zero historical
materialization, original ACL/lifecycle/hash/replay controls, exact unlocked/
locked boundaries and unchanged rich readers pass at1/501 history. The four
tail fixture/head errors have a complete 74-case native replacement, not a
product-code waiver. Old9c local Docker ended RED (2,617 passes/six failures,
no browser execution); retain its complete evidence. Context/privacy/dirty
fences remain Partially fixed until the frozen combined candidate passes full
Docker/CI and exact-production Playwright. No deployed-fix closure yet.

03:32 UTC: context/privacy and dirty-release fencing are **Partially fixed**,
not deployed. Actual native4/static5/Node252 pass; native Git dirty guards pass
242/243 with one original Windows skip. SDK/Docker canary failures retain their
FAKE-only classification. Six frozen-9c PostgreSQL calls failed; browsers were
not run. New complete replacements are mandatory, not an old-green transfer.
Court-import preparation hydration is a real defect, **Partially fixed** by the
narrow bounded-load opt-out; no query-budget increase or historical-load waiver.
Default read contracts and fresh persistence locks must retain positive proof.
Upload admission/worker/request-principal versus system-creator evidence and
future-safe captured-head/ancestry regressions are still under final acceptance.
Guarded production/live Playwright remain required for deployed-fix closure.

02:21 UTC: license packaging remains **Partially fixed**, not deployed. Native
SDK discovery reproduces all 55 operator files missing from Cloud Build input;
the separate narrow filter correction passes three native cases (62 paths,
builder closure, secret/cache exclusions and old-glob negative control).
Git leaf-ignore success was incomplete traversal proof, not the reproduction.
Expanded-fixture count failure remains retained as setup-only evidence. 9c
hosted Security/CodeQL and its actual local image pass; full 9c Docker is still
running and cannot certify the changed child. Fresh child review/full gates,
canonical main, guarded deployment and exact-live Playwright remain required.

01:29 UTC: source-only license/public packaging remain **Partially fixed** pending
actual new image and production replay. The exact-19 managed-SaaS review and
fresh Windows/logical inventories pass without widening base14; Python 139 and
Node 252 complete controls pass. The two web observer-delivery fixtures are
**Partially fixed** for release: deterministic RED and complete final 1,279-case
GREEN retain all UI assertions/deadlines, but do not prove retrospective host
starvation or a production route defect. Thirty current public cases and full
new Docker/musl/CI/main/live acceptance remain required. No deployed-fix claim.

License admission and public notices are **Partially fixed**, source-only.
Owner selected compliance review; exact package acquisition and 128 Python/11
notice unit passes do not replace independent obligations or real musl/browser
release acceptance. Global allowlist remains unchanged. Documents-only batch
recovery is **Partially fixed** pending full release: all 99 CLI/module controls
pass, recovery caps at five and drain retains 1..100. The combined unpublished
migration fork is **Partially fixed**: single-head/lineage/SQLite checks pass,
but fresh PostgreSQL rehearsals and complete replacement acceptance are pending.
Original preflight cause remains **Inconclusive** until exact-production replay.
No deployed-fix claim, budget baseline, provider activation or model promotion.

## October 11 Court-Write Investigation

22:12 UTC: workspace/retention repairs are **Partially fixed**, not deployed.
Independent narrow workspace review verifies 117 cases/351 phases, 107 standard
units and current-guard actual musl R2. Complete 129-identity/163-copy coverage
correctly blocks eight policy entries pending owner disposition. Retention has
38 Windows passes/114 phases, with long-path and both-shell coverage; independent
review, Linux/current full amended acceptance remain required. All earlier
38 failed retention calls are classified and preserved; R11's actual missing
Drive evidence remains open. Ruff/16 static gates pass. Production still serves
3db at 22:08:49 UTC; original preflight cause stays **Inconclusive**, no live fix
or primary-promotion claim. Global processing/retention consent remains pending.

21:47 UTC: license coverage remains **Partially fixed**: the real pruned musl
step reconciles 129 identities/163 copies and exits 1 for eight policy denials;
owner review/replacement is open. A workspace link's actual target/manifest
binding is **Not fixed** in the reviewed 103-case source. R11 browser retention
is **Not fixed**: 28 cleared path attachments include actual Drive process and
seven-unit transcript evidence. All 540 browser outcomes reconcile (530 passes,
10 explicit skips/no failures or retries); 2,344 native passes and final health/
cleanup do not replace missing bytes. Narrow repairs and full amended gates
remain required. Original preflight cause stays **Inconclusive**. No merge,
production fix, Gemini activation or primary-promotion claim.

20:55 UTC license coverage: **Partially fixed**, source-only. Strict nonempty
inventory exposes existing licenses outside the unchanged policy; owner review
or replacement is pending. Host-platform proof is not Alpine/musl runtime
coverage. The CodeQL cleanup independently passes 45 cases/135 phases, but four
actual findings need a new exact-ref scan. Alert 550 is a proven dynamic-fixture
false positive, dismissed with current native evidence; the fixture is retained.
d829 hosted 540 browser identities reconcile (523 pass/17 skips/no retries),
and frozen Docker R11 passes 2,344 native cases/7,032 phases. Docker browsers,
final health and complete amended gates remain pending. Original preflight
latency cause is still **Inconclusive**. Production serves 3db at 20:55 UTC;
no deployed-fix, Gemini activation or primary-promotion claim follows.

20:27 UTC security coverage: **Not fixed**. The successful d829 license job
retained an empty report, and the unqualified alert listing missed five open
PR-ref quality instances. Four test-code findings have source-only cleanup;
the migration fixture has actual four-case hosted native use and requires
independent false-positive review, not deletion. Full license admission and
focused regression are pending in the separate child. d829 hosted native/API
acceptance cannot certify this amendment or its running full Docker/browser.
No production fix, provider activation or primary-promotion claim follows.

19:17 UTC replacement: **Partially fixed** at the test/evidence boundary only.
Complete six-module R4 reports 202 passes and the four old-lock susceptibility
cases still fail intentionally; R3's exact-receipt failure remains retained.
Twenty-eight offline browser controls persist selected sanitized files and
reject private/oversized output, with no retries/skips. Ruff/typecheck/static
gates pass. Full new Docker, hosted uploaded bytes and exact-live acceptance
remain pending; R10's original preflight cause remains **Inconclusive**.
No product closure, global Gemini activation or production deployment claim.
[Evidence](runbooks/AI_BUDGET_RELEASE_2026-10-11.md).

R10 actor-safety fixture and hosted subprocess retention: **Not fixed**.
Eight setup errors reject the independently migrated native database; no body
assertions ran. The complete hosted browser artifact omits three required
diagnostic attachments despite green CI. Guard/retention amendments preserve
security, deadlines and all failed evidence; complete replacement is required.

R10 native failures: **Inconclusive** for product closure. Auth/writer timing
coupling and upload preflight/final-admission mismatch are separately proven
fixture defects. Corrections are unverified; the original preflight latency
cause remains unknown. Retain complete native receipts and all failure phases,
preserve two-second lock/eight-second Event deadlines and require full replay.
No production fix or common-cause claim follows from a corrected fixture.

47 CI header-expression drift: **Not fixed in this release yet**. One complete
API call failed a stale literal assertion; its setup/teardown passed and hosted
browser execution skipped. Explicit helper binding/marker and inherited-config
checks plus negative controls and resolved headers need complete replacement.
No paid transport, deployment or fixed production claim follows from this.

R8's introduced wrapper image-ID defect is reproduced separately; native and
browser tests did not run. Caller controls pass, but product closure remains
Inconclusive pending the full replacement and exact-production journeys.

Latest gate: **Inconclusive** for product/root-cause closure. bf2 CI passed;
its exact Docker R7 native stage passed all 2,301 cases, but five browser cases
failed (two poll subprocesses, selection, Drive isolation, demo replay).
Desktop inventories reconcile 490 passes / five failures / 12 skips; four
mobile cases and final health are unrun. Retain failed evidence. Database
isolation and fixture/transport amendments are not production fixes until
complete amended Docker/CI and exact live journeys pass.
[Current checkpoint](runbooks/AI_BUDGET_RELEASE_2026-10-11.md).

Native CI timeout: **Inconclusive** until the complete capacity replacement
runs. On `9667ad02`, shard 1 passed 571/576 calls before its 12-minute job
timeout, with no completion/JUnit and no reported pytest failure. All other
native shards passed; exact selection covers all 2,301 identities, but the
aggregate failed and hosted browsers skipped. Reduce per-runner work with
eight shards/four-runner peak, preserve timeout/assertions and rerun completely.
Do not call a partial timed-out run a fixed bug or release acceptance.

Native Company lock timeout: **Inconclusive**; no proven deadlock/CPU cause.
Separate broad retained-history hydration under three court-write locks:
**Partially fixed**, intended three-case RED and complete 68-case PostgreSQL
GREEN independently reconciled. Neither hosted green CI nor the removed prior
temporary artifacts certifies production. Preserve the recorded failed Docker
R2 and require fresh complete replacement and dated live browser journeys.
[Investigation](runbooks/MATTER_COURT_WRITE_BOUNDS_2026-10-11.md).

## October 11 Financial Denial Regressions

Fallback amendment remains **Inconclusive / not production-certified** until
new native and end-user acceptance: exact owner-selected 3.5 Flash-Lite, native
strict schema, availability-only recovery and no third transport attempt or
financial/security/safety bypass. R3 was intentionally interrupted for this
scope; retain its incomplete evidence. Global activation and comparative legal
quality remain separate open dependencies, not a reason to call a mock correct.
Independent review additionally reproduced stale authority body/version/access
acceptance and a late credential refresh escaping the shared deadline.
Both are **Inconclusive / not production-certified** until their amendments,
complete replacement inventory and exact live user-visible proof. Local source
corrections must not supersede `67fab368`'s failed CI or interrupted R4.
The amendment captures original retrieval metadata and excerpt hashes, checks
current source bytes under bounded work, retains final-save source locks, and
bounds managed authentication/admission as well as SDK transport. Four intended
metadata RED cases also reproduced stale title/summary/citation/source labels.
These are source corrections; deployed end-user proof is still missing.
Frozen affected/adjacent proof is 762 passed/24 files, including 39 PostgreSQL
cases, zero skips and 2,286 reconciled phases. Verdict remains **Inconclusive**
for deployed end-user behavior until full current release/browser evidence.

**Partially fixed in source; not production-certified.** Independent review
reproduced continued batch submission, deletion of unprocessed ingest inputs,
false source quarantine and exhausted summary transport retries after account
money denial. Candidate amendments distinguish this operational stop from a
corrupt source or ordinary provider failure. Compliance retains deterministic
items while explicitly recording a deferred AI phase. Exploratory contract
transaction-release receipts remain historical, not
final acceptance. Additional corpus finalization retention passed all 154
affected cases; contract typed-denial handling passed all 53 cases after 24
intended RED failures. Contract transaction ownership is unchanged and its
post-provider source/access revalidation work remains a separate open gap.
Earlier harness/setup failures and incomplete Docker evidence remain retained; combined native,
clean-image Docker, amended CI and exact-serving browser acceptance precede
closure. [Evidence](runbooks/AI_BUDGET_RELEASE_2026-10-11.md).

## October 11 Browser Contract Repair

NO-GO. Full5f hosted browser evidence is490 pass/17 unverified skip/five fail,
all512 identities retained. `91486e85` corrects only two specs' exact badge
text and explicit nullable no-body diagnostics; no assertion weakening or
product-logic change. Both reindex sequences still need complete replay.
Docker307 R3's623 passed calls are an interrupted prefix without completion
or JUnit, not full PG acceptance. Fresh corrected-source Docker/CI and exact
production proof remain required; serving3db and open dependencies are
unchanged. [Evidence](bugfix-document-worker-production-2026-10-10.md).

## October 11 Container Input Regression

Candidate `19f12ec8` integrates the reviewed builder/context fix and twenty
regressions. Fresh owned-runtime Main replay completes557 passes/one known
POSIX-only skip, with stable source/dependency hashes. Earlier5f API/PG native
replacement has9,074 unique passes, two opt-in/platform skips and all six
previous PG failures passing. Do not upgrade #527: new-source full Docker/CI
and exact serving-production replay still have not completed.

#527 remains Not fixed on serving `3dbf364d`. `5f4e70a8` completes 528 local
passes/one unverified POSIX skip and fresh zero-result SARIF, but the real
Docker web build fails before PG/browser tests: two new shared helpers and
their import closure are absent from its narrow builder context. Preserve
that failure, repair builder/context admission without suppressing types,
and gate the actual web builder in CI. Require independent frozen-runtime
local replay, complete final-image Docker and exact production acceptance;
source-tree build success is not a deployed fix. See
[evidence and limits](bugfix-document-worker-production-2026-10-10.md).

## October 10 Live Certification Failure

#527 is Not fixed on deployed main `3dbf364d`: the full 341-identity production
run completes 320 passes, 18 unverified skips and three failures. All three
actual mutation responses are 503 with corroborating Company lock timeouts;
historical holder attribution is unknown. Fresh Notice 2/2 is diagnostic only.
Queue/execution repair is in progress; no production closure or cadence resume.
Clean candidate `e0fc0044` passes the complete scoped actor/compliance/governance
r18 inventory (120 cases, 360 phases, zero skips) and all 12 control-plane
commands. Retained-chunk API reindex replacement passes 19 cases; PostgreSQL
interleavings, full Docker, hosted CI/SARIF and live browser proof remain open.
Full evidence, current verdict and required replacement:
[document execution and production certification](bugfix-document-worker-production-2026-10-10.md).

Later draft `1d5eb65b` remains NO-GO: complete hosted API has 6,468 passes,
2,513 unverified skips and seven failures across 8,988 identities. All four
PostgreSQL shards are genuinely interrupted at the unchanged deadline, with
449 identities not started and no final XML/completion. Portable conditional
dependency selection, eight-shard controls and restore-forward downgrade
units pass complete local r20 (76/76); new native rollback/race fixtures,
full Docker, fresh CodeQL note 540 and exact production replay remain open at
that historical checkpoint.

Integrated checkpoint `9b524ab6` completes all 109 changed unit/SQLite cases
and 327 phases without skips/errors; refreshed control-plane commands pass.
Its actual three-language SARIF has zero findings and alert540 is fixed,
not dismissed. Fresh CI38071812851 still has PostgreSQL failures under full
native review; two legacy fixtures stop before the database guard because
their positive deadline precondition is absent. No Docker/live closure follows
unit or static proof. #527 remains Not fixed on serving `3dbf364d`.

## October 10 Summary Gate Repair

Summary browser acceptance remains Inconclusive; #527 remains not fixed in
production. Integrated `a8979a41` passes complete scoped 66-case Python/198-
phase and 42-case Node 22 regressions with exact inventories. Startup batching
and independent cleanup preserve the original workers/assertions/budgets.
Require the complete fresh Docker/browser gate and exact live replay before
closure. [Evidence](bugfix-production-acceptance-and-security-2026-10-09.md).

## October 10 E489 Release Checkpoint

#527 remains **Not fixed in production**; summary acceptance is **Inconclusive**.
Full native Docker PostgreSQL passes 2,235 cases/6,705 phases. Browser partition
one has 252 passes, one known unverified skip, one 600000-ms summary timeout
and secondary cleanup error; 254 identities remain unexecuted. Preserve the
failed reports, all 17 byte-identical media/log copies and the documented
manual owned-worker restoration. A bounded setup/readback and independent
cleanup correction still requires complete replacement and live replay.
Hosted green CI/zero PR SARIF results do not close main's 28 alerts, serving b1,
Google exclusion/Calendar consent or the user-kept dependencies. See
[complete native readback](bugfix-production-acceptance-and-security-2026-10-09.md).

## October 10 Downstream Participant Replacement

Adjacent Company-disable delivery gap: **Partially fixed / not deployed**.
Complete 42-case dual-database baseline retains 12 active passes/30 genuine
disabled-tenant product failures, 126 phases and exact JUnit. Candidate
Complete native claim/disable replacement now passes 115 cases/345 phases and
unchanged SQL caps 394/400 and 7,114/7,600. Complete Company replacement passes
260 cases/780 phases. Separate
worker baseline: 16 identities, four actual late-grant failures, 12 controls;
`20f3f72b` restores the final predicate. Complete replacement on `e1a8182c`
passes 128 cases/384 phases in eight files, zero skips/errors, exact JUnit and
unchanged source. Complete Docker/CI and the discovered Calendar browser on the
exact production revision remain pending. Prior passes are
scoped source checkpoints, not acceptance of these subsequent corrections.

**Partially fixed; not fixed in production / NO-GO.** The candidate fences
actual historical/null creators, elected audit actors, work assignees and
notification recipients before parent persistence without weaker locks or
mutation retries. Combined `ea625cac` passes 75 API cases/225 retained phases,
all 1,234 frontend cases/197 files and a fresh build. Native finalizer and
participant checkpoint passes 102 cases after preserving four SQL-receipt
assertion failures and one long-path setup error. Actual all-SQL accounting
reproduces 17,621 statements for 500 recipients, exceeding 7,600. `bcde1467`
passes 54 SQLite/53 PostgreSQL shared-policy checks with one SQL per batch;
bounded integration now passes the unchanged complete query limits: 394/400
and 7,114/7,600 statements, delivering 20/500 notifications. Separate complete
Main replays pass 69 adjacent-policy, 26 dual-database notification and 42
expanded isolation/nested-query cases. The automatic Calendar candidate's
wrong filter signature reproduces 42 TypeErrors with 14 passing explicit-path
controls, then passes all 56 replacement identities. Retain initial fixture
failures separately; no local gate establishes live OAuth or bug closure.
Complete final native races pass 108 identities/324 phases, exact JUnit and
source identity with clean owned-database teardown. Complete combined backend
integration passes 218 cases/654 phases in 12 files, zero skips.
Docker/CI/main/security/live gates remain open, as do genuine
Google/provider/privacy dependencies. Evidence:
`docs/bugfix-production-acceptance-and-security-2026-10-09.md`.

## October 10 Interrupted Native Evidence

**Partially fixed; not fixed in production / NO-GO.** A real killed Node
reporter now retains completed failure/error packets without writing a finish
receipt; the wrapper preserves discovery and rejects incomplete execution.
Two complete affected files pass 139 cases/417 phases with exact native/JUnit
agreement, including 27 reporter controls. The first 119-case replacement
retains 118 passes/one stale count assertion failure. A later 174-pass gate
overlaps a formatting change and is not frozen-source acceptance. Stable replay,
actual final browser execution and production acceptance remain required.
See `docs/bugfix-production-acceptance-and-security-2026-10-09.md`.

Stable replacement `native-progress-complete-stable-r5.*` has 180 passes,
540 phases and exact JUnit/native inventory agreement; all 32 reporter controls
pass. Real installed Playwright ABI accepts four expected outcomes/two skips,
while its actual failed global setup preserves safe diagnostics and stays
incomplete. Invocation startup cannot certify early errors deferred by the
public adapter. Final Docker/CI/production proof is still pending.

## October 10 Frozen C7 Counterexamples

**Not fixed in production; NO-GO.** `c7dfdc5c` has 1999 complete PostgreSQL
passes, but first Docker browser partition completes 248 passes, one known
unverified skip and two failures out of 251. The other 254 identities did not
run. BUG-042's immediate court-order creation returns 503 from a real worker
downstream compliance versus interactive parent deadlock, independently forced
as native SQLSTATE `40P01`; green indexing-only races missed that later phase.
The FAQ failure is a stale copy contract, not an absent panel. Hosted CI
`37996598078` separately completes 489 passes, one FAQ failure and 15 unverified
skips; its missing structured browser inventory is an evidence gap, not green
coverage. Failed artifacts and the strict failed audit remain retained. Full
participant/provenance ordering repair, corrected FAQ interaction and native
CI evidence need fresh integrated replacement and exact-serving proof.
See `docs/bugfix-production-acceptance-and-security-2026-10-09.md`.

## October 10 Integrated Replacement Evidence

**Not fixed in production.** Integrated `e0004687` completes scoped replacement
coverage: 257 edge/admin API passes, 1,225 frontend passes and 335 native-report/
deploy passes with one explicit POSIX-only Windows skip. Failed baselines are
retained; native cloud topology inspection made no cloud mutation. PR #528
still needs fresh final-head Docker/CI/security, canonical merge, guarded
deployment and every complete formerly failed journey on the serving release.
Current production is `b1d3fb23`. Proof and separate external gaps:
`docs/bugfix-production-acceptance-and-security-2026-10-09.md`.

## October 10 Acceptance Follow-Up

**Not fixed in production.** Frozen `99297e17` has complete positive local
Docker proof (1992 PostgreSQL passes; 495 browser passes/eight known skips),
but CI and adjacent audit expose missing demo page coverage, inherited source
names bypassing 404 and required dependency-guard drift. Forwarded throttle
identity and production native-results retention are separate control repairs.
No source-tree result closes #527 or the five actual-serving failed journeys.
PR #528 remains draft until the repaired head completes fresh acceptance.
See `docs/bugfix-production-acceptance-and-security-2026-10-09.md`.

## October 9 Exact-B1 Acceptance Follow-Up

Serving API/web are `b1d3fb23` (PRs #525/#526), not older candidates below.
Issue #527 remains **Not fixed in production**: run `37909107955` fails
recordal, bulk update, two sign-in journeys and notice upload. Reproduced
auth/provenance and populated invalidation contributors have scoped candidate
repairs, not production closure. All 28 scan findings, pending PRs and external
boundaries: `docs/bugfix-production-acceptance-and-security-2026-10-09.md`.

## October 9 Custom Cursor Counterexample

**Not fixed in production.** PR #525 is merged as `47e3554c`, but main CI
`37889146392` catches 9803-key cursor sorting that its exact-tree Docker and
PR CI did not expose. The deterministic pre-import histogram regression fails
at 10005 family work, then passes the narrow cursor InitPlan repair. No bound,
ACL, timeout or candidate inventory is relaxed. Replacement full gates and
exact-serving Playwright proof are required before closure. Details:
`docs/bugfix-patent-cursor-plan-2026-10-09.md`. Calendar consent stays Inconclusive.

## October 9 Release Blocker

PR #525 / `82ccf412` is not deployed. Its complete Docker PostgreSQL run has
1,930 passes and one patent-list scale failure: the generic plan scans and
sorts 10,001 wide family rows, using 11,437 buffers despite bounded docket
identity work. The replacement now passes 89 complete affected-file cases,
including 48 bounded page/hydration plans, full pagination and warm-identity
races. Fresh full Docker/CI and serving-release proof remain open; green
historical CI cannot close this counterexample. Calendar BUG-003/004 stay
**Inconclusive**, not additional workbook rows or confirmed reopen defects.
See `docs/bugfix-patent-outer-pagination-2026-10-09.md` for retained evidence,
the incomplete earlier Docker runs, required regression and production gates.
The later retained-history replay supersedes that 89-pass checkpoint: global
grant work exceeds the unchanged bound, and a new independently migrated
regression also exposes global family-PK traversal. The canonical IP ACL and
tenant seek repair now passes 112 complete affected-file cases and a separate
deterministic successor case, with 60 bounded page/hydration plans. Fresh
committed-candidate Docker/CI and production replay are still required.

## October 8 Confirmed Follow-Up Causes

**Not fixed** on serving `b20f86bd`: canonical source/projection whitespace
hash disagreement is reproduced and confirmed against bounded read-only
production data. Separate same-actor Company/Membership deadlocks are proven
on real PostgreSQL for both worker and interactive patent producers versus
Matter metadata/disposal. Do not conflate these with benign concurrency or
PR #524's source-version cycle. Evidence, dependency closure and open gates:
`docs/bugfix-private-authority-followup-2026-10-08.md`.
Adjacent confirmed causes include nullable notice visibility, file deletion
after an uncertain commit response, and omitted retained IP bytes in quota.
Local replacements retain their failed baselines and full inventories. A
candidate-only old-upload admission across an explicit dispose/reopen cycle
was reproduced and repaired; this is not proof of automatic case resurrection.
PR #524 and its main CI are green; this follow-up is not yet deployed.

PR #525's shared inbound-helper change also exposed obsolete Gmail and Drive
production callers. Both require outer-owned atomic admission and fresh current
authority, not only a signature adjustment. Gmail's complete six-file 425-case
gate passes; Drive's complete 369-case corrected database replay and five
desktop/mobile browser cases pass locally. Final committed-candidate Docker/CI
and serving-release acceptance remain pending. Candidate `329175eb` additionally
fails patent scale acceptance on 1,010,427 docket rows examined despite a
252-case local pass; keep its unique-identity lookup repair open. These
overlapping scoped results do not certify production. Evidence
and retained failed fixtures are in the follow-up document above.

## October 8 Production Acceptance Follow-Up

PR #523 is deployed as `b20f86bd` on both services after full Docker and green
main CI. Production run `37716144183` exposed a real patent source-save
deadlock (393px journey), not a locator timeout. Verdict: **Not fixed** on
that serving revision. Worker autoflush and adjacent document link/state lock
ordering are under repair. Evidence and gates:
`docs/bugfix-patent-source-deadlock-2026-10-08.md`.
Calendar BUG-003/004 remain **Inconclusive** pending actual Google consent and
positive connection/reload acceptance. Earlier candidate checkpoints below
are historical, not the current deployed identity.

## October 8 Calendar OAuth Workbook In Progress

`CaseOps_Bugs(ll).xlsx` contains exactly two issues, BUG-003/004, both valid
Calendar OAuth bugs. Current production `82a6d932` reproduces the missing
identity scopes and uncaught userinfo failure; the related committed claim
causes bounded in-flight conflicts. Adjacent Outlook, Gmail and Drive paths
are included in the repair. Both verdicts remain **Inconclusive** pending
Docker and exact-release browser proof; this candidate is not yet deployed.
Root causes, prior coverage attribution errors, original failed evidence and
live Google consent boundary: `docs/bugfix-ram08oct-2026.md`.

## September 14 Release Engineering Checkpoint

Recorded 2026-09-14 by the release-engineering handover session; the
Codex-owned queue and the ownership ledger are unchanged. Release verdict for
the programme remains **NO-GO**: BUG-013 and BUG-014 stay **Inconclusive**, the
catalogue inventory is incomplete, and the 25 IP slices are unchanged. This
entry records what was proven about the current candidate, not a closure.

- Candidate `20e34129d58d4218849872cd8c22e76a5b2a631d` (`main`, PR #461) is
  validated but **not deployed**. Production still serves
  `3681517726993b7b59e2ab7bd342b86de729627f` (API `caseops-api-00451-b57`,
  web `caseops-web-00428-77v`). The delta is migration
  `20260913_0001_ip_filing_transactions` plus the IP filing-transaction slice.
- Gates passed on the candidate: CI `34766275625`, Security `34766275620`,
  CodeQL `34766275618` (all `main`, 2026-09-13); nine contract validators and
  both change gates green locally; migration graph single head. Fresh local
  Docker acceptance (`scripts/verify-docker.ps1`, detached worktree, Node
  22.14.0 hash-verified, source fingerprint unchanged across build, browser
  and certification): PostgreSQL + pgvector suite **388 passed, 0 failed**;
  Playwright against Docker + PostgreSQL **191 + 187 + 4 passed, 6 skipped**.
  The six skips are local-inapplicable by design - one provider-gated Pine
  Labs payment link and five exact-deployed-release/production-Matter
  assertions - and are covered by the recurring production workflow instead.
  Retained: `postgres.xml`, `postgres-results.jsonl`, proxy logs.
- Recurring `Prod verification (Playwright)` on the serving release passed
  three times (`34753951907`, `34766559670`, `34780794244`): ram-batch 122
  passed / 7 skipped, statute sources 113/113, patent 23/23. The seven skips
  (BUG-012 x3, BUG-016/018/019/021) and the always-skipped IPLF-037B renewal
  step (no approved fixture IDs configured) are standing `Inconclusive` items.
  The canary-survival property (retained answers, exports, search,
  autocomplete, count, scope discovery all revoked without reopening the
  terminal fixture) is exercised on every run by
  `iplf-066b-private-retrieval-2026-08-31-prod.spec.ts`.
- Every CI failure on `main` since 2026-09-12 was root-caused and is already
  repaired by a later commit: stale release-managed statute rows (`ef809f21`),
  IPLF-063B review detail (`36815177`), BUG-002 structured search latency
  (`439fa1d6`), mid-run release flip (`a710263e`), one pytest attribute
  (`0de9d641`). No recurring signature remains open on `main`.
- `scripts/deploy-prod.sh 20e34129d58d...` was prepared from the validated
  detached worktree and **not executed**: the workstation's automation policy
  refused the production mutation. It is an operator action. Merging PR #462
  first would advance `main` and invalidate this candidate's acceptance;
  deploy `20e34129` first, then merge.
- PR #462 (`claude/release-engineering-20260914`): EH-SGR-06 fail-open
  controls closed with falsified regressions; enterprise-ledger integrity
  repaired and pinned by tests; EH-SGR-05..16 re-verified (nine unchanged,
  three partially fixed, only 06 closes). Codex automated review did not run
  (reviewer usage limit). Its own Docker acceptance is still required before
  it can be a release candidate.
- Not started, with reasons: client-data catalogue acquisition for
  `constitution-india`, `income-tax-1961`, `motor-vehicles-1988` and the
  `cpc-1908` page inventory (official-source work under RAM10-S2, not code);
  BUG-014 court identity (owner clarification outstanding since Sep 10);
  EH-SGR-10 pagination (two web surfaces consume the unbounded list, so a
  server bound alone would silently truncate - a bounded UI+API slice).

## September 10 Workbook In Progress

BUG-013 and BUG-014 remain **Inconclusive** pending complete local Docker and
exact-release production Playwright acceptance. They extend the existing
catalogue and hearing work; they do not create duplicate modules. Fresh
production inspection confirms 17 of 23 Acts have zero selectable provisions,
and three screenshot Matters lack both CNR and court identity. Never enable
unverified provisions or guess a court from party names. Source reconciliation,
journey/test mappings, root causes and release gates are in
`docs/bugfix-ram10sep-2026.md`. Release remains **NO-GO**.

Local checkpoints now include 1,012 integrated frontend tests, 308 combined
hearing/provider tests, 102 catalogue API tests, 12 isolated compiler tests and
289 preservation/governance tests. These overlapping, source-pinned inventories
are not one final release gate. Hearing concurrency follow-ups and the complete
Docker browser candidate still require acceptance; neither workbook issue nor
any of the 25 IP slices is closed by these counts.

## September 09 Execution In Progress

Owner: Codex, with user-authorized parallel implementation agents. Release remains
**NO-GO**. The catalogue and 25 IP slices are not relabelled complete while their
requirements and integrated proof remain outstanding. Provider repair now includes
durable leases, post-transport authorization, conservative spend reservations,
free asynchronous refresh-status recovery and a bounded 18:00-20:00 cadence.
The first PostgreSQL provider gate passed 8 tests. A broader offline provider
run passed 68 tests and exposed one obsolete cost assertion; its correction and
new adjacent-path tests are still being verified. Cold-start changes and tests
are integrated, with three sidecar local HTTP runs below 30 seconds; this is not
production or integrated release-image certification. Exact ownership, milestones
and gates: `docs/ip-implementation/closure-execution-2026-09-09.md`.

## September 08 Workbook And Expanded Candidate (Historical Snapshot)

Owner: Codex. Release verdict: **NO-GO**. BUG-011 remains **Partially fixed**
under the existing BUG-010 catalogue scope (J05/J07, MOD-TS-017, US-046A-D,
IPLF-006). BUG-012 remains **Inconclusive** (J08, MOD-TS-006, FT-078-082).
The two workbook rows do not create duplicate programme work.

The uncommitted runtime fingerprint `f0a13e53a55d6c52d9f8530764777e1d9cadc6c3`
passed fresh Docker acceptance: all 204 PostgreSQL tests and 310 Playwright
tests, with five explicit browser skips (four production-only and one payment
provider). The hearing journeys cover CNR, case-number/court and a supported
record beyond 50 rejected records, with actual dates and reload at three widths.
All 2,941 current source records were checked; this does not prove a complete
catalogue. Source selection, attachment and reload passed at 393/768/1280px.

The full offline API run had 4,276 passes, 200 skips and ten storage-exhaustion
failures/errors. Every affected node passed with corrected executable storage.
Together with PostgreSQL, native-model, Windows and focused supplements, all
4,496 currently collected identities have passing observations. This is composed
evidence, not a clean single current-source full run or release approval.

Open: eight existing Act editions and wider source packs; provider transaction,
durable-claim and crash-recovery repair; whole-tenant nightly throughput;
party-only identity discovery; all 25 unfinished IP slices; production acceptance.
Real-scanner HTTP upload/download, rejection, outage and recovery passed locally,
but cold readiness varied from a failed 30-second gate to a 29.66-second pass.
The earlier 19.36-second result was a scanner-service check, not HTTP upload
proof. The reported 53-second production latency remains open.

Canonical detail, failed attempts, source provenance and next acceptance:
`docs/bugfix-ram08sep-2026.md`. Programme ownership and remaining work:
`docs/ip-implementation/catalogue-ip-completion-2026-09-08.md`.

## Earlier September 08 Expanded Catalogue Checkpoint

Codex owns the expanded BUG-010 / RAM05-STATUTES scope (J05/J07, MOD-TS-017,
US-046A-D, IPLF-006) and all 25 unfinished IP slices. Baseline production is
`5145fb3a4b51b26af116220ff10a7389bde6324d`; older pre-deployment notes below
are historical, not the current serving identity. This new candidate is not
committed, deployed or certified.

The source audit found a real retained-data defect: BNS section 358 omitted
subsection (4) on PDF page 111. The candidate restores it and adds a regression.
BSA's 170 sections and complete certificate Schedule, NI's 155 numbered
identities and retired Schedule, and the Limitation Act's 32 sections plus
complete Schedule are compiled from retained official bytes. Eight source
documents yield 2,049 identities (1,987 verified, 60 retired, two quarantined).
These are source-bundle counts, not fresh database or global-completeness proof.
Fifteen existing Act editions and four retained editions' wider page inventories
remain incomplete. The Income-tax Act, 2025 successor and IP source packs are
additional required scope. Incorrect, missing and incomplete publisher files
are recorded, not admitted as complete law.

A cold-start candidate removes duplicate route cloning and serial scanner/API
initialization while preserving required scanner readiness. Its OpenAPI is
byte-identical to baseline. Focused offline Docker startup/deployment checks
pass 111 tests; full integrated acceptance and production latency remain open.
All 25 IP slice statuses remain unchanged: no new IP workflow is complete in
this checkpoint. Existing family/application/party/priority work must not be
reimplemented just because older notes call it pending.

Authoritative new work map: `docs/ip-implementation/catalogue-ip-completion-2026-09-08.md`.
Source candidates and gaps: `docs/ip-implementation/catalogue-sources-2026-09-08.json`.
`python scripts/audit_statute_catalogue.py --require-complete` must fail while
this inventory is partial. BUG-010 is **Partially fixed**, not closed; the
expanded release verdict is **NO-GO** pending implementation and full acceptance.


September 08 follow-up pre-deployment checkpoint: PR #458's release
`2664ee29` is deployed, but its production certification failed on three stale
contracts and sixteen HTTPS-to-HTTP patent setup redirects. The repaired local
Docker candidate now passes 4,198 API, 192 PostgreSQL, 968 frontend and 275
browser tests. All 194 API skips have exact passing supplements; the five
browser skips remain explicit. All 1,689 statute records and 23 production-shaped
patent journeys pass locally. Committed-source, PR/main CI and exact-production
acceptance remain required before certifying the follow-up release.
See `docs/ip-implementation/evidence/bug010-production-followup-2026-09-08.md`.
Broader catalog and pending IP requirements remain open.

Historical September 08 pre-deployment checkpoint: PR #458 was open. The rebuilt
Docker runtime is `19a33de2b82f6253d42ba6ba5a7ae63dcf6a5d6e`, a source
fingerprint, not a released commit. Its complete browser suite passes 274 tests
with zero failures and five explicitly reconciled skips. All 192 PostgreSQL
tests pass across four independent fresh databases with exact collection/result
reconciliation. The 112 focused API checks and ten dated replay/history browser
journeys pass. The unchanged frontend retains its 968-test coverage proof,
verified against all 449 frontend/configuration hashes. The original 496-row
import and all 1,689 named-Act source records pass on this new runtime.
Complete API coverage passes 4,173 tests and all thresholds. Every one of its
194 skipped identities has an exact passing supplement. All 23 production-shaped
patent/domain journeys and all 43 source-data batches also pass locally.
Final PR/main CI and exact-production acceptance remain separate pending gates;
production is unchanged. The terminal replay fix is published in PR #458;
its later CI-launcher guard passes separately without changing application bytes.
See `ip-implementation/evidence/bug010-source-release-2026-09-07.md` for the
authoritative scoped checkpoint and retained failures. Older dated statuses
below are historical, not the result of this candidate. Wider catalog coverage
and all 25 unfinished IP slices remain open.

Purpose: fail-closed release gate after the Hari and Ram bug-sheet review. No
agent may claim "all bugs fixed" until every item below meets its done-when
criteria and required verification.

Current evidence from 2026-04-22 verification:

- Targeted web Vitest rerun passed: 20/20 tests.
- Targeted Playwright rerun passed: 8/9 tests.
- Remaining confirmed failure: `BUG-011`.
- Backend pytest confidence is reduced because the local API environment is not
  cleanly runnable yet.

## Allowed Closure Labels

- Properly fixed
- Partially fixed
- Not fixed
- Inconclusive

## Ram September 05 Source Reconciliation

Latest BUG-010 checkpoint: Inconclusive, not closed. A complete pinned
numbered-section bundle for the five reported Acts is implemented, with source
history and fail-closed exclusions. Complete current Docker API, PostgreSQL and
browser evidence passes; exact-production acceptance is still pending. Source truth and
scoped-release acceptance are in
`ip-implementation/evidence/bug010-source-release-2026-09-07.md`. The older
zero-verified-section results below remain historical reproduction evidence.

September 07 production-request follow-up: b525 adds bounded ancestry traversal
with local PostgreSQL/HTTP and fresh-image Playwright proof. Production has not
run, so release closure remains Inconclusive. Fresh Docker acceptance exposed a
separate missing release-seed step; the verifier now restores real seed data
after database rollback tests. Its unchanged ten-test replay has nine passes
and BUG-010 still fails: all five reported Acts are present but disabled, with
zero verified sections. Verdict for BUG-010: Not fixed. Original import replay
and all-cell/mapped-field verification pass on b525. Exact results and retained
setup failures are in `ip-implementation/evidence/local-patent-priorities-2026-09-07.md`.

September 07 priority review: three f030 Docker browser journeys passed, and
178 migration-first PostgreSQL checks passed without skips. Screenshot review
then exposed duplicate active navigation and squeezed tablet title rows.
The corrected 7ec22 runtime passes all three priority widths and four mobile
journeys, with all nine priority screenshots inspected. Formal verdict for the
adjacent navigation/title defects: Inconclusive because production acceptance
has not run. The navigation defect reproduced on 21 paths before the shared
most-specific-path correction. The complete 231-test desktop inventory has 225
passing identities, BUG-010 failed and five skipped checks after the explicit
test-only replay. Unsupported Playwright locator options exposed a missing E2E
type gate; it now passes in offline Docker and gates CI/local verification.
The provider deadline test now isolates provider timing, proves health remains
responsive while it is blocked, and rejects late projection persistence; the
complete 29-test module passes. Full evidence and retained test-harness
failures: `ip-implementation/evidence/local-patent-priorities-2026-09-07.md`.
This does not close BUG-010, historical Matter reopening or any production item.

September 07 shared-lock continuation: local PostgreSQL reproduced and fixed a
different-actor patent-party/closure deadlock without weakening lifecycle or
private-generation fences. Complete database and dated browser proof, the
retained initial failures and subsequent test-only corrections are recorded in
`ip-implementation/evidence/local-patent-parties-2026-09-07.md`. This is not
production verification or proof of the cause of the reported historical Matter
reopening. Formal workbook verdicts and the BUG-010 release blocker remain.

September 06 adjacent rollback finding: the local repeated PostgreSQL run
reproduced independently committed index removals surviving an evidence-based
downgrade refusal. Formal verdict: Partially fixed, pending full release and
exact-production verification. All 132 PostgreSQL tests passed on fresh and
retained Docker databases, with clean index health after both runs. Five
downgrade functions now remain in the
enclosing transaction; the regression asserts two consecutive refusals preserve
the exact schema, every index and retained evidence. See
`ip-implementation/codex-takeover-2026-09-06.md` for failed runs and subsequent
proof. This finding does not establish the cause of a historical Matter reopening.

Owner: Codex. Release verdict: **NO-GO**. Full source, journey and test mapping:
`docs/bugfix-ram05sep-2026.md`. One populated workbook bug, nine overlapping
bulk error categories and one E-Case enhancement were supplied. The copied
four-bug summary is not the source inventory. All 496 original import rows
were recovered with tenant-scoped read-only access; no production commit ran.

| Item | Formal verdict | Evidence / remaining work |
| --- | --- | --- |
| BUG-010 statute completeness | Not fixed | Production API and browser reproduce 22 disabled Acts; 1 of 3,393 provisions verified. Five reported Acts remain without selectable sections. Complete source data and attachment/reload acceptance before closure. |
| Bulk owner/team/lawyer sample assignments | Inconclusive | Invalid identities correctly rejected. CSV/XLSX sample assignments corrected locally; template round-trip and dated browser tests added. Exact-production proof pending. |
| Bulk duplicate code/case/title-client suppression | Inconclusive | Only admitted rows now claim identities; invalid-first, skipped-existing chain, valid sibling, commit and replay regressions pass locally. Production pending. |
| Bulk/manual catalog context and uncatalogued context retention | Inconclusive | Explicit-ID and category/name conflicts rejected; missing catalog metadata cannot accept invented manual values; uncatalogued context preserved. Expanded 90-test Docker subset and final dated browser workflows pass. Production proof pending. |
| Bulk ambiguous/unsupported original courts | Not fixed | Three official-source qualified aliases added locally and round-trip tested. Remaining ambiguous/private/city-only values still need factual context. Do not guess districts or convert a private arbitrator into a registry court. |
| Saved import original-source revalidation | Inconclusive | Confirmation and interrupted recovery now re-resolve original cells and reject withdrawn/retargeted court identities; forced-interleaving tests pass. Production pending. |
| Billing profile stale-list race | Inconclusive | Initial-load gating, server-result caching, saved-value hydration and dirty-only PATCH implemented for profiles/rates. 831 frontend tests and final held-read browser journey pass. Production proof pending. |
| Outside-counsel stale lists | Inconclusive | Upload, invoice and time-entry writes cancel older list requests and await fresh data. Forced-interleaving unit/browser workflows and persisted reload pass locally. Production proof pending. |
| Empty import admission | Inconclusive | This batch briefly bypassed the no-work guard for all-invalid/duplicate files. Corrected and caught by existing API plus new browser disabled-action/direct-400 regressions. Production proof pending. |
| Local proxy cancellation | Inconclusive | Reproduced retained upstream on browser response closure. Four Windows and four Docker transport tests pass; dated browser replay has no proxy errors. Test-harness repair, not a production API claim. |
| Temporary E-Case Number | Inconclusive | Additive model/migration/API/workspace/UI/search/bulk implementation. Mobile and desktop dated local journeys pass. PostgreSQL interrupted-index recovery and restore-forward checks pass. No deployment yet. |
| Historical Matter reopening | Inconclusive | Bounded September 1-5 tester audit returned no disposal/reopen events. Specific affected Matter/time still needed; local lifecycle guards remain intact and are browser-tested. |

The dated spec is registered in local discovery and both relevant production
config selectors. The final expanded 90-test API subset passes; complete API
closure passed 3,966 with zero failures and 140 explicitly retained skips.
Final fresh Docker acceptance passed 122 PostgreSQL
and 196 browser tests, failed only BUG-010 and skipped five. The original
496-row local Ram replay created 391 valid Matters and verified all 28
importable fields plus all 10,416 retained original cells. No item above is
production-closed. Thirteen regression lessons are persisted in both AGENTS
instruction files; full evidence is in the batch report.

## CaseOps automatic next-hearing sync - Ram 2026-09-04

Source document:
`C:\Users\mishr\Downloads\CaseOps_AI_Auto_Next_Hearing_Date_Sync.docx`.
Permanent learning record:
`docs/BUG_REOPEN_LEARNINGS_2026-09-04_AUTO_NEXT_HEARING_SYNC.md`.

| ID | Classification | Formal verdict | Evidence / action |
| --- | --- | --- | --- |
| ENH-001 | Valid CaseOps enhancement; the source contains one requirements brief, not a populated bug list | `Inconclusive` until exact-main production proof | Implements bounded 18:00 IST automatic sync for eligible old and new matters, with the existing next-hearing field as the only write target and Sync Now using the same service. Dated regression: `tests/e2e/ram-2026-09-04-bugs.spec.ts`. |
| ADJ-MATCH-001 | Valid systemic correctness defect | `Partially fixed` pending exact-main production proof | First-result acceptance is replaced by exact unique CNR or exact case-number-plus-court validation; not-found, ambiguity, mismatch, invented identifiers, and past dates cannot update a matter. |
| ADJ-STATE-001 | Valid systemic state defect | `Partially fixed` pending exact-main production proof | Provider failure now retains the last valid date; confirmed absence is distinct and may clear only an unlocked provider-managed date. Disposed matters remain excluded and lifecycle fields are unchanged. |
| ADJ-CONCURRENCY-001 | Valid systemic concurrency defect | `Partially fixed` pending exact-main production proof | Tenant/matter advisory locking plus partial unique database indexes prevent duplicate bookmarks and duplicate running operations; repeated/concurrent refresh is typed and idempotent. |
| ADJ-IDENTITY-001 | Valid PostgreSQL identity-convergence defect found by full Docker acceptance | `Partially fixed` pending exact-main production proof | A case-number row that learns an already-canonical CNR previously violated the tracked-case unique key and left the poll session rollback-only. Active references now converge onto the locked canonical row, the retired row remains hashed lineage, and a per-case savepoint prevents one constraint failure from crashing the multi-tenant run. |
| ADJ-GATE-001 | Valid unnecessary workflow gate | `Partially fixed` pending exact-main production proof | A verified authoritative provider result writes directly under machine rules. No human/Claude approval route is introduced; a manual date lock remains a fail-closed data-ownership boundary, not an approval gate. |

Reopen analysis: no evidence shows that this feature automatically reopened a
persisted Matter. The prior weakness was presentational and operational: a
loose or stale next-hearing update could make a terminal or old matter appear
current. The fix does not weaken the dedicated, audited `Disposed -> Intake`
lifecycle transition. It excludes terminal matters and asserts status,
`is_active`, lifecycle version, and final reloaded state around refreshes.

Closure requires the final commit to pass PostgreSQL migration/concurrency
tests, the complete Docker inventory, the dated local Playwright journey,
canonical CI, exact deployed API/web release identities, and the dated
production surface test. These rows deliberately remain below `Properly fixed`
until the deployed proof exists.

## Forbidden Claim Patterns

- Claiming "fixed" because copy improved.
- Claiming "fixed" because a route redirects or a dead end moved somewhere else.
- Claiming "fixed" because the backend error is clearer while the UI still
  invites the invalid action.
- Claiming "fixed" after checking only one read, write, or parse path when
  adjacent paths still drift.
- Claiming "fixed" on desktop only for a mobile or responsive bug.
- Claiming "fixed" without rerunning the strongest practical regression.

## Stop-Ship and High-Priority Items

### 0. Hari 2026-05-05 BUG-026 / BUG-027 - Client and outside-counsel portal access

Status: Properly fixed

Root cause of the reopen:

- The backend portal, portal users, magic-link auth, and matter grants existed,
  so the earlier closure treated the report as stale.
- That was too shallow. The app UI still had no obvious staff-facing place to
  invite a client or outside counsel and grant a matter, so a real user working
  only through `caseops.ai/app` could reasonably conclude that no client/OC
  login workflow existed.
- Outside-counsel magic-link verification also landed on `/portal`, the client
  portal. The OC user then saw an empty client-matter list instead of the
  assigned-matters workspace at `/portal/oc`.
- The grant flags `can_upload` and `can_invoice` were recorded but not enforced
  by the OC portal mutation services, so "scoped access" was not actually
  scoped for uploads, invoices, or time entries.

Implementation:

- `apps/web/app/app/admin/page.tsx` now includes an "External portal access"
  card gated by `portal:invite`. Owners/admins can invite a client or outside
  counsel, choose the matter grant, and set reply/upload/invoice permissions.
- `apps/web/lib/api/portal.ts` now exposes `invitePortalUser`, matching
  `/api/admin/portal/invitations`.
- `apps/web/app/portal/verify/page.tsx` redirects outside-counsel users to
  `/portal/oc` after magic-link verification; `apps/web/app/portal/page.tsx`
  also redirects already-signed-in OC users away from the client portal.
- `apps/api/src/caseops_api/services/portal_outside_counsel.py` enforces
  `can_upload` for work-product upload and `can_invoice` for invoice/time
  submission.

Adjacent-path audit:

- Verified existing client portal routes, OC portal routes, admin invitation
  API, matter assignment API, generated frontend portal helpers, and existing
  Playwright coverage.
- Added explicit denial tests for OC uploads/invoices/time entries when the
  grant flags are false so the recorded scope cannot silently drift from
  enforcement again.

Verification:

- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npm run test:web -- --run app/app/admin/page.test.tsx app/portal/verify/page.test.tsx app/portal/page.test.tsx` - PASS 12/12.
- `uv --directory apps/api run pytest -q tests/test_portal_outside_counsel.py tests/test_code_scanning_regressions.py ...` - PASS 19/19.
- `npm run test:e2e:app -- tests/e2e/portal-invite-access.spec.ts tests/e2e/oc-portal.spec.ts` - PASS 2/2. This is the browser-level proof for BUG-026/027 and the adjacent OC portal workflow: owner invites client + OC from Admin, client signs into `/portal`, OC signs into `/portal/oc`, both see only the scoped matter, and the OC can still upload work product, submit an invoice, and log time when grant flags allow it.

Security alert addendum from the same 2026-05-05 pass:

- GitHub code scanning still showed 17 open alerts because these fixes were
  local and unpushed at the time of review. Treat the GitHub count as
  authoritative until the fixed commit reaches `main` and CodeQL reruns on that
  SHA.
- Closed the remaining alert classes locally: explicit workflow token
  permissions, demo-request email ReDoS, Python HTML/tag cleanup, whitespace
  ReDoS normalisers, matter-code trailing-number ReDoS, sensitive judge-date
  script output, and incomplete Pine Labs URL host checking in tests.
- Added source/runtime regressions in
  `apps/api/tests/test_code_scanning_regressions.py`,
  `apps/api/tests/test_retrieval_normalisers.py`,
  `apps/api/tests/test_intake.py`, `apps/api/tests/test_hari_ii_regressions.py`,
  and `tests/e2e/marketing.spec.ts`.

Final local verification before commit:

- `uv --directory apps/api run pytest -q tests/test_code_scanning_regressions.py tests/test_retrieval_normalisers.py tests/test_intake.py::test_matter_code_available_endpoint tests/test_hari_ii_regressions.py::test_pine_labs_parses_plural_v2_native_field_names ...` - PASS 25/25.
- `uv --directory apps/api run ruff check src tests` - PASS.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npm run test:e2e:marketing -- tests/e2e/marketing.spec.ts` - PASS 13/13.
- `npm run test:e2e:app -- tests/e2e/portal-invite-access.spec.ts tests/e2e/oc-portal.spec.ts` - PASS 2/2.
- `git diff --check` - PASS (line-ending warnings only).

Done when:

- ✅ A staff user can create a client portal login and grant a matter from the app UI.
- ✅ A staff user can create an outside-counsel portal login and grant a matter from the app UI.
- ✅ Outside counsel magic-link sign-in lands on `/portal/oc`, not the client portal.
- ✅ OC upload/invoice/time actions honor grant flags.
- ✅ Regression coverage includes API permission tests, web unit tests, and Playwright end-user workflow proof.

### 1. BUG-011 - Fresh matter overview still shows empty-state court-order UI

Status: Properly fixed

Root cause of the "Not fixed" reading:

- The fix in `apps/web/app/app/matters/[id]/page.tsx:89` (gate the Last
  court order card on `latestOrder ?` truthy) HAD landed on `f74f7b1`.
- But Playwright's webServer in `playwright.app.config.ts` runs
  `npx next start` against the prebuilt `.next/` directory, and that
  directory was built BEFORE `f74f7b1`. The verification ran against
  stale HTML, so the test failed even though the source was correct.
- Stale-bundle false negatives like this can recur on any future fix.
  Mitigation: `scripts/verify-web.sh` now mandates `npm run build`
  before launching Playwright (see Item #10's verification recipe).

Evidence after fresh build:

```
$ npm run build && npx playwright test --config playwright.app.config.ts -g "BUG-011"
  ✓  1 BUG-011: overview hides all three empty-state cards on a fresh matter (6.4s)
  ✓  2 BUG-011 companion: a populated matter shows Upcoming hearings card (2.6s)
  2 passed (46.7s)
```

The companion test prevents a future "always hide" regression — it
seeds a hearing via the API, confirms Upcoming hearings DOES render
on the populated matter, while the other two empty cards remain
hidden.

Done when:

- ✅ A fresh matter hides Last court order + Open tasks + Upcoming hearings.
- ✅ A populated matter shows Upcoming hearings (companion regression).
- ✅ The Playwright spec passes — assertion is `toHaveCount(0)` for the
  empty case + `toBeVisible()` for the populated case (no weakening).

### 2. Outside counsel schema and status drift related to BUG-018 and BUG-023

Status: Properly fixed

Backend canonical (apps/api/src/caseops_api/db/models.py):

- OutsideCounselPanelStatus: `active | preferred | inactive` (3)
- OutsideCounselAssignmentStatus: `proposed | approved | active | closed` (4)
- OutsideCounselSpendStatus: `submitted | approved | partially_approved | disputed | paid` (5)

Drift sites closed:

- `apps/web/lib/api/schemas.ts`:
  - `panelStatus` matched on a prior pass
  - `outsideCounselAssignmentStatus`: was `proposed | approved | declined | completed` → fixed to canonical
  - `outsideCounselSpendStatus`: was `submitted | approved | rejected | paid | disputed` (missing `partially_approved`, had invalid `rejected`) → fixed
- `apps/web/lib/api/endpoints.ts`:
  - `OutsideCounselPanelStatus` write type: was `active | on_hold | preferred | archived` → fixed
  - `OutsideCounselAssignmentStatus` write type: was `proposed | approved | declined | completed` → fixed
  - Added new `OutsideCounselSpendStatus` exported type; `createOutsideCounselSpendRecord.input.status` no longer has an inline incorrect literal
- `apps/web/components/app/NewCounselDialog.tsx`:
  - Form Zod was `["active", "on_hold", "preferred", "archived"]` → fixed
  - SelectItems removed `on_hold` + `archived`, added `inactive`

Adjacent-path 404 found + fixed during audit:

- `apps/web/lib/api/endpoints.ts:277` was POSTing to
  `/api/outside-counsel/spend` but the backend route is
  `/api/outside-counsel/spend-records` — every spend record in
  production was 404'ing. Fixed.

Verification:

- `apps/web/lib/api/schemas.test.ts` now pins 18 cases (3 panel +
  4 assignment + 5 spend canonical accepts; 6 previously-incorrect
  rejects). Each enum has its own describe block so the failure
  identifies which enum drifted. PASS 24/24.
- `apps/web/components/app/NewCounselDialog.test.tsx` 2/2 still pass
  with the new enum values.
- `tests/e2e/matter-outside-counsel.spec.ts` extended with a workspace
  E2E that seeds **canonical-but-previously-rejected** values (panel
  `inactive`, assignment `active`, spend `partially_approved`), then
  loads `/app/outside-counsel` and asserts the page header + counsel
  name render — proving every read-path Zod parse succeeds. PASS 2/2.
- Backend `apps/api/tests/test_outside_counsel.py` already covers
  round-trips with `partially_approved` etc. (line 96–103).

Done when:

- ✅ Backend schema, frontend Zod, frontend TS types, NewCounselDialog
  form, NewCounselDialog SelectItems all use the same enum values.
- ✅ The UI cannot emit invalid outside counsel statuses (form Zod
  rejects them at submit).
- ✅ The UI can read every canonical backend value without parse
  failure (E2E proves panel=inactive, assignment=active,
  spend=partially_approved all render).
- ✅ Spend record POST hits the right route (`/spend-records`).

### 3. BUG-021 - Duplicate matter-code validation is still reactive, not proactive

Status: Properly fixed

Implementation:

- New backend endpoint `GET /api/matters/code-available?code=XXX`
  (apps/api/src/caseops_api/api/routes/matters.py + service helper
  `matter_code_available` in services/matters.py). Tenant-scoped via
  `context.company.id` like every other matter endpoint. Returns
  `{available, normalised, suggestion, reason}` — `suggestion` mirrors
  the frontend `suggestNextMatterCode` so client + server propose the
  same value on a dup.
- Frontend (`apps/web/app/app/intake/page.tsx::PromoteButton`):
  - 350ms debounced `checkMatterCodeAvailable` on every code change
    once the dialog is open + the code is ≥2 chars.
  - When the response says `available: false`, `aria-invalid` flips
    on the input, the warning + suggestion render, AND the Create
    button is disabled (`disabled={busy || code < 2 || codeInUse}`).
  - The post-submit error path (BUG-017's auto-suggest) stays as a
    backstop for the race between the check and the actual submit
    (e.g. two operators grabbing the same code in the 350ms window).
- Server uniqueness guard untouched — still the source of truth.

Verification:

- `apps/api/tests/test_intake.py::test_matter_code_available_endpoint`:
  asserts free + taken cases (with case-insensitive normalisation,
  proper bumped suggestion, tenant isolation). PASS.
- `tests/e2e/hari-ii-bugs.spec.ts::BUG-021`: opens the promote
  dialog, types a known-taken code, asserts the warning +
  suggestion appear AND the Create button is disabled — without any
  click on Create. Verifies the user cannot reach a failed submit.
  PASS alongside the existing BUG-017 spec (which tests the
  backstop path); 2/2 after npm run build.

Done when:

- ✅ The intake UI warns before submit AND disables Create on a
  taken code (no failed submit needed for the user to see the
  conflict).
- ✅ The server-side uniqueness guard remains in place
  (services/intake.py:244-258).
- ✅ The user can resolve the conflict by clicking the
  one-click suggestion BEFORE any failed submit.

### 4. BUG-022 - Client detail completeness is still below the reported need

Status: Properly fixed

Implementation:

- DB columns added via Alembic `20260422_0002_clients_full_address`
  (uses `op.batch_alter_table` so SQLite-backed tests + Postgres
  prod both upgrade cleanly): `address_line_1`, `address_line_2`,
  `postal_code` (all nullable, varchar 255 / 255 / 20).
- Model `Client` (apps/api/src/caseops_api/db/models.py) gains the
  three columns + a docstring noting the BUG-022 rationale.
- Pydantic schemas (`apps/api/src/caseops_api/schemas/clients.py`):
  `ClientCreateRequest`, `ClientUpdateRequest`, `ClientRecord` all
  carry the three new fields.
- Service (`apps/api/src/caseops_api/services/clients.py`):
  - `_client_record` returns the new fields
  - `create_client` strips + persists them
  - `update_client` field-list now includes the new fields so
    `PATCH` can clear them (via the existing strip-on-update path)
- Frontend types (`apps/web/lib/api/endpoints.ts`): `ClientRecord`
  + `ClientCreateInput` mirror the backend exactly (same field
  names, same nullability).
- Create form (`apps/web/app/app/clients/page.tsx`): two new
  Input rows for Address line 1 + Address line 2, plus a Postal
  code input next to State + Country. State persists via
  `useState` and is wired into the createClient mutation.
- Detail page (`apps/web/app/app/clients/[id]/page.tsx`): Contact
  card now renders Address line 1, Address line 2, City, State,
  Postal code, Country as separate dt/dd rows. Empty fields show
  "—" so the user sees exactly what's recorded vs missing.

Verification:

- `apps/api/tests/test_clients.py::test_client_full_address_round_trips`
  asserts CREATE → fetch → PATCH (with explicit clear of
  address_line_2) → re-fetch all preserve the canonical fields. PASS.
- Full `test_clients.py` suite: 15/15 still pass.
- `npx tsc --noEmit` on web: clean.

Done when:

- ✅ The client model supports the full mailing address (street +
  locality + postal code + country).
- ✅ Create form, detail view, and update path all handle the same
  field set.
- ✅ Round-trip regression pinned in the backend test suite so a
  future schema or service drift fails CI.

### 5. BUG-013 - Reminder parity is still incomplete

Status: Properly fixed

Implementation:

- Backend service helper
  `services.hearing_reminders.list_reminders_for_matter` returns
  the rows for a single matter, ordered by `scheduled_for desc`.
- New route `GET /api/matters/{matter_id}/reminders` (in
  `routes/matters.py`) — gates via the existing `get_matter` ACL
  (tenant + matter-access) so anyone with `matters:read` who can
  see the matter can see its reminders. Returns the same record
  shape as the admin notifications endpoint, scoped to one matter.
- Frontend wrapper `listMatterReminders` in
  `apps/web/lib/api/endpoints.ts` + types `MatterReminderRecord`
  and `MatterRemindersResponse`.
- Matter cockpit Hearings tab
  (`apps/web/app/app/matters/[id]/hearings/page.tsx`) gains a
  `useQuery` on a 30-second polling cadence so the user sees
  queued → sent → delivered transitions live, and a new
  `HearingReminderStrip` renders inline under each hearing
  summary — colour-coded pills (queued = neutral, sent = ink,
  delivered = brand, failed = warn) with the scheduled time.

Verification:

- `apps/api/tests/test_hearing_reminders.py::test_per_matter_reminders_endpoint_is_tenant_and_matter_scoped`
  asserts owner sees both queued reminders, an empty matter
  returns `[]`, and a cross-tenant caller 404s. PASS.
- `tests/e2e/hari-ii-bugs.spec.ts::"BUG-013 in-app"` opens
  `/app/matters/{id}/hearings` after the API has seeded a hearing
  4 days out and asserts the `hearing-reminder-strip` testid is
  visible with the queued pill. PASS.
- The original BUG-013 dialog-copy spec also still passes.

Done when:

- ✅ End-user in-app reminder surface ships (per-matter strip on
  the Hearings tab — visible to anyone who can see the matter,
  not just workspace admins).
- ✅ Email and in-app paths share the SAME row in
  `hearing_reminders` — what the admin sees, what the matter
  team sees, and what the SendGrid worker sends are all the
  same record. The webhook update flips both surfaces in lock-
  step (queued → sent → delivered).

### 6. Ram BUG-004, BUG-005, and BUG-006 - mobile and responsive fixes are under-proven

Status: Properly fixed

Implementation:

- `playwright.app.config.ts` gains a second project `app-mobile`
  using `devices['Pixel 5']` (393×851, touch, Mobile Chrome UA).
  The project is `grep`-restricted to `[mobile]`-tagged tests +
  `testMatch`-restricted to `mobile-responsive.spec.ts` so it
  doesn't double-run desktop specs on a viewport they weren't
  written for. Pixel-5 is Chromium-based — no separate browser
  binary needed; reuses the bundled Playwright Chromium.
- New `tests/e2e/mobile-responsive.spec.ts` with three tests, one
  per Ram bug:
  - **BUG-005**: bootstrap → sign in → /app → assert sidebar is
    `hidden`, `mobile-nav-trigger` is visible + tappable, drawer
    opens with the same nav body, tapping a nav link auto-closes
    the drawer + navigates.
  - **BUG-004**: open New Contract dialog on the iPhone-class
    viewport, scroll the Cancel + Submit buttons into view +
    assert visible (would fail if footer were clipped behind
    `overflow-hidden`). Also asserts the two-column field grid
    stacks vertically (Type input's y is below Code input's
    bottom — the `grid-cols-1 sm:grid-cols-2` proof).
  - **BUG-006**: same shape for New Counsel dialog on
    `/app/outside-counsel`.

Verification:

- `npx playwright test --config playwright.app.config.ts --project app-mobile`
  PASS 3/3 (~41s).
- Desktop project unaffected: re-ran 9 representative
  desktop specs (Hari II + workspace OC) PASS 9/9 (~70s).

Done when:

- ✅ Phone-sized viewport has dedicated automated coverage for the
  three flows the bug sheet referenced (Topbar nav, New Contract,
  New Counsel).
- ✅ The dialogs are usable without horizontal clipping (assertion
  that the field grid stacks) or hidden actions (scrollIntoView +
  toBeVisible on Submit + Cancel) or trapped scrolling
  (DialogContent gained `overflow-y-auto` in commit 7376873).

### 7. Contract intelligence provider-failure regressions are still not pinned down

Status: Properly fixed

Implementation (commit 4104265): added `_structured_with_retry`
helper to `services/contract_intelligence.py` that catches
`LLMProviderError` (the parent of the format-error subclass), retries
once with the same model on transient overload, and raises
`HTTPException 422` with an actionable detail naming the failure
shape if the retry also fails. All three callers
(extract_clauses, extract_obligations, compare_playbook) route
through the helper.

Regression:
`apps/api/tests/test_contract_intelligence.py::test_structured_with_retry_returns_actionable_422_when_provider_keeps_failing`
— calls the helper directly with a stub provider that raises
`LLMProviderError("503 overloaded")` on every call, asserts the
final HTTPException carries status 422 + the user-actionable
phrase ("Could not extract clauses ... LLMProviderError ... retry
in a minute"). Direct unit test covers all three call sites
uniformly without bootstrapping the contract upload pipeline. PASS.

### 8. Hearing-pack provider-failure regressions are still not pinned down

Status: Properly fixed

Implementation (commit 4104265): added Haiku fallback +
`LLMProviderError` parent-class catch in
`services/hearing_packs.py` (mirroring drafts/recommendations).
Both primary and fallback failures emit an HTTPException 422 with
an actionable detail (`Could not assemble a hearing pack: the
primary model is unavailable (LLMProviderError) ... retry in a
minute`).

Regression:
`apps/api/tests/test_hearing_packs.py::test_hearing_pack_provider_error_returns_actionable_422`
— mocks `services.hearing_packs.build_provider` to return a stub
that raises `LLMProviderError("503")` on every call AND mocks
`_haiku_fallback_provider` to return None (worst-case branch),
asserts POST `/api/matters/{id}/hearings/{id}/pack` returns 422
with the actionable detail. PASS.

### 9. Drafting provider-failure regressions still need explicit proof

Status: Properly fixed

Implementation (commit 4104265): broadened
`services/drafting.py::generate_draft_version` `except` from
`(LLMResponseFormatError, ValidationError)` to `(LLMProviderError,
ValidationError)` so 503 / httpx timeout bubbles into the Haiku
fallback branch instead of escaping as a 500. Both primary and
fallback failure paths raise HTTPException 422 with detail naming
the failure shape.

Regression:
`apps/api/tests/test_drafting_studio.py::test_generate_draft_provider_error_returns_actionable_422`
— mocks `services.drafting.build_provider` to return a stub that
raises `LLMProviderError("503")`, mocks `_haiku_fallback_provider`
to None, asserts POST `/api/matters/{id}/drafts/{id}/generate`
returns 422 with `primary model is unavailable ... LLMProviderError
... retry in a minute`. PASS.

Frontend `apps/web/app/app/matters/[id]/drafts/[draftId]/page.tsx`
already renders `ApiError.detail` verbatim (verified during the
2026-04-22 audit), so the 422 detail reaches the user as the toast.

### 10. Backend verification environment is still not trustworthy enough

Status: Properly fixed

Evidence:

- `slowapi` IS in `apps/api/pyproject.toml:22` (`slowapi>=0.1.9`) and in
  `apps/api/uv.lock` (3 entries). The earlier `ModuleNotFoundError` was a
  partial-sync artefact — the venv where pytest ran had not been refreshed
  after slowapi was added. The repo state is correct.
- New canonical recipe: `scripts/verify-backend.sh` (Bash) and
  `scripts/verify-backend.ps1` (PowerShell). Both:
  - Resolve `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (Unix).
  - Bootstrap with `uv sync --frozen --no-install-project` if the venv is
    missing — `--no-install-project` skips rebuilding `Scripts/*.exe`
    wrappers, which is the file-lock that bites when a long-running process
    holds them.
  - Run an import sanity check that fails loudly on a partial sync, listing
    every missing module by name (catches the slowapi case before pytest's
    confusing collection-time ImportError).
  - Run ruff + targeted pytest with whatever args the caller passes.
- Documented in `CODEX.md` under "Canonical backend verification recipe".

Verification run (2026-04-22):

```
scripts/verify-backend.sh tests/test_recommendations.py tests/test_drafting_studio.py \
  tests/test_hearing_packs.py tests/test_contract_intelligence.py \
  tests/test_clients.py tests/test_intake.py tests/test_hearing_reminders.py
→ 67 passed, 1 warning in 194.52s
```

Done when:

- ✅ `uv sync --frozen --no-install-project` runs cleanly on a clean checkout.
- ✅ Targeted backend pytest runs complete for outside counsel, intake,
  clients, reminders, contract intelligence, hearing packs, and drafting.
- ✅ The recipe is in `scripts/` + documented in `CODEX.md` so any agent can
  repeat it without guessing.

## Release Gate

No agent may claim "all bugs fixed" until all of the following are true:

- ✅ `BUG-011` is properly fixed (#1 above).
- ✅ Outside counsel schema drift is closed on both read and write paths (#2).
- ✅ Any reopened bug has fresh end-user verification (BUG-011, BUG-013, BUG-018, BUG-022).
- ✅ Mobile or responsive bugs have actual mobile proof (#6 + `app-mobile` Playwright project).
- ✅ Provider-failure paths that were part of this audit have dedicated regression coverage (#7, #8, #9).
- ✅ Backend verification is runnable enough to support the claimed fix scope (#10 + `scripts/verify-backend.sh`).
- ✅ This document is updated with the final verdict and evidence for every item.

### Final verdict per item (10/10 closed, 2026-04-22)

| Item | Status | Lead commit |
|---|---|---|
| #1 BUG-011 fresh-matter overview cards | Properly fixed | 03891b3 |
| #2 Outside counsel schema drift | Properly fixed | 6af16f4 |
| #3 BUG-021 pre-submit dup-code guard | Properly fixed | c1e0997 |
| #4 BUG-022 client street-address | Properly fixed | 82ac66a |
| #5 BUG-013 in-app reminder visibility | Properly fixed | (pending commit at end of this batch) |
| #6 Mobile + responsive proof | Properly fixed | cc9a049 |
| #7 Contract intelligence provider failure | Properly fixed | 9d453de |
| #8 Hearing-pack provider failure | Properly fixed | 9d453de |
| #9 Drafting provider failure | Properly fixed | 9d453de |
| #10 Backend verification env | Properly fixed | 03891b3 |

**Codex sign-off pre-conditions:**

- `scripts/verify-backend.sh tests/test_intake.py tests/test_hearing_reminders.py tests/test_clients.py tests/test_drafting_studio.py tests/test_recommendations.py tests/test_hearing_packs.py tests/test_contract_intelligence.py` should report all green.
- `scripts/verify-web.sh --quick` (vitest + tsc) should report all green.
- `scripts/verify-web.sh -g "BUG-"` (Playwright app suite) should report all green.
- `npx playwright test --config playwright.app.config.ts --project app-mobile` should report 3/3 green.
- The release gate above is fully checked.

---

## Hari 2026-05-09 batch

Five PRs opened in response to the 2026-05-09 Hari workbook
(`C:\Users\mishr\Downloads\CaseOps Bug List_Hari9May2026 .xlsx`).
All are **Partially fixed** by the strict bug-fixing skill until the
prod-Playwright spec for each passes against `caseops.ai` on the
deployed commit SHA. Each PR body carries the full verification
matrix; this section is the durable index.

| # | Bug / Area | PR | Merge SHA | Branch | Verdict | Prod-Playwright spec |
|---|---|---|---|---|---|---|
| H-01 | BUG-034 — custom-role catalog `custom_role_delegable` flag + UI gating | [#20](https://github.com/mishrasanjeev/caseops/pull/20) | `78108e4` | `fix/bug-034-protected-capability-catalog` | **Properly fixed** | `tests/e2e/hari-2026-05-09-prod.spec.ts` (2/2 pass on prod `ec55dc2`, run 25628453223) |
| H-02 | BUG-033 — `/account/setup` + `/account/reset-password` Next.js routes | [#21](https://github.com/mishrasanjeev/caseops/pull/21) | `877c615` | `fix/bug-033-account-setup-links` | **Properly fixed** | `tests/e2e/hari-2026-05-09-bug-033-prod.spec.ts` (3/3 pass on prod `ec55dc2`, run 25628453223) |
| H-03 | BUG-038 — SendGrid webhook valid-sig test, unsubscribe handling, tenant suppression, Cloud Run wiring, runbook | [#22](https://github.com/mishrasanjeev/caseops/pull/22) | `2b571cc` | `fix/sendgrid-webhook-delivery-visibility` | **Partially fixed** — provider, runtime, and live ingestion all verified; only DB-side suppression-row proof outstanding | n/a (server-only). Runtime proof: `CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY` wired via `secretKeyRef name=caseops-sendgrid-webhook-public-key key=latest` on `caseops-api-00132-c6n` (image `:ec55dc2`); fail-closed verified — invalid + missing signatures both return 401 at canonical URL `https://api.caseops.ai/api/webhooks/sendgrid/events`. Provider proof (2026-05-10, Codex): SendGrid Event Webhook enabled in dashboard with all 6 required event types (`delivered`, `bounce`, `dropped`, `spam_report`, `unsubscribe`, `group_unsubscribe`) + `public_key_present: true`; SendGrid official webhook test API returned **HTTP 204** (settings id `c3d614d6-40fa-4db7-b295-c3e6cf44cd92`); Cloud Run logs show real `User-Agent: SendGrid Event API` POSTs to `/api/webhooks/sendgrid/events` returning **HTTP 200** (samples: `2026-05-10T15:42:14Z` 0.162s, `2026-05-10T15:40:03Z` 0.094s, `2026-05-10T15:35:17Z` 1.738s). Remaining caveat — sole reason for not graduating to Properly fixed: a database-side query showing a tenant-scoped `EmailSuppression` row written from a real production bounce/unsubscribe event. The 200 status is strong indirect evidence (the route handler writes the row before returning), but per the bug-fixing skill we hold the conservative verdict until the row is observed. |
| H-04 | BUG-039 — Outlook bounded bulk sync endpoint + Calendar UI button | [#23](https://github.com/mishrasanjeev/caseops/pull/23) | `7761a1b` | `fix/outlook-sync-all` | **Properly fixed** | `tests/e2e/hari-2026-05-09-outlook-sync-prod.spec.ts` (2/2 pass on prod `ec55dc2`, run 25628453223) |
| H-05 | BUG-032 — manual court-order create from matter Hearings page | [#24](https://github.com/mishrasanjeev/caseops/pull/24) | `ed01fdd` | `fix/bug-032-hearing-order-upload` | **Properly fixed** | `tests/e2e/hari-2026-05-09-bug-032-prod.spec.ts` (2/2 pass on prod `ec55dc2`, run 25628453223) |

Pre-cursor merge that cleared CVE-2026-44843 (`langchain-core` 1.3.0 → 1.3.3, transitive via `voyageai`):
**[#18](https://github.com/mishrasanjeev/caseops/pull/18) → `b827efb`** (dependabot). Without this merge first, every Hari PR's `pip-audit` gate stayed red.

URL-fix follow-up that corrected stale `https://api.caseops.ai/api/sendgrid/events` references in workbook + audit docs to the canonical `https://api.caseops.ai/api/webhooks/sendgrid/events`:
**[#26](https://github.com/mishrasanjeev/caseops/pull/26) → `ec55dc2`**. Application code unchanged; runbook was already correct.

All five fix PRs + #18 + #26 merged to main on 2026-05-10. Final main SHA: `ec55dc2`. Deployed to production via `scripts/deploy-prod.sh ec55dc2` (caseops-api revision `caseops-api-00132-c6n`, caseops-web revision `caseops-web-00121-278`, ClamAV sidecar present, health 200).

### Closure pre-conditions (2026-05-10)

For each row above to graduate to **Properly fixed**:

1. The PR is merged to `main`.
2. The merged commit is deployed to `caseops.ai` via the canonical
   `scripts/deploy-prod.sh` (per the EG-002 hard rule — never
   ad-hoc `gcloud run deploy`).
3. The named prod-Playwright spec passes against the deployed
   commit SHA via the scheduled or `workflow_dispatch`
   `Prod verification (Playwright)` workflow.
4. For H-03 (SendGrid) only: provider-side SendGrid dashboard
   toggles AND the `caseops-sendgrid-webhook-public-key` Secret
   Manager value are set per the runbook. Without those two
   operator-side steps, signed events fail-closed at 503 and
   suppression rows never populate.

### testMatch overlap on `playwright.app.config.ts` and `playwright.prod-ram.config.ts`

PRs #20, #21, #23, #24 all add entries to the testMatch lines.
Whichever merges first, the others must be rebased keeping ALL
spec entries:

- `hari-2026-05-09-bugs.spec.ts` (PR #20 local)
- `hari-2026-05-09-prod.spec.ts` (PR #20 prod)
- `hari-2026-05-09-bug-033.spec.ts` (PR #21 local)
- `hari-2026-05-09-bug-033-prod.spec.ts` (PR #21 prod)
- `hari-2026-05-09-outlook-sync.spec.ts` (PR #23 local)
- `hari-2026-05-09-outlook-sync-prod.spec.ts` (PR #23 prod)
- `hari-2026-05-09-bug-032.spec.ts` (PR #24 local)
- `hari-2026-05-09-bug-032-prod.spec.ts` (PR #24 prod)

Spec files are uniquely named so no spec-content conflicts.
Dropping any entry silently disables that bug's prod regression.

### Adjacent-path audit findings

The audit ran alongside the bug fixes:

- **Generated email links must map to real frontend routes.**
  `services/employee_mailer.py` had been generating
  `/account/setup` and `/account/reset-password` URLs since the
  LegalWorkspace LW-S5 employee admin shipped, but neither route
  existed on the frontend. Closed by PR #21. Going forward, every
  email-link generator should be paired with a `tests/e2e/*` route-
  exists test.
- **Backend protected-capability rules must be reflected in UI.**
  `services/capabilities.py::_NON_DELEGABLE_CUSTOM_ROLE_CAPABILITIES`
  rejected `email_templates:manage` / `portal:invite` /
  `portal:manage_grants` for custom roles, but the
  `CapabilityRecord` schema only carried an `owner_only` boolean,
  so the frontend could only gate owner-only caps. Closed by PR #20
  via `custom_role_delegable` + `protected_reason` fields.
- **Linked-record selectors need a discoverable create path.**
  Documents-page Linked-order selector existed, but
  `MatterCourtOrder` rows could only come from court-sync. Closed
  by PR #24 with the manual create endpoint + dialog.
- **Provider integrations need code + infra + runtime + provider
  config to all agree.** SendGrid send had been working from
  imperatively-set Cloud Run env vars; the webhook side had no
  declarative wiring at all (manifest + Secret Manager + dashboard
  config all missing). PR #22 adds the manifest + runbook; the
  dashboard + Secret Manager steps remain operator work documented
  in `docs/runbooks/sendgrid-event-webhook.md`.
- **Bounded sync vs durable automation.** Outlook sync-all (PR #23)
  and SendGrid event ingestion (PR #22) both intentionally avoid
  durable background loops — the `durable_automation:
  blocked_pending_provider_approval` literal in the response is the explicit
  declaration so callers cannot mistake bounded manual sync for
  continuous automation.

## Hari 2026-05-11 batch — BUG-042 to BUG-048

Reported on `CaseOpsBugList_Hari11May2026.xlsx` (Downloads). Worktree branch
`worktree-hari-bugs-2026-05-11`, HEAD commit `91d31d1`. Local Playwright
proof in `tests/e2e/hari-2026-05-11-bugs.spec.ts` (9/9 PASSED). Prod
re-run required after `scripts/deploy-prod.sh`. Summary xlsx:
`C:\Users\mishr\Downloads\CaseOpsBugFixSummary_Hari11May2026.xlsx`.

| ID | Severity | Verdict | Spec | Notes |
|----|----------|---------|------|-------|
| BUG-042 | P2 | Properly fixed (local) | `hari-2026-05-11-bugs.spec.ts::185` | View order document button on hearings order list |
| BUG-043 | P2 | Properly fixed (local, client-side scope) | `hari-2026-05-11-bugs.spec.ts::213` | Search + hearing-filter on documents tab |
| BUG-044 | P1 | Properly fixed (local) | `hari-2026-05-11-bugs.spec.ts::245+261` | Outlook 409 → Connect Outlook pre-empt + actionable toast |
| BUG-045 | P2 | Properly fixed (local) — migration required at deploy | `hari-2026-05-11-bugs.spec.ts::286` | `matter_attachments.hearing_id` FK + UI |
| BUG-046 | P2 | Stale report | `hari-2026-05-11-bugs.spec.ts::351` | BenchStrategyPanel already mounts at `apps/web/app/app/matters/[id]/page.tsx:100` |
| BUG-047 | P1 | Stale report | `hari-2026-05-11-bugs.spec.ts::371` | Role select ships in both create + edit dialogs |
| BUG-048 | P1 | Properly fixed (local) | `hari-2026-05-11-bugs.spec.ts::387+455` | Matter access admin panel on EditEmployeeDialog |

Adjacent gaps surfaced by the audit (NOT fixed in this batch — separate
tickets to be filed):

- **Upload-but-no-view (BUG-042 class).** `contracts/[id]/page.tsx:602-650`
  only renders View redline for DOCX; PDF/TXT contract attachments have no
  View affordance. Same pattern as BUG-042.
- **Raw `apiErrorMessage` on actionable failure (BUG-044 class).** Five
  highest-value sites where the toast should pre-empt or render an actionable
  CTA: documents upload 422, contracts upload 422, draft create 429/422,
  court-sync 400 (no live adapter), calendar visible-range sync 401/403.
- **Backend exists, no admin UI (BUG-048 class).** `services/custom_roles.py`,
  `services/notification_rules.py`, `services/conflict_checks.py` all ship
  REST routes but have no admin page; admins must run SQL to use them.

## Hari 2026-05-31 batch (BUG-042 reopen, BUG-043, BUG-049)

Full writeup + runbook: `docs/BUG_FIX_HARI_2026-05-31.md`.

- **BUG-042 (P1, reopened) — Partially fixed.** Root cause is a deploy/credential
  seam, not missing code: Secret Manager has no `caseops-ecourtsindia-api-token`
  (api-service.yaml references it → deploy would fail), and the search UI failed
  silently on 0-results / provider errors. Fixed UI legibility (verbatim error +
  empty-state) and locked the adapter contract. LIVE search = Inconclusive pending
  token (Runbook A) + automation deploy (Runbook B).
- **BUG-043 (P2) — Partially fixed.** Bookmark + poll→in-app-notification already
  exist and are tested; the nightly poll Cloud Run job + scheduler were committed
  as YAML but never deployed. Automation = Inconclusive pending Runbook B (and the
  eCourts token).
- **BUG-049 (P2) — Partially fixed.** "Inputs unreliable" = silent-failing
  create/run/source-sync mutations (now render verbatim errors); create→persist
  verified. Nightly PRS sync job + scheduler committed but never deployed
  (token-free) → Inconclusive pending Runbook B.
- **Adjacent class confirmed:** only `caseops-ecourtsindia-api-token` is missing of
  all cloudrun secretKeyRefs; no app/app page-level mutation lacks an error surface
  after this batch. Proof: vitest (3 new), Playwright `hari-2026-05-31-bugs.spec.ts`
  (4, PASSED), backend test_case_tracking.py + test_statutes_routes.py (42 PASSED).

---

## Hari 2026-06-24 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari24Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| BUG-001 | P1 High | Locally fixed | Matters / Add Matters / District Court forum selector | Valid reopened bug. The shallow all-state fallback was replaced with a scraped India.gov.in District Courts Contact Directory seed: 36 states/UTs, 724 scraped rows, 723 unique active district court catalog entries. The selector still provides typed uncatalogued fallback, but catalog-to-Other now clears inherited catalog metadata so district/court names are required. Strict verdict remains below `Properly fixed` until PR CI, merge, deploy, and production Playwright pass on the shipped commit. |

Regression evidence added:

- `apps/api/alembic/versions/20260624_0001_seed_india_gov_district_courts.py` - India.gov district court seed migration with scrape-count validation.
- `apps/api/src/caseops_api/scripts/seed_data/india_gov_district_courts.json` - scraped source snapshot: 36 states/UTs, 724 rows, 723 unique active courts.
- `apps/web/components/matters/ForumSelector.test.tsx` - India.gov state list, Assam fallback, and catalog-to-Other clearing behavior.
- `apps/web/components/app/NewMatterDialog.test.tsx` - New Matter creates uncatalogued Assam lower-court metadata only after district and court names are supplied.
- `apps/web/components/matters/MatterForumCard.test.tsx` - edit path preserves no-catalog/stale-catalog lower-court state/district/court metadata without resubmitting inactive catalog IDs.
- `apps/api/tests/test_legalworkspace_forum_selector.py` - backend exposes 723 active India.gov district courts and accepts uncatalogued lower-court metadata.
- `tests/e2e/hari-2026-06-24-bugs.spec.ts` - browser workflow for all India.gov jurisdictions, Assam catalog rows, and fallback-required metadata.
- `tests/e2e/hari-2026-06-23-bugs.spec.ts` - prior Delhi regression updated to India.gov Delhi directory entries.

Local verification on 2026-06-24:

- `uv --directory apps/api run ruff check alembic/versions/20260624_0001_seed_india_gov_district_courts.py tests/test_legalworkspace_forum_selector.py` - PASS.
- `uv --directory apps/api run pytest tests/test_legalworkspace_forum_selector.py` - PASS 4/4.
- `npm run test:web -- ForumSelector.test.tsx MatterForumCard.test.tsx` - PASS 9/9.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-24-bugs.spec.ts --project app-chromium` - PASS 1/1.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-23-bugs.spec.ts --project app-chromium` - PASS 1/1.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-24_HARI.md`.

---

## Hari 2026-06-26 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari26Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| bug-001 | Medium | Locally fixed | Research / Context Research | Valid bug. Prior UI-only garbled-preview masking was shallow. Retrieval now penalizes low-quality OCR text and the authority route orders readable results ahead of garbled OCR before pagination. Production verdict remains below `Properly fixed` until committed Playwright passes against the deployed build. |
| bug-002 | Low | Locally fixed | Matters / New Matter | Valid bug. Matter Code now has a shared backend grammar and frontend grammar: uppercase letters, numbers, and hyphens only; spaces, underscores, slashes, and other special characters are rejected. Direct matter create, availability, intake promotion, and New Matter UI are covered. Production verdict remains below `Properly fixed` until committed Playwright passes against the deployed build. |

Regression evidence added:

- `apps/api/src/caseops_api/services/retrieval.py` - OCR readability classifier and rank penalty.
- `apps/api/src/caseops_api/services/authorities.py` - readable authority results are ordered ahead of low-quality OCR before pagination.
- `apps/api/src/caseops_api/schemas/matters.py` - shared backend Matter Code grammar and normalization.
- `apps/api/src/caseops_api/schemas/intake.py` - intake promotion reuses the same grammar.
- `apps/api/tests/test_authorities.py` - contextual cheque dishonour search ranks readable Section 138/142 authority ahead of a matching garbled OCR authority.
- `apps/api/tests/test_matter_code_validation.py` - invalid Matter Code rejected by create, availability, and intake promotion paths.
- `apps/web/lib/matter-code.ts` - shared frontend Matter Code grammar.
- `apps/web/components/app/NewMatterDialog.test.tsx` - New Matter rejects invalid code before submit.
- `apps/web/app/app/intake/page.test.tsx` - Intake promotion rejects invalid code before availability check or submit.
- `tests/e2e/hari-2026-06-26-bugs.spec.ts` - Playwright workflow for Context Research and New Matter validation.
- `playwright.app.config.ts` - June 26 Playwright regression registered in the normal app suite.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-26_HARI.md`.

---

## Hari 2026-06-27 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari27Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| bug-001 | Medium | Locally fixed; formal production verdict Inconclusive | Research / Context Research | Valid reopened bug. The June 26 fix still allowed a garbled OCR authority card to occupy result slots when readable authorities existed. Authority search now suppresses low-quality OCR rows whenever readable results are available, while preserving damaged OCR as a last-resort fallback when no readable source exists. |
| bug-002 | Medium | Locally fixed; formal production verdict Inconclusive | Research | Valid bug. Draft filter controls are now separated from committed search criteria. Filter edits no longer auto-fire stale searches or disable the explicit Search action; keyword and contextual modes both submit the selected filters only when Search is clicked. |
| case-reopening audit | Medium | Locally fixed; formal production verdict Inconclusive | Matters / status lifecycle | Not a workbook row, but explicitly requested. Backend already normalizes legacy `closed` to `disposed`; added reload/read-back Playwright proof that a disposed matter remains disposed and aligned portfolio terminology to `Dispose`. |

Regression evidence added:

- `apps/api/src/caseops_api/services/authorities.py` - low-quality OCR authority rows are suppressed when readable authority results exist.
- `apps/api/tests/test_authorities.py` - readable Section 138 / Section 142 authority suppresses the matching garbled OCR authority; garbled OCR remains available only when it is the only match.
- `apps/web/app/app/research/page.tsx` - draft filter state is committed into `SearchCriteria` only on submit.
- `apps/web/app/app/research/page.test.tsx` - filter edits stay staged until Search is clicked, and garbled OCR result cards are hidden when readable results exist.
- `apps/web/app/app/matters/page.tsx` and `apps/web/app/app/matters/page.test.tsx` - portfolio lifecycle label uses `Dispose`.
- `tests/e2e/hari-2026-06-27-bugs.spec.ts` - browser proof for bug-001, bug-002 in keyword and contextual modes, and disposed-status persistence after reload.
- `tests/e2e/hari-2026-06-26-bugs.spec.ts` - prior OCR regression strengthened so it no longer preserves the shallow "bad card visible with placeholder" behavior.
- `playwright.app.config.ts` - June 27 Playwright regression registered in the normal app suite.

Local verification on 2026-06-27:

- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_uses_garbled_ocr_only_when_no_readable_match_exists` - PASS, 2 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx app/app/matters/page.test.tsx` - PASS, 11 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-27-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 4 tests.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-26-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 2 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_gba_law_office_prd.py::test_matter_status_closed_input_normalizes_to_disposed` - PASS, 1 test.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-27_HARI.md`.

---

## Hari 2026-06-29 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari29Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| bug-001 | Medium | Already fixed in current main; revalidated locally | Research / Context Research | Valid product symptom. Current `main` already suppresses low-quality OCR authorities when readable authorities exist, preserving damaged OCR only as last-resort fallback. No new code path was needed; the existing June 27 regression remains the anchor. |
| bug-002 | Medium | Locally fixed; formal production verdict Inconclusive | Research | Valid bug. UI promised `Court name contains`, but backend authority search used exact equality across multiple retrieval branches. Search now uses case-insensitive substring court filtering in the exact-name prefilter, pgvector probe/filtered CTE, fallback scan, and boost logic. |
| case-reopening audit | Medium | Process learning updated | Cross-product regression quality | No new matter-status defect was present in the workbook. Reopen cause here was shallow proof: prior bug-002 tests proved payload submission, not backend filter semantics. |

Regression evidence added:

- `apps/api/src/caseops_api/services/authorities.py` - shared court filter normalization and contains semantics across authority retrieval paths.
- `apps/api/tests/test_authorities.py` - seeded `Madras High Court` authority returned by partial `court_name: "madras"` for the workbook bail query.
- `apps/web/app/app/research/page.test.tsx` - partial `Madras` filter is submitted and returned `Madras High Court` result renders.
- `tests/e2e/hari-2026-06-29-bugs.spec.ts` - browser proof that the Research UI submits `Madras` and renders a matching `Madras High Court` result.
- `playwright.app.config.ts` - June 29 Playwright regression registered in the normal app suite.
- `docs/BUG_REOPEN_LEARNINGS_2026-06-29_HARI.md` - root cause and permanent learning added.

Local verification on 2026-06-29:

- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_authority_search_court_name_filter_is_case_insensitive_contains apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_uses_garbled_ocr_only_when_no_readable_match_exists` - PASS, 3 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx` - PASS, 6 tests.
- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/authorities.py apps/api/tests/test_authorities.py` - PASS.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp\hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-29-bugs.spec.ts tests/e2e/hari-2026-06-27-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 5 tests.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-29_HARI.md`.

---

## Hari 2026-06-30 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari30Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| bug-001 | High | Locally fixed; formal production verdict Inconclusive | Matter Management / Matter Creation / eCourt Integration | Valid bug. Direct matter creation now auto-registers a matter-scoped case-tracking bookmark when case tracking is enabled/configured and the matter has a valid CNR or case number. The `/app/matters` New Matter dialog now captures and submits case number + CNR; a backend-only fix would have left the reported UI path broken. |
| case-reopening audit | High | Process learning updated | Cross-product regression quality | Reopen cause was shallow proof: prior eCourt work tested manual sync/bookmark flows, not the matter-create lifecycle invariant. |

Regression evidence added:

- `apps/api/src/caseops_api/services/case_tracking.py` - reusable bookmark upsert and matter-create auto-link helper.
- `apps/api/src/caseops_api/services/matters.py` - direct create path calls the helper and records auditable auto-link metadata.
- `apps/web/components/app/NewMatterDialog.tsx` - New Matter UI captures case number and CNR.
- `apps/api/tests/test_case_tracking.py` - configured auto-link, disabled-provider non-blocking create, support-matrix-blocked non-blocking create.
- `apps/web/components/app/NewMatterDialog.test.tsx` - UI submits case identity fields.
- `tests/e2e/hari-2026-06-30-bugs.spec.ts` - browser workflow creates the matter from `/app/matters` and verifies Case Tracking contains the linked CNR/case.
- `playwright.app.config.ts` - June 30 Playwright regression registered in the normal app suite.
- `docs/BUG_REOPEN_LEARNINGS_2026-06-30_HARI.md` - root cause and permanent learning added.

Local verification on 2026-06-30:

- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/case_tracking.py apps/api/src/caseops_api/services/matters.py apps/api/tests/test_case_tracking.py` - PASS.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_case_tracking.py` - PASS, 11 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_audit_events.py` - PASS, 6 tests.
- `npm --prefix apps/web test -- components/app/NewMatterDialog.test.tsx` - PASS, 10 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp\hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-30-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 1 test.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-30_HARI.md`.

---

## Hari 2026-07-02 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari02Jul2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| BUG-001 | High | Locally fixed; formal production verdict Inconclusive | Research / Context Search | Valid reopened bug. Context Research must not render corrupted authority title, summary, or snippet text. Authority search now omits unreadable preview records entirely and returns an explicit omitted-record notice when the only matches are unreadable. |
| BUG-00X | High | Locally fixed; formal production verdict Inconclusive | Matter Management / Matter Details | Valid enhancement/bug. Notice documents already existed as attachment metadata, but the matter cockpit did not expose a Notice workflow. Matter details now include a Notices tab with notice-only listing and notice-classified upload. |
| case-reopening audit | High | Process learning updated | Cross-product regression quality | Reopen cause was shallow OCR proof: previous fixes preserved a corrupted last-resort path and did not test the exact screenshot-shaped corpus path through the real API and browser route. |

Regression evidence added:

- `apps/api/src/caseops_api/services/retrieval.py` - screenshot-shaped ASCII OCR fragment detection.
- `apps/api/src/caseops_api/services/authorities.py` - unreadable authority card suppression, readable-result backfill before final limit slicing, and contextual omitted-record coverage notice.
- `apps/api/tests/test_authorities.py` - API proof that the exact July 2 corrupted cheque dishonour authority is omitted when no readable preview exists.
- `apps/web/app/app/research/page.tsx` - defense-in-depth unreadable result filter and empty-state notice.
- `apps/web/app/app/research/page.test.tsx` and `apps/web/app/app/research/isGarbledSnippet.test.ts` - UI and detector proof for the July 2 OCR shape.
- `apps/web/components/app/MatterCockpitNav.tsx` - Notices tab registered in the matter cockpit.
- `apps/web/app/app/matters/[id]/notices/page.tsx` - notice-only list, summary counters, and notice-classified upload workflow.
- `apps/web/app/app/matters/[id]/notices/page.test.tsx` - notice listing and upload metadata regression.
- `tests/e2e/hari-2026-07-02-bugs.spec.ts` - browser proof for Context Research corrupted-content omission and Matter Notices upload.
- `playwright.app.config.ts` - July 2 Playwright regression registered in the normal app suite.
- `docs/BUG_REOPEN_LEARNINGS_2026-07-02_HARI.md` - root cause and permanent learning added.

Local verification on 2026-07-02:

- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/retrieval.py apps/api/src/caseops_api/services/authorities.py apps/api/tests/test_authorities.py` - PASS.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_omits_corrupted_authority_when_no_readable_preview_exists` - PASS, 2 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx app/app/research/isGarbledSnippet.test.ts "app/app/matters/[id]/notices/page.test.tsx"` - PASS, 13 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-07-02-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 2 tests.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-07-02-bugs.spec.ts --project app-chromium` - both browser tests passed, then the command hit a Windows web-server teardown timeout; the no-webserver replay above is the clean exit-code evidence.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-07-02_HARI.md`.

## Hari 2026-07-03 Matter Management Reopen Rules

- `BUG-003`: Matter edit is not fixed by an API route alone. The reported matter page must expose an editor, persist title/code/parties/case identifiers/status/forum/court/summary fields, reject duplicate matter codes, and show the corrected values after save.
- `BUG-004`: Multi-document download must be a selected-document ZIP workflow with tenant/matter scoping, deterministic archive names, row selection UI, selected count, browser download proof, and cross-tenant denial coverage.
- `BUG-005`: Notice upload must capture notice source, notice subject/about, date received, and reply/response as durable schema fields. The Notices page must display those facts, not only the uploaded filename.
- Every Hari workbook fix must update API schema/service tests, React UI tests, and a registered Playwright spec for the exact reported page flow.
- Do not mark a workbook item production-fixed until the deployed build has been re-tested with the supplied tester credentials or an explicitly created local equivalent when deployment has not occurred.

---

## Ram 2026-07-15 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bugs_Ram15Jul2026.xlsx`.
Detailed root-cause record:
`docs/BUG_REOPEN_LEARNINGS_2026-07-15_RAM.md`.

| ID | Severity | Classification | Formal verdict | Scope |
| --- | --- | --- | --- | --- |
| BUG-001 | Medium | Valid product enhancement | `Properly fixed` for the deployed July 15 scope; reconciled 2026-07-22 | Standalone tenant-wide Notice Management from main navigation; create received/sent notices independently with zero or multiple matter links, search/filter/assign/track, and retain secure file handling plus legacy matter-notice visibility. |
| BUG-002 | Medium | Valid workflow/policy enhancement | `Properly fixed` for the deployed July 15 creation-only scope; superseded by the July 22 policy | New matters default to Active and direct Active creation is allowed without mandatory conflict clearance. The historical July 15 contract retained the explicit Intake/On-hold activation gate; that clause is no longer current. |
| Lifecycle adjacent defect | High | Valid systemic defect | `Properly fixed` for the deployed July 15 lifecycle scope; conflict-gate clause superseded July 22 | Explicit terminal state machine, optimistic concurrency, dirty metadata PATCH, reason/capability/audit, reopen to Intake with prior clearance retained as historical evidence, and post-disposal operational/background guards. |

Pre-change production reproduction on the `legal` tester tenant:

- authenticated login succeeded;
- main navigation exposed zero Notice links and `/app/notices` returned 404;
- direct Active matter create returned 409 with the mandatory
  Intake/conflict-clearance message;
- generic Disposed PATCH returned 200 and read back as Disposed, demonstrating
  persistence but not protection from stale or background writers.

Required closure evidence for this batch:

- API tests for Notice independence/multi-link/security, Active create policy,
  lifecycle transition matrix/concurrency/side effects;
- React tests for the global Notice workflow, Active default, dirty-field edits,
  and explicit Dispose/Reopen actions;
- registered `tests/e2e/ram-2026-07-15-bugs.spec.ts` local proof;
- registered `tests/e2e/ram-2026-07-15-prod.spec.ts` deployed proof;
- exact deployed commit/build identity paired with each final verdict.

The rows above were reconciled on 2026-07-22 with the deployment and production
Playwright evidence recorded in `docs/BUG_REOPEN_LEARNINGS_2026-07-15_RAM.md`.
That historical evidence does not close the newer July 22 policy.

Historical local-candidate evidence captured before the later July 15
deployment, with final regression shards completed on 2026-07-16:

- complete 2,120-test API inventory collected and covered through three
  disjoint product-final-tree shards: 2,089 passed, 31 environment-gated skips,
  and 0 outstanding failures. One exact-text PG-001 documentation assertion
  exposed by the shards passed immediately after correcting only that ledger
  line. The 13 PostgreSQL-only tests executed separately on PostgreSQL 17;
  overlapping focused and shard run counts were not summed;
- fresh PostgreSQL 17 + pgvector suite: 13/13 passed after upgrade to head,
  including prior-revision legacy-child and provider-calendar tombstone repair;
- complete web suite: 115 files / 540 tests passed;
- Ruff lint across 490 in-scope Python files, TypeScript typecheck, optimized
  production build, strict dated-spec compilation, and single-head Alembic
  verification passed;
- `tests/e2e/ram-2026-07-15-bugs.spec.ts`: 3/3 passed against fresh local
  `legal` tenant data and the exact tester identity, using the production web
  build and no mocks;
- the complete run exposed and corrected three false-green patterns: dangling
  notification/custom-role foreign-key fixtures, legacy Matter PATCH callers
  missing mandatory CAS, and a test shortcut that created a terminal alias
  instead of using the lifecycle endpoint. Permanent controls now require valid
  parent fixtures, repository-wide mutation-call-site audits, and denial of
  terminal entry through create/import/generic PATCH;
- at that checkpoint, production execution was still pending. The later
  deployed-build identity and production Playwright closure are recorded in
  `docs/BUG_REOPEN_LEARNINGS_2026-07-15_RAM.md`; they close only that dated
  scope.

---

## Ram 2026-07-22 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bugs_Ram22Jul2026.xlsx`.
Detailed root-cause record:
`docs/BUG_REOPEN_LEARNINGS_2026-07-22_RAM.md`.

| ID | Severity | Classification | Formal verdict | Scope |
| --- | --- | --- | --- | --- |
| BUG-001 | Medium | Valid workflow/policy enhancement, not a regression against the July 15 creation-only contract | `Properly fixed` on deployed `34f19ad` | Conflict review remains optional and auditable. Missing, pending, conflicted, cleared, waived, invalid, stale-scope, and pre-reopen results must not block creation or an Intake/On-hold to Active transition. |

Why the bug appeared to reopen:

- July 15 exempted direct matter creation but explicitly kept the later status
  gate. July 22 expands the contract to all activation paths.
- Exact 409 tests, UI recovery copy, lifecycle documentation, public copy, and
  helper fixtures fossilized the older invariant, so changing only one service
  branch would be another shallow fix.
- Cases themselves do not reopen accidentally: the dedicated, capability- and
  CAS-gated lifecycle endpoint is still the only Disposed-to-Intake path.

Required closure evidence:

- API matrix for Intake and On hold with no check plus pending, conflicted,
  stale-party-scope, and pre-reopen results; every transition must persist and
  emit no conflict-gate denial;
- conflict scan, candidate review, clear/conflict/waive, tenant/access,
  performance, and audit behavior still works independently;
- React proof removes blocking guidance while keeping the optional card usable;
- registered local and production July 22 Playwright specs exercise final
  read-back with the tester account/local equivalent; and
- exact deployed commit/build identity is paired with the passing production
  run before changing `Inconclusive` to `Properly fixed`.

Local candidate evidence captured on 2026-07-22:

- canonical backend verification passed Ruff plus all 59 tests in the affected
  conflict, lifecycle, intake, and import files;
- three focused React files passed 19 tests, TypeScript passed, and the
  64-route production Next.js build passed;
- the combined July 15 and July 22 local Chromium run passed 5/5 in 20.5s with
  the shared exact local tester identity. The July 22 spec passed 2/2: the
  no-check Intake case in 1.3s and the controlled
  Dispose -> Reopen -> Historical-cleared -> Active case in 2.1s, including
  lifecycle-version/CAS assertions and final reload persistence; and
- before deployment, the extended production spec authenticated as the
  supplied tester and reproduced the prior build's legacy HTTP 409. The second
  serial controlled-reopen case did not run, while `afterAll` emitted no
  cleanup failure;
- exact commit `34f19ad2bc0a5b48398144998cf546cc9e7a815a` was deployed to API
  revision `caseops-api-00210-fnv` and web revision
  `caseops-web-00189-k9f`, with registry/runtime digest equality and 100%
  traffic proved independently; and
- the committed July 22 production spec passed 2/2 with the supplied `legal`
  tester account. GitHub run `29929098217` then passed both cases on the
  independent QA tenant, the RAM batch (46 passed, four expected conditional
  skips), and the notice module (2 passed).

The formal production verdict is `Properly fixed`. See
`docs/runbooks/release-signoff-2026-07-22-34f19ad.md`.

## Ram 2026-07-28 product-boundary and deployed lifecycle audit

Source workbook: `C:\Users\mishr\Downloads\Enhancements_Ram28Jul2026.xlsx`.
Permanent learning record: `docs/BUG_REOPEN_LEARNINGS_2026-07-28_RAM.md`.

| ID | Classification | Verdict | Evidence / action |
| --- | --- | --- | --- |
| Workbook rows 1-3 | Valid-looking Edumatica work items, invalid for this CaseOps repository | `Inconclusive` / out of scope | The modules and external URL are absent from this repository. No CaseOps implementation was made for an unrelated product. |
| ADJ-REOPEN-2026-07-28 | Valid deployed CaseOps lifecycle defect or deployment drift | `Inconclusive` | Local lifecycle code and local API/Playwright regressions pass; deployed `tests/e2e/ram-2026-07-15-prod.spec.ts:676` accepted pre-reopen conflict clearance with HTTP 200 and reactivated the Matter. Deploy the candidate, prove build identity, and rerun the same spec. |
| ADJ-NOTICE-FILTER-2026-07-28 | Suspected transient production filter failure | `Inconclusive` | First production replay showed an empty combined filter result; the second replay passed and a direct authenticated production API probe returned the filtered record. Keep the existing notice regression and monitor; do not claim a code fix from one flaky observation. |

Why cases were reopening: previous local evidence was allowed to stand in for
deployed-build evidence. The exact production lifecycle journey still allowed
old conflict clearance to reactivate a reopened Matter. This audit does not
upgrade the production verdict until the corrected candidate is deployed and
the dated production spec passes on a provable build.

## CaseOps BUG-001 — Ram 2026-07-28 Judge Aliases navigation

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bugs_Ram28Jul2026.xlsx`.

| ID | Classification | Formal verdict | Evidence / action |
| --- | --- | --- | --- |
| BUG-001 | Valid CaseOps UI/navigation bug | `Properly fixed` | `apps/web/components/app/Sidebar.tsx` now exposes `/app/admin/judge-aliases` with the `workspace:admin` capability gate. Local `tests/e2e/ram-2026-07-28-bugs.spec.ts` passed 1/1 and deployed `tests/e2e/ram-2026-07-28-prod.spec.ts` passed 1/1 on web candidate `7495bc6`, Cloud Run revision `caseops-web-00191-vn9`, 100% traffic. |
| DEPLOY-GATE-2026-07-28 | Valid adjacent release blocker | `Inconclusive` | `caseops-migrate-job-7mmw2` failed before API rollout because production references absent Alembic revision `20260723_0001`. The web-only fix was deployed; API traffic was not changed. |

The previous shallow failure pattern was also present in this row's shape: the
route and Admin landing-page link existed, so a direct-URL or page-only test
could pass while the actual main navigation remained broken. The regression now
starts at the shared desktop/mobile navigation primitive and proves the loaded
destination. The summary workbook records the item-level fix separately from
the release-level migration blocker.

## CaseOps BUG-001..004 — Ram 2026-08-14 Bulk Matter Upload

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bug_list_Ram14Aug2026.xlsx`.
Summary workbook: `C:\Users\mishr\Downloads\CaseOps_Bug_list_Ram14Aug2026_BugFixSummary.xlsx`.
Permanent learning record: `docs/BUG_REOPEN_LEARNINGS_2026-08-14_RAM.md`.
Fix commit: `6db34b64` (deployed) on `claude/bulk-import-ram-20260814`, PR #222.

| ID | Classification | Formal verdict | Evidence / action |
| --- | --- | --- | --- |
| BUG-001 | Valid CaseOps import/validation bug | `Properly fixed` | Forum values outside the alias tables leaked the raw pydantic Literal error to the user. Aliases expanded and unsupported values now return an actionable message. `tests/e2e/ram-2026-08-14-prod.spec.ts:286` PASSED on deployed `6db34b64` (rev `caseops-api-00289-l9g`); prod matter `RAM814-FAM` stored `forum_level=lower_court`. |
| BUG-002 | Valid CaseOps import/validation bug | `Properly fixed` | Bulk import was stricter than manual creation for the identical object; proved on production that `POST /api/matters/` accepted `tribunal` + free-text "DRT Delhi" while bulk rejected it. Categories now fail open to the canonical level, with scoped token matching retaining lineage on match. `tests/e2e/ram-2026-08-14-prod.spec.ts:286,352` PASSED on `6db34b64`. |
| BUG-003 | Valid, reported one layer off | `Properly fixed` | Duplicates were already excluded from creation; the defect was classifying them `invalid`. New `duplicate` row status is skipped and excluded from `validation_error_count`/`failed_count`, first-occurrence-wins so the original still imports. `tests/e2e/ram-2026-08-14-prod.spec.ts:409` PASSED on `6db34b64`. |
| BUG-004 | Valid in part | `Properly fixed` | Header aliases accepted a bare name column while resolution was email-only. Owner/lawyer now resolve by unique full name too; ambiguous names rejected, not guessed. `tests/e2e/ram-2026-08-14-prod.spec.ts:467` PASSED on `6db34b64`. |
| ADJ-TEAM-SCOPING-2026-08-14 | Not a defect | n/a | "Matter owner must belong to the assigned team" also fires on manual creation (`services/matters.py:1376`). It is a scoping control; only the message was made actionable. Deliberately not weakened. |
| ADJ-DEPLOY-COLLISION-2026-08-14 | Valid release-process defect (self-inflicted) | `Properly fixed` | Deploying migration-bearing `6db34b64` from an unmerged branch applied `20260814_0001` to production and failed the concurrent `f24d5aff` migrate job (`caseops-migrate-job-2kg2t`) with `Can't locate revision identified by '20260814_0001'`. Resolved by merging PR #222 so the revision rejoins the chain. `alembic_version` was never hand-edited. |

Why this case reopened: the 2026-08-11 prevention rule 5 specified strictness
in one direction only and was implemented as a three-family allowlist, making
bulk import stricter than the manual path it was meant to match. That rule is
now annotated as superseded in place. Two structural guards close the class:
`test_bulk_import_is_never_stricter_than_manual_creation` and
`test_every_forum_the_template_offers_can_actually_be_imported`.

## CaseOps BUG-007..009 - Ram 2026-09-04 providers and Bare Acts

### Alias administration discovery follow-up on 2026-09-05

The final evidence audit found that the committed forum-alias administration
spec was absent from the app config inherited by Docker acceptance. Earlier
green runs prove ordinary alias resolution, not administration CRUD. Explicit
discovery exposed an invalid reserved-domain fixture email before the browser
could reach the feature. The correction aligns the host and isolated Docker
founder identity, uses the configured browser base URL, and adds mobile
deactivation/reload plus ordinary-owner API/UI denial. A contract regression
protects discovery and Docker fixture propagation. Synthetic global catalog
writes are loopback-only; production must not acquire invented legal aliases
for test convenience. Existing API coverage independently checks audit events.
Verdict: `Inconclusive` until the corrected dated test and complete clean Docker
inventory pass. Final release evidence must distinguish local admin CRUD from
production resolution using existing reviewed catalog data.

The executed journey also found a real mobile overflow: an absolute accessible
Actions heading escaped its table's clipping ancestor (914 px document width
at a 360 px viewport). Positioning the scroller restored 360 px in a direct
Docker browser experiment. The permanent regression preserves the column's
accessible name and checks six viewport/breakpoint widths. This layout fix
remains below production closure until the exact release is verified.

Final local acceptance passed at fingerprint
`f80dc83d2c7d031ba73c91abf6356eaea01121b95806fe88ecf7f7929dff1256`:
120 PostgreSQL tests, 190 desktop journeys, four mobile journeys, 825 web unit
tests, and 67 deployment contracts. Five explicit local provider/release skips
are excluded from pass counts. Both alias-admin journeys passed, including all
six viewport widths. This append is documentation only. Production curator
CRUD is not inferred from local synthetic aliases or ordinary production
resolution; exact-main CI, deployment and production verification still gate
the final release.

### Recurring verification follow-up on 2026-09-05

Scheduled production run `33941782162` passed 108 tests but failed two private
QA journeys after the first release run had correctly disposed their shared
canary. This is a valid verification-lifecycle defect. The follow-up uses the
persistent Intelligent Review target and adds affirmative retained-revocation
proof for later runs. The initial release still exercises the complete private
answer-and-dispose workflow. Clean Docker fingerprint
`22566e7821eeecfa6cefef122a3ec2399999fca5abaf8b838329cdbcd6295441`
passed 120 PostgreSQL tests, 188 desktop journeys and four mobile journeys,
with five explicit provider/release skips. Retained revocation ran twice through
the real local endpoints. Both repaired production journeys then passed against
serving release `c0d3874e55ba00d35cf498f6eb9c9393f2e404b0`, without reopening
the terminal fixture. All 11 browser-workflow contract tests also passed.
This evidence-only addition changes no tested runtime or browser input.
Verdict remains `Inconclusive` until final PR/main CI and exact-release first-run
plus repeated-run deployment proof pass; the final release record must name both.

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bugs_Ram04Sep2026.xlsx`.
Enhancement source:
`C:\Users\mishr\Downloads\CaseOps_AI_Bulk_Upload04_Sep2026.docx`.

The populated Bug Sheet contains three authoritative rows. Its Summary tab says
four bugs with two High and two Medium; that copied summary is stale and must
not be used as the issue count.

| ID | Classification | Current verdict | Candidate correction |
| --- | --- | --- | --- |
| BUG-007 | Valid paid-provider access/accounting bug | `Properly fixed` | eCourts human search, refresh, scheduled refresh, and source download use tenant/provider budget reservations and provider-keyed billing. Exact-release production proved readiness, the explicit automation boundary, provider contribution versus shared-account spend, and unchanged spend after blocked automation calls. |
| BUG-008 | Valid Bare Act detail/coverage bug | `Partially fixed` | Every catalogued section now opens a truthful detail and Act-source surface, and verified provisions remain selectable. Exact official section text is still unavailable for unverified catalog rows; completing that governed source-verification data is not honestly a closed content-completeness claim. |
| BUG-009 | Valid paid-provider access/accounting bug | `Properly fixed` | Licensed Indian Kanoon human retrieval uses the same shared account budget and billing report. Exact-release production proved provider readiness and balance reads without an external probe, blocked automation transport, and unchanged provider and account spend. |
| ENH-FORUM-2026-09-04 | Valid court hierarchy and bulk-upload enhancement | `Partially fixed` | Manual and bulk flows now share reviewed aliases and contextual ambiguity handling for the supplied Delhi examples. All-India reviewed alias completeness remains open and is not replaced by guessed parser mappings. |
| ADJ-LIFECYCLE-2026-09-04 | Reported matter reopening risk plus valid adjacent disposal defect | `Properly fixed; no unauthorized reopen reproduced` | Production persisted disposal/reopen state and audit events prove that only the lifecycle endpoint performs `Disposed -> Intake`. The real adjacent defect was a disposal rollback during concurrent failed-shadow cleanup; generation-scoped projection mutation and the PostgreSQL race regression now prevent it. |

Required closure evidence:

- one fresh local Docker run covering migration, PostgreSQL/index checks, API,
  web, and the registered dated browser journey;
- exact-main CI, security, and production deployment;
- production nonbillable provider checks proving unchanged spend before/after;
- production verification of both named companies' two active unlimited policy
  rows; and
- persisted lifecycle state plus audit evidence, not inference from UI labels.

Follow-up release evidence on 2026-09-05:

- deployed candidate `7734ec35` passed canonical CI, security, provider-policy,
  live-provider, and persisted lifecycle audits, but exact-release production
  workflow `33923480806` remained red and therefore did not close these rows;
- the production Matter-disposal 500 was a valid adjacent defect: concurrent
  failed-shadow cleanup deleted a shadow projection already loaded by the
  lifecycle ORM session, and the resulting `StaleDataError` rolled back the
  authoritative disposal;
- the correction limits ordinary event mutation to the event's captured active
  generation, retains all-generation tenant disposition as a set-based wipe,
  fences shadows by epoch, and reconciles ambiguous mutation response loss
  without replay; and
- clean local Docker validation passed on source fingerprint
  `7711f0f2478379a69f0b48b0cbd3615bbe5bdcd9c23b5127ade88cae1ffca370`:
  120 PostgreSQL/pgvector tests, 186 desktop Playwright tests, and four mobile
  Playwright tests passed; five provider/release-gated tests were intentionally
  skipped. The complete network-independent API inventory also passed 3,923
  tests across 13 disjoint file shards with 147 explicit environment-gated
  skips, and all 824 web unit tests passed. Current exact-main CI,
  redeployment, production Playwright, and two quiescent private-projection
  maintenance cadences remain required.

Final closure evidence on 2026-09-05:

- PR #454 passed all required checks and merged as
  `c0d3874e55ba00d35cf498f6eb9c9393f2e404b0`; fresh push CI run
  `33932463982` completed with 19 successful jobs, while Security
  `33932463979` and CodeQL `33932463969` also passed;
- the canonical deploy built immutable API digest
  `sha256:2d48717660938c7e7cf17e4ce093bde10f942a549a8564a461765a7fac9f8469`,
  applied migration execution `caseops-migrate-job-5rbs6`, passed index-health
  execution `caseops-db-index-health-npz9x`, and routed API revision
  `caseops-api-00442-n4p` plus web revision `caseops-web-00419-r76` at 100%
  latest-only traffic;
- exact-release production workflow `33934998564` passed 110 canonical browser
  journeys, the dedicated cost acceptance, and two notice journeys. It included
  persisted lifecycle/audit reads, the Matter disposal path, statute trust,
  provider readiness, and foreign-associate response reconciliation;
- the separately opted-in no-paid-provider production spec passed against the
  supplied test tenant. It compared provider contribution and shared-account
  budget spend independently and proved both stayed unchanged after eCourts and
  Indian Kanoon automation calls were rejected before transport;
- read-only execution `caseops-provider-policy-audit-c0d3874-qs5mf` proved four
  active unlimited rows: both providers for GBA Law Office and both providers
  for Pinelabs Pvt. Ltd. The disposable audit job was deleted afterward; and
- quiescent maintenance execution
  `caseops-private-projection-maintenance-hjblt` rebuilt the alerted tenant with
  zero blockers and `release_blocked=false`. Execution
  `caseops-private-projection-maintenance-n8chm` and resumed scheduler executions
  `j2q6v` and `nc7fr` were clean steady-state cadences with `rebuild_count=0`,
  no pending or failed events, and `release_blocked=false` for all four tenants.

## CaseOps ECOURTS-RESP-001 - eCourtsIndia success rendered as stale data (2026-09-15)

Report: wherever CaseOps calls eCourtsIndia (reference route
`/api/partner/case/DLND020389022025`), the provider succeeds but the UI keeps
showing old case data.

Reproduction against serving release `f4f39eb257fb17b12a103e17939de72debdfd71d`:

- production logs on 2026-09-15 03:24-03:43 UTC show the provider returning
  `HTTP/1.1 200 OK` (and `404`) while CaseOps answered
  `POST /api/case-tracking/bookmarks/{id}/refresh` and
  `POST /api/case-tracking/search` with `502` in under 0.7 s; later refreshes
  returned `429` because the failure was stored as transient `provider_error`;
- the live provider now sends `Content-Encoding: br`/`gzip` behind Cloudflare
  when the client advertises it (httpx does by default);
- the adapter streamed and decoded the body, then rebuilt an `httpx.Response`
  that still carried `Content-Encoding`, so httpx decoded plain JSON a second
  time and raised `DecodingError`. The unmodified adapter reproduced this
  against the live, free refresh-status endpoint; the fixed adapter decoded it.
  The real case payload for the reference CNR parses correctly once decoded.

Root cause and scope: one buffering defect in
`apps/api/src/caseops_api/services/case_tracking_providers.py` shared by case
detail, search, manual refresh, scheduled bulk refresh/status and source
download. Every eCourts-backed surface (Case Tracking search/refresh, matter
auto-link, scheduled next-hearing sync, source download) was affected.
Adjacent UI defect: the Case Tracking page never rendered a failed refresh and
did not reload the bookmark after failure, so the row silently kept stale data
and an enabled Refresh button.

Correction:

- buffered provider responses drop `Content-Encoding`, `Content-Length` and
  `Transfer-Encoding` after decoding, for both JSON and source downloads;
- the Case Tracking page shows refresh and bookmark-update errors and reloads
  case-tracking data after a failed refresh;
- the Docker acceptance eCourts emulator now gzip-compresses for clients that
  accept it, so local acceptance exercises the live CDN contract.

Regression evidence:

- `apps/api/tests/test_20260915_ecourts_compressed_responses.py`: gzip, deflate
  and zstd detail/search/404, scheduled bulk refresh, source download, emulator
  compression, and a route-level refresh that replaces stale bookmark data. All
  8 original tests failed on the unmodified adapter (refresh returned the exact
  production 502 body) and pass with the fix;
- `apps/web/app/app/case-tracking/page.test.tsx`: failed refresh is shown and
  the bookmark reloads; fails without the page change, passes with it.

Release evidence on 2026-09-15:

- PR #463 merged as `3c23288380bbe9d9d8133ebabbd73e21685428da`; its tree is
  identical to Docker-certified candidate `da39d1f6` (tree `6ba00a0e`). CI on
  `da39d1f6` passed 33 checks after one rerun of an unrelated private-retrieval
  timing assertion that passed 3/3 locally;
- `scripts/verify-docker.ps1` printed `PASS da39d1f6`: 388 PostgreSQL tests,
  191 and 187 desktop journeys and 4 mobile journeys, with 6 explicit
  production-identity or Pine Labs provider skips;
- `scripts/deploy-prod.sh` routed API revision `caseops-api-00453-xk8` and web
  revision `caseops-web-00430-5pn` at 100% on `3c23288`, completed the migrate
  job and index-health execution `caseops-db-index-health-gnqmh`;
- the exact deployed API image
  `sha256:d25343471bc9a56e751cc0f2cbf391b29268a9309a60d46e2f8fe413a3faa51a`
  (revision label `3c23288`) decoded a live gzip reply from the free
  eCourtsIndia refresh-status endpoint; the previous source failed the same
  probe with `DecodingError`;
- exact-release prod verification run `34947405170` succeeded with 261 passed,
  0 failed and 7 pre-existing data/capability skips, including provider
  freshness, tracked-case source evidence at 360 px, transient case-tracking
  recovery and zero-spend automation. The first dispatched run `34942342996`
  was cancelled at its 55-minute limit after intermittent BUG-010 timeouts at
  two viewports (the 768 px variant passed); it is not counted as evidence.

Production end-user evidence on 2026-09-20, release `3c23288` serving since
2026-09-15 07:31 UTC:

- zero `502` responses on any `/api/case-tracking/*` route in five days. The
  reported symptom is gone from production;
- provider transport in the API service logged 65 x `200`, 10 x `404` and
  2 x `500`; the `200` bodies are compressed and now decode once;
- real browser users (non-automation source addresses) ran 37 manual refreshes:
  13 x `200` across six bookmarks, 2 x `404`, and 22 x `409` across eighteen
  bookmarks. One bookmark returned both, so the failure is per tracked case,
  not global;
- the scheduled 18:00 Asia/Kolkata poll job ran its five-minute cadence with
  `exit(0)` and no warning or error output.

Verdict for the decoding defect: `Properly fixed`. Provider success now reaches
the tenant instead of failing closed, proven by the deployed-image live probe,
the exact-release production suite, and five days of production traffic with no
`502`.

Verdict for the reported user workflow: `Partially fixed`. A distinct failure is
now visible for the same user action. On 2026-09-19 17:41 UTC two refreshes on
separate bookmarks each logged a provider `200 OK` followed by CaseOps `409`,
and eighteen bookmarks are in that state. A `409` on this route after transport
comes only from `ambiguous_match`, `concurrent_refresh` or
`match_validation_failed`, so the identity verification in
`_verified_sync_snapshot_identity` or the linked-Matter recheck in
`apply_snapshot` is rejecting a provider record the tenant expects to accept.
That guard exists to stop one case's hearing date being written onto another
matter, so it must not be loosened blindly. The 2026-09-03 registration-versus
filing-number correction is the nearest known cause family.

Next step: read the exact `response_class` and `last_error` for one affected
tracked case (both are already returned by `GET /api/case-tracking/bookmarks`
and rendered on the page after the error-surfacing change), then reproduce that
exact identity shape in a dated regression before changing any matching rule.
Do not close this row while eighteen bookmarks cannot refresh.
# 2026-09-24 — Ram workbook and lifecycle checkpoint

The 22 populated BUG-010..BUG-031 rows plus two DOCX proposals are reconciled
in `docs/bugfix-ram24sep-2026.md` and the sanitized workbook
`C:/Users/mishr/Downloads/CaseOps_Bug_Fix_Summary_2026-09-24.xlsx`. Candidate
`86886a5f` is local-only and production remains **NO-GO**. Docker evidence is
388 PostgreSQL tests passed and a separate focused Playwright run 2/2; the full
Docker harness did not pass as one invocation, and production exact-SHA browser
verification is absent. No reported Matter reopening is established without
its persisted lifecycle version and ordered audit events. Do not interpret a
hearing-date update or private-projection maintenance blocker as a lifecycle
transition. See the dated report for row-level verdicts, failed-run history,
remaining eCourts/DOCX scope, and root-cause learnings.

## 2026-09-25 — legacy hearing release-bound incident

PR #470 merged as `9835f11e` after complete Docker acceptance (389 PostgreSQL,
both desktop shards and mobile) and clean CI. The exact-image production deploy
stopped before routing at `caseops-backfill-next-hearings-ptgdk`: the 500-row
per-tenant cap was derived from a 52-row fixture, while one production tenant
had about 1,073 eligible legacy dates. The first 500 committed and the job
failed closed. A read-only diagnostic measured 940 remaining across three
tenants (573, 363, 4); no provider was called. Both schedulers were resumed
after the failed release, and serving API/web remained at the older revision.
The follow-up candidate preflights the shared eligibility predicate before any
new writes, requires a zero-remaining postflight after every tenant (including
a short SKIP LOCKED page), allows 2,500 per tenant and 10,000 release-wide,
gives the bounded job 30 minutes, and adds a 1,200-row PostgreSQL replay
regression. These are
candidate changes only until complete Docker, clean CI, canonical-main merge,
exact-image deploy, and production Playwright all pass. The partial backfill is
not a deployment claim or an end-user fix verdict.

An independent review of `57e7ee38` stopped the release despite its 390/390
PostgreSQL pass: the legacy selector ignored terminal same-date hearings while
the shared helper could rewrite one to `scheduled`; a short page could also
mask later writes, and membership-based enumeration could miss an active firm.
The candidate now excludes every existing same-date hearing from backfill,
preserves terminal rows during unchanged-date repair, uses active company IDs,
bounds actual writes, and runs a final cross-tenant recount. PostgreSQL tests
cover production volume, terminal statuses, a memberless active company and a
real new-date schedule; unit tests cover live-growth boundaries. The earlier
Docker browser shard was intentionally interrupted, not accepted. Full Docker
and CI must be rerun on the changed commit before merger or deployment.

## 2026-09-25 — BUG-006 / ENH-007 bulk update production history

`tests/e2e/ram-2026-09-21-bugfixes.spec.ts` (BUG-006 DOCX / ENH-007 bulk update)
passed in local Docker but failed on `tester-prod-chromium`. Two separate
causes, classified from the retained Playwright snapshot and Cloud Logging:

- **Release `91719e47`, run `36091367446`, line 217 (no apply toast).**
  `POST /api/matters/bulk-update/apply` and `GET .../history` returned 500 on
  `caseops-api-00463-2qp` (04:16:16 UTC): `UndefinedColumn
  matter_bulk_update_operations.row_results_json`. Revision `20260924_0001` had
  reached production before the column was added to it. Repaired by
  `20260925_0001_bulk_update_row_results_repair` (PR #475); apply and history
  have returned 200 since `caseops-api-00464-9wd`. Schema drift, now closed.
- **Release `65a9c5b0`, run `36112912771`, line 225 (row results missing).**
  Not a missing row payload. The failure snapshot shows two
  `matter-bulk-update.csv` operations in the persistent QA tenant: this run's
  (08:53:51, `BULK-UPDATE-CASEOPS-03B0EA45`) and a retained one from 07:49:13
  (`BULK-UPDATE-CASEOPS-CC8B10B4`). The spec asserted the filename cell before
  the post-apply history refresh arrived, so only the retained row matched.
  `.first()` then expanded the retained operation's results; the new row
  appeared above it afterwards. Docker never reproduced this because every
  local run bootstraps a fresh tenant with no history.

Adjacent defects fixed in the same change: operations that share a filename had
identical accessible action names (`View results for <file>`), and a slower
initial history read could overwrite the history fetched after an apply,
dropping the just-applied operation from the table (reproduced in a unit probe
against the unfixed page: 2 rows → 1). The page now applies only the most
recently issued history read, labels each action with its upload time, and
marks the row matching the apply response as `This upload` (`aria-current`).

Regression coverage: PR #478 independently gave each run a unique upload
filename, so other runs' retained history cannot collide. This change keeps that
per-run filename and seeds a retained operation with the same name through the
public API before the browser journey, in every environment. The spec then
follows the exact `operation_id` from the apply response, asserting that row's
two results, that the retained row stays collapsed, and the per-operation
download filename. Action labels include the operation ID, so two same-name
uploads in one displayed second stay distinguishable. `page.test.tsx` adds the
production-shape unit case. No assertion was relaxed; filename- and
position-based selection was replaced by identity.

Evidence, 2026-09-26:

- PR #479 (head `6d93d993`) was merged to `main` as `61de35a4`. Full Docker
  acceptance on `6d93d993` returned `PASS`: 396 PostgreSQL tests passed, and
  Playwright passed 202 + 196 desktop (1 + 7 skipped) and 4 mobile.
  `ram-2026-09-21-bugfixes.spec.ts:129` passed in `app-chromium`. The skips are
  one provider-gated payment link and seven assertions that apply only to the
  exact production release.
- Two earlier Docker attempts are retained as incomplete. Attempt 1 failed
  before any test when PostgreSQL missed its healthcheck while another
  acceptance stack was loading the host. Attempt 2 was stopped during the image
  build.
- A Docker replay of the pre-fix spec against the unfixed revision was not run.
  The original defect is evidenced by the production snapshot of run
  `36112912771` and by the unit probe against the unfixed page.
- Release `b1ffd1c7` (API `caseops-api-00467-dw6`, web `caseops-web-00444-dxr`)
  contains `61de35a4`. Exact-release prod-verify dispatch `36175978724`, job
  "Prod Playwright (tester)", passed
  `tests/e2e/ram-2026-09-21-bugfixes.spec.ts:129` in `tester-prod-chromium` on
  its first attempt (27.3 s, no retry). The job totalled 94 passed and 5
  skipped; the skips are the standing BUG-012 and 2026-09-24 production items.

Verdict: **Properly fixed**, proven by
`tests/e2e/ram-2026-09-21-bugfixes.spec.ts:129` passing on release `b1ffd1c7`
in prod-verify run `36175978724`.

## 2026-09-26 — Ram workbook (IV): BUG-032, BUG-033, BUG-034

Source `CaseOps_ai_Bugs(lV).xlsx`, three populated rows, all valid. Root-cause
report: `docs/bugfix-ram26sep-2026.md`. Permanent rules: `AGENTS.md`
(2026-09-26 entries). No credentials are reproduced in the repository.

- **BUG-032 (High):** Case Tracking called a Matter's own eCourts case "Does not
  match this Matter". Two identity policies existed for one decision: the manual
  search/resolve/link matcher rejected a CNR-identical case on free-text court or
  party wording, while refresh, polling and next-hearing sync accepted it on its
  CNR. Every path now calls `identity_matches`; the signed selection carries the
  provider's published matching identity; results list visible Matters that
  already record the CNR, and the page shows "Linked to this Matter" / "Open
  matter". Review additions: a CNR-less Matter must carry a typed case number
  before it can be linked manually (registries reuse numbers across case types),
  and the existing-Matter SQL key drops every non-alphanumeric character.
- **BUG-033 (Medium):** cause list PDF text overlapped columns. Fixed-width
  single-line fpdf2 cells summed to 199 mm on a 190 mm page, nothing wrapped,
  values were cut at 32 characters, and a non-Latin title raised
  `UnicodeEncodeError`. New `services/pdf_layout.py` (wrapping table, wrapped
  pairs, safe font class); landscape A4 with a Date column and "Page N of M".
  Audit found and fixed the same defects in the matter invoice (unwrapped line
  items; a `multi_cell` that drew the Matter line off the page). Guards reject a
  bare `FPDF` or a `multi_cell` without `new_x`.
- **BUG-034 (Medium), reopened:** Tasks & Deadlines fields collapsed. The
  2026-09-24 change used a viewport breakpoint with `minmax(0,1fr)`; at xl the
  two cards share a row and the title column shrank to about 20 px; its proof
  measured a 600 px viewport where the defect cannot occur. Forms are now sized
  by their card with container queries. A product-wide form-layout guard sweeps
  every page in the product's own navigation and every Matter tab at four widths;
  its first run found the portal invite form 397 px wide on a 390 px phone
  (fixed on the form and with a base rule `select { max-width: 100% }`).

Evidence to date (PR #487):

- Unfixed-commit reproduction in a checkout of `dd07291e`: the six identity
  tests and both cause-list layout tests failed for the reported reasons
  (missing link token for a CNR-identical case; glyphs crossing column borders;
  `UnicodeEncodeError`).
- Fixed: identity 7/7 and PDF layout 9/9 on SQLite; on Docker PostgreSQL the
  hearing-matching races 24/24, access reviews 18/18 and identity 7/7. A first
  link recheck that was stricter than search broke 16 PostgreSQL races and was
  removed before merge. Web typecheck, e2e typecheck, case-tracking and admin
  page tests, 12/12 contract validators, OpenAPI client regenerated and matching.
- Playwright against the Docker stack: the BUG-032/033/034 journeys pass; the
  layout sweep passes at 1280/1440/1920 px and, on the pre-fix image, flags only
  the portal invite form at 390 px. Full Docker acceptance on `f10faba8`: the
  PostgreSQL suite passed 403/403; desktop shard 1 failed one 2026-05-30
  case-tracking journey whose search mock omits the new optional
  `existing_matters` field and crashed the page. The row now tolerates the
  omission; the run is repeated on the corrected commit.
- Full Docker acceptance on the final commit `1a5ab9d4`: PostgreSQL 403/403;
  app-chromium 208 passed/1 skipped and 197 passed/7 skipped (standing
  provider-gated and exact-production-release skips); app-mobile 4/4; the dated
  spec 7/7, repeated signed in as the tester-supplied account recreated in local
  Docker with its password supplied only through the process environment.
- PR #487 merged to `main` as `2febd211`; CodeQL reports 0 open alerts on
  `main`. Deployed 2026-09-27: API `caseops-api-00470-msx`, web
  `caseops-web-00447-8sw`, both reporting `2febd211`.

Production run 1, 2026-09-27 (run 36276564868 on `2febd211`): **failed**, two
tester tests. Analysis in `docs/bugfix-ram26sep-2026.md` ("Production run 1").
Neither was a product regression: the BUG-032 production branch asserted the
blocked-provider body as `detail.code` (the API puts `code` at the top level;
the branch had never executed before release), and the 2026-09-24 QA journey's
fixture `WP(C) <hex>/2026` parsed only when its hex slice ended in a digit
(62.5% of runs; `public_number` was identical on both releases). Fixes: shared
`expectPaidProviderBlocked` helper plus a pytest pinning the exact request and
body; registry-shaped fixture; and, product-wide, `identity_gap` so search,
resolve and link tell the user which of invalid CNR, missing identifiers,
unreadable case number or missing case type to correct, with the recorded value,
and a parser that reads `No.`/`of`/hyphen spellings of one case identity while
rejecting compound entries. Review of that change (P1) found automatic linking,
the scheduled backfill and the refresh/polling of automatic links still accepted
a bare number; a reproduction on `452ae52d` re-pointed a `WP(C) 6209/2019`
Matter to the provider's only `CRL.A. 6209/2019` result and wrote its hearing
date. Every path that establishes or keeps a case from a Matter's identity now
calls `identity_gap` before any provider spend; existing bare-number automatic
links stop refreshing with the case-type reason (recorded contract change). New
tests: `test_20260927_case_identity_readability.py` (49 cases; the automatic-path
regressions fail on the pre-fix commit), its PostgreSQL wrapper (9 cases) and the dated journey "a Matter that
cannot be matched is told exactly what to record". Maintenance cadence remained
paused until the green production run 3 recorded below.

PR #488 merged to `main` as `1c617a31` after full Docker acceptance on
`6f04de37` (PostgreSQL 412/412 including 9 new PostgreSQL proofs; app-chromium
208 passed/1 skipped and 198 passed/7 skipped; app-mobile 4/4) and the dated spec
8/8 as the tester-supplied account. Deployed 2026-09-27: API
`caseops-api-00471-n4q`, web `caseops-web-00448-rbl`, both reporting `1c617a31`.

Production run 2, 2026-09-27 (run 36291638337 on `1c617a31`): **failed**, two
tester tests; legacy and supporting shards passed. With `--retries=0` against the
serving release, the reported rows passed: BUG-034 (`:125`), BUG-033 (`:161`) and
BUG-032 (`:225`), and the 2026-09-24 QA journey passed with its corrected fixture.

- The new identity-gap journey (`:286`) failed on its own fixture: it created a
  Matter with the fixed number `6209/2019`, the production tenant already held
  that number, and the duplicate-case rule counts disposed Matters, so cleanup
  never frees a number. BUG-033's journey drew from 9,000 values and would
  collide the same way as runs accumulate, and the Docker-only BUG-032 journey
  (fixed emulator CNR) reused one case number, which failed its second pass as
  the tester-supplied account. All three now use clock-plus-serial registry
  numbers (a CNR still decides the BUG-032 case); the unreadable entry is
  unreadable by construction. The pre-fix journey was reproduced failing with
  the same 409 on its second pass in one retained local tenant; the fixed
  journeys pass twice there and twice more as the tester-supplied account in a
  Docker tenant already holding every earlier run's Matters.
- `iplf-063b-intelligent-review-2026-08-28-prod.spec.ts:140` failed because
  `GET /api/research/reviews?limit=50` took 32.4 s. Cloud Run logs show a new API
  instance starting at that moment (ClamAV sidecar ready after 8 startup-probe
  attempts, application ready about 26 s after the request): on the
  concurrency-one service with four warm instances, the page's concurrent
  requests and CORS preflights exceeded warm capacity and the list request
  waited for the cold instance. The same endpoint took 39 s on 2026-09-25 and
  normally takes 1.5-4 s (an N+1 manifest check per review). Unrelated to the
  three reported rows; recorded as a separate capacity finding, not retried away.

PR #489 merged to `main` as `328761c5` after full Docker acceptance on
`3ca13371` (PostgreSQL 412/412; app-chromium 208 passed/1 skipped and 198
passed/7 skipped; app-mobile 4/4; the dated spec in full) and the four bug
journeys passed twice as the tester-supplied account in a Docker tenant already
holding every earlier run's Matters.

Production run 3, 2026-09-27 (run 36301223622 on `328761c54ffc9d48522aae2fe3e2865086e5ed57`): **passed**.

- `scripts/deploy-prod.sh 328761c5` from a detached worktree of `origin/main`
  (preflight: head = merge commit, no local changes, no ongoing builds, no
  active production verification): images built, migrations applied,
  exact-image legacy hearing materialization and catalog seeds executed,
  latest-only traffic routed to API revision `caseops-api-00472-5p5` and web revision
  `caseops-web-00449-lqt`. `/api/build` and `/api/release-identity` report `328761c54ffc9d48522aae2fe3e2865086e5ed57`.
- `prod-verify.yml` with `expected_release_sha` = the release succeeded in every
  shard (tester, legacy, supporting, patent-statute). The tester project ran
  with `--retries=0` against the serving release (98 passed, 9
  skipped by design): `ram-2026-09-26-bugs.spec.ts` BUG-034 (`:134`), BUG-033
  (`:170`), BUG-032 (`:234`) and the identity-gap journey (`:298`) passed; the
  layout sweep is a local Docker acceptance test and is skipped in production by
  design. The 2026-09-24 QA-owned matter journey passed. The QA tenant sends the
  no-paid-provider marker, so the BUG-032 production journey asserts the 409
  `paid_provider_blocked_for_test` rejection, not a provider search.
- Private-projection maintenance re-certified after the release-owned QA
  mutations: execution `caseops-private-projection-maintenance-pvwnm` converged and execution `caseops-private-projection-maintenance-wsksk` was a clean
  no-rebuild cadence; the maintenance scheduler was resumed on the exact API
  image for release `328761c5` (`--qa-run-id 36301223622`).

Verdicts:

- **BUG-032: Properly fixed.** Search, resolve, link, automatic linking and
  backfill, refresh, polling and next-hearing sync share one identity decision,
  proven on SQLite and PostgreSQL, including the automatic-path regressions that
  fail on the pre-fix commit, and the browser journey passed in Docker on the
  exact image and repeatedly as the tester-supplied account. Because automated
  production runs may not spend provider credits, the reported search was then
  observed directly on the deployed release on 2026-09-27, 13:30-13:32 UTC, in a
  browser session the owner signed in as the tester (`test-legal`), with the
  exact reported input. `/api/release-identity` reported `328761c5`
  (`caseops-web-00449-lqt`) and `/api/build` `caseops-api-00472-5p5`.
  - Inside Matter 5695 ("SATISH KUMAR MEHANI VS PUNJAB NATIONAL BANK", CNR
    `DLHC010317282019`, court "Delhi High Court"), a search of the CNR returned
    "Satish Kumar Mehani v Punjab National Bank & ORS. / DLHC / Pending / AFTER
    NOTICE MISC. MATTERS / Next hearing: 2026-12-01" with **Link to Matter**; the
    page contained no "Does not match this Matter", although the provider's
    court and party wording differ from the Matter's.
  - Outside the Matter, the same search showed "Existing matter: 5695 - SATISH
    KUMAR MEHANI VS PUNJAB NATIONAL BANK" with **Open matter**, which opened
    `/app/matters/02b4a35b-55c8-478b-b6ea-f1f5f9071412`.
  - The API request log records both searches: `POST /api/case-tracking/search`
    200 at 13:30:53 and 13:31:44 UTC on `caseops-api-00472-5p5`. The Matter was
    not linked during the check, so no tester data changed.
  - How the proof is split, deliberately: `AGENTS.md` forbids automated suites
    from making credit-bearing provider calls and establishes provider-paid
    operation through authenticated human use, so no committed production test
    can repeat this paid search. Repeatable regression coverage runs on every
    release instead: the identity suite on SQLite and PostgreSQL with the
    reported wording, the Docker browser journey on the exact image, and the
    production no-paid gate. This recorded human-use observation is the
    deployed-release confirmation of the paid path.
- **BUG-033: Properly fixed.** Glyph-position assertions and the pdf.js browser
  check show every value inside its own column on the deployed release.
- **BUG-034: Properly fixed.** Container-query sizing verified at seven widths
  from 390 to 1920 px, including the xl split layout where the 2026-09-24 fix
  had collapsed; the product-wide form-layout sweep is retained in Docker
  acceptance.
- Not claimed: the Intelligent Review cold-start latency recorded under
  production run 2 is a separate capacity defect with its own task.

## 2026-09-28 — Docker acceptance ran another checkout's browser suite

Docker acceptance for PR #501 was started as
`powershell.exe -File C:\Users\mishr\caseops-acceptance\docker-c4eec853\scripts\verify-docker.ps1`
from a different, older CaseOps checkout
(`C:\Projects\CaseOps\caseops\.claude\worktrees\trusting-clarke-7b3987`, `328761c5`).
The images, the stack and the complete PostgreSQL + pgvector suite came from
`c4eec853`. Every later step that resolved paths from the working directory
used the older checkout instead:

- `npm ci` reinstalled that checkout's `node_modules`, and `npm run typecheck:e2e`
  type-checked its specs.
- `npx playwright test --config playwright.docker.config.ts` loaded its config,
  specs and support helpers.
- Its helpers imported that checkout's unsynced venv
  (`ModuleNotFoundError: No module named 'sqlalchemy'`): 63 failed and 145 passed.
- `test-results` was written into that checkout.

The run failed, so nothing was certified. Had the older specs passed, the
harness would have printed `[docker-acceptance] PASS c4eec853...` for browser
evidence from another source: the candidate-source guard fingerprints only
`$RepoRoot`. The failed log and its `test-results` are retained with the run's
evidence. #501 was re-certified from inside its own acceptance worktree.

Fix (`scripts/verify-docker.ps1`):

- **Working directory:** the harness enters `$RepoRoot` before its first native
  step and leaves it in the final `finally`. That covers npm, uv, Python and
  Compose. The API proxy also starts with `-WorkingDirectory $RepoRoot`.
- **Playwright entry point:** Playwright runs only through
  `Invoke-CandidatePlaywright`, which uses the candidate's installed CLI
  (`node_modules/@playwright/test/cli.js`) with an absolute `--config`, from
  `$RepoRoot`. It never resolves through `npx`, which follows the working
  directory and can fetch an unpinned copy.
- **Suite preflight:** before the Docker stack is built,
  `Assert-CandidatePlaywrightSuite` lists the selected suite and retains the
  listing as `playwright-inventory.json`. It fails closed when:
  - the resolved config is not the candidate's;
  - the root or any project test directory lies outside `$RepoRoot`;
  - a listed spec lies outside `$RepoRoot`;
  - the listing has load errors or no specs;
  - the helpers' `CASEOPS_E2E_PYTHON` (now pinned by the harness to the
    candidate venv) lies outside `$RepoRoot`;
  - the candidate's own Playwright is missing.
- **Import check:** the host import check now requires `caseops_api` to load
  from the candidate's `apps/api`.

Verification:

- `tests/docker-acceptance-repo-root-guard.ps1` runs at the start of every
  acceptance run. It executes the harness's own launcher and preflight,
  extracted from its syntax tree, from a foreign directory holding a decoy
  `playwright.docker.config.ts` and a decoy Playwright CLI. It covers 14 cases:
  - the candidate CLI runs from `$RepoRoot` with the absolute config, and the
    caller's location is restored;
  - six listing failures are refused;
  - foreign and missing helper Python are refused;
  - a missing candidate CLI is refused without falling back to the decoy;
  - four path-containment traps are rejected.
- Mutation checks: with the launcher reverted to a relative config and no
  location change, the guard fails with "Playwright ran in ...\foreign". Without
  the resolved-config check, it fails because a foreign config is accepted.
- `apps/api/tests/test_20260928_docker_acceptance_guards.py` executes both
  guards in pytest, so CI runs them too. It fails rather than skips under `CI`
  when PowerShell or Node is missing. Both guards now take their default script
  path in the body: under `-File`, Windows PowerShell leaves `$PSScriptRoot`
  empty while evaluating parameter defaults.
- The existing candidate-source guard still passes its 4 cases.
  `test_deploy_prod_hardening.py` now pins the new launcher structure
  (103 passed, 1 pre-existing POSIX-only skip).

The complete harness at `f0ecd4b9`, which includes main `c6def4b4`, was
deliberately launched from the older checkout (`328761c5`, which holds its own
`playwright.docker.config.ts`). The preflight reported 418 specs from the
candidate's `tests/e2e`, and the run printed
`[docker-acceptance] PASS f0ecd4b9ab3aa8c52ab3f8f6707ae67e9d7cf5e6`:
PostgreSQL 440 passed; browser 208 + 198 + 4 passed, with the 8 by-design
production-only or provider-gated skips. The foreign checkout stayed clean,
with no `test-results` and an unchanged `node_modules`.
# 2026-09-30 BUG-012/014 GBA provider identity checkpoint

- **Verdict:** Not fixed end to end. Production still serves `37d54ec9`;
  the local prevention candidate is not merged or deployed.
- **Reproduction:** candidate `92eb79bf` passed 461 PostgreSQL/pgvector tests
  but its Docker Playwright selection failed the dated case-number and
  combined registration/filing hearing journeys. Only the CNR journey passed;
  three selected tests were locally inapplicable. The source requires a
  provider court code or CNR for safe exact search, while legacy Matters carry
  a human court name but no provider code.
- **Correction under test:** reject the unsafe paid search before transport and
  spend reservation, keep missing-code cases visibly blocked/backlogged, and
  disable their Refresh control. The revised browser journeys must prove the
  visible blocked state and a provider-code-backed search/link/date after
  reload. Do not call this properly fixed until fresh Docker and exact-release
  production Playwright pass.
- **Evidence:** `docs/audits/GBA_PROVIDER_READINESS_2026-09-30.md` and the
  retained Docker acceptance under
  `.tmp/docker-acceptance/b50b6f3fe8344d9393b8456061d079cb/`.
- **Second failed candidate:** `9369d6ae` ran all 461 PostgreSQL identities:
  458 calls passed and three failed because the new code hint obscured the
  existing missing-court/case-type guidance. Browser execution was withheld.
  The corrected precedence and current-Matter-CNR read check passed five
  exact PostgreSQL repros and 136 local adjacent tests; this is not closure.
  Retained run: `.tmp/docker-acceptance/58e620899c764440a37ab558846b8f00/`.
## October 10 Public-Claims Boundary

#515: residual solo/firm/guide universal legal-safety copy is
qualified and visible review limitations are added to dated mobile/desktop
browser acceptance. Reproduced failures retained. Verdict remains Inconclusive
for production until final release replay; see the dated production audit.

Adjacent shared homepage/FAQ, GC rollup and guide pack/recommendation statements
had the same unsupported guarantees. Seven expanded source failures are retained;
the complete 25-case replacement passes. Homepage browser acceptance must open
the drafting tab and safety FAQ, not inspect only default content. Live verdict
remains Inconclusive; no backend legal-safety predicate is weakened.

## October 21 Production Builder Compatibility

- **Scope:** release packaging for the existing API, IP/Calendar and reports
  journeys; no new product capability or provider entitlement.
- **Confirmed defect:** Cloud Build's legacy Docker parser rejects the API's
  inline Python heredoc (`unknown instruction: IMPORT`, build
  `0125c489-c3b8-4002-8d59-3e39158d2692`). Docker Desktop BuildKit acceptance
  did not cover this production parser. R22 stopped before migration/routing.
- **Correction:** copy and execute the unchanged certificate-removal build
  script using legacy-compatible instructions. Keep the compromised-root
  rejection, unrelated-root equality, hostname verification and frozen lock.
- **Regression:** `test_api_image_tls_tools_20261021.py` covers both production
  Dockerfiles and the complete certificate policy; `test_deploy_prod_hardening.py`
  covers inclusion in both API upload contexts. The new parser contract
  reproduced one API failure and one web pass before correction.
- **Verdict:** Inconclusive for production until the corrected candidate passes
  fresh Docker/CI, the real production builder and exact-serving Playwright.
  Full R22 evidence remains retained, not reassigned to the corrected revision.
  See `docs/bugfix-renewal-cte-identity-2026-10-21.md` for the failed release.

October28 installer follow-up: uv0.13.4 already has clean120 roots, but its
separate0.103.14 verifier is affected. The current uv0.13.5 pin uses0.103.16
without replacing Requests/HTTPX roots; Linux image acceptance stays pending.


## October 29 exact-case planner-cost diagnosis and tenant-band candidate

The expected-failing diagnostic on clean 8e78eaef retained the actual same-case
index catalog: the six-column source-proof index is valid, ready, expression-free,
full and eligible, with standard text operator classes and ordering. Audit table
estimates remained -1 rows / 0 pages. All three actual profiles still failed at
162,400 relation / 163,000 provenance work versus the unchanged 820 bound. The
ordinary old index plus sort cost 8.20 at PlanRows=1; the separate sort-disabled
estimate chose the new covering index at 8.29. That estimate did not execute
the query or prove bounded work. No production planner setting is introduced.

The original run remains failed. Its source/runtime, known owned-container
absence and command closures are separate passed components. A separately
timed post-run strict paired output audit retained every one of the 33 full
cleanup records and passed in 0.1993 seconds; it does not repair the original
clock or acceptance. Hash-bound evidence is retained in the task cache under
pg05-index-catalog-diagnostic-06/actual-diagnostic-receipt.json.

Candidate six (subsequently failed as recorded below) used a full six-key lower tuple bound and an
upper bound on company before the ordered single-candidate limit. Together
they select only the trusted tenant without an equality whose stale estimate
collapses the row count; complete exact policy stays outside the barrier.
The two cross-dialect semantic cases now establish three real tenants, sort
them by database order, select the middle owner and reject both lower and
higher foreign audit candidates. Wrong successors, foreign import ownership,
prebuilt-statement freshness and independent direct/page/staged dates remain
required. The original 29 identities / 87 phases and all 820/228, two-body,
64 KiB, query-count and timeout limits remain unchanged. Verdict: Not fixed
until actual ordinary, adverse, generic and full same-source workflows pass.


## October 29 additive type-leading candidate (private, unverified)

The six-key tenant-band candidate also failed all ordinary, adverse and generic
profiles: 162,400 relation / 163,000 provenance work versus820. Its old company
index used derived company lower/upper conditions plus an Incremental Sort;
all 811 tenant audit rows were still inspected per candidate. The sort-disabled
estimate retained that incremental sort, so it did not establish a new-index
choice. The original failed run, all33closures and a separate strict paired
post-run audit remain preserved; no failure is reclassified as acceptance.

Actual catalogs also contain the legacy target_id index. A target-first rewrite
would therefore still permit a target-prefix incremental sort over foreign
same-target history. Candidate07 instead adds revision20261029_0002 with a
full type-leading (target_type,target_id,company_id,ip_docket_id,action,id) index.
Revision0001 and its company-leading index remain unchanged. The query uses
full lower and three-column prefix upper ROW bounds before its one-candidate
limit, then retains the complete exact policy outside. No production planner
setting, ANALYZE waiver, old-index removal or larger work limit is introduced.

The intended complete inventory is38cases/114phases: all original29 identities,
eight new cross-dialect migration cases and one PostgreSQL history-work case.
The new roundtrip starts at named0001, includes a real interrupted concurrent
build/recovery on PostgreSQL, and proves downgrade preserves the old index,
raw rows, catalog and revision. Current-head0002 health and conflicting-name
downgrade refusal remain distinct from that historical boundary.

The work case seeds25,728 foreign same-target audit rows across both tenant
sides, plus12,864 owned NULL-docket and12,864 NULL-target rows and type/source
neighbors. Positive and missing-owned-proof phases each retain every actual
default/adverse/generic plan, original820relation/proof/materialized limits,
64KiB SQL, two-body and query-count assertions. NULL SQL comparison behavior
and B-tree work must be observed; no nullable key is assumed safe by sorting.
The two existing dialect semantics cases additionally retain before/after
prefix neighbors, actual selected-candidate identities, independent direct/page/
staged dates, and NULL/missing source JSON controls. Any unreached later phase
remains unverified. Six separate419+30component windows report aggregate time
separately. Verdict remains Not fixed until those actual workflows pass.


### 2026-10-29 — Source07 focused provenance result and fixture correction

The committed source07 `3b6130a5` passed the original PostgreSQL minimal-page case under default, adverse and actual generic prepared plans: date-query relation work 400 and attributable proof work 800 remained within the unchanged 820 bound; continuation work was 2/4. All five plans per profile, source/runtime stability, known container absence and all 33 owned process closures are retained. This is a scoped original-case pass, not complete release acceptance.

The independent stress case failed before history staging or query acceptance: its second fixed company bootstrap returned 409 instead of 200. Positive/missing-proof phases and their plans were unreached. Both new semantic dialect cases shared that fixture defect and remain unverified. The test-only actor helper now accepts the existing normal-API unique bootstrap for these three multi-actor cases while preserving original callers, cookie clearing, authentication, complete workspace configuration and acknowledgements. The iOS shell companion is regenerated to bind the current helper bytes. Neither correction changes product SQL, indexes, work bounds or the full 38-case/114-phase inventory. Replacement focused/full verification and both native platforms remain pending.

Evidence: `X/pg07-typed-prefix-verification-08/actual-focused-results.json` SHA256 `8ee4aa2920e85571d77ca733ca1197f1d00a6fa98f55c29df1c918039f77a20e`. The stress run and its separate audit01 stale-count refusal are preserved; audit02 reconciles all 34 actual contiguous dispatch/closure pairs under the original audit limits.


### 2026-10-29 — Source08 physical-work gap and reverse-prefix candidate09

Source08 `9505e0ea` completed the corrected stress case (99.090964s; one case, three passed phases, 16 marked HTTP requests), retaining all five plans for each default/adverse/generic profile in both positive and missing-proof phases. Positive Audit access used 1000 shared-hit blocks, while missing-proof access used 244302 despite zero returned/removed Audit rows. The original row-work checks passed (400/800 and 200/200 against 820); that pass does not establish bounded internal index work. Source/runtime/output and all 33 actual owned process groups closed cleanly.

Candidate09 is a minimal unverified reverse seek: one upper comparison over the five complete identity fields, all six index keys descending, LIMIT 1, no lower prefix and no ID sentinel; a source-NULL gate avoids an invalid comparison bound. Complete exact policy and ImportRow primary-key ownership remain outside that barrier. Existing wrong-successor policy denials stay covered, with selected wrong predecessors, lower/higher tenants, nullable histories and duplicate proof IDs added to the same cross-dialect cases. No model, migration or index changes are proposed.

The independent physical oracle counts inclusive Audit relation buffer accesses once, without multiplying counters by loops or charging bitmap children twice. Its fixed 201-seek contract is 16*201+64=3280 accesses: a conservative six-level descent plus metadata/VM, leaf/heap boundaries and slack per seek, with fixed overhead. It is a bounded-fixture contract, not a universal index-height guarantee or a value fitted to the failed measurement. The retained positive1000 baseline must pass and missing244302 baseline must fail. Original820/228 row-work, SQL/body/count/deadline bounds remain unchanged. All38caseIDs/114phases, migration journeys and native acceptance remain pending until actual complete replacement evidence.

Evidence: `X/pg08-fixture-verification-09/actual-stress-results.json` SHA256 `a148175da44fe66b83da264ebd3d943aaf3abadd579ef9fa13d63476a82f0bcc`. Successful fixture teardown normally drops the case database; no cold volume reopening or retained-data claim was made.


### 2026-10-29 — Candidate09 Result-node failure and CASE-bound candidate10

Both source09 `e819b84d` focused runs failed their unchanged supplemental820 work assertion in all three retained positive profiles. The reverse typed IndexOnlyScan was actualBackward and bounded at the relation/physical layer (relation400; MIN600 and stress1000 buffer accesses). The separate source-NULL predicate introduced an attributable Result One-TimeFilter node, adding200 work and raising the complete proof count to1000. That node remains charged; no observer, assertion or bound is relaxed. Stress missing-owned-proof remained unreached. Both source/runtime/cleanup/known-absence checks and separate complete output audits passed (MIN33, stress34 actual command groups).

Candidate10 moves only that existing source-NULL condition into a CASE expression in the first upper-row value. Valid sources retain the identical five-field reverse bound. Missing sources produce a NULL first key, retaining the no-candidate contract without a separate constant WHERE filter. All complete outside-policy, ImportRow primary-key, date, predecessor/successor, foreign-tenant, nullable and duplicate-ID checks remain unchanged. The compile contract now pins the one CASE guard, exact NULL refusal and sole upper comparison. Original820/228 row-work,3280 physical-work,64KiB/two-body/query-count/deadline bounds and all38caseIDs/114phases are unchanged. Actual replacement focused/full and native verification remain unexecuted.

Evidence: `X/pg09-reverse-prefix-verification-10/actual-focused-failure.json` SHA256 `8684f1d0e327f75d4e1861af54e18af8b82915e74c1328046c29d34793d5b250`; fullplans `ab8c0094a546f517532c67e5bdc736b257259e495f19f508a438ecbca9cf3c37`. No unchanged retry or historical failure reclassification.


### 2026-10-29 — Complete attempted38 inventory: observer failure and capacity refusal

The complete frozen source7033 replacement attempted all six admitted components, with at most two active. Thirty cases executed:29passed and one compile-only observer failed;89passed/1failed phase reports account for90of114planned phases. The eight new0002migration cases and their24phases were unreached because Docker refused network creation after all predefined address pools were allocated. No database or pytest body began for that component; it is infrastructure-incomplete, not eight migration failures or a green prefix. Aggregate observed537s is separate from each unchanged419+30window. Every component completed source/runtime postflight and strict owned command/output closure.

The sole executed failure was test_five_stage_names_preserve_pg_materialization_acl_and_current_source: its raw substring count found13 occurrences, including repeated ip_materialized_proof_seek aliases, while the preceding actual typed graph still contained exactly six unique nested CTEs. The corrected oracle retains six, requiring six PostgreSQL TextClause MATERIALIZED prefixes and six rendered AS MATERIALIZED declarations; an alias-only decoy contributes three substrings but zero declarations. All stage, ACL/source, actor/tenant parameter, warm read, category/date, postcommit and count assertions remain unchanged. No production query, model, migration or limit changes are involved.

Source7033 actualfocused plans retain the repaired missing-proof physical work1045 versus prior244302, within fixed3280, and all original row-work bounds. Both dialect semantic cases passed within the attempted inventory. Exact-owned network capacity recovery is separately planned for seven receipt-bound closed networks; no broad prune, data-volume removal, foreign/live-network cleanup or unchanged replay is authorized by this observer correction. A fresh coherent complete38/114 run and native Android/iOS acceptance remain pending.

Evidence: `X/pg10-case-upper-verification-11/full38-unarmed/actual-attempt-results.json` SHA256 `7aa737576880b7e8f3e2d92bf14ad3976b156137b10db89b07e678b8a23fc285`; all original reports and unreached phases are retained.


### QA12: interrupted typed-index catalog fixture, 2026-10-29

The complete source-bound run on `4bc5c7dc` executed all 38 cases and all 114 setup/call/teardown reports: 37 cases passed and one failed (113 passed phases, one failed phase). The original failed result remains at `pg11-materialized-observer-verification-12/full38-unarmed/actual-attempt-results.json` (SHA256 `98e80df89a38f2cc90ba2eebab647239796eabdf6a54d328798db9f708c46c34`). All six source/runtime postflights, owned process groups, container absence checks and later complete output audits closed. The aggregate observed 497 seconds is separate from each original 419-second body plus 30-second cleanup bound.

The PostgreSQL typed-index roundtrip stopped while recording its deliberately canceled concurrent index build: the ordinary catalog helper correctly rejected `ix_audit_events_typed_source_proof_seek` as invalid/unready. The repair continuation, restart, downgrade and reupgrade in that failed case remain unverified. The historical intermediate catalog/individual flags were not persisted before that assertion; a new exact expected descriptor is prospective proof, not a historical observation.

The proposed fixture uses a separate interrupted-index catalog observer with one exact key, complete six-column PostgreSQL index definition and explicit flags `(false,false,true,false,false,false)`. The ordinary `schema_catalog(engine)` remains healthy-only. Every other index must remain healthy, the expected interrupted index must exist, and the complete intermediate catalog must equal the parent plus that one index. The real fixture first proves the default helper rejects its actual invalid index. All existing repair, full-health, identity, row preservation, downgrade and reupgrade assertions remain required.

Independent observer regressions cover the exact snapshot/default rejection and wrong name, definition, flags, a healthy target, a missing target, an extra invalid index and an invalid descriptor. Eight private source controls passed with zero database/network calls. The complete adjacent unit inventory is 13 cases (the original five real SQLite DDL cases plus eight observer controls); the affected migration inventory remains eight. Neither private controls nor a future scoped eight-case pass make the failed complete-38 run green. Full native Android/iOS build and device acceptance remain open.


### C23 — offline deployment loopback marker source repair

Verdict: **Inconclusive**; the complete affected deployment rehearsal and platform release acceptance remain pending. On clean source e58130f870bfe332a04d5c79099164cc490b9373, source review found that test_uvicorn_connection_close_is_advertised_and_body_completes sent its raw loopback GET without the required X-CaseOps-Automated-Test: no-paid-providers marker. This was a verification protocol deviation against an invocation-owned temporary ASGI application, not evidence of a product or billable provider request. No actual HTTP constructor was dispatched during this source preparation.

The narrow candidate adds the marker to the existing request literal, so every existing retry carries it, and makes that actual temporary ASGI app assert the received header before responding. Method, Host, Connection behavior, exact caseops-ok body, readiness/read/cleanup deadlines and the complete 102 base-function inventory are preserved. AST comparison proves the other101 test functions and all other module statements unchanged. Six offline controls passed, including the exact request, the synthetic app marked response, and missing/wrong marker refusal before any response. These controls do not replace the complete offline rehearsal. The first malformed inline Python control invocation failed at syntax parsing before controls and remains retained separately.

Evidence: /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/web-node-security-20261029-01/source-draft-01/offline-deploy-marker-proposal-01/source-controls-result-02.json SHA256 6e272f8b178e3becbfb42cfe3bd957493c195da08be949f4900514283fc84ca3 (1331bytes); writer-preflight.json SHA256972d0f654367f3fdcbdfa582ee68619cfa7a13387cd4fec902f0456b5eb8ab1c. Original failed pure invocation is in source-proposal.json SHA256242decbb79dc7d7d8f82c819ac3dd9c5532b09bc04e40172c15c53db643956ef. Full frontend coverage, deployment/upload/image gates and Android/iOS native/store acceptance remain open.
