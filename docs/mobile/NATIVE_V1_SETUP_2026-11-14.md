# Disposable V1 workspace setup — November 14, 2026

J20/M22, US-MOB-01/02/08, SOURCE-01/03/04/06 and the83-case Android/iOS
inventory. Candidate **Partially implemented**; bug verdict **Inconclusive**;
complete native acceptance **NO-GO** until the normal setup and native suites run.
This change concerns the isolated QA gateway, not production API authorization.

## Observed boundaries

At source4265240f, both fresh native builds passed. Android's actual replacement
installation preserved app data and matched the APK hash; the owned emulator
proved API36, ARM64 and16KB pages. A public QA CA was installed through Settings
only on that dedicated emulator, preserving the prior certificate bytes. Its
one setup session is independently absent. These setup actions earn no native
case credit. The real phone received no commands or QA certificate.

The fresh synthetic-owner attempt stopped at its bootstrap POST with an
unacknowledged transport result. Do not infer the original HTTP status from that
exception or replay its original credential payload. A separately dated invalid
empty-payload probe measured403 on the public gateway's bootstrap route; the
observed allowlist omitted that route. An independent read-only query found zero
Company rows for the exact synthetic slug. Preserve the failed attempt and its
private files. A different invalid empty-payload probe measured501 for the normal
workspace-configuration PUT. The serving gateway has no PUT handler.

The owner preflight independently matched API-side and PostgreSQL-side database,
system identifier and exact server-start microseconds, an internal network, no
published PostgreSQL port, owned fresh volume and API mounts/image. No owner was
created and no entitlement was granted. A prior embedded-Python quoting failure
occurred before its DB connection; retain it separately. The preflight now parses
that exact Python program offline before any live dispatch.

## Narrow repair and adjacent checks

Add PUT handling only for the literal API-origin
`/api/ip/workspace/configuration`, without query aliases. The exact route still
must be explicitly admitted. The web proxy, other PUT paths, missing marker,
unadmitted route and oversized body remain rejected before upstream transport.
Forward the original normal Bearer authority and request bytes once; keep normal
API authentication/MFA, tenant permissions and body bounds. No provider route,
browser cookie authority, producer permit or production policy is expanded.
Update the independently reviewed gateway implementation pin to the actual bytes.

Two unchanged regressions retain seven red assertions against the original
gateway and pass after this repair. The positive executes real loopback TLS and
one upstream HTTP exchange, verifying marker, exact route, Bearer and byte-exact
body. Negative guards cover absent route, marker, another explicitly listed PUT,
query, web origin and first oversized body. The complete local fixture module
passes119 cases, with no skips;11 gateway route/immutable-snapshot/producer
consumers also pass. A first complete module run inherited a broken ambient
Node16 executable and failed three readiness-child assertions. Preserve that
report; the unchanged119-case replacement activates pinned Node24.15.0 and passes.

## Remaining actual execution

The initial Core allowlist remains narrow. Before any fresh V1 owner credential
is used, the owned V1 operator must publish its canonical declared fixed setup
routes, including bootstrap and MFA enrollment. During its separate37-call
normal governance phase, admit only the exact workspace PUT and exact subsequent
calendar/rule activation routes after their normal acknowledged creation. Remove
the temporary setup PUT before native route-authority capture; native route-file
and descriptor grammars remain unchanged. Retain immutable configuration and
allowlist snapshots, rather than binding later validation to a mutable path.

Use the existing canonical single nonbillable entitlement worker with fresh
Company/current owner locks, exact two entitlement keys, independent PostgreSQL
identity, unchanged32-statement/30-second bound, one durable claim and exact
postcommit readback. Never promote roles through SQL, use direct API-port HTTP,
replay an uncertain mutation or extend the original profile expiry.

The source4265240f per-scope rebuild also left a refused mixed API/web candidate.
Retain its failure. The owned replacement staged both source identities before
canonical Compose/build-web/finish, preserved the original CA/profile expiry and
all77 retained containers, and independently reconciled the70 unrelated ones.
The later park preserves all data and advances only unreached cleanup; a completed
emulator kill is not replayed after its controller stopped.

Evidence resides under the owned native evidence root in
`qa-gateway-put-security-20261114-01/`,
`v1-4265240f-bootstrap-route-diagnostic-01/`, the two failed owner directories,
`android-v1-4265240f-coherent-rebind-02/` and the dated park directories. Fresh
committed-source gates, rebuilt native artifacts, normal bootstrap/governance and
all83 actual cases on each platform remain due. Earlier native passes and either
source4265240f build do not certify this newer candidate. Physical hardware and store
signing remain separate acceptance boundaries.


