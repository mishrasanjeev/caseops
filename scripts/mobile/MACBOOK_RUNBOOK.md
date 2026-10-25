# Owner MacBook: Standalone iOS Simulator Build And XCUITest

**Status: NOT RUN on macOS/iOS.** These are owner-run instructions, not build,
Simulator, signing or native interaction evidence. Windows Hermes exports do not
change that status. No cloud Mac, billing, new account or CI dispatch is needed.

## 1. Use The Exact Shared Candidate

Use development branch `codex/mobile-app-build-20261024` once the parent confirms
its push. A checkout of the old production/base commit alone does not contain
the app. In a clean dedicated Mac checkout, fetch that branch and select it
without resetting another user's work. Do not transfer `.env`, tokens, signing
keys or real customer data. The branch is not a merge/release certification.

```sh
export CASEOPS_REPO="/absolute/path/to/CaseOps"
cd "$CASEOPS_REPO"
git rev-parse HEAD
git branch --show-current
git status --short -- apps/mobile scripts/mobile
node --version
npm --version
xcodebuild -version
xcode-select -p
xcrun simctl list devices available
```

Required: supported Node >=22.19.0 (tested Windows tooling uses 24.15.0), npm >=10,
full Xcode, an installed compatible Simulator runtime and a dedicated device
UDID selected from the actual list. The owner must review any Xcode license or
runtime prompt. Do not silently run a license-accept command, change the global
developer directory, shut down all simulators or stop unrelated services.

## 2. Install The Independent App Package

Parent confirmed Expo SDK58/RN0.88. `apps/mobile` is **not a root npm workspace**.
Use its own checked-in lock and local CLI, never `npm --workspace`, a global Expo
or `npx` that can fetch another version. Do not regenerate the lock on macOS.

```sh
cd "$CASEOPS_REPO/apps/mobile"
npm ci
npm ls expo react-native expo-dev-client expo-secure-store expo-web-browser
npm run typecheck
npm test
```

Any platform-specific install/lock failure is a prerequisite failure. Preserve
the error and coordinate with parent, rather than silently changing dependencies.

## 3. Prepare An Isolated HTTPS Backend And Marker Gateway

Use the parent's isolated Docker API/PostgreSQL + deterministic providers and
synthetic QA auth fixture. If using a standalone deterministic server instead,
label receipts `deterministic-simulator`; do not label them Docker integration.
Never use production or a billable provider. Do not invent seed identities,
bootstrap accounts in a shared tenant or inject native tokens to simulate login.

The standalone Release build uses `__DEV__=false`; HTTP is deliberately rejected.
Use parent-provisioned HTTPS listeners, for example API
`https://127.0.0.1:8443` and web `https://127.0.0.1:3443`. The API listener must
forward through the marker-enforcing gateway, not bypass it. Bind host listeners
to loopback and keep the Docker database/providers isolated. Do not expose a
fixture to the LAN. Do not copy the Windows Docker volume or private CA key to
the Mac: provision a separate ephemeral local fixture and CA there.

Generate the internal gateway config from the fixture's real route inventory. It
contains `upstream` (loopback origin), a free explicit `port`, unique `runId`, and
reviewed exact `METHOD /api/path` strings. Include actual native-auth endpoints,
`GET /api/build` and the known Today/Matter/calendar/note reads, but no paid or
generation routes. See `README.md` for schema and bounds. Start in a terminal:

```sh
cd "$CASEOPS_REPO"
node scripts/mobile/no-paid-gateway.mjs /absolute/path/gateway-config.json
```

The HTTP gateway is an internal hop behind the local HTTPS listener, not the
origin embedded in the standalone app. The proxy rejects any app request missing
`X-CaseOps-Automated-Test: no-paid-providers`; it does not manufacture a positive
marker test by merely injecting the header. Use the real native sign-in button,
system browser and single-use handoff. If browser auth/MFA/PKCE completion is not
implemented for the isolated fixture, stop: this is an auth prerequisite, not
permission to inject a token or scrape browser cookies. Existing browser login
alone is not native session evidence.

## 4. Establish Simulator-Only TLS Trust

