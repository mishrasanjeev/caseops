# Native Core Inventory: 25 October 2026

J20/M22; US-MOB-01..06/08; underlying J01/J03/J04/J08/J14,
M01/M02/M03/M08/M13/M14 and FT-002/003/006/007/008/011..015/042/061.
Implementation status: Partially implemented. Android dated core: **23/23 passed**;
full mobile release remains **NO-GO**, not complete MOB-01..40 acceptance.
The replacement Android16/API36 report
`native-core-20261025-eb7d9106-eeff-407f-a3f6-37ac618779fb/reports/2026-10-25T09-19-38-852Z-android-ae0d1bc1`
completed all setup/call/teardown and preflight/postflight with exit0 at
09:38:31 UTC, source/API/web4959129a and installed APK SHA
`1e5b075e1b0de2fee170f081cb2fb0053f83194e21c3951e2362f0418577ca29`.
There were no blocked/unexecuted cases or failed phases. The exact dirty harness
is separately hash-bound in the report. iOS23 remain NOT RUN; Files is a distinct
supplement, not part of this 23. The new dependency audit still blocks release.

**Historical attempts retained:**
The exact installed ee8dde90 APK completed a 23-case attempt: NATIVE-01..09 and
NATIVE-11..15 passed (14 calls); NATIVE-10/16/17 failed, and NATIVE-18..23 did not
execute after the owner-helper deadline. Postflight remained fail-closed.
A separate NATIVE-16 component replay and native Files/TXT read passed. The
new upload replacement passes mobile304/22 files but still requires rebuild and
full native replay. Retained wrong-binary/interrupted/failed runs are not passes.
See `MOBILE_BUILD_CHECKPOINT_2026-10-25.md` for current evidence and open gates.
The parent owns emulator, browser/CA installation, binary build, services and
serialized execution. No Metro launch, policy workaround, production access,
paid call, commit, push or worktree creation is authorized by this sidecar.

## Executable Inventory

`apps/mobile/e2e/core-20261025.json` is the independent intended inventory;
`journeys.mjs` supplies discovery. Each platform has exactly 23 identities,
prefixed `android:` or `ios:`. Collection is not execution. Windows cannot
certify iOS; the same harness still needs an actual Mac/Xcode Simulator run.

The following table retains the original sidecar discovery state, not the
latest runtime verdicts summarized above.

| Case | Concrete native boundary | Original Sidecar State (Historical) |
| --- | --- | --- |
| NATIVE-01 | Real browser form, explicit login/consent MFA stage, unchanged PKCE and principal/workspace; consent has 403 attempt, one verified MFA/fresh identity read, explicit second Connect, Open CaseOps gesture, one 200 grant/token | Earlier handoff failed; replacement not run |
| NATIVE-02 | Today, Matters, Calendar and Work destinations | Not run |
| NATIVE-03 | Seeded Today task title, source identity, date/status and exact Matter navigation | Not run |
| NATIVE-04 | Exact matter-code search, detail, authoritative reload and restart | Not run |
| NATIVE-05 | Exact case-number search, detail, authoritative reload and restart | Not run |
| NATIVE-06 | Exact filing-number search, detail, authoritative reload and restart | Not run |
| NATIVE-07 | Exact CNR search, detail, authoritative reload and restart | Not run |
| NATIVE-08 | Exact temporary e-case number search, detail, authoritative reload and restart | Not run |
| NATIVE-09 | One acknowledged note POST; server-owned saved ID and body retained after restart | Not run |
| NATIVE-10 | Exact recorded agenda date/value, reload, source Matter and next-hearing value | Not run |
| NATIVE-11 | Invalid date has an actionable error, preserves selected day and sends no agenda request | Not run |
| NATIVE-12 | Work task source; current draft revision, body, exact citations or honest empty list; reload and no formal/generation mutation | Not run |
| NATIVE-13 | One-character note disables save; corrected text enables save; zero POST | Not run |
| NATIVE-14 | Unsaved navigation Stay preserves text; Leave discards; zero POST | Not run |
| NATIVE-15 | Actual process restart refreshes once, rechecks identity, reloads Matter, no browser token exchange | Not run |
| NATIVE-16 | Killed editor has no automatic save or memory-only text restoration | Not run |
| NATIVE-17 | Dedicated active Matter disposed by real fixture owner while editor is held; stale save rejected, notes and terminal lifecycle retained | Fixture owner required; not run |
| NATIVE-18 | Dedicated held Matter loses access through real owner; reload denies and hides source labels; notes unchanged | Fixture owner required; not run |
| NATIVE-19 | Real seeded foreign-tenant search produces no foreign row/title/code | Foreign seed required; not run |
| NATIVE-20 | Native device-session Current flag, cancel without DELETE, confirm one 204 DELETE, real logout, restart signed out | Not run |
| NATIVE-21 | Complete ledger includes exact per-login MFA attempt/grant/token sequence; zero rejected markers/routes or overflow | Not run |
| NATIVE-22 | Acknowledged logout once, no private surface, no refresh after restart | Not run |
| NATIVE-23 | After NATIVE-22 passes all phases: actual Android Home keycode 3 / iOS Home, observed running background (Android package left), activate bound app without termination; signed-out panel and enabled sign-in restored, no private UI or auth requests | Not run |