## 2026-11-14 — CI observability audit contract reconciliation

Status: Partially implemented. Release verdict: NO-GO pending complete native execution and remaining CI.

CI run 43535689936, API coverage shard 13/13 (job 132264142381), exposed the older FastEmbed workflow source assertion still requiring the base-only sync command. The security workflow intentionally installs `--extra observability` so the strict physical installed-metadata audit includes the optional telemetry packages. Reproduced against frozen revision 723552ba: 13 passed, one failed in `test_fastembed_pillow_rebuild_20261021.py`; updated only the expected exact sync command. All existing `uv pip check`, strict OSV, installed-site-package and no-ignore/no-fix guards remain intact.

Verification: complete FastEmbed module plus the unchanged explicit hearing-channel module: 48 passed, zero skips/errors (33.40 seconds), retained JUnit `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/ci723-contract-green-01.xml`. The second module independently verifies the backend's empty-channel contract; this is not a native or deployed-production acceptance claim. Native builds and executions remain bound to the separate clean 723552ba checkout; this test/document-only follow-up does not alter application, dependency, gateway, build or native harness bytes. Current native acceptance is still incomplete; no historical case credit is transferred.


## 2026-11-14 — Native V1 raw matter DTO boundary

Bug verdict: Partially fixed; native verification remains incomplete. The actual source-723552ba V1 producer created its 26 contracts, eight matter parents, three IP families, scoped grants and three confirmed deadlines, then refused its external fixture projection because raw MatterRecord omits the invented `is_disposed` and `restricted_access` keys. Retained failed run: `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/v1-723552ba-android-producer-01/phases`; it is incomplete, with zero native credit, and must not be resumed or renamed into a passing aggregate. A separate marked member GET returned all three exact deadline rows; that read does not complete the failed phase.

Adjacent canonical viewer and inbox producers also assumed raw `is_disposed`. A shared strict boundary now validates actual company, UUID, lifecycle version, operational status and `is_active` before producing the internal `is_disposed: false` fixture field. Missing/unknown/closed/disposed status, missing/false activity, a foreign tenant or contradictory derived state remain rejected before any child write/worker. The external base plan must derive restriction from the acknowledged access response rather than MatterRecord. Raw API acknowledgements are not rewritten.

Verification: complete 178-case V1 JavaScript module and the independent Python inventory passed at `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/v1-matter-record-contract-fix-01/`. Existing tests now exercise raw API-shaped matter responses without the derived key; the negative inbox journeys retain zero worker/child dispatch. The first focused attempt exposed an incomplete calendar composition double missing the actual lifecycle field (177 passed, one failed); the double now models the real required field, with original assertions and counts unchanged. Stronger fresh-profile API and native acceptance is still pending.


## 2026-11-14 — Actual Android control and read-admission observations

Status: Partially implemented. Bug verdict: Partially fixed. Release verdict: NO-GO.
The current 19852a38 Android APK and iOS Simulator app both built successfully;
these are local QA artifacts, not store archives. Normal primary and independent
viewer Android Firefox/MFA/PKCE/native-identity/logout observations passed in
`v1-19852a38-android-primary-auth-04/` and
`v1-19852a38-android-viewer-auth-01/`. They earn no native inventory credit.
The four-stage normal V1 producer completed all stages without replay; its
immutable receipts and the earlier failed 723552ba producer remain retained.

Actual Android observations found a TextView label with checked=false and its
direct android.view.View parent with checkable=true, checked=true. The V1
retained-selection assertion read only the label. Bind the checked-state read
to that exact observed parent, require its measured type and the same unique
label element, and reject unchecked, unrelated, ambiguous or unreviewed owners.
Do not accept false as selected. iOS and directly selected label recipes keep
their original path. Separately, the actual Android work-leave Alert exposes
STAY/LEAVE EDITOR on android:id/button2/button1, rather than mixed-case text.
Verify the owning app, exact work-dialog title and both captions before one
protocol click. Preserve direct close for a purged editor and Stay for an
unknown outcome. The actual repaired functions passed parent-selection and
Stay/Leave checks on installed source19852a38; this diagnostic is not execution
of the full seventeen-case inventory on the newer harness.

Source-contract replay of the actual Matter and account-privacy repository
constructors also found missing exact read routes. Admit only the returned
Matter IDs and the same four read-only Account/Work routes already used by the
Core setup; do not add account-deletion writes, wildcard records or manufactured
Matter routes for an IP docket. The observed earlier gateway rejection counters
remain incomplete diagnostics: no rejected URL was captured for those dated
attempts, so this source finding is not a measured attribution of every earlier
network refusal. The original ledgers and each failed observation remain failed.

