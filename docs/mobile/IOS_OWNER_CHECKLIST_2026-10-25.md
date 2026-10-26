# iOS Owner Handoff Checklist

Date: 25 October 2026. Journeys J20/M22 and existing J01/J03/J04/J08/J14;
US-MOB-01..08. **macOS/Xcode/iOS: NOT RUN. Release acceptance: OPEN.**
This is an owner action checklist, not a test receipt or closure of all forty
MOB groups. Follow the [Mac runbook](../../scripts/mobile/MACBOOK_RUNBOOK.md);
do not execute its gated steps before their blockers are resolved.

## Superseding 26 October status

Latest source update: source-gates-12 verifies348 mobile tests;530 tooling cases/528 pass/two Windows-only skips;96 Python; selected API124 pass/five platform skips;2022 web tests with real coverage thresholds;8 actual built-browser cases and both builds/types. Guarded HTTPS production configuration is prepared, not signed/deployed/association-verified. Android753 APK/static16KiB and preserved API/web receipts are historical after this source update; final matching iOS/Android builds and40 cases each remain pending. Earlier dated counts/receipts below are retained history; STORE_RELEASE_2026-10-26.md has the current evidence map.


The Windows-only25 October checklist and unchecked case table below are retained historical handoff material; their `NOT RUN` labels do not erase later actual Mac executions. Current evidence and release blockers are maintained in [STORE_RELEASE_2026-10-26.md](STORE_RELEASE_2026-10-26.md).

An older signed Simulator app passed23/23 core cases. The later host-fixed8Tddh13c app completed the full17 Files inventory with15/17 calls passed and two genuine embedded-reader failures (FILES09 PDF page readiness, FILES10 image zoom acknowledgement), all51 phases/17 sessions retained. Its five uploads/source-byte admissions,13 privacy boundaries, six-cohort original preservation, zero private copies and final signed-out restart passed. Runtime `Function.toString()` under the actual pinned Hermes produced a bytecode placeholder; the generated static browser-script replacement is source/browser/Hermes-control verified and awaits a new canonical signed app and actual17 Files/fresh23 core replay. Android requires its own matching rebuilt23core/17Files/privacy execution; no platform export or older native pass substitutes for it.

Latest integrated source gates:523 tooling collected/521 passed/two existing Windows-only skips; mobile346/346 plus TypeScript and asset check; Python96/96; selected API72 passed/one Windows curl.exe skip plus Ruff; web1979/1979 with build and both type-checks. Exact logs and the retained initial failures are under `pr558-release-20261026/canonical-final-10/`. Four high Expo/node-forge audit entries remain a release blocker. No store upload, release approval or current40-case native certification is recorded.

A completed required hosted API shard11/13 on older published762980ab is failed:14 failures,876 passes,452 skips, including `tests/test_public_lead_notifications_20261021.py`. Incoming-main marker/transport expectations remain under investigation; local scoped passes are not replacement hosted acceptance. Preserve that failed head and require fresh canonical checks.

For the next canonical run, use the current Mac runbook and actual immutable build/backend/owner/consent/MFA references. Preserve DB/uploads/keys/CA/routes and all historical cohorts, install the new QA app in place, use fresh core member/negative targets, and retain failed/unknown mutations without replay. Historical unsigned-build and inferred-consent instructions below must not override the current ad-hoc signature verification or observed no-alert/consent recipe.

## Historical Evidence Boundary

| Item                                | Evidence and limit                                                                                                |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Local app/API/web baseline | `4959129a0108bd332c4eacc86a3e0ec18f05711c`; Android16/API36 dated core23/23 passed, not iOS/full-v1 |
| Finite iOS Hermes export | Actual Windows export:900 modules,9,210,328 bytes; NOT Pods, Xcode, an installed `.app`, SwiftUI behavior or an iOS test |
| Mac host, CocoaPods and Simulator   | Not run; Windows cannot certify these                                                                             |
| Dated core                          | 23 intended/executable IDs, NATIVE-01..NATIVE-23, `native-core-2026-10-25`; offline collection only               |
| iOS core results                    | All 23 NOT RUN; require actual source/binary/backend-bound phases and completion                                  |
| Files supplement | Separate Android supplement still unverified; two actual native uploads persist, latest0/2; no iOS Files inventory/execution |

