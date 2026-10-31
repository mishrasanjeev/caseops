# Native Tooling And Core Appium Gate

J20/M22; US-MOB-01..04/08. This is a six-case P0/P2 subset, not completion of
MOB-01..40. Android UiAutomator2 and iOS XCUITest execute the same core cases
separately. A browser, Metro export or fake Appium server is never native proof.

## Current Prerequisites

- Node >=22.19.0, npm >=10. Tested host: Node 24.15.0/npm 11.12.1.
- `tooling.json` pins Appium, drivers and WebdriverIO outside the root lock.
- Android: JDK compatible with the scaffold's Gradle version, Android SDK,
  matching platform/build tools, emulator image and one explicitly selected
  booted emulator or dedicated device. Tool preparation does not accept SDK
  licences; package installation requires separate explicit owner consent.
- iOS: owner's MacBook, full Xcode, selected developer directory, owner-reviewed
  Xcode terms, simulator runtime and booted simulator. Windows cannot substitute.
- Real compiled `.apk` or Simulator `.app`, build source snapshot, application
  version/build number and actual OS/device identity. This gate does not install
  on physical iPhones or configure signing.
- Isolated deterministic backend/auth fixture, or isolated Docker API/PostgreSQL
  with deterministic providers and independently seeded QA identities. A
  deterministic server run is `deterministic-simulator`, not Docker integration.
  This harness does not create users, tenant entitlements or production records.

## Windows Preparation

From the repository, run `./scripts/mobile/probe-native.ps1`. Optional
`-OutputPath` refuses to overwrite an earlier probe. Then:

```powershell
./scripts/mobile/setup-open-source-tooling.ps1 -WithJdk
$env:CASEOPS_MOBILE_TOOLING_HOME = "$HOME/.cache/caseops-mobile/tooling"
$env:APPIUM_HOME = "$HOME/.cache/caseops-mobile/appium"
# Use the exact JAVA_HOME printed by setup, for this shell only.
node "$env:CASEOPS_MOBILE_TOOLING_HOME/node_modules/appium/index.js" driver doctor uiautomator2
```

For this Windows workstation, the owner explicitly authorized the standard free
SDK licences on October24. The selected SDK packages were installed separately;
this is not blanket permission for additional Google products or paid services.
The reusable tool/JDK preparation is:

```powershell
./scripts/mobile/setup-android.ps1
. ./scripts/mobile/use-android-env.ps1
# Optional: persist only this Windows user's tool paths, not machine settings.
./scripts/mobile/use-android-env.ps1 -Persist
```

Both publisher-pinned archives are SHA256 verified before extraction. Downloads
and extraction use separate staging; failed evidence and existing installations
are preserved. See `docs/mobile/NATIVE_TOOLING_EVIDENCE_2026-10-24.md` for the
actual workstation receipt, including the selected package versions.
Do not pipe `yes` into the broad `sdkmanager --licenses`. After consent/setup, use
`emulator -accel-check`, `emulator -list-avds`, and `adb devices -l`. A Windows
hypervisor flag alone is not usable acceleration evidence. Do not kill an
unrelated AVD, ADB server, Docker container or process. Do not change Windows
features/BIOS or restart the machine without owner coordination.

The native plugins also request the existing pinned JDK17 toolchain, even when
Gradle itself runs on JDK21. Register both local installations for the build;
otherwise Gradle may download another JDK. With the test origins/marker below
set before prebuild and Metro, the Windows build from `apps/mobile/android` is:

```powershell
$env:GRADLE_USER_HOME = "$HOME/.cache/caseops-mobile/gradle"
$jdk17 = "$HOME/.cache/caseops-mobile/jdk/jdk-17.0.20.1+1"
./gradlew.bat :app:assembleDebug "-Dorg.gradle.java.installations.paths=$jdk17,$env:JAVA_HOME" `
  -Dorg.gradle.java.installations.auto-download=false -PreactNativeArchitectures=x86_64 `
  -Pandroid.cmakeVersion=3.30.5 -Pexpo.android.cmakeObjectPathMax=250 `
  --no-daemon --max-workers=4 --console=plain