Evidence under `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/`:
`inspect-calendar-selected-198-04.json`, `inspect-work-alert-198-01.json`,
`v1-19852a38-warm-selector-observation-06/actual-work-dialog-repair-proof.json`,
that attempt's selector-group-1.json and result.json, plus the paired
selected-segment/work-alert/native-read-admission regression red/green TAP files.
The separate read-only PostgreSQL proof
`v1-19852a38-notification-readonly-proof-02/proof.json` verifies the current
explicit empty hearing channels, zero outbox records and zero provider attempts.
Its prior UUID-vs-varchar diagnostic failure is retained separately.

The complete V1 JavaScript module now discovers179 tests (one additional
regression); the complete final changed module passes179/179 with zero failures, skips, cancellations or todos (`native-observed-controls-complete-green-01.tap`).
Native acceptance is still0/83 Android and0/83 iOS for this candidate. Earlier
native passes are not transferred. Fresh complete source gates, current-commit
builds and actual complete native groups remain required before release sign-off.
Apple organization enrollment remains a separate pending external review.


## 2026-11-14 — Mainline conflict reconciliation

PR612 head e46122b3 had no new pull-request workflow runs because GitHub reported mergeable=false / dirty against main34ce599d. Resolve the ten actual conflict files in a separate checkout; preserve the frozen native source and its failed setup evidence. Keep main's all-extras strict audit, both independent WKS inventories (10 unittest cases and nine parameterized pytest cases), both telemetry and DNS notices, and the upstream original/cherry-picked fix references. Runtime API code, uv.lock and native build inputs remain byte-identical to e46122b3.

Verification: all seven affected complete Python modules passed144 cases, zero failures/skips, plus17 unittest subtests, in `main-reconciliation-targeted-01/result.xml` under the owned native evidence root. Exact per-module reconciliation and bundled notice hashes are in that directory's `reconciliation.json`; focused Ruff passed. This is local Mac dependency-contract verification, not Linux/Windows acceptance or a completed native suite. The replacement merge commit needs fresh hosted CI and source-bound native acceptance; current release verdict remains NO-GO.


## 2026-11-14 — Record-specific Inbox native controls

Status: Partially implemented; bug verdict: Inconclusive; release verdict: NO-GO. On the installed e46122b3 Android APK, all ten measured segment groups and normal MFA/PKCE/native identity succeeded. Setup then failed locating Open source record under its notification card. The independently retained passive observation `inspect-e46122b3-inbox-controls-01.json` shows that exact visible label and its enabled clickable native ancestor inside the card's frame, but outside the card's accessibility subtree. No native case completion is inferred from that setup.

Assign all four native Inbox buttons exact notification/action test identities. The new runner recipe independently checks device/build binding, one exact card and action ID, actual native button type, enabled/visible state, exact label and contained window/card frame before one protocol dispatch. Wrong records, duplicate IDs, missing/hidden/disabled controls, type/label drift, out-of-card frames and lost click acknowledgements remain fail-closed; a lost acknowledgement is not replayed. Existing measured descendant recipes remain available for older platform observations.

Complete V1 module: retained original179pass/1failure and candidate180pass/zero skips/cancellations/todos in `native-notification-id-regression-{red,green}-02.tap`. The earlier restricted-PATH attempt also failed six unrelated Python/Xcode setup cases; its raw red/green01 logs remain retained and are not a passing replacement. Fresh native builds and actual Android/iOS interaction with these new identities are still required.


## 2026-11-14 — Manual workspace restoration route

Status: Partially implemented; bug verdict: Inconclusive; release verdict: NO-GO. Pre-execution review of SOURCE-04 found that a normal configuration update disables the disposable IP workspace, whose restoration requires POST /api/ip/workspace/enable. The QA registration's global owner-route allowlist omitted that exact route. This is a source/contract finding, not a measured production API or network failure.

Admit only SOURCE-04/applyIpPolicy's manual restoration: the immediately preceding acknowledged GET must read workspace configuration; expected_config_version must reference its exact version; enabled_automations must remain empty, with no extra body keys. Check the immutable recipe during public registration admission and again before actual HTTP, then require a positive integer resolved version. Existing normal API authorization, isolation, deadlines, one-shot claims, disabled defaults and all mutation restrictions remain unchanged. Other cases, capabilities, reads, static versions, provider/body additions and automation enablement are refused.