The historical `inventory.json`, `core.mjs` and `testids.json` remain the original
six-case subset. The reconciler selects that subset only for its original
scope and absent inventory ID. It never relabels six-case receipts as the dated
23. Prior dated 22-case receipts remain historical and cannot certify the new
case. No failed or historical report is rewritten.

## Parent Integration Contract

The existing `scripts/mobile/local-bootstrap.py` receipt is the infrastructure
owner, not a replacement auth server. Assemble an external, secret-free
`CASEOPS_MOBILE_FIXTURE` from that receipt, the actual seed ledger and the binary
receipt. No sample customer or invented legal record is admitted.

- Keep the existing binary/device fields: absolute `appPath`, `appId`,
  `binaryVersion`, `binaryBuild`, `deviceName`, `platformVersion`, `udid`,
  `binarySourceSha`, `binarySourceFingerprint`. The dedicated app ID is
  `ai.caseops.mobile.dev`, or the exact Android
  `ai.caseops.mobile.dev.localacceptance` / iOS
  `ai.caseops.mobile.dev.simulatoracceptance` only under this isolated
  Docker/synthetic dated fixture. Cross-platform and arbitrary suffixes,
  including the nonexistent `ai.caseops.mobile.qa`, are rejected.
  Source changes require a rebuild.
- For either standalone acceptance ID, `buildReceipt: {path, sha256}` binds AgentB's actual standalone
  `build-acceptance.mjs` receipt. Its platform/profile, app ID, source SHA and
  fingerprint, artifact path/hash, API/web origins, embedded marker and
  `devEnabled: false` must match. Also provide actual device-side `apiOrigin`.
  Android also requires `publicCa: {path, sha256}` matching the build receipt's
  embedded public-CA hash. Appium enforces installation of the bound artifact
  without clearing retained session data; binary bytes are rehashed post-run.
- Set `coreInventory: "native-core-2026-10-25"`, `environment:
  "docker-integration"`, `syntheticDataOnly: true`; provide `backendSha`,
  `backendRevision`, `webSha`, `webRevision`, `gatewayRunId`, host-loopback
  `gatewayUrl` and TLS `webGatewayUrl`. Map web identity from the existing
  receipt's `webIdentity`. Dirty `unavailable` release identity is not accepted.
- `isolationEvidence: {path, sha256}` binds the unchanged actual Docker
  `receipt.json`: exact API/web identities, project-owned API/web/PostgreSQL
  container/image/network inventory, `webAcceptanceMarkerBuild: true`,
  `metroLaunched: false`, `productionAccessed: false` and synthetic-data flag.
  Container/image receipt and a boolean are prerequisites, not native proof.
- Provide exact `principalLabel`, `workspaceLabel`; `auth` contains
  `webOrigin` (device-side TLS origin), `companySlug`, `emailEnv`, `passwordEnv`,
  and explicit `mode: "native-firefox"` or `"web-context"`.
  Environment names must begin `CASEOPS_MOBILE_`; values never enter fixtures,
  arguments, journals or screenshots. Optional `mfaRequired: true` requires
  `totpSecretEnv` holding only this synthetic account's enrollment secret and
  explicit `mfaStage: "login" | "consent"`. Enrollment never guesses the stage.
  For this observed optional-tenant setup, use `mfaRequired: true` and
  `mfaStage: "consent"`: initial login must not challenge. After checking
  account/workspace and PKCE, click Connect once, require the typed-error-only
  `native-mfa-code` form, submit one current TOTP via Verify code, require
  `Code verified. Select Connect app to continue.`, recheck identity and
  unchanged PKCE, then explicitly click Connect a second time. No automatic
  authorization/replay is accepted. The ledger must contain exactly
  authorize 403 -> one step-up 200 -> fresh identity 200 -> authorize 200 ->
  one token 200. Login-stage fixtures still require their actual login MFA
  challenge and only one successful authorization/token pair.
  Codes are entered into the actual MFA form once; enrollment/recovery is not
  automated. iOS web-context mode can explicitly request the normal consent
  sheet with `iosConsent: true`; it never accepts arbitrary alerts.