Parent supplies one public CA certificate in PEM format outside every Git
checkout, its independently recorded SHA-256 and HTTPS server certificates with
IP SAN `127.0.0.1` (and DNS SAN `localhost` if used). Never transfer a private
key, add a production trust exception, disable hostname verification, set
`NODE_TLS_REJECT_UNAUTHORIZED=0`, use `curl -k`, or add ATS exceptions.

Select and boot only the dedicated simulator from the actual available list.
Do not repeat `boot` when it is already booted. The owner must approve the
simulator-specific CA installation; it is not a host Keychain installation.

```sh
export SIMULATOR_UDID="ACTUAL-DEDICATED-SIMULATOR-UDID"
export CASEOPS_LOCAL_PUBLIC_CA="/absolute/outside-git/public-ca.pem"
shasum -a 256 "$CASEOPS_LOCAL_PUBLIC_CA"
xcrun simctl boot "$SIMULATOR_UDID"
xcrun simctl bootstatus "$SIMULATOR_UDID" -b
xcrun simctl keychain "$SIMULATOR_UDID" add-root-cert "$CASEOPS_LOCAL_PUBLIC_CA"
```

Compare the public certificate hash to the parent's independent receipt first.
If the installed runtime requires manual activation, the owner enables only
this identified CA under Settings > General > About > Certificate Trust Settings.
Prove the exact HTTPS web origin in the selected Simulator's system browser
without a certificate warning. A CA trusted by an app does not automatically
establish trust in a separate browser. Review Simulator TLS failure as a setup
failure; never click through a warning for acceptance. Keep this CA/device
disposable and use the owner's normal device cleanup after evidence collection.

## 5. Build A Bundled Unsigned Release Simulator App

Wait for the parent's exact candidate/scaffold-ready confirmation. Run from a
clean dedicated Mac checkout with the installed local package. No Metro process
is needed or started. The wrapper uses the installed Expo prebuild, CocoaPods,
then `xcodebuild -configuration Release -sdk iphonesimulator` with both code
signing switches disabled. This is not a physical-device or App Store build.

```sh
cd "$CASEOPS_REPO"
export EXPO_PUBLIC_API_ORIGIN="https://127.0.0.1:8443"
export EXPO_PUBLIC_WEB_ORIGIN="https://127.0.0.1:3443"
node --test scripts/mobile/build-config.test.mjs
bash scripts/mobile/build-ios-simulator-acceptance.sh
```

The wrapper sets only its child process profile `ios-simulator-acceptance`,
marker `1`, and exact HEAD. Both HTTPS origins must be explicit loopback origins
with unprivileged ports. Android CA variables are forbidden for this profile.
It does not change the default iOS identifier or add an ATS/CA plugin. Its QA
bundle ID is `ai.caseops.mobile.dev.simulatoracceptance`. Native auth remains
disabled in production; only the isolated Docker fixture may enable it.

The first prebuild/Pods may download free open-source build dependencies. Install
the owner-reviewed CocoaPods prerequisite first. A retained `Podfile.lock` uses
`pod install --deployment`; a fresh generated project uses `pod install` and
retains the resulting lock with the build evidence. Stop on new terms, accounts,
signing or paid-service prompts. Never add `-allowProvisioningUpdates`.

Each run has a unique directory under `~/.cache/caseops-mobile/ios-build-*` with
prebuild/Pods/Xcode logs, before/after source identity, embedded Expo config and
binary hash. Failures remain there. Require the current `.app`, a nonempty
`main.jsbundle`, marker `true`, matching origins/source, and the distinct QA
bundle ID. A Hermes export alone is not an Xcode build. An unchanged SHA alone
does not identify dirty app bytes; the wrapper also requires equal fingerprints.

Only after a successful build, use its reported path, never a stale DerivedData
match. Parent owns installation, simulator launch and native E2E:

```sh
export APP_PATH="/actual/new-run/DerivedData/Build/Products/Release-iphonesimulator/CaseOps.app"
plutil -extract CFBundleIdentifier raw -o - "$APP_PATH/Info.plist"
plutil -extract CFBundleShortVersionString raw -o - "$APP_PATH/Info.plist"
plutil -extract CFBundleVersion raw -o - "$APP_PATH/Info.plist"
xcrun simctl install "$SIMULATOR_UDID" "$APP_PATH"
xcrun simctl launch "$SIMULATOR_UDID" ai.caseops.mobile.dev.simulatoracceptance
```