Complete Python control module: original43pass/2failure; candidate45pass. Raw logs `native-workspace-restoration-regression-{red,green}-01.log` remain under the owned native evidence root. Actual normal API restoration and complete native suites are still required. The fresh b633ce1b profile is unconsumed by any owner/producer/native journey; preserve its initial source receipt, CA and original expiry before any coherent source rebind. No completed fixture or native acceptance is transferred.


The first complete frozen55fc96b2 gate correctly refused the changed shared control bytes: the client-extension JavaScript composition and three independent Python inventories/loaders retained the prior exact base digest. All other gates completed; the failed whole report is preserved at `frozen-source-55fc96b2-01/`. Reconcile all four literal consumers (gateway loader, queue Python, queue JavaScript and client-extension Python) to the actual changed descriptor-verified source digest. Keep runtime hash validation and all tamper-refusal tests; do not replace the pin with dynamic trust or erase the original failed gate. A complete replacement gate is required before any native build.


The replacement13b527a8 gate passed every Python module but refused the changed gateway at the separate reviewed exporter pin. Preserve that failed whole gate at `frozen-source-13b527a8-01/`. The gateway delta is solely its exact reviewed shared-base digest; reconcile the exporter to that actual gateway file after the complete gateway/queue/client source controls pass. The four shared-base consumers and this transitive exporter form one exact closure; runtime mismatch/tamper rejection remains mandatory. No native build was started on either failed frozen gate.


## 2026-11-14 — Remaining CI all-extras assertion

Status: Partially implemented; bug verdict: Partially fixed; release verdict: NO-GO. Current ca71f1da CI43556303195 API coverage shard4 (job132329896722) completed1309passed/687explicitly skipped/1failed. The only failure is `test_otel_util_http_packaging_20261114.py::test_strict_installed_ci_audit_also_admits_optional_cohort`, whose tokenized command expectation still requires --extra observability after main deliberately broadened the strict installed audit to --all-extras. Preserve the failed job and bounded sanitized log under `ci-ca71f1da-api-shard4-failure-02/`. The first log fetch refused terminal escape sequences and is retained separately.

A separate checkout reproduces the complete five-case module: four pass/one fails. Change only its exact command expectation, retaining every installed identity/notice/strict-OSV/uv-pip-check/no-ignore assertion. Complete replacement across all eight related dependency/packaging modules passes149cases, zero skips/errors/failures, plus17 unittest subtests. Independent JUnit reconciliation and original/replacement reports are retained under `ci-ca71f1da-otel-command-{red,green}-01/`. Hosted replacement remains required.

This follow-up changes only that API test and documentation. The ca71f1da native build/backend/harness checkout stays frozen for its actual device work; both its Android APK and strict-signed iOS Simulator app built successfully. Exact runtime-input equality must be recorded separately rather than renaming those receipts or claiming these are store archives. The full83-case native inventories remain incomplete.


## 2026-11-14 — Host and mounted credential identity

J20/M22 / US-MOB-01/02/08; implementation status: Partially implemented;
bug verdict: Partially fixed; release verdict: NO-GO until native acceptance.

The frozen ca71f1da Android preparation completed normal API/MFA provisioning,
the complete producer, and the native primary-account sign-in/UI/logout
observation. These are preparation observations, not any of the83 acceptance
cases. The next registration boundary exposed incompatible namespaces: the
immutable viewer producer and native host reader require the original host
credential reference, while the gateway reader requires a direct child of its
mounted runtime state directory. Rewriting the producer receipt or relaxing the
private reader would erase the required provenance or ownership checks.

An optional `runtimeCredentialEvidence` now names the mounted copy separately.
Its exact private-reference shape and SHA must agree with the original payload;
its parent must equal the authority's admitted runtime state directory. The
actual gateway reader repeats the mapping check against its own root before
opening anything, then retains the existing descriptor, UID, single-link,
regular-file, private-mode, bounded-byte and SHA checks. The native host still
reads the original `credentialEvidence`; immutable viewer equality is unchanged.
The original and mounted UID values may differ and each belongs to its actual
filesystem descriptor. Authentication still uses the normal login and MFA APIs
and verifies tenant, membership, role and capabilities. Controls remain disabled
by default; registration and mapping do not grant native mutations.

Reproduced Python regression:48 tests, two failures and one error in the original
candidate (`native-credential-mapping-python-red-01.log`). Replacement complete
module:48 passed (`native-credential-mapping-python-green-01.log`). It exercises
actual owned files, separate original/runtime references and normal login,
plus malformed mapping/hash/root and UID/mode/symlink/content/hardlink refusal.
The complete JavaScript module reproduced179 passed/two failures, then181
passed with zero skipped/cancelled/todo (`native-credential-mapping-javascript-
{red,green}-01.tap`). Public admission refuses malformed mappings before private
member reads and preserves exact host references on the valid path.