The final pushed candidate may be newer than this baseline. Parent must supply
its full SHA after publishing all reviewed app/API/web/bootstrap/harness inputs.
Do not build an older branch tip and execute newer tests against it.

The iOS receipt `ios-hermes-4959129a-20261025-e3162c/receipt.json` binds app
fingerprint `be52fcdc07d205e7d5b2c3ca80fef382957e90f74224b06b13d94ca57fb5c000`
and Hermes SHA `297d811f317bac13d669b8565ba495ebc8979230f98b7d230de5d2dc763146ed`.
Its `localhost` API/web origins are not the Mac fixture's `127.0.0.1` origins.
Rebuild on Mac; do not reinterpret this Windows export as an installed binary.
The fresh high-severity node-forge advisory through Expo's CLI is unpatched;
the unchanged security gate blocks public release/signing, not just a checklist
label. No audit waiver, crypto fork or forced older SDK downgrade was applied.
The complete Windows four-file tooling run is263/263, not a Mac execution.
Preserve Mac's actual inventory and its two explicit Windows-only skips.

## Owner Prerequisites

- [ ] Parent has pushed `codex/mobile-app-build-20261024` and supplied the exact
      SHA and authorized repository URL. Use one clean dedicated Mac checkout, not
      copied Windows native folders, generated secrets or fixture volumes.
- [ ] Record Mac architecture/macOS, Node/npm/Python/Ruby/CocoaPods, full Xcode
      path/version and Simulator device/runtime/UDID. Prefer retained Node 24.15.0;
      host Python must be >=3.11. Do not infer the Xcode/toolchain from RN's minimum.
- [ ] Owner reviewed Xcode terms/first-launch components/runtime and Docker
      Desktop prerequisites/terms. No silent license acceptance, global developer
      directory switch, new paid/cloud service or unrelated service shutdown.
- [ ] Install with `apps/mobile`'s own `npm ci --include=dev` and lock; it is not
      a root workspace. Keep Expo 58.0.19, RN 0.88.0, React 19.3.0 and `@expo/ui`
      58.0.23. iOS controls are the real SwiftUI adapter, not Compose or DOM controls.
- [ ] Verify WebView 14.0.1, PDF.js 6.4.299 asset hashes/notices and
      `prepare-viewer-assets.mjs --check`; run current type/component/tooling checks.
      Do not rewrite locks, repair dependencies automatically or fetch viewer CDNs.
- [ ] Exact owner-managed Ruby/CocoaPods pair is recorded. There is no committed
      project Ruby lock or iOS Podfile.lock in this source. First Pods resolution
      and resulting lock/native closure need review; no `pod update`, unpinned sudo
      install or SwiftPM migration. The wrapper uses `pod` on PATH.
- [ ] One dedicated Simulator is selected; only its boot/install/trust changes
      are authorized. No physical signing, provisioning update, distribution
      account, TestFlight or App Store action is required by this handoff.

## Portability Components And Mac Gates

The bounded implementation now adds `--platform android|ios` (Android default),
stored/validated origins, an outside-Git iOS public-URL Compose override,
Darwin-only read-only Simulator locale observation and config-bound iOS
`web-context` / `iosConsent: true`. Android origins/Firefox remain unchanged.
Gateway/shared harness files and their 64-entry admission bound were not edited.
Verdict: **Partially fixed**, with offline component tests only. The checkboxes
below require actual Mac proof and remain unchecked. The complete Python test
module passed **39/39** on Windows: all prior 19 plus 20 added cases, preserving
the 64-entry admission boundary. No real Docker, device, simctl or Xcode run was
performed; external commands in portability tests are mocks.

