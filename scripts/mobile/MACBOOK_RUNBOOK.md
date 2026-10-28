# Owner MacBook: Standalone iOS Simulator Build And XCUITest

**Local Mac update, 25 October 2026:** a locally ad-hoc-signed Release Simulator
build passes strict signature and private Keychain-group verification.
The complete authenticated iOS core inventory now passes **23/23**:
all 69 setup/call/teardown phases and preflight/postflight checks passed, with
zero failed, blocked or unexecuted calls. The earlier failed runs remain retained.
The final harness passes 352 tests with two Windows-only skips; all 304 mobile
tests and 43 Python fixture tests pass. The rebuilt app also passed an actual
open-keyboard scroll proof with unchanged note text and zero note submission.
The original Windows handoff instructions below do not constitute additional
native evidence. No production change or distribution signing is authorized.

## Observed Local Mac Setup

The dedicated checkout uses `codex/mobile-app-build-20261024` at
`6de2bacc3d8afaa5f352e6b811f1297be07379ed`, with the local Apple Silicon fixture
override documented by its uncommitted helper diff. Current signed app inputs have
fingerprint `432546c21e973b621e09719650702fd3cda3d3fcaf8bd9e8f1e64052caa1803e`.
Observed tools: Xcode 27.1 (updated from 26.6 during setup), iOS Simulator 26.5,
Node 24.15.0/npm 11.12.1,
Ruby 4.0.9/CocoaPods 1.17.0, Watchman 2026.10.19.00, Appium 3.8.0 and
XCUITest 12.20.0. The shell-local developer directory avoids changing the
global Xcode selection. The activation file is local to this Mac, outside Git:

```bash
source "$HOME/.cache/caseops-mobile/ios-setup/use-env.sh"
cd "$CASEOPS_REPO"
python scripts/mobile/local-bootstrap.py status --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE"
xcrun simctl launch "$SIMULATOR_UDID" ai.caseops.mobile.dev.simulatoracceptance
# Rebuild the locally ad-hoc-signed Simulator app when needed:
bash scripts/mobile/build-ios-simulator-acceptance.sh
```

`CaseOps iPhone 17` is the dedicated Simulator. The owned Colima profile is
`caseops-ios`; Docker configuration is isolated from the user's default context.
API and web use `https://127.0.0.1:8443` and `https://127.0.0.1:3443`.
The new fixture CA is trusted only in this Simulator, with a process-local Node
CA setting. Synthetic credentials/private keys remain protected in the fixture
cache; they are not committed or printed here.

Xcode 27.1 uses `Contents/Applications/DeviceHub.app` for the Simulator UI.
Absence of the older `Contents/Developer/Applications/Simulator.app` path is
not an installation failure. The pinned XCUITest driver supports DeviceHub.
The earlier build with signing disabled failed actual SecureStore startup;
preserve that failure rather than using it as authenticated-test evidence.

Evidence is retained under `$HOME/.cache/caseops-mobile/ios-setup/environment.json`,
which references the actual build, installed-binary hash, smoke result and fixture
receipts. Mobile TypeScript, all 304 mobile cases, and all 43 Python fixture
cases passed. The harness collected 354 cases: 352 passed and two intentional
Windows-only cases were skipped. The real backend's
status/TLS/authentication/scanner probes passed. Startup checks verified native
context, enabled SwiftUI sign-in, background/resume and cold relaunch. Existing
screen-capture protection produces black captures; these are not visual-rendering
acceptance results. The first CoreSimulator discovery hang and interrupted build
are retained alongside the successful targeted-service-recovery build.

The full native inventory and Files supplement remain separate gates. The
existing four high Expo CLI/node-forge audit findings are still open.

Final standalone build receipt:
`~/.cache/caseops-mobile/ios-build-kat0eU0h/receipt.json`.
Canonical app hash:
`e4f1abd01e6ebc328fde08359afe5e3b8ced2cbada20a8d38db88ddd453c4f34`.
Final native report:
`~/.cache/caseops-mobile/ios-acceptance-i47Hqf5B/native-reports/2026-10-25T16-20-32-949Z-ios-1cd06c81/summary.json`.
Its frozen harness hash is
`1b67b4ba6a86f6882337015fbebd354258cf21241f8bde1a9c706b8de51be486`.
The run used fresh synthetic member/terminal-action targets, real browser MFA,
the actual installed signed app, and isolated API/web images at the source SHA
above. Native traffic finished with zero marker/route rejections or overflow.