Require a real CaseOps screen, not a development launcher, with no Metro listener.
The unchanged callback is `caseops://oauth/callback`: a side-by-side old dev app
may claim it. Parent must prove the callback resolves to the QA app on this
dedicated simulator rather than editing auth/domain code or pretending a token
injection proves sign-in.

## 6. Prepare Appium/XCUITest

Install only into the owner cache, not the repository's root or app lock:

```sh
export CASEOPS_MOBILE_TOOLING_HOME="$HOME/.cache/caseops-mobile/tooling"
export APPIUM_HOME="$HOME/.cache/caseops-mobile/appium"
npm install --prefix "$CASEOPS_MOBILE_TOOLING_HOME" --save-exact --no-audit --no-fund appium@3.8.0 webdriverio@10.1.0
node "$CASEOPS_MOBILE_TOOLING_HOME/node_modules/appium/index.js" driver list --installed --json
node "$CASEOPS_MOBILE_TOOLING_HOME/node_modules/appium/index.js" driver install xcuitest@12.20.0
node "$CASEOPS_MOBILE_TOOLING_HOME/node_modules/appium/index.js" driver doctor xcuitest
node "$CASEOPS_MOBILE_TOOLING_HOME/node_modules/appium/index.js" --address 127.0.0.1 --port 4723 --log-level error
```

Do not reinstall an already matching driver; review a different existing version
rather than overwrite it. A doctor failure is a setup failure. Do not enable
relaxed Appium security, configure distribution signing or dispatch CI here.

## 7. Collect, Execute And Reconcile

Generate the fixture JSON from the isolated seed ledger and actual app/device
metadata using the current `apps/mobile/e2e/fixture-contract.mjs` and the parent's
isolated-fixture instructions in `local-README.md`. The current dated inventory
is `apps/mobile/e2e/core-20261025.json` (22 cases); `inventory.json` retains the
historical six and must not be relabelled as the expanded core. Inspect the
source-frozen selectors and owner-control targets, including distinct disposable
negative targets, before execution. Never invent IDs, expectations or capability
evidence to satisfy the validator. Set `environment` honestly and retain the
separate Docker source/image/database receipt. Missing capability is a blocker,
not an approved skip or a reason to inject a session.

Use the actual bundle ID `ai.caseops.mobile.dev.simulatoracceptance` in the
fixture. The original harness at `d5a6641e` admitted only `ai.caseops.mobile.dev`.
Parent must land/review its dedicated QA-ID admission before execution; never
mislabel this binary to bypass that fence. The harness control-plane gateway
URL remains host-loopback (not `10.0.2.2`) and must identify the same run. For a
custom-CA HTTPS control-plane endpoint, use process-scoped `NODE_EXTRA_CA_CERTS`
with the verified public PEM; do not disable TLS validation. Keep Appium local.

```sh
cd "$CASEOPS_REPO"
export CASEOPS_MOBILE_FIXTURE="/absolute/path/isolated-ios-fixture.json"
export CASEOPS_MOBILE_APPIUM_URL="http://127.0.0.1:4723"
export CASEOPS_MOBILE_REPORT_ROOT="$HOME/.cache/caseops-mobile/evidence"
node --test scripts/mobile/build-config.test.mjs scripts/mobile/tooling.test.mjs
node scripts/mobile/run-native.mjs ios --collect
node scripts/mobile/run-native.mjs ios
node scripts/mobile/reconcile-native.mjs ios /actual/run/events.jsonl
```

Require all 22 ordered intended/discovered identities in the dated inventory,
complete setup/call/teardown results,
native `NATIVE_APP` context, no retries, exact backend/source/binary identity and
zero missing-marker/unadmitted-route counters. After a process restart, the note
must come from the authoritative workspace reread. Keep failures and interrupted
runs unchanged; missing completion, missing fixture, no binary or incomplete
handoff is **not** success. Never retry an uncertain note save.

Return the complete unique run directory, sanitized build/config/doctor results,
Xcode/OS/device versions and exact candidate inputs to parent. This dated core
slice does not certify the forty-group matrix, physical iPhone,
VoiceOver, camera, biometrics, APNs, signed distribution, TestFlight or production.

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