- [ ] On this Mac, `up --platform ios` persists the iOS platform and exact
      loopback API/web origins in its new cache. The web build, API public URL,
      extension and immutable receipt agree. Use `--platform ios` for every
      subsequent action; do not reinterpret an existing Android cache.
- [ ] The generated iOS Compose override changes only API/migration public web
      URL. Canonical Compose/CORS/TLS/network/provider/image fences are unchanged.
      Immutable receipt's `platformComposeOverride` path/SHA-256 matches that file.
      Strict HTTPS/SAN/unknown-CA/wrong-host/no-paid checks still pass on real Docker;
      no fake receipt, DNS/routing workaround, generic gateway or ATS weakening.
- [ ] `extend --platform ios --udid <actual-UUID>` sees exactly one available,
      already-booted iOS Simulator on Darwin. Retain its two read-only CLI commands,
      five-second deadlines, accepted 64 KiB response bounds, actual AppleLocale
      and normalized locale evidence. No boot/erase/locale write/app launch occurs
      in extension observation. Missing/unsupported locale is a failure, not a
      default. Formatted labels remain expectations until actual UI assertions.
- [ ] iOS extension auth is `web-context` with `iosConsent: true`; actual
      system-browser context/normal consent and MFA stage are still observed on
      this Mac. Never copy Android Firefox selectors, scrape cookies, inject a
      native token or accept arbitrary alerts. Android uses its host SDK's real
      `adb.exe` on Windows or `adb` on macOS/Linux without PATH fallback.
- [ ] Pinned Docker images work on the selected Mac architecture, with real
      bind mounts, fresh migrations, required scanner, disk/inode and unchanged
      source checks. No image substitutions or external provider runtime networking.
- [ ] Parent supplies a Mac-local run plan and hash-bound schema-2 dynamic
      policy/status descriptor. Existing `--inspect-local`/`--prepare-local`
      validate/assemble supplied evidence; they do not generate it. Bootstrap
      preserves prior gateway policy metadata but does not manufacture a complete
      descriptor or session ID. No shared harness change is authorized here.
- [ ] Effective seed projection matches `inspectLocalPlan`'s actual flat
      `taskId`, `draftId`, `hearingId`, `calendarDate`, `otherMatterId`
      fields, nested `calendar.eventId` and extended member/task identities.
      Keep the exact opaque event ID from Calendar; never derive it from the
      hearing UUID. Raw extension JSON is nested;
      the base owner seed names the wrong actor/task for access proof. Retain both
      immutable receipts/hashes. The reviewed projection remains parent-owned.
- [ ] Dynamic current-session admission is bound to the reviewed
      `local-gateway.py`, isolation receipt, fresh status/run ID and exact routes.
      `session-admission.mjs` linkage validates; current-only/unrevoked/no-cookie/
      consume-on-attempt behavior and the 64-event history remain intact. The
      generic Node gateway cannot replace this or guess NATIVE-20's DELETE ID.
- [ ] Mac-local owner bindings reference actual API image/container and hashed
      extension/Python/module files, not Windows paths. All four bounded operations
      are admitted; read-only baseline checks succeed. Use the fresh member,
      member-owned task and distinct lifecycle/access targets. Owners bypass Matter
      restrictions; never reopen or reuse a consumed target.

## HTTPS And Native Build

- [ ] Owner-authorized `up --platform ios` uses a fresh outside-Git cache,
      explicit API/web ports and `--mfa`, as shown in the runbook. Retain actual
      status/probe/auth-probe/scanner-probe outcomes; new code and Windows mocks do
      not prove the Mac bootstrap. No existing frozen 60f image/service/device was
      changed by this implementation.
- [ ] New CA/key remain outside Git on this Mac. Import only its hash-verified
      public CA into the one dedicated Simulator. Verify SANs and exact HTTPS
      API/web origins, host loopback binding, and separate native/browser/Node
      trust. No Windows CA-key transfer, host-wide Keychain trust, `curl -k`,
      `NODE_TLS_REJECT_UNAUTHORIZED=0`, ATS exception or warning continuation.