- `matter: {id, title, identityLabel, searches}` uses the actual seeded API
  values. `searches` must contain distinct values, in this exact order:
  `matter_code`, `case_number`, `filing_number`, `cnr_number`,
  `temporary_e_case_number`, each `{kind, value}`. The code must be displayed
  as `identityLabel`. Keep exact `noteRoute` and `matterReloadRoute` from the
  existing fixture contract. Do not replace unsupported or missing identities
  with the same matter code five times.
- `today` and `work.task`: `{id, kind: "task", title, metaLabel, matter}`;
  each nested Matter has `{id, title, identityLabel}`. `today` additionally
  requires actual `dueOn`, rendered `dateLabel` and `status` inside `metaLabel`.
  Use the inspected device locale's exact date presentation, not the host's.
- `work.draft`: actual `{id, kind: "draft", title, matter, entry, statusLabel,
  revisionLabel, body, citations, verifiedCitationCountLabel}`. `entry` is
  `"matter-work"` for a manually seeded draft on the task's Matter, or
  `"reviews"` only if the actual review feed contains it (also supply
  `metaLabel`). An empty citation array is honest and explicitly asserted;
  do not manufacture citations or move a draft into review just to pass.
- `calendar`: actual `{day, dayLabel, title, metaLabel, matter,
  nextHearingLabel}`. The ISO input's actual accessibility label remains
  `Agenda date, YYYY-MM-DD`. Current code uses its actual Go to date and
  Reload agenda labels; new parent-owned picker IDs do not establish picker
  interaction coverage until the harness and actual binary are reconciled.
- Optional `foreignMatter`, `lifecycleMatter`, `accessMatter` each require
  `{id, title, identityLabel, search}` from real seed records. Their search
  value must differ from private title/code so input echo cannot masquerade
  as a leaked record. Lifecycle/access targets must be dedicated fresh rows,
  separate from the positive Matter; never reopen a prior disposed target.

The current initial Docker seed only has a matter code, task/hearing IDs,
manual draft, already-disposed negative record and foreign Matter IDs. It does
not yet satisfy all five identifier expectations or fresh stale-editor/access
targets. Preserve these missing prerequisites; do not prune the inventory.

## Firefox Handoff

Firefox 158.0.2 is not a Chromium WebView. Native Firefox mode uses Appium's
real Android accessibility tree and checks `org.mozilla.firefox`, never a fake
web context. Expected official signer SHA256:
`A78B62A5165B4494B2FEAD9E76A280D22D937FEE6251AECE599446B2EA319B04`.
The parent verifies the APK signer and installs/trusts the ephemeral fixture CA
through normal isolated-device settings. No TLS-warning continuation exists in
this harness. Process-scoped Node CA trust must preserve normal verification.

`auth.firefoxUi` requires `packageName`, `version`, `signerSha256`,
`caTrustedThroughSettings: true`, `locatorEvidencePath`,
`locatorEvidenceSha256`, and `locators`. The hashed secret-free evidence JSON
has `kind: "observed-native-firefox-locators"`, the package/version and the
identical locator map. Parent must observe these controls on the real browser
before adding them; unit recipes are not device observations.

Each locator is `{kind: "id" | "label" | "text" | "buttonText", value}` with an exact unique
visible match. Required keys: `urlOpen`, `urlValue`, `companySlug`,
`email`, `password`, `submit`, `principal`, `emailFact`, `workspace`, `connect`.
Optional actual `signInLink` / `useAnotherAccount` locators enter the real form;
MFA requires `mfaCode` / `mfaSubmit`. Consent specifically requires
`mfaCode: {kind: "id", value: "native-mfa-code"}`, exact Verify code
`mfaSubmit`, and `mfaVerified: {kind: "text", value:
"Code verified. Select Connect app to continue."}` in the hash-bound observed
recipe. A new unobserved control stays incomplete, not inferred from source.
Use `urlCloseMode: "android-back"` only with its observed evidence; Back loops
at most twice while the exact URL editor remains visible, stopping as soon as
it closes. Otherwise `urlClose` is required. Up to three observed `prepare` actions
can open the custom tab in Firefox; up to two `afterConnect` actions can
complete the normal app-opening prompt. No XPath, ordinal field, coordinate
login, cookie scrape, browser storage read, token injection or forged callback.
The address is read only before Connect, checked against `/native/sign-in`
and the identical return from `/sign-in`; callback authorization codes are
neither read nor logged. Missing observed controls means incomplete auth.

