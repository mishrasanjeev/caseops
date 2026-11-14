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