The same repository-constructor regression adds the exact supporting
`GET /api/matters/{id}/drafts` reads and read-only Counsel Matter hydration,
including known race, linked, Inbox and viewer parents. No wildcard, invented
parent or additional mutation route is admitted. An explicit new gateway
process preparation observed four successful drafts reads and no additional
route rejections during actual native sign-in/UI/logout, retained in
`v1-ca71f1da-primary-auth-03-draft-read-reconciliation.json`. The original failed
attempt did not retain rejected route values: its network root cause remains
Inconclusive, and its failed report/counters/journals are preserved separately.

Every shared-base pin and the transitive gateway-exporter pin is reconciled to
the reviewed implementation bytes. Full frozen source verification, fresh
source-bound native builds, mounted-runtime validation and83 cases on each
platform remain required. Current-candidate formal acceptance is0/83 Android
and0/83 iOS. No historical source's case count or receipt is relabelled.
All evidence paths above are under
`/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/`.


## 2026-11-14 — V1 member authentication and Core seed boundaries

J20/M22 / US-MOB-01/02/08; implementation status: Partially implemented;
bug verdict: Partially fixed; release verdict: NO-GO pending native acceptance.

Revision fbf2ea31 passed all21 source gates (697 mobile,1746 harness passes with
three explicit Windows-only skips,452 Python cases across all18 modules).
Its actual Android APK and strict-signed iOS Simulator app both compiled; the
Android artifact independently passed signature, manifest permission projection,
16KB ZIP alignment and all20 ARM64 ELF checks. Its fresh normal-API V1 producer
completed all four phases on its first attempt. Both primary and viewer accounts
then completed actual native Firefox/MFA/PKCE sign-in, principal/workspace
verification, logout and independently confirmed Appium session cleanup. The
primary also completed the native segment and exact Inbox action observations.
These remain preparation observations, not any of the83 formal acceptance cases.

The mounted credential mapping additionally passed actual normal login/MFA and
tenant/membership/role/capability checks for all three registered actors. Docker
exposes the copied files with UID0, while their host descriptors report UID501.
The original failed probe used the host UID and was refused before its credential
byte read or authentication constructor. It remains failed; a separate metadata
observation and replacement probe use the actual runtime UID with unchanged SHA,
private mode, single link, original references and copied bytes. Retained proof:
`v1-fbf2ea31-runtime-credential-mapping-02/proof.json`. Its `actors` and
`runtimeAuthority` fields contain the actual current runtime bindings; the
`copies` array preserves the original copy-phase provenance rather than replacing
that failed attempt's UID references. No actor file, producer receipt or guard
was rewritten to obtain the positive result.

A subsequent preflight audit exposed a separate runner dependency:
`admitV1BeforeMembers` called the complete Core fixture validator for each V1
member. After all shared authentication and isolation checks, that function also
requires the Core23 matter/search/task/draft/calendar seed. Those fields are not
part of the separately produced V1 fixture. Replaying both actual public member
fixtures with explicitly synthetic offline credential environments reproduces
`SEEDED_MATTER_ID_REQUIRED`, without private credential reads or HTTP. Original
proof: `native-v1-member-validation-actual-red-01.json`; the V1 inventory was not
started and receives zero case credit.

Extract the unchanged authentication/isolation prefix as
`validateNativeFixtureAuthentication` and use it for V1 member admission.
`validateCoreFixture` still calls that prefix and retains its complete original
seed/record validation tail. V1 retains its own complete17-case record validation,
exact source/binary/backend identities, browser/MFA observations, private reader
checks and two-company membership binding. This changes no case, deadline, source
fence, authentication requirement or Core acceptance criterion. New regressions
cover authentication-only fixtures, retained Core refusal, credential/MFA/browser/
marker/source/isolation denials and both scoped private member environments.
The complete two-module focused run passes638 tests with zero skips/errors/
failures. Replay of the same two actual public fixtures passes the shared helper,
retains Core refusal and passes eight security negatives; it is explicitly an
offline contract replay, not new native acceptance.

Independent adversarial review confirms the shared prefix and remaining Core tail
are byte-identical and finds no blocking or major issue. Full frozen source gates,
new source-bound native artifacts and complete per-platform native inventories
remain required. No fbf2ea31 receipt or earlier case count transfers to a newer
revision. All evidence paths above are under
`/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/`.


## 2026-11-14 — Complete owned gateway handler observation in CI tests