The real web API client currently needs the parent's explicit test-only local
web marker build. Set `browserApiMarkerVerified: true` only after that build
and gateway evidence. Every API request must arrive marked; the harness does
not inject authorization or patch browser fetch. Gateway evidence must include
real browser `/api/auth/native/authorize` alongside native token exchange.

## Bounded Fixture Owner Controls

No lifecycle/access endpoint is invented by this harness. Optional
`ownerControls: {modulePath, sha256, capabilities}` admits a reviewed local
adapter only when the real isolated fixture owner implements it. Its sole
export is `control({operation, targetId, runId, backendSha, marker, signal})`.
Supported capabilities: `disposeMatter`, `readMatterState` on the dedicated
lifecycle target; `revokeMatterAccess`, `readNoteState` on the dedicated access
target. Native device revocation uses the real Account UI, not this adapter.

Each call must finish/abort its real SQL/transport within ten seconds, never
replay an uncertain mutation, and return `{kind: "docker-owner-control",
operation, targetId, runId, backendSha, evidencePath, evidenceSha256, result}`.
The evidence file is bounded, hash-checked and retained outside Git. State
results contain actual lowercase `status`, `isActive`, `lifecycleVersion` and
canonical ordered `noteIds`; access revocation returns `accessAllowed: false`.
No undefined note/version comparison is accepted. An uncertain adapter poisons
subsequent mutation setup. Missing capability produces blocked setup and an
explicit not-run call, never a skip/pass. Adapter evidence cannot certify an
unexecuted native body or the separate locked post-preflight disposal race.

Gateway admission must include the actual read/auth/note routes and the new
`GET /api/auth/native/sessions`. Session DELETE requires the exact current
server-owned session ID, admitted safely from the real bounded session list;
do not introduce unrestricted route wildcards. Record count is bounded at 500;
overflow or missing marker is a failure, not permission to discard history.
Consent recovery also needs marked `POST /api/auth/mfa/step-up` and marked
`GET /api/auth/me`. The parent-observed CustomTab preparation is More options
then Open in Firefox; those two label locators must be present in the pinned
external observation/recipe, not added as an unverified fallback.

## Full Matrix Still Open

Every row remains unverified on Android and iOS. A listed case covers only the
named boundary, not its entire acceptance group.

| Group | Dated core subset or still-missing work |
| --- | --- |
| MOB-01 | NATIVE-01; native run and all required MFA variants missing |
| MOB-02 | NATIVE-01 real PKCE path; invalid invitation/reset/replay/expiry negatives missing |
| MOB-03 | Missing OTP recovery, biometrics, enrollment-change and app-lock proof |
| MOB-04 | NATIVE-15/20; expired-access, refresh replay and external device-revocation negatives missing |
| MOB-05 | NATIVE-19/22/23; tenant switching and mixed-realm/cookie negatives missing |
| MOB-06 | Missing verified cold/warm links and forged/revoked/wrong-account link negatives |
| MOB-07 | NATIVE-03; ownership/team/unassigned/count/continuation semantics missing |
| MOB-08 | NATIVE-04..08; five real fixture identifiers and native execution required |
| MOB-09 | NATIVE-18/19; ethical-wall, direct foreign-detail/file bytes and grant/membership variants missing |
| MOB-10 | NATIVE-17 stale preflight rejection; locked mutation race, retained reads and controlled web reopen/replay missing |
| MOB-11 | NATIVE-09/13; native save/persistence execution required |
| MOB-12 | Missing lost acknowledgement and exact-operation reconciliation/Unknown journey |
| MOB-13 | Missing supported hearing mutation and server audit/reload journey |
| MOB-14 | NATIVE-10/11; native picker, midnight/leap/DST/timezone variants missing |
| MOB-15 | NATIVE-10; busy agenda, overflow/continuation, filters and return-position proof missing |
| MOB-16 | Missing integrated GC obligation/source/responsible-person native journey and fixture |
| MOB-17 | Missing integrated IP date/rule/source native journey and fixture |
| MOB-18 | Missing counsel/budget exact-currency/precision source journey and fixture |
| MOB-19 | NATIVE-12 task; complete undated queue, ordering and continuation contract still missing |
| MOB-20 | NATIVE-12 draft; recommendation read-through and exact citations/version execution missing |
| MOB-21 | Missing Files/hearing-pack viewer, audited source, zoom and return-position journey |
| MOB-22 | Missing native clean file/camera upload, scanner availability and byte reload journey |
| MOB-23 | Missing native EICAR, scanner outage, access/lifecycle upload race journeys |
| MOB-24 | Missing native permissions, picker fallback, format and size boundary journeys |
| MOB-25 | Missing native upload cancel/unknown/kill/staging cleanup journeys |
| MOB-26 | Missing private viewer/cache/temp/backup/reinstall/share and revoked-byte proof |
| MOB-27 | Missing real authorized inbox/count/read/dismiss native journey |
| MOB-28 | Missing physical push foreground/background/killed/locked-screen and reauthorization proof |
| MOB-29 | Missing device-token/notification-permission/unregister/provider/duplicate-delivery proof |
| MOB-30 | NATIVE-21 plus all request windows; browser marker build/native run/full device-network audit missing |
| MOB-31 | Missing full AI-policy/budget/revoked-source negative native journey |
| MOB-32 | Missing real TalkBack/VoiceOver/200%-text/contrast/reduced-motion proof |
| MOB-33 | NATIVE-14 back control only; full target/keyboard/safe-area/iOS gesture proof missing |
| MOB-34 | Missing small/large phone/tablet geometry and long-content execution |
| MOB-35 | NATIVE-23 signed-out warm resume only; actual offline/slow/error/stale/authenticated foreground-authority journeys missing |
| MOB-36 | NATIVE-14/16/23; real unsaved/kill/signed-out resume execution and physical privacy checks missing |
| MOB-37 | Missing previous-client/additive rollout/minimum-version/rollback proof |
| MOB-38 | Missing named-device startup/work/tab budgets, row/query bounds and responsiveness proof |
| MOB-39 | Binary/source/backend/harness binding implemented; signing/SBOM/store/privacy/deletion review missing |
| MOB-40 | Missing complete two-platform/Docker/CI/main/exact-release/signed-beta acceptance |