- [ ] Native API `https://127.0.0.1:8443` and web
      `https://127.0.0.1:3443` match the reviewed Mac-aware fixture/browser build.
      Android CA environment variables are unset.
- [ ] Actual Mac runs `build-ios-simulator-acceptance.sh` with explicit UDID;
      child profile `ios-simulator-acceptance`, marker 1, exact source and bundled
      production-mode JS. No Metro, Expo Go or `run:ios` dev-server substitute.
- [ ] New unsigned Release Simulator `.app`, nonempty `main.jsbundle`, QA ID
      `ai.caseops.mobile.dev.simulatoracceptance`, version/build and embedded
      origins/marker/source pass build verification. Both signing switches remain
      disabled; no `-allowProvisioningUpdates`. Retain prebuild/Pods/Xcode logs,
      Podfile.lock, source fingerprints and canonical bundle-tree binary hash.
- [ ] Install/launch only that reported `.app` on the selected Simulator. See
      genuine CaseOps/SwiftUI controls, not a development launcher. Verify unchanged
      `caseops://oauth/callback` goes to this QA app, not a second dev installation.
- [ ] Owner-local Appium 3.8.0, WebdriverIO 10.1.0 and XCUITest 12.20.0 pass
      doctor and actual WDA/Xcode/runtime checks. No project lock edit, relaxed
      security, distribution signing or cloud Mac. Tool versions are not a pass.

## Exact 23-Case iOS Gate

Every row is **NOT RUN on iOS**. These summarize the dated inventory, not the
entire mapped MOB groups. Blocked/skipped/unstarted/interrupted is not passed.

| Case      | Required native boundary                                                                                        | iOS     |
| --------- | --------------------------------------------------------------------------------------------------------------- | ------- |
| NATIVE-01 | Real browser login, explicit MFA stage, unchanged PKCE/principal/workspace, one successful grant/token          | Not run |
| NATIVE-02 | Four actual native destinations                                                                                 | Not run |
| NATIVE-03 | Seeded Today task/date/status opens exact Matter                                                                | Not run |
| NATIVE-04 | Matter-code search/detail/reload                                                                                | Not run |
| NATIVE-05 | Case-number search/detail/reload                                                                                | Not run |
| NATIVE-06 | Filing-number search/detail/reload                                                                              | Not run |
| NATIVE-07 | CNR search/detail/reload                                                                                        | Not run |
| NATIVE-08 | Temporary e-case search/detail/reload                                                                           | Not run |
| NATIVE-09 | One acknowledged note, same ID/body after restart                                                               | Not run |
| NATIVE-10 | Exact agenda date/value, reload/source navigation                                                               | Not run |
| NATIVE-11 | Invalid agenda date neither fetches nor replaces date                                                           | Not run |
| NATIVE-12 | Work task/current read-only draft revision/body/citations after reload                                          | Not run |
| NATIVE-13 | Short note disables save; corrected input enables without POST                                                  | Not run |
| NATIVE-14 | Unsaved Stay retains text; Leave discards without POST                                                          | Not run |
| NATIVE-15 | Restart rotates refresh once, no browser token exchange                                                         | Not run |
| NATIVE-16 | Process kill neither restores nor saves memory-only note                                                        | Not run |
| NATIVE-17 | Fresh owner-disposed target rejects stale editor without resurrection                                           | Not run |
| NATIVE-18 | Held target loses member access; reload hides private content                                                   | Not run |
| NATIVE-19 | Other-tenant search leaks no foreign label/row                                                                  | Not run |
| NATIVE-20 | Current session cancel/one confirm/acknowledged DELETE; signed out after restart                                | Not run |
| NATIVE-21 | Whole-run staged-MFA/grant/token ledger; zero missing marker/unadmitted route                                   | Not run |
| NATIVE-22 | Acknowledged logout purges private content and survives restart                                                 | Not run |
| NATIVE-23 | After NATIVE-22, actual Home background/warm resume restores usable signed-out controls without private UI/auth | Not run |