Retain each failed native report under the acceptance directory. iOS browser
attachment must identify a fresh, visible, focused authorization page and verify
its full PKCE identity before credentials; process-wide window lists can repeat
retained pages. Native rows may expose their complete text as one accessible
button label, and an empty iOS text view's `getText()` can return its label.
Use the verified native value and exact control scope instead of weakening
identity, content or privacy assertions. iOS swipes target the measured outer
ScrollView gutter, avoiding child controls and localized keyboard containers;
the note form uses native iOS keyboard insets. An off-screen home heading must
be bound to its own visible scroll container before any additional Back action.

Gateway descriptors now retain an exclusive `.routes.json` snapshot beside
their status evidence. The mutable fixture inventory is provenance only;
extending the fixture must not invalidate an earlier run's route evidence.

## 1. Evidence And Publication Gate

Retained Android app/API/web evidence uses source
`4959129a0108bd332c4eacc86a3e0ec18f05711c`. The actual Android16/API36 dated
core completed23/23 with passed postflight; that is not an iOS or full-v1 pass.
Older60f1decc references are historical snapshots.

The finite Windows iOS receipt is
`ios-hermes-4959129a-20261025-e3162c/receipt.json`: **900 modules, 9,210,328 bytes**,
Hermes SHA-256 `297d811f317bac13d669b8565ba495ebc8979230f98b7d230de5d2dc763146ed`,
app fingerprint `be52fcdc07d205e7d5b2c3ca80fef382957e90f74224b06b13d94ca57fb5c000`.
Its origins are `https://localhost:8443` and `https://localhost:3443`.
This proves bundling only, NOT a Simulator binary, Mac127.0.0.1 origin
acceptance, CocoaPods, Xcode, SwiftUI behavior or iOS E2E. Build the exact final
published candidate afresh using the Mac-local fixture origins and public CA.