```

The actual SDK CMake3.30.5 bundles Ninja1.10.2. On this workstation, long-path
support is disabled; it was not changed. Worklets has a178-character object
directory and a36-character maximum object basename:128 is too small to permit
CMake's hashed path, while1024 retains an unsafe377-character path. The measured
250 budget produces a248-character maximum across all56 Worklets objects.
Recalculate for a deeper checkout or changed native inventory; do not just raise
the limit. The local CaseOps Gradle profile records this budget and both JDKs.
Shell activation selects that cache without persisting GRADLE_USER_HOME globally.

Run `./scripts/mobile/android-tooling.ps1 -SelfTest` from the repository for the
complete offline Windows setup inventory. The standard mobile CI selects it on
both Windows PowerShell5.1 and PowerShell7 and retains their live JSONL journals.
These tests never install tools, call providers or establish native acceptance.

## Owner MacBook Preparation (Not Executed Here)

Inspect `xcodebuild -version`, `xcode-select -p` and
`xcrun simctl list devices available`. Any Xcode license/runtime installation
requires owner action; no cloud service or new external account is required for
an unsigned local simulator build. With the same supported Node/npm versions:

The previous bare npm/Appium recipe is superseded by
[scoped host tooling preparation](../../docs/mobile/HOST_TOOLING_SECURITY_2026-10-28.md).
Use exact Node24.15.0/npm11.12.1 and a new per-platform `{core,home}` root,
Appium3.9.0/WebdriverIO10.1.0 and XCUITest12.22.2. Derive the exact child
trust recipe from held reviewed source before npm or an Appium entry starts;
never overwrite the retained3.8 cache or reuse a logged bootstrap URI blindly.
Driver doctor/server commands are held until fresh complete installed/locked
advisories, notices, scoped TLS and full runtime inventory are admitted.

Only after parent confirms SDK58/RN0.88 pins, native dependencies and scaffold:
set `CASEOPS_MOBILE_AUTOMATED_TEST=1`, `EXPO_PUBLIC_API_ORIGIN` to the local
gateway, and `CASEOPS_MOBILE_RELEASE_SHA` to the inspected Git SHA **before**
building. Parent owns Expo prebuild/scaffold changes. From `apps/mobile`,
`node ./node_modules/expo/bin/cli run:ios --device "$SIMULATOR_UDID"` builds a native debug simulator
application. Keep the associated Metro server available. Inspect the actual
workspace/scheme and build output; do not invent a `.app` path. Debug local HTTP
is needed unless an owner-configured local TLS backend exists; the network
client deliberately rejects release HTTP. A Metro bundle export alone is not
an iOS build. Capture `source-snapshot.mjs` before and after building and require
identical fingerprints; record the installed `.app` and Xcode/Simulator versions.
Physical iPhone signing, APNs, biometrics, camera and TestFlight remain separate.

The analogous Android build is `node ./node_modules/expo/bin/cli run:android --device "$ANDROID_UDID"`
after SDK consent and a real `emulator -accel-check`. Use `adb -s "$ANDROID_UDID"
reverse tcp:PORT tcp:PORT` only for the dedicated selected device if using host
loopback, or configure the emulator's `10.0.2.2` host alias. Never point automated
builds at production. Do not claim a build until its actual command succeeds.

## TestIDs And Fixture Contract

Shared IDs agreed with parent/UI agent:
`tab-today`, `tab-matters`, `tab-calendar`, `tab-work`, `matter-search`,
`matter-row-{actual-server-id}`, `note-input`, `note-save`, `account-open`,
`sign-out`. Android uses React Native resource IDs with Appium ID auto-prefixing
disabled; iOS uses accessibility IDs. No XPath or visible-label guesses.

The fixture file is generated from the authorized isolated backend seed ledger,
not checked-in example customer data. Set `CASEOPS_MOBILE_FIXTURE` to its absolute
path. Required properties:

- `environment`: `deterministic-simulator` or `docker-integration` (declared
  environment; Docker image/database receipts must be retained independently).
- `syntheticDataOnly: true`; `backendSha`, `backendRevision` must match the real
  local `/api/build`; `gatewayUrl`, `gatewayRunId` must match the dedicated proxy.
- `binarySourceSha`, `binarySourceFingerprint` from
  `node scripts/mobile/source-snapshot.mjs` at build time. Dirty sources are
  recorded honestly; nonignored uncommitted app inputs are included, E2E/build
  caches and secret/config credential files are excluded. Ignored generated
  native projects are not covered by this fingerprint; retain native build logs
  and their generated-input receipt separately. Rebuild after an input change.
- `appPath`: absolute `.apk`/Simulator `.app`; `appId`, `binaryVersion`,
  `binaryBuild`, `deviceName`, `platformVersion`, `udid`: actual build/device
  metadata. Version/build fields are operator-supplied, not signing proof.
- `principalLabel`, `workspaceLabel` and `matter: { id, search, identityLabel }`:
  exact expected authorized synthetic identity, taken from the seeded API.
- Authentication uses the actual `sign-in` control and waits at most 60 seconds
  for the real system-browser handoff to finish. Prepare the isolated browser
  sign-in through the real supported flow; otherwise setup fails. There is no
  native password form, access-token injection, browser-cookie scrape or auth
  bypass. Browser challenge/PKCE/MFA automation remains a separate prerequisite,
  not a completed MOB-01/02 claim. Do not put credentials in fixtures or CLI args.
- `ids`: real implemented IDs for `principal`, `workspace`, `accountClose`,
  `matterIdentity`, `savedNote`, `signedOut`, `searchSubmit`,
  `noteAcknowledgement`, `noteReturn`, and
  `screens: {today, matters, calendar, work}`. Optional `noteOpen`/`activityOpen`
  navigate the actual detail tabs. Coordinate these with UI agent before a run.
  `savedNote` must identify the newest saved note's actual body, not a toast.
  `noteAcknowledgement` must be the persisted-confirmation state, not Unknown
  or Acknowledged-without-reload. `noteReturn` enters actual matter activity.
- `noteRoute`: exact `/api/matters/{id}/notes`; `matterReloadRoute`: actual
  workspace reread path, currently `/api/matters/{id}/workspace`.

## No-Paid Request Fence

Start `node scripts/mobile/no-paid-gateway.mjs /absolute/gateway-config.json`
with `{upstream, port, runId, routes}`. `upstream` is a loopback-only origin.
`routes` is a reviewed nonempty list of **exact** `METHOD /api/path` strings.
Include only actual auth/read/note endpoints used by this fixture, including
`GET /api/build`; no wildcard, paid-provider, generation or paid PDF routes.
Examples of existing read owners are `/api/me/today`, `/api/matters`,
`/api/matters/{id}`, `/api/matters/{id}/workspace`, `/api/calendar/events`.
Auth paths must come from the implemented native-auth contract, not guesses.

Every native request must already carry
`X-CaseOps-Automated-Test: no-paid-providers`; the proxy rejects missing markers,
unadmitted routes and redirects before any external request. It preserves auth,
encoded queries and mutation bytes and never retries. Only sanitized method,
pathname, sequence and status are retained, capped at 500 requests/1 MiB request
body; no cookies, query values, tokens or response bodies are logged. The harness
checks the proxy counters and exact note POST count. This fence covers traffic
through the configured gateway, not arbitrary device networking; full MOB-30
still requires the app transport/backend regression and physical-device review.

## Execute And Reconcile

```sh
node scripts/mobile/run-native.mjs android --collect
node scripts/mobile/run-native.mjs ios --collect
node scripts/mobile/source-snapshot.mjs
node --test scripts/mobile/tooling.test.mjs
node "$CASEOPS_MOBILE_TOOLING_HOME/node_modules/appium/index.js" --address 127.0.0.1 --port 4723 --log-level error
# In another shell with the same fixture/auth environment:
node scripts/mobile/run-native.mjs android
# On the owner MacBook only:
node scripts/mobile/run-native.mjs ios
node scripts/mobile/reconcile-native.mjs android /absolute/run/events.jsonl
```

`node --test scripts/mobile/tooling.test.mjs` is the standard self-test command.
Self-tests test tooling only, not native execution. `--collect` independently
reconciles canonical and discovered ordered identities. Native runs have zero
WebdriverIO transport retries, a 20-minute overall bound, bounded waits, an
exclusive per-run directory and fsynced JSONL setup/call/teardown events.
Missing infra creates failed setup + explicitly unexecuted calls, exit 1.
Interrupted journals lack completion and the reconciler rejects them. Failed
runs are never overwritten. Default evidence directory is
`$HOME/.cache/caseops-mobile/evidence`; override `CASEOPS_MOBILE_REPORT_ROOT` for
an owned CI artifact directory. No CI dispatch is included or authorized here.

No screenshots/UI dumps are captured automatically, to avoid exposing login
secrets or private content. Add redacted captures only with the coordinated
synthetic fixture. Six core cases do not prove MFA/refresh/PKCE, tenant isolation,
lifecycle races, file scanning, calendar completeness, push, accessibility,
physical devices, signing or the remaining planned acceptance matrix.