J20/M22 / US-MOB-01/02/08; status: Partially implemented; bug verdict:
Partially fixed; release verdict: NO-GO pending native acceptance and hosted CI.

Hosted Mobile run43566147215, job132360325641, failed the119-case Python module
at `GatewayTests.test_public_identity_and_preflight_do_not_forge_a_native_marker`.
The HTTP OPTIONS body had arrived, but the last journal row was still the earlier
GET build identity. The uncontrolled gateway deliberately records ordinary
requests in its handler's finally block after sending the response; V1/producer
requests retain their existing durable-before-response behavior. A readable
response is not proof that the test server has completed that final observation.
Original raw and separately sanitized logs are retained in
`ci-6b44841b-mobile-source-failure-01/`.

Change only the Python test's owned-server observation: track actual handler
finish by the exact server port/client peer, consume the complete response, and
wait for that handler using the remainder of the existing three-second budget.
The affected direct TLS, calendar and response-header helpers use the same
completion boundary. The production gateway, its journal ordering, source pins,
app/backend code, native executors and assertions are unchanged. Completion
waiting has a finite wall-clock deadline; socket timeouts remain per-I/O idle
timeouts, and this change does not claim a new whole-body transport deadline.

Two new real-socket regressions deterministically hold upstream close after the
response is readable. The original helper returns an empty journal and fails to
report the missing completion deadline; both original regressions fail in
`native-gateway-handler-completion-red-01.log`. The replacement proves the exact
preflight class, absent native marker, original status/body, single HTTP dispatch,
finite timeout and explicitly released cleanup. The original119 test bodies keep
their payload, header, route, marker, classification and negative guards.

Complete replacement:121 tests passed with zero skips/errors/failures, retained
in `native-gateway-handler-completion-green-02.log`. The earlier complete run
still contains three failed readiness-constructor subtests because the ambient
Homebrew Node16 aborts on its missing ICU73 library. Retain that report as failed;
the separate direct runtime diagnostic confirms the loader failure, and the
replacement changes PATH to the pinned Node24 without changing any test budget.
Independent adversarial review found no blocking or major issue.

This follow-up changes only the Python unit test and documentation. Keep the
6b44841b application/backend/native checkout frozen for actual builds and tests;
record complete runtime-input equality separately. Native receipts and case
counts retain their actual source revision. No native credit transfers to this
follow-up and no store archive is established by a Simulator build. All named
evidence paths are under
`/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/`.


## 2026-11-14 — preserve failing intrinsic Node child diagnostics

J14/M14, QG-CI; **Partially implemented**, CI defect verdict **Inconclusive**,
native release **NO-GO**. Hosted Mobile source run43568858887/job132368612254
failed the real intrinsic Node24 child at `tooling.test.mjs:5932` with exit1 and
empty stderr. Its synthetic evidence TAP was captured but absent from the
assertion message. Preserve the original raw/clean logs under
`native-release-20261111-ZzEIol4V/ci-672b2ed3-mobile-source-failure-01/`.

Include the already bounded child stdout, stderr, signal and overflow in the
existing failed-exit assertion, after child completion. This changes no child
arguments, deadlines, guards, case counts or cleanup. It is diagnostic only;
there is no measured root cause or fixed claim. Full Mac Node24 tooling passes
456/456 with zero failures/skips; the unchanged two intrinsic CLI siblings pass
on Mac and official integrity-verified Linux ARM64 Node24.15.0 in an isolated
Debian container. Retain the earlier missing-dependency, image UID, Node22,
unshared-bind and Alpine dynamic-loader setup refusals separately; they did
not reproduce the hosted child failure. Evidence: `source-observer-diagnostic-
full-tooling-01.tap` and `source-observer-linux-diagnostic-05/` under that same
owned native evidence root. Exact invocation-owned diagnostic containers are
independently absent; unrelated containers and native receipts are unchanged.

Source6b44841b remains the actual native execution target. Fresh Android and iOS
Simulator builds both passed; Android installed APK SHA
`94eac488236ca37114d777dffedab7c1a41a866f0f6f772c367da9d5b3ab3942`
matches its build receipt. The fresh disposable V1 owner, governance, member and
complete producer finished normally; the first current Android browser attempt
failed before any private credential read with Firefox Secure Connection Failed.
Preserve `v1-6b44841b-android-primary-auth-01/`; complete known-session absence
and an empty actual Appium inventory were proved. Current formal native counts
remain0/83 per platform; compiled builds and setup do not earn case credit.


## 2026-11-14 — canonical installed-observation receipt compatibility