The October25 dependency audit fails on unpatched high advisory
[GHSA-86w9-cpqp-85rv](https://github.com/advisories/GHSA-86w9-cpqp-85rv) in
node-forge1.4.0 through Expo58's CLI. Public release/signing stays NO-GO.
No forced older Expo downgrade, audit exclusion or unreviewed crypto fork is
part of this handoff. Isolated development checks do not waive that gate.

The current dated inventory is **23 cases**, `NATIVE-01` through `NATIVE-23`,
not the historical six or previous 22. Files is a separate pending supplement,
not an extra iOS core case. See the
[owner checklist](../../docs/mobile/IOS_OWNER_CHECKLIST_2026-10-25.md).
A 23-case core result cannot certify all forty MOB acceptance groups.
Android Files remains separately unverified despite two confirmed native uploads;
do not describe its latest0/2 replacement as green. The complete Windows tooling
gate passes263 cases across all four selected files; two PowerShell-specific
cases are explicitly platform-skipped on macOS, whose actual results remain open.

Wait until parent confirms that `codex/mobile-app-build-20261024`, including
all reviewed bootstrap/harness changes, is pushed and supplies its full SHA.
The final published candidate may be newer than the observed `4959129a`.
Use one clean dedicated Mac checkout, not copied Windows native output, volumes,
CA keys, tokens or customer data. Do not reset another user's checkout.

Open a dedicated **Bash** shell (macOS may default to zsh). Replace the three
owner-supplied placeholders, then:

```bash
set -euo pipefail
umask 077
export CASEOPS_REPO_URL="OWNER-AUTHORIZED-REPOSITORY-URL"
export CASEOPS_REPO="/absolute/path/to/CaseOps"
export CASEOPS_EXPECTED_SHA="PARENT-CONFIRMED-PUBLISHED-40-HEX-SHA"
git clone --single-branch --branch codex/mobile-app-build-20261024 "$CASEOPS_REPO_URL" "$CASEOPS_REPO"
cd "$CASEOPS_REPO"
test "$(git rev-parse HEAD)" = "$CASEOPS_EXPECTED_SHA"
test -z "$(git status --porcelain --untracked-files=all)"
git rev-parse HEAD
git branch --show-current
git ls-remote --heads origin refs/heads/codex/mobile-app-build-20261024
mkdir -p "$HOME/.cache/caseops-mobile"
export CASEOPS_HANDOFF="$HOME/.cache/caseops-mobile/ios-handoff-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$CASEOPS_HANDOFF"
sw_vers
uname -m
node --version
npm --version
python3 --version
ruby --version
pod --version
docker version
docker compose version
xcodebuild -version
xcode-select -p
xcrun simctl list devices available
node scripts/mobile/source-snapshot.mjs > "$CASEOPS_HANDOFF/source-before.json"
node scripts/mobile/run-native.mjs ios --collect > "$CASEOPS_HANDOFF/ios-collection.json"
```

Require the remote branch to resolve to the same parent-confirmed SHA. Do not
pull/change source during a build or native run. Record all tool/OS versions
and Mac architecture; do not overwrite a prior handoff directory.

Required: supported Node >=22.19.0 (retained Windows version 24.15.0; prefer
that exact version), npm >=10, host Python >=3.11 (`datetime.UTC`), owner-managed
Ruby/CocoaPods, full Xcode and a compatible installed Simulator runtime.
Owner must review Xcode terms, first-launch/components/runtime and Docker
Desktop terms/availability. Windows consent does not cover these. Do not silently
accept licenses, change the global developer directory, shut down all devices,
or stop unrelated services. Full Xcode must be selected, not Command Line Tools
alone. Do not infer compatibility from RN's minimum: installed Expo/ExpoUI
podspecs require iOS 16.4; the exact Xcode/runtime/package set still needs Mac
compilation. Missing prerequisites are blockers, not completed steps.

## 2. Locked Dependencies And Local Checks

`apps/mobile` is **not a root npm workspace**. Use its checked-in package lock
and local CLI, never a global Expo, fetching `npx`, or dependency repair:

```bash
cd "$CASEOPS_REPO/apps/mobile"
unset NODE_ENV
npm ci --include=dev
npm ls expo react-native react @expo/ui react-native-webview pdfjs-dist
node "$CASEOPS_REPO/scripts/mobile/prepare-viewer-assets.mjs" --check
npm run typecheck
npm test
cd "$CASEOPS_REPO"
node --test scripts/mobile/build-config.test.mjs scripts/mobile/tooling.test.mjs scripts/mobile/local-owner-controls.test.mjs apps/mobile/e2e/files-20261025.test.mjs
git diff --exit-code -- apps/mobile/package.json apps/mobile/package-lock.json
```

Current pins: Expo 58.0.21, RN 0.88.0, React 19.3.0, `@expo/ui` 58.0.25,
WebView 14.0.1, and public PDF.js inputs 6.4.299. iOS uses the actual SwiftUI
adapter, not Android Compose or DOM controls. Verify committed renderer assets
and notices; a missing closure is a stop, not permission for a CDN, fake PDF
image or new package. These checks are components, not native execution.

No committed project Ruby/CocoaPods lock or iOS Podfile.lock was found in this
handoff source. Owner/parent must select and record the exact Ruby/CocoaPods pair.
The wrapper uses `pod` on PATH, not `bundle exec pod`. First generated Pods
resolution remains provisional until the resulting Podfile.lock/native closure
is reviewed and retained. Do not run unpinned `sudo gem install`, `pod update`,
`expo install --fix`, a lock rewrite or an unreviewed SwiftPM migration.
[CocoaPods guidance](https://guides.cocoapods.org/using/getting-started.html)
describes owner-managed Ruby and version pinning, not proof of this package set.

## 3. Platform-Aware Python Fixture (Mac Not Run)

The QA-ID dated gate requires **synthetic docker-integration**, not a fake server.
Use `local-bootstrap.py`, `compose.mobile-local.yml` and `local-gateway.py`.
Do not substitute the generic `no-paid-gateway.mjs`: it lacks the dynamic
current-session DELETE behavior needed by NATIVE-20.

The actual commands below are an owner-authorized local provisioning attempt,
**not a Mac-tested recipe**. `up` refuses an existing cache, builds canonical
API and marker-enabled derived web images, migrates an independently fresh
database, seeds synthetic records and creates a new local CA. It requires at
least 12 GiB measured Docker filesystem build headroom; also inspect Docker
inodes, host space and pinned image architecture. Only gateway ports publish
on host loopback. Runtime API/web/PostgreSQL/scanner networking is isolated and
has no paid-provider keys. Free public build dependencies/images may download.

```bash
cd "$CASEOPS_REPO"
export CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE="$HOME/.cache/caseops-mobile/ios-docker-$(date -u +%Y%m%dT%H%M%SZ)"
python3 scripts/mobile/local-bootstrap.py --help
python3 scripts/mobile/local-bootstrap.py up --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE" --api-port 8443 --web-port 3443 --mfa
python3 scripts/mobile/local-bootstrap.py status --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE"
python3 scripts/mobile/local-bootstrap.py probe --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE"
python3 scripts/mobile/local-bootstrap.py scanner-probe --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE"
python3 scripts/mobile/local-bootstrap.py auth-probe --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE"
```

**Portability implementation (offline component proof, not a Mac pass):**

- `--platform android|ios` is explicit and defaults to Android. New
  `config.json` stores platform, exact API/web origins and ports. iOS derives
  `https://127.0.0.1:8443` / `https://127.0.0.1:3443`; Android retains
  `10.0.2.2`. Web build arguments, receipts and extension inputs consume the
  same validated config. Foreign/HTTP/path-bearing origins, bad ports and
  attempts to reinterpret an existing cache's platform fail closed.
- The iOS helper writes a content-bound JSON Compose override **outside Git**
  changing only API/migration `CASEOPS_PUBLIC_APP_URL` to the configured iOS
  web origin. The canonical Compose file, CORS, TLS, networks, provider fences
  and image definitions are unchanged. Legacy/default Android Compose/build
  commands stay unchanged. The immutable receipt retains the generated override
  path/SHA-256 as `platformComposeOverride`, alongside canonical Compose hash.
- `extend --platform ios --udid <actual-Simulator-UUID>` requires the actual
  Darwin host and exactly one already-booted, available iOS device. It performs
  only `xcrun simctl list devices available --json` and
  `xcrun simctl spawn <UUID> defaults read NSGlobalDomain AppleLocale`, each
  with a five-second deadline and a 64 KiB accepted-response cap. It does not
  boot, erase, change language/locale, install or launch an app. A missing,
  duplicate, non-iOS, unavailable or unbooted target, malformed output or
  unsupported locale fails without a guessed fallback. Locale underscores are
  normalized only after validating the actual returned value. Read-only command
  evidence is hashed and retained; formatted captions remain expectations, not
  native rendered-label proof.
- iOS extension auth is server-config-bound `web-context` with
  `iosConsent: true`; no MFA stage or observed browser success is invented.
  Android remains `native-firefox` and uses the real host's SDK `adb.exe`
  on Windows or `adb` on macOS/Linux, never PATH fallback. Existing route
  metadata/dynamic admission policy and the 64-event history are preserved.

Use `--platform ios` on **every** action against the new iOS cache. Existing
Android caches are not converted; an omitted/default-Android option against an
iOS cache is refused before transport. This task has not run Docker, built an
image, changed a device or reconfigured the frozen 60f API/web/APK.

**Remaining gates, not silently solved by these helper changes:**

- Actual Mac/Apple Silicon image manifests, bind mounts, host CLI/defaults
  availability, source fingerprints, strict TLS and complete bootstrap have not
  run here. Preserve setup failures; do not substitute pinned images or enable
  external provider networking.
- The helper preserves a gateway route descriptor but does not generate the
  complete schema-2 dynamic-session policy/status evidence or local run plan
  required by `local-run.mjs`/`session-admission.mjs`. Parent-owned reviewed
  preparation remains needed; no shared harness was changed.
- Raw `extended-seed-*.json` is not the flat DTO consumed by
  `inspectLocalPlan` (`taskId`, `draftId`, `hearingId`, `calendarDate`,
  `otherMatterId`) plus nested `calendar.eventId`. Preserve the exact opaque
  event ID returned by Calendar; never reconstruct it from `hearingId`.
  A provenance-bound effective projection must retain the
  immutable base/extension receipts and name the actual extended member/task,
  not the base owner's original task. This separate preparation is still open.

Windows unit mocks do not prove a Mac helper works. No DNS/routing workaround,
ATS weakening, production fixture or billing-enabled provider is allowed.

The Python TLS gateway requires the client's authoritative
`X-CaseOps-Automated-Test: no-paid-providers` marker and exact method/path.
It learns one current, unrevoked ID from a successful marked native Bearer
`GET /api/auth/native/sessions`, records the source request ID and consumes
that exact DELETE on the first attempt. Never guess a session ID, add wildcard
routes, pre-revoke it, or reset the ledger during execution.

`auth-probe` exercises real API/MFA/PKCE/token behavior on disposable proof
records; it does not sign in the device browser or inject native credentials.
`scanner-probe` proves real configured clean/EICAR behavior, not a native upload
or post-start scanner-outage boundary. Genuine app sign-in/system browser/MFA
and one-use callback must still run.

After section 4 has selected and booted the one dedicated Simulator, the
concrete extension/owner sequence is now:

```bash
python3 scripts/mobile/local-bootstrap.py extend --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE" --udid "$SIMULATOR_UDID"
python3 scripts/mobile/local-bootstrap.py bind-owner --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE"
python3 scripts/mobile/local-bootstrap.py admit-source --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE"
node scripts/mobile/local-owner-read.mjs
python3 scripts/mobile/local-bootstrap.py begin-core-ledger --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE" --mfa
```

These owner-run commands create fresh synthetic member/targets through the
existing real APIs and preserve prior seed/history. They are **not executed by
this Windows task**. Keep all ordinary TLS/auth/negative probes before the
final clean ledger. Only if API/web inputs really change after a freeze, parent
must explicitly direct `rebuild-api --platform ios --mfa` and/or
`resume --platform ios --mfa` with that same cache, then rebind and retain new
immutable receipts. Do not rebuild the currently frozen 60f images as part of
this implementation, and never reset/restart a ledger during native traffic.

`bind-owner` binds actual running API image/container and extension/Python
hashes. `local-owner-controls.mjs` supports only `disposeMatter`,
`readMatterState`, `revokeMatterAccess`, `readNoteState`, using canonical
services in the owned Docker API with SQL/child deadlines inside the harness's
10-second limit. `local-owner-read.mjs` is a read-only fresh-baseline check.
Destructive controls retain exclusive no-replay attempt files. A new full run
needs fresh disposable targets, never reopened predecessors or an uncertain
command replay. Device-session revocation remains the actual Account UI action.

## 4. Simulator-Only Strict TLS

Use the **new Mac fixture's** public PEM
`$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE/tls/ca.crt`, outside Git, and compare its
SHA-256 to an independently retained local receipt. Never copy the Windows CA
key or private fixture state. Leaf certificates need IP SAN `127.0.0.1` and
DNS SAN `localhost` if used; browser/native/host origins must match.

Select one actual dedicated Simulator. Boot only if not already booted. The
owner explicitly approves importing this one public CA into that Simulator,
not the host Keychain or a normal device:

```bash
export SIMULATOR_UDID="ACTUAL-DEDICATED-SIMULATOR-UDID"
export CASEOPS_LOCAL_PUBLIC_CA="$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE/tls/ca.crt"
shasum -a 256 "$CASEOPS_LOCAL_PUBLIC_CA"
xcrun simctl boot "$SIMULATOR_UDID"
xcrun simctl bootstatus "$SIMULATOR_UDID" -b
xcrun simctl keychain "$SIMULATOR_UDID" add-root-cert "$CASEOPS_LOCAL_PUBLIC_CA"
```

If the selected runtime needs manual activation, owner enables only this CA
in Certificate Trust Settings. Prove the exact web origin in the actual system
browser without a warning, separately from native app trust and process-scoped
Node `NODE_EXTRA_CA_CERTS`. No `curl -k`, hostname-verification bypass,
`NODE_TLS_REJECT_UNAUTHORIZED=0`, ATS exception or warning continuation.
Missing strict TLS is failed setup, not a native product result.

## 5. Bundled Unsigned Simulator Build

After parent-approved source/fixture prerequisites, use the checked-in wrapper.
No Metro, Expo Go or `run:ios` development-server substitute. It uses local
Expo prebuild, CocoaPods and Release `xcodebuild -sdk iphonesimulator`, with
`CODE_SIGNING_ALLOWED=YES`, `CODE_SIGNING_REQUIRED=YES`, local identity `-`,
and Xcode base-entitlement injection. Strict signature verification, bound
Info/resources and embedded per-architecture application identifiers prove
the app's exact private Keychain group. Apple may derive the default private
group from the application identifier without an explicit Keychain-groups array.
No shared group, provisioning profile or Apple account is required. It is not a
physical-device, distribution-signing or App Store build.

```bash
cd "$CASEOPS_REPO"
export EXPO_PUBLIC_API_ORIGIN="https://127.0.0.1:8443"
export EXPO_PUBLIC_WEB_ORIGIN="https://127.0.0.1:3443"
unset CASEOPS_MOBILE_ANDROID_CA_FILE CASEOPS_MOBILE_ANDROID_CA_SHA256
node --test scripts/mobile/build-config.test.mjs
bash scripts/mobile/build-ios-simulator-acceptance.sh
```

Child profile: `ios-simulator-acceptance`, marker `1`, exact HEAD,
`NODE_ENV=production`, `EXPO_NO_DOTENV=1`. Both origins must be explicit
HTTPS loopback origins with unprivileged ports. Android CA variables are
forbidden. QA bundle ID: `ai.caseops.mobile.dev.simulatoracceptance`;
default development ID is not changed and no ATS/CA plugin is added to iOS.
Native auth stays disabled in production, enabled only in this isolated fixture.

An existing generated Podfile.lock uses `pod install --deployment`; a fresh
project uses `pod install` and retains the new lock. Stop on new terms,
accounts, signing or paid-service prompts. Never use `-allowProvisioningUpdates`.
Unique `~/.cache/caseops-mobile/ios-build-*` directories retain before/after
fingerprints, prebuild/Pods/Xcode logs, lock, embedded config and canonical
bundle-tree hash. Require the actual new `.app`, nonempty `main.jsbundle`,
matching origin/source/marker and bundle ID. Preserve failures. An unchanged SHA
does not certify dirty bytes, and a Hermes bundle does not certify Xcode.

After success use only the reported artifact path, not a stale DerivedData match:

```bash
export APP_PATH="/actual/new-run/DerivedData/Build/Products/Release-iphonesimulator/CaseOps.app"
plutil -extract CFBundleIdentifier raw -o - "$APP_PATH/Info.plist"
plutil -extract CFBundleShortVersionString raw -o - "$APP_PATH/Info.plist"
plutil -extract CFBundleVersion raw -o - "$APP_PATH/Info.plist"
xcrun simctl install "$SIMULATOR_UDID" "$APP_PATH"
xcrun simctl launch "$SIMULATOR_UDID" ai.caseops.mobile.dev.simulatoracceptance
```

Require a genuine CaseOps screen/SwiftUI controls, not a development launcher.
Prove unchanged `caseops://oauth/callback` resolves to this QA app on the
dedicated Simulator; a side-by-side dev app may claim it. Do not edit auth or
inject a token to conceal a callback collision.

## 6. Owner-Local Appium/XCUITest

These are pinned tooling versions, not proof of compatibility on the owner Mac.
Use outside-repository caches and inspect an existing installation before
changing it. Owner approves installation; no relaxed Appium security or cloud Mac.

The earlier bare npm/Appium commands are retired: their raw Node trust and
retained driver homes are rejected scopes. Follow
[scoped host tooling preparation](../../docs/mobile/HOST_TOOLING_SECURITY_2026-10-28.md)
for the held-buffer bootstrap, typed child environment and fresh per-platform
`{core,home}` root. Current official pins are Appium3.9.0/WebdriverIO10.1.0,
XCUITest12.22.2 and UiAutomator2 8.7.3 on exact Node24.15.0/npm11.12.1.

Before driver doctor or a new loopback server: reconcile all actual physical and
locked package identities/advisories/notices, exact scoped TLS, internal Appium
alias/registration and the complete bounded payload inventory. Keep successful
stderr diagnostics and actual exit status. Start only the invocation-owned
loopback listener under its reviewed process controller; neither a version string
nor metadata sizing establishes native readiness. No relaxed Appium security or
cloud Mac is admitted. Older installation and native evidence stays historical.

## 7. Prepare, Run And Reconcile All 23 Cases

Stop here until section 3's Mac requirements are resolved. The real existing
preparation CLI is `run-native.mjs ios --inspect-local /absolute/plan.json`
then `ios --prepare-local /absolute/plan.json`. There is no
`prepare-local-run.mjs` or complete Mac plan/policy exporter. A prepared plan
is not a native pass.

Parent must supply a secret-free plan generated from this Mac's real evidence,
not a copied unit/Android fixture. Exact fields are in `local-run.mjs`,
`fixture-contract.mjs` and `session-admission.mjs`:

- `schemaVersion: 1`; absolute/hash-verified `dockerReceipt`, `seed`,
  `buildReceipt`, `publicCa`, `gatewayRoutes`; outside-Git `outputFixture`.
  Effective seed must have the real flat plan-consumer shape and fresh extended
  member/task identities, with immutable base/extension provenance retained;
  neither the base owner-only seed nor raw nested extension suffices. Resolve
  `current-receipt.json` to its named immutable receipt and hash that file,
  not the pointer. Use Mac paths, never copied Windows references.
- Actual bundle version/build, device/runtime/UDID and QA ID. Native embedded
  origins and live API/web SHA/revisions agree with the frozen candidate.
  Retain separate native source fingerprint and harness fingerprint.
- Canonical `expectations`: five distinct identifiers; Today/Work/current
  draft/calendar values in the observed Simulator locale; foreign Matter and
  distinct fresh lifecycle/access targets. No invented IDs/captions/legal data.
- Hash-bound `ownerControls`, all four operations, actual API image/container,
  extension/Python/module hashes and fresh read-only baseline. Owners bypass
  restricted Matter access; use the extension's member.
- Actual iOS `auth.mode: "web-context"`, explicit observed MFA `mfaStage`
  (`login` or `consent`), plan-named credential environment variables.
  `iosConsent: true` is opt-in only for the observed normal Continue prompt.
  Android Firefox recipes are not Safari/ASWebAuthenticationSession proof.
  Stop if XCUITest cannot attach to the real system-browser context.
- A schema-2 `gatewayRoutes` descriptor containing
  `dynamicAdmissions.nativeCurrentSessionDelete`, exact static route list,
  `native-current-session-delete-v1` invariants, reviewed Python source/hash,
  matching run ID, immutable isolation reference and hashed current status.
  Session-list/request-ID linkage, one live current/unrevoked native ID,
  cookie exclusion and consume-on-attempt must validate. Static routes alone
  fail `CURRENT_SESSION_DELETE_ADMISSION_MISSING`. The bootstrap does not
  currently export this complete descriptor; do not invent a session ID/policy.

Load only the actual extended member values named by the plan from its protected
local credential file. Do not print the file, put secrets in JSON/CLI/history,
enable `set -x` or record the terminal. For the current variable names,
Bash reads existing values without terminal echo:

```bash
IFS= read -r -s CASEOPS_MOBILE_CORE_EMAIL
printf '\n'
IFS= read -r -s CASEOPS_MOBILE_CORE_PASSWORD
printf '\n'
IFS= read -r -s CASEOPS_MOBILE_CORE_TOTP_SECRET
printf '\n'
export CASEOPS_MOBILE_CORE_EMAIL CASEOPS_MOBILE_CORE_PASSWORD CASEOPS_MOBILE_CORE_TOTP_SECRET
```

Environment is process-local, not secret-free storage. Do not dump it; unset it
after execution. Do not enroll/reset a real user or replace missing credentials.

```bash
cd "$CASEOPS_REPO"
export CASEOPS_MOBILE_RUN_PLAN="/absolute/outside-git/real-ios-plan.json"
export CASEOPS_MOBILE_APPIUM_URL="http://127.0.0.1:4723"
export CASEOPS_MOBILE_REPORT_ROOT="$HOME/.cache/caseops-mobile/evidence"
export NODE_EXTRA_CA_CERTS="$CASEOPS_LOCAL_PUBLIC_CA"
node scripts/mobile/run-native.mjs ios --inspect-local "$CASEOPS_MOBILE_RUN_PLAN"
node scripts/mobile/run-native.mjs ios --prepare-local "$CASEOPS_MOBILE_RUN_PLAN"
export CASEOPS_MOBILE_FIXTURE="/actual/outputFixture/path/reported-by-prepare-local.json"
node scripts/mobile/local-owner-read.mjs
node scripts/mobile/run-native.mjs ios --collect > "$CASEOPS_HANDOFF/ios-final-collection.json"
node scripts/mobile/run-native.mjs ios
node scripts/mobile/reconcile-native.mjs ios /actual/run/events.jsonl
unset CASEOPS_MOBILE_CORE_EMAIL CASEOPS_MOBILE_CORE_PASSWORD CASEOPS_MOBILE_CORE_TOTP_SECRET
node scripts/mobile/source-snapshot.mjs > "$CASEOPS_HANDOFF/source-after.json"
```

Require zero preparation blockers and all **23 ordered intended/discovered
identities**, complete setup/call/teardown, genuine `NATIVE_APP` context,
preflight/postflight and completion, zero retries, exact source/binary/backend/
web identities and zero missing-marker/unadmitted-route counters. Keep the
30-minute whole-run bound unchanged, alongside each original individual
deadline. Missing completion, fixture, browser handoff,
owner capability or binary is incomplete, never success or an approved skip.

NATIVE-20 must link a fresh marked native session-list read to the actual current
ID and its single acknowledged DELETE, then stay signed out after restart.
NATIVE-23 follows acknowledged logout in NATIVE-22: perform actual Home
background and warm resume, restore usable signed-out controls, and prove no
private UI/auth traffic returns. A cold launch or permanent privacy cover does
not satisfy it.

Consent-stage MFA requires actual authorize 403 -> one successful step-up ->
fresh identity -> explicit second Connect -> one authorize 200 -> one token 200,
with unchanged PKCE/principal/workspace. Login-stage MFA needs its own observed
challenge. API auth-probe does not prepare the browser or certify these controls.

Return complete unique build/run directories, sanitized versions/doctor/config,
immutable Docker/seed/extension/scanner/TLS/isolation and dynamic-policy receipts,
native lock/binary hash, source/harness fingerprints and all failures to parent.
Never retry an uncertain note, upload, session-delete or owner mutation. Another
full attempt needs fresh disposable targets, not reopened consumed fixtures.

The pending `files-20261025.mjs` supplement is Android-only, outside the core
CLI and anchored to an owner's Windows fixture IDs. FILES-01 describes TXT
source read/return; FILES-02 deliberately blocks without actual picker/upload
evidence. Do not transplant those IDs into a fresh Mac tenant, call an opened
picker an upload, claim iOS Files coverage, or silently count it in the 23.
A separately reviewed iOS source/picker/viewer/upload/cleanup inventory is open.
The forty-group matrix, physical iPhone, VoiceOver/large text, camera, biometrics,
push, signing/TestFlight/store and exact-release product gates remain open.

Only after owner-directed shutdown:

```bash
python3 scripts/mobile/local-bootstrap.py stop --platform ios --cache "$CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE"
```

This validates/stops only the owned Compose project and retains volumes/evidence.
No `down -v`, global prune, broad Simulator shutdown or trust-store cleanup.
Any selected-device CA removal/cleanup is a separate explicit owner action.

## 8. Android Contract And Default-Config Recovery

The corresponding Windows parent command is:

```powershell
./scripts/mobile/build-android-local-acceptance.ps1 `
  -PublicCaFile 'C:/absolute/outside-git/public-ca.pem' `
  -PublicCaSha256 'ACTUAL_64_CHARACTER_LOWERCASE_SHA256'
```

It uses `use-android-env.ps1` session-only, existing CaseOps Gradle settings and
`:app:assembleLocalAcceptance`, not `expo start`, policy changes or a Metro
wrapper. Default origins are `https://10.0.2.2:8443` and
`https://10.0.2.2:3443`; server certificates need IP SAN `10.0.2.2`. Android's QA
app ID is `ai.caseops.mobile.dev.localacceptance`. Its standard release-derived
non-debug variant falls back to release dependencies, bundles JS with
`devEnabled=false`, and uses the existing debug signing identity only for local
installation. No production signing configuration is changed.

The Android plugin admits exactly one current self-signed public CA with an
exact PEM-byte SHA-256, rejects Git-contained or key-bearing files, and generates
four files only under ignored `android/app/src/localAcceptance`. Only the exact
configured loopback hosts trust that CA, without the user/system CA stores for
those hosts; all other hosts retain system trust. Android network-security
rules are host-scoped, not port-scoped. HTTP remains denied, including Android
17's implicit localhost exception. System-browser TLS trust is a separate
parent-owned prerequisite. Never install a QA CA into a normal production device.

A QA-configured generated Android tree enables only `localAcceptance`, so it
cannot package QA constants as the default release. It rejects changed profile,
marker, origins, source SHA or CA hash. To regenerate default native config in a
fresh normal shell, unset `CASEOPS_MOBILE_BUILD_PROFILE`, both Android CA
variables and both `EXPO_PUBLIC_*_ORIGIN` overrides, then run the local Expo
prebuild for the intended platform. The plugin removes only its own Android
overlay files and Gradle block; it does not recursively delete native work or
inject trust into iOS. Keep all CA/key files, fixture secrets and generated
native output out of Git. No commit, push, main merge or deployment is authorized
by these build steps.

Reference behavior: [Expo local release variants](https://docs.expo.dev/more/expo-cli/),
[Android host-specific trust](https://developer.android.com/privacy-and-security/security-config),
[Apple Simulator certificate management](https://developer.apple.com/videos/play/wwdc2020/10647/).
The implementation also checks the installed Expo58/RN0.88 Gradle and Xcode
scripts; current upstream documentation alone is not exact-version proof.

Current primary references:
[Expo SDK 58](https://expo.dev/changelog/sdk-58) confirms RN 0.88 and the supported
default CocoaPods path; [Apple Xcode components](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components)
and [XCUITest setup](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/)
guide owner prerequisites. These sources do not certify this application on Mac.

## Portability Component Verification

Verdict: **Partially fixed**. The original iOS web-origin regression failed
before the change (Android build arguments despite iOS config), then passed.
The original 19-case Python module and its 64-entry gateway history remain
required alongside the added offline portability tests. The complete replacement
module ran **39 tests: 39 passed, no failures/errors/skips**, including all prior
19 and 20 added regression/portability cases, on Windows with mocked external
CLIs and isolated loopback gateway test doubles. A first expanded run
retained an eager home-directory failure (even with an explicit SDK) and a
test command-slice failure; both were corrected and the full replacement
inventory is reconciled above. This is not a Mac, Xcode or native acceptance
receipt. No shared gateway/harness, app/API/web source, checked-in Compose,
images, services, device state or commit was changed by this bounded task.