Files and IP/contracts source components being developed by other agents are
not counted as integrated or passed here. No unverified skip can close a row.

## Verification And Receipts

Run only tooling unit tests and collection in this sidecar:

```text
node --test scripts/mobile/tooling.test.mjs
node scripts/mobile/run-native.mjs android --collect
node scripts/mobile/run-native.mjs ios --collect
```

The parent later runs the actual binary against the isolated fixture. New
receipts bind `inventoryId`, full intended/discovered arrays, actual APK/app
hash, source fingerprint, exact API/web identities and a separate harness
fingerprint. They fsync setup/call/teardown incrementally, enforce phase order,
reject interrupted or mismatched completion, retain blocked/not-run identities
and recheck serving revisions/source/harness after the run. Existing evidence
is never overwritten. Unit doubles test orchestration only; they do not count
as native, Docker, browser-login or iOS E2E acceptance.

Historical initial sidecar verification on 25 October: **56/56 tooling unit
cases passed**, zero failures/skips/cancellations/todos; both collection CLIs
then independently discovered the exact **22/22** inventory. That result is
not evidence for NATIVE-23. Later Firefox setup evidence and the 64-case
source-freeze manifest were retained outside Git, without credential entry.

NATIVE-23 is a separate regression for the parent-reproduced signed-out
foreground privacy-cover defect. Its setup cannot authenticate and requires
NATIVE-22's setup/call/teardown to have passed in this same run. A process kill,
app still foreground after Home, missing/disabled sign-in, private UI or any
auth request (including an in-flight refresh) fails the case. iOS uses its
actual Home button and observes running background/suspended state; Windows
collection does not certify that behavior. No new fixture mutation is needed.
The sidecar does not touch the parent's current device/Appium inspector.
**NATIVE-23 native execution is not run; the reported bug remains Inconclusive
until the parent runs the source-bound rebuilt binary.** Existing reports
remain untouched. Files/source/upload groups remain explicitly missing until
actual fixture metadata and native journeys are integrated.

Post-regression tooling verification: **73/73 unit cases passed**, zero
failures/skips/cancellations/todos. Both collection CLIs independently
reconciled the exact **23/23** intended/discovered inventory. Scoped
`git diff --check` passed. These are harness checks, not native execution.

Consent-MFA follow-up: **84/84 tooling unit cases passed**, zero failures,
skips, cancellations or todos; intended/discovered collection remains
**23/23 per platform**. The suite covers explicit consent/login staging,
typed-error-form absence, refused verification, changed account/PKCE,
automatic Connect rejection, exact traffic ordering and editor-visible-only
Back dismissal. These checks use unit doubles, not native/browser acceptance.
No device, Appium, service or historical report was changed by this update.