J20/M22, US-MOB-01/02/08; candidate **Implemented**, native bug verdict
**Inconclusive**, full release **NO-GO**. The complete source6b44841b disposable
producer accepted its real raw `observeInstalled()` evidence before private
admission. Its immutable viewer receipt binds that exact reference. Actual
unmodified `admitV1BeforeMembers()` then refused at line232 because it required
an additional nested `buildReceipt` absent from canonical observations on both
platforms. The unchanged actual call used no dependency injection and stopped
before private-member admission/control activation. Retain
`v1-6b44841b-final-inputs-03/actual-native-admission-refusal.json` under the owned
`native-release-20261111-ZzEIol4V` evidence root.

Accept the canonical raw schema while requiring any supplied nested build
reference to match exactly. Independently retain the build artifact/source/hash,
serving identities, device, complete producer/viewer reference equality and
private-admission ordering. Also compare **every** freshly observed native field
against retained evidence, including Android boot/data-directory identity and
iOS app/container/runtime/state; this strengthens the old selected-field check.

The complete revised190-case V1 module against the original runner has188pass
and2fail, one canonical raw-observation positive per platform, both at the
missing nested reference assertion (`native-installed-receipt-contract-red-
02.tap`). The corrected runner passes190/190 with zero failure, cancellation,
skip or todo (`...green-04.tap`). Adjacent negatives reject conflicting optional
receipts, every platform-specific native identity drift and replacement of the
producer-bound observation before any private reader. Preserve earlier red01
and green01/02/03 reports: their Android fixture app/boot/device metadata defects
were setup failures, not positive acceptance. Full source gates and native
replacement on the corrected source remain required.

Both actual source6b builds passed. Its Android primary02 and viewer02 normal
Firefox/MFA/PKCE/native identity/logout observations passed with complete session
absence, grant-to-native5916ms and4897ms respectively; primary also observed all
required V1 selectors. They earn zero formal83-case credit. Firefox initially
reported an unknown issuer; retiring only the six exact verified older emulator
QA CAs, preserving their public bytes, left the current CA unchanged and restored
normal verified HTTPS. No exception was accepted, no personal-phone command ran,
and earlier failure evidence remains separate.

Two external preparation defects were retained separately: a literal current
grant ID absent from the original producer oracle and a null obligation company
placeholder. The corrected **separate** projection selects the exact registered
member's unique grant from the immediately preceding owned-docket GET and derives
company identity from both actual acknowledged obligation pages. The canonical
resolver passes actual/reordered data and rejects missing, duplicate, wrong-
subject and101-row responses. It preserves all151 original oracle identities,
registers exactly55 control identities plus four native-creation reservations,
and performs no extra HTTP or mutation. Both old projections and original raw
producer receipts remain unchanged. No V1 registration has been activated.


## 2026-11-14 — bind V1 access timestamps to the actual server response clock

J20/M22, US-MOB-01/02/08; candidate **Implemented**, original native setup
defect verdict **Inconclusive**, full release **NO-GO**. The source6721039b
producer stopped after the acknowledged design access apply200; its original
receipt omitted the exact exception. Preserve all494 events and attempted
mutations under `v1-6721039b-android-producer-01/`; no failed phase was replayed.
An independently admitted, authenticated read of that exact owned panel found
its valid grant timestamps about5ms later than the original Mac failure clock.
The held, original `readGrant` predicate rejects that actual grant at the
original host observation and accepts it later. This proves the clock-sensitive
validator defect, but **does not establish the original stop's complete root
cause**: the original apply body and prior assertions were not retained. Keep
`v1-6721039b-producer-readonly-diagnostic-01/` (route not yet admitted), `...-02/`
and its `exact-predicate-replay.json` separate. No response body, credential,
record identity or query is exposed in public diagnostics.

The native producer host now captures the first canonical received HTTP Date
only for exact queryless access-panel GETs and typed preview/apply responses.
It admits one header or the canonical gateway-plus-upstream pair within one
second; missing, malformed, extra or incoherent headers fail before settling
the response and poison the client without replay. Grant activation compares
against the exclusive upper bound of its corresponding server response second,
without a client-clock fallback or selecting a later header. Initial owner and
new member grant checks use their own panel/apply observations. MFA expiry,
revocation/expiry, full owner equality, actor and source lineage, byte
provenance, member readback, request count and all original deadlines remain.