- [ ] `node scripts/mobile/run-native.mjs ios --collect` returns all identical
      ordered intended/discovered 23 IDs. Windows collection in this task is
      only an offline inventory check, not an iOS run.
- [ ] Mac plan passes `ios --inspect-local` with zero blockers, then
      `ios --prepare-local`; output fixture is outside Git with verified
      seed/owner/gateway/build/CA/isolation references and real expectations.
- [ ] App/API/web source identities and actual live revisions agree before
      mutations. Fresh member/targets and clean gateway run are bound. Negative
      probes precede `begin-core-ledger`; never reset it during native traffic or
      erase old failures. Rebind owner controls after final API rebuild.
- [ ] Load protected synthetic member/TOTP values only into plan-named process
      variables. No secrets in plans/logs/screenshots. Browser performs its actual
      login/consent MFA, not API auth-probe's session. Unset values after the run.
- [ ] `node scripts/mobile/run-native.mjs ios` completes its finite 30-minute,
      zero-retry run in genuine `NATIVE_APP`; retain every setup/call/teardown phase,
      preflight/postflight/completion and source/binary/device/backend/web/harness
      identities. Do not prune cases or raise deadlines to force a pass.
- [ ] `node scripts/mobile/reconcile-native.mjs ios <actual-events.jsonl>`
      accepts the exact 23-case receipt, unchanged source/bundle/live revisions and
      marker/route ledger. Missing completion remains incomplete.
- [ ] NATIVE-20 links a fresh marked native session-list read to its current
      unrevoked ID and single consumed acknowledged DELETE. NATIVE-23 is actual warm
      resume after acknowledged logout, not cold launch, re-auth or permanent cover.
- [ ] Retain failed/blocked/unstarted cases and unknown mutations. A new full
      attempt gets fresh targets; no note/upload/session-delete/owner mutation
      replay or resurrection. Return complete unique directories to parent.

## Files And Wider Acceptance Still Open

- [ ] Separate iOS Files inventory and actual Simulator picker/source fixture
      exist. Current `files-20261025.mjs` is Android-only, owner-pinned to a Windows
      fixture and outside the core CLI. FILES-01 describes TXT read/return, not an
      iOS receipt. FILES-02 deliberately blocks for real picker/upload evidence.
- [ ] Prove native file choice, exact Matter/lifecycle precondition, real scan
      outcome, acknowledged identity/hash and persisted reload; separately cover
      cancel/unknown/no-resubmit, EICAR, scanner outage and access/lifecycle races.
      `admit-upload` is exact route admission, not native upload acceptance.
- [ ] Prove actual iOS PDF/image/TXT and bounded DOCX behavior, source/zoom/page
      controls, revoked-byte rejection and return position. Bundled renderer/Hermes
      output, external URL/share or fake images are not private reading evidence.
- [ ] Prove root-owned picker/background reauthorization, signed-out purge,
      owned-temp cleanup, cache/backup/reinstall/screen-preview restrictions and
      disabled external sharing. Never keep hidden private screens alive to pass.
- [ ] Full MOB-01..40, physical-device/VoiceOver/large-text/responsive/privacy,
      camera/biometrics/push, signing/distribution and exact-release product gates
      remain separately inventoried. A 23-case core result cannot close them.

## Return And Cleanup

Return approved source SHA/input fingerprint; Mac/Xcode/runtime/tool versions;
immutable Docker seed/extension/image/revision/scanner/TLS/isolation and dynamic
policy receipts; build logs/native lock/embedded config/canonical `.app` hash;
exact 23-case collection/events/summary/reconciliation and failures; plus the
pending Files/wider-matrix list. Never send passwords/TOTP/tokens/private keys or
customer records.

Only owner-directed `local-bootstrap.py stop --platform ios --cache <same>` may stop the owned
stack. Preserve volumes/evidence; no global prune, `down -v`, broad Simulator
shutdown or global trust changes. Selected-device cleanup is a distinct owner
action. No services, installs, commits, pushes or deployment were performed by
this Windows offline component task.
