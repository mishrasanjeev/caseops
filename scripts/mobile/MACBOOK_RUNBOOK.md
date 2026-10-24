# Owner MacBook: iOS Development Build And XCUITest

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

## 3. Start A Truly Isolated Backend And Marker Gateway

Use the parent's isolated Docker API/PostgreSQL + deterministic providers and
synthetic QA auth fixture. If using a standalone deterministic server instead,
label receipts `deterministic-simulator`; do not label them Docker integration.
Never use production or a billable provider. Do not invent seed identities,
bootstrap accounts in a shared tenant or inject native tokens to simulate login.

Generate the local gateway config from the fixture's real route inventory. It
contains `upstream` (loopback origin), a free explicit `port`, unique `runId`, and
reviewed exact `METHOD /api/path` strings. Include actual native-auth endpoints,
`GET /api/build` and the known Today/Matter/calendar/note reads, but no paid or
generation routes. See `README.md` for schema and bounds. Start in a terminal:

```sh
cd "$CASEOPS_REPO"
node scripts/mobile/no-paid-gateway.mjs /absolute/path/gateway-config.json
```

The proxy rejects any app request missing
`X-CaseOps-Automated-Test: no-paid-providers`; it does not manufacture a positive
marker test by merely injecting the header. Use the real native sign-in button,
system browser and single-use handoff. If browser auth/MFA/PKCE completion is not
implemented for the isolated fixture, stop: this is an auth prerequisite, not
permission to inject a token or scrape browser cookies. Existing browser login
alone is not native session evidence.

## 4. Prove Development Configuration Before Building

Use the actual gateway port below. These flags must be set in **both the build
shell and the Metro shell**. This runbook uses a native debug development build,
not an App Store/production binary. The app rejects HTTP outside development.

```sh
cd "$CASEOPS_REPO/apps/mobile"
export CASEOPS_MOBILE_AUTOMATED_TEST=1
export CASEOPS_MOBILE_RELEASE_SHA="$(git rev-parse HEAD)"
export EXPO_PUBLIC_API_ORIGIN="http://127.0.0.1:8796"
node ./node_modules/expo/bin/cli config --type public --json | node --input-type=module -e '
import assert from "node:assert/strict";
let raw=""; for await (const chunk of process.stdin) raw+=chunk;
const config=JSON.parse(raw);
assert.equal(config.extra.automatedTest,true);
assert.equal(config.extra.apiOrigin,process.env.EXPO_PUBLIC_API_ORIGIN);
assert.equal(config.extra.releaseSha,process.env.CASEOPS_MOBILE_RELEASE_SHA);
assert.equal(config.ios.bundleIdentifier,"ai.caseops.mobile.dev");
console.log(JSON.stringify({automatedTest:true,apiOrigin:config.extra.apiOrigin,releaseSha:config.extra.releaseSha,bundleIdentifier:config.ios.bundleIdentifier}));'
node ../../scripts/mobile/source-snapshot.mjs
```

Retain only the whitelist proof above, not a dump of environment variables or
credentials. Record the source snapshot before and after the build and require
identical fingerprints. The commit SHA alone does not identify dirty app inputs.

## 5. Build And Install On The Selected Simulator

Wait for parent/UI's explicit scaffold-ready confirmation. Set `SIMULATOR_UDID`
from the actual available list. Boot only that dedicated simulator if needed.

```sh
export SIMULATOR_UDID="ACTUAL-DEDICATED-SIMULATOR-UDID"
xcrun simctl boot "$SIMULATOR_UDID"
xcrun simctl bootstatus "$SIMULATOR_UDID" -b
cd "$CASEOPS_REPO/apps/mobile"
node ./node_modules/expo/bin/cli run:ios --device "$SIMULATOR_UDID" --no-bundler
```

Do not repeat `boot` when the selected device is already booted. The first local
prebuild/Pods may download free open-source build dependencies. Stop on any new
terms, account, signing or paid-service request. An unsigned/ad-hoc simulator app
does not require an Apple distribution identity and does not prove iPhone signing.

In a separate shell with the **same three development flags**, start Metro:

```sh
cd "$CASEOPS_REPO/apps/mobile"
node ./node_modules/expo/bin/cli start --dev-client --localhost --port 8081
```

Record the actual build output and `.app` path; do not choose an old DerivedData
artifact merely because it has the same name. Use Xcode's reported workspace,
scheme and build directory if discovery is necessary. Inspect the built app:

```sh
export APP_PATH="/actual/build/output/CaseOps.app"
plutil -extract CFBundleIdentifier raw -o - "$APP_PATH/Info.plist"
plutil -extract CFBundleShortVersionString raw -o - "$APP_PATH/Info.plist"
plutil -extract CFBundleVersion raw -o - "$APP_PATH/Info.plist"
node "$CASEOPS_REPO/scripts/mobile/source-snapshot.mjs"
```

Require bundle `ai.caseops.mobile.dev`, actual version/build and an unchanged
source fingerprint. A successful `expo export --platform ios` is only a Hermes
bundle export; this step needs the compiled native `.app` and installed Simulator.

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
metadata using the required fields in `README.md`. Recommended concrete UI IDs
are in `apps/mobile/e2e/testids.json`; verify them against the final UI rather
than silently changing selectors. Set `environment` honestly and retain the
separate Docker source/image/database receipt when applicable.

```sh
cd "$CASEOPS_REPO"
export CASEOPS_MOBILE_FIXTURE="/absolute/path/isolated-ios-fixture.json"
export CASEOPS_MOBILE_APPIUM_URL="http://127.0.0.1:4723"
export CASEOPS_MOBILE_REPORT_ROOT="$HOME/.cache/caseops-mobile/evidence"
node --test scripts/mobile/tooling.test.mjs
node scripts/mobile/run-native.mjs ios --collect
node scripts/mobile/run-native.mjs ios
node scripts/mobile/reconcile-native.mjs ios /actual/run/events.jsonl
```

Require six intended/discovered identities, complete setup/call/teardown results,
native `NATIVE_APP` context, no retries, exact backend/source/binary identity and
zero missing-marker/unadmitted-route counters. After a process restart, the note
must come from the authoritative workspace reread. Keep failures and interrupted
runs unchanged; missing completion, missing fixture, no binary or incomplete
handoff is **not** success. Never retry an uncertain note save.

Return the complete unique run directory, sanitized build/config/doctor results,
Xcode/OS/device versions and exact candidate inputs to parent. This six-case
development slice does not certify the forty-group matrix, physical iPhone,
VoiceOver, camera, biometrics, APNs, signed distribution, TestFlight or production.