The complete changed V1 module passes202/202, zero failures, cancellation, skip
or todo (`native-grant-server-clock-green-04.tap`). Actual marked TLS covers
panel and typed preview/apply capture, unrelated-route exclusion, malformed
wire rejection and no replay. Patent/design regressions control host and server
clocks independently and exercise999ms/1000ms boundaries and negative guards.
The original-runner red02 report has198 cases,192pass and6fail, with zero
cancellation/skip/todo, retained separately alongside preliminary red01. Fixed allowlisted
stop codes improve future diagnosis without reflecting exception values or
causes; an own message descriptor avoids invoking arbitrary getters. Independent
adversarial review found no blocking or major issue in the five-file correction.
Fresh complete source gates, builds and formal native execution remain due.
Exclusive dependency installation completed with pinned Node24/npm tooling;
the earlier outer-PATH preinstall refusal performed no installation and remains
retained separately as `grant-response-clock-runtime-install-01/`.

Both actual source6721039b Android and iOS Simulator builds passed. Android APK
SHA `a4915a8d4cf8931e68842c6af54f501a266a1d58da15aaedd410c67e11ad8bba`
was installed and independently checked, but setup never reached formal native
cases. The original failed iOS precompile guard and successful compile02 are
retained separately. Current-source formal acceptance remains0/83 per platform;
no older source's case count transfers. All119 retained containers were preserved
and stopped, along with this run's emulator/Appium/private VM, before rebuilding.


## November 14 — settled Firefox consent viewport

Bug verdict **Partially fixed**; complete native release **NO-GO**. The actual
source `db725c0130b189780f03508cf8186da8bcaf9f58` Android V1 run reached all
three exact browser identity reads, then failed the final Connect lookup with
`NATIVE_CONTROL_NOT_VISIBLE`. All17 workflow calls remained unexecuted. The
one Appium session is independently absent, the complete session inventory is
empty and the actual gateway control run is closed. Claims were not reset and
the failed run was not replayed.

The dated journal records a principal-read swipe before the final wait-only
Connect lookup. Read-only follow-up found the keyboard open and Connect absent;
a single keyboard dismissal changed visibility after accessibility settled.
Do not attribute the original failure to a specific account cookie or claim
that a native scroll alone repaired it. The first candidate replay still failed:
a false keyboard observation immediately after URL dismissal did not establish
that the later identity-read viewport would remain keyboard-free. Its failed
report and subsequent keyboard-open observation are retained separately.

Keep the initial asynchronous Connect lookup wait-only. Only after unchanged
PKCE and exact principal, email and workspace reads, observe the keyboard in a
bounded settled lookup, dismiss it at most once and require acknowledgement.
Recover a below-viewport Connect with at most3 downward gestures in the original
10-second lookup budget. Verify the caption and dispatch that exact element ID
once. Preserve the independent post-MFA identity check, absent MFA field, second
explicit Connect and one app-open callback. Active/deadline probes forbid a late
visibility response or delayed geometry from issuing another command after the
outer wait expires; acknowledged gestures still release their input.

Proof lives under the owner-held `native-release-20261111-ZzEIol4V` root:

- `v1-db725c01c-full01-failure-reconciliation-01/proof.json`: original full
  runner0/17 calls, exact session absence and closed actual control run.
- `firefox-consent-viewport-red-01.tap`: dependency setup failed before tests;
  no test credit. `red-02.tap`: the3 selected regressions execute,1pass/2fail
  against the original harness. `focused-01.tap`:51pass/2fail on the first
  candidate, preserving the missing fixed diagnostic-name registration.
- `firefox-consent-viewport-focused-05.tap`:60/60 Firefox regressions pass,
  including late IME, recurrence, delayed native visibility, bounded missing
  Connect, original transport exceptions, stale/lost click acknowledgements and
  late-callback gesture admission/release. Existing delayed initial-Connect,
  identity, PKCE and MFA negatives retain their assertions and time budgets.
- `firefox-consent-viewport-canonical-auth-diagnostic-01`: failed native
  readiness before sign-in; preserve it. Diagnostic02 failed final Connect and
  remains failed. Diagnostic03 completes actual canonical authenticate/logout
  for primary, viewer and primary, using normal browser MFA/PKCE each time.
  Each real session is independently absent. Explicit owned-app process restarts
  preserve app data. This is a harness diagnostic against actual M20 APK
  `8646587140917f1cda27694d4883dca2e47dc06fad1eaeb8acdf2d7f0be12df6`
  and M20 backend, not a new-source build or any of the83 acceptance cases.
- The previous pushed revision's CI43578668131 completes53 jobs:52success,
  one expected staging-deployment skip. Its Mobile source workflow also passes.
  These results do not certify this later candidate.

The runtime app and production authorization are unchanged. New-source gates,
fresh platform binaries/backends and all independent native inventories remain
required. No old source's case passes transfer to the new candidate. The
personal OnePlus receives no QA CA or new trust change.
