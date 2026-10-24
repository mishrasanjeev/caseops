# Native Tooling Evidence: 24 October 2026

Owner: native tooling/E2E agent. Shared worktree:
`C:/Users/mishr/.codex/worktrees/document-index-snapshot-20261018/CaseOps`.
Scope: J20/M22 P0/P2 tooling; US-MOB-01..04/08. This does not certify the native
app, all forty MOB groups, a Docker integration, signed beta or production.

## Immediate Feasibility

Observed at 15:23:59 UTC with `scripts/mobile/probe-native.ps1`:

| Item | Actual observation |
| --- | --- |
| Host | Windows build 26300 / 26H2; Intel Core Ultra 9 285H |
| Disk / memory | 1,627.56 GiB free on C:; 63.46 GiB physical RAM |
| Existing Node/npm | v24.15.0 / 11.12.1 |
| Java/JDK | Not on PATH; no JAVA_HOME; standard Java directories absent |
| Android | No ANDROID_HOME/ANDROID_SDK_ROOT, standard SDK directory, adb, sdkmanager or emulator |
| Native processes | No emulator, qemu-system-x86_64, adb or java processes found |
| Virtualization | HypervisorPresent=true; vmcompute running; CIM CPU firmware/SLAT flags report false under hypervisor |
| Acceleration verdict | Unverified, not unsupported: require actual `emulator -accel-check` after SDK setup |
| iOS | Not run; Windows cannot run Xcode, iOS Simulator or XCUITest |

Owner will use their MacBook separately. No cloud Mac service, spend, new account,
CI dispatch or signing credential inspection was attempted. Source CI inspection
found a conditional macOS runner expression in `.github/workflows/codeql.yml`,
but its actual matrix contains actions/JavaScript/Python only. It is not an active
native macOS build/test path. No existing native runner was established.

Android setup is blocked on owner-reviewed SDK terms and the required SDK
platform/build-tools/emulator image. **No Android tools were downloaded, no SDK
licenses were accepted, no `yes`/license hashes were installed.** No Windows
features/BIOS settings were changed. No unrelated process/device/container was
stopped. No native prebuild was started while UI work was incomplete.

## Open-Source Tooling

User-owned cache: `C:/Users/mishr/.cache/caseops-mobile`.
Root/app dependency files were not edited by this agent.

- Appium **3.8.0**, WebdriverIO **10.1.0** installed under `tooling/`.
- UiAutomator2 **8.7.0** installed under the separate `APPIUM_HOME=.../appium`.
- XCUITest **12.20.0** pin/instructions prepared for the MacBook, not installed
  or run on Windows.
- Temurin JDK **17.0.20.1+1** installed successfully. The official archive matched
  the pinned SHA-256
  `e53a79c3c3d86865bd7e787903884331068e71321714ffd44f145785affc7cb0`.
  before extraction, and the executable printed `17.0.20.1+1` with exit 0.
  Session-only `JAVA_HOME` is
  `C:/Users/mishr/.cache/caseops-mobile/jdk/jdk-17.0.20.1+1`.
- `require('webdriverio').remote` resolves to a function from the isolated
  cache. A first optional package-metadata probe exited 1 because WebdriverIO
  does not export `webdriverio/package.json`; the corrected module probe exited
  0. This was not a native session failure.
- An actual Appium child server started on an ephemeral loopback port;
  `/status` returned `{ready:true, version:"3.8.0"}`. The check terminated only
  its own child. This proves server startup, **not** Android/native readiness.
- UiAutomator2 doctor exited **1**: four required fixes (ANDROID_HOME, Android
  adb/emulator, JAVA_HOME, Java binary) and three optional tools (bundletool,
  ffmpeg, GStreamer). The SDK findings remain blockers, not silent skips.
- After JDK installation, doctor again exited **1**, now with **two required SDK
  fixes** only; both JAVA_HOME and `bin/java.exe` passed. The same three optional
  tools remain absent. Driver inventory returned UiAutomator2 8.7.0, exit 0.

Generated `android/gradle/wrapper/gradle-wrapper.properties` uses **Gradle 9.4.1**;
the installed React Native Gradle version catalogs pin **AGP 9.2.1**. JDK 17
matches [AGP 9.2's official compatibility table](https://developer.android.com/build/releases/agp-9-2-0-release-notes)
and [Gradle's JVM requirements](https://docs.gradle.org/current/userguide/upgrading_major_version_9.html).
No Gradle task was started while Android SDK terms remained pending.

Pins come from actual npm registry metadata. Parent owns Expo **SDK58** /
React Native **0.88** and the independent `apps/mobile` dependency installation.
Future Expo commands must use that project's own Expo CLI, not the root workspace
or an implicitly downloaded CLI. Android package: `ai.caseops.mobile.dev`.

## Harness And Traceability

`apps/mobile/e2e/inventory.json` declares six ordered identities **per platform**:

| Identity | Core assertion | Planned group mapping, not full group completion |
| --- | --- | --- |
| CORE-01 | Actual native principal/workspace | MOB-01 |
| CORE-02 | Four native tab destinations | MOB-07/15/19 |
| CORE-03 | Search and open exact seeded Matter | MOB-08 |
| CORE-04 | One note POST, acknowledgement, process restart, authoritative reread | MOB-11 |
| CORE-05 | Sign-out removes private surface and stays signed out after restart | MOB-05 |
| CORE-06 | Observed native gateway traffic retains no-paid marker and exact routes | MOB-30 |

Uses the agreed tab/search/row/note/account/sign-out testIDs. Additional
identity/screen IDs are mapped explicitly in `apps/mobile/e2e/testids.json`;
parent reports implementing that exact map in the UI. Native accessibility-ID
exposure and real native auth handoff remain unverified. No fake customer names, access-token
injection, browser-cookie scrape or invented live authentication is supplied.
The app's safe system-browser PKCE handoff requires separate integration proof.

Native execution requires an actual `.apk`/Simulator `.app`, explicit device,
synthetic isolated seed ledger, real `/api/build` match, source commit plus dirty
source fingerprint and binary hash. The fingerprint covers nonignored app/root
package inputs, not ignored generated native projects; their exact build inputs
need a separate receipt. Each run uses a unique directory, fsynced
setup/call/teardown JSONL, exact intended/discovered reconciliation, zero transport
retries and a twenty-minute bound. Interrupted runs lack completion and fail
reconciliation. Source changes during a run fail postflight.

The loopback-only gateway requires the authoritative no-paid marker on the app's
incoming request and an exact method/path allowlist. It does not log credentials,
queries, bodies or private response data; rejects redirects and caps retained
request evidence at 500. It is not proof of arbitrary device network traffic or
all MOB-30 paths. Deterministic simulator evidence and Docker/PostgreSQL receipts
must remain separate. No screenshots containing login/legal data are auto-saved.

## Actual Commands And Results

| Command | Actual result |
| --- | --- |
| `./scripts/mobile/probe-native.ps1` | Exit 0; observations above |
| `./scripts/mobile/setup-open-source-tooling.ps1 -WithJdk` | Exit **0**; Appium/client/UiAutomator2 and checksum-verified Temurin JDK installed |
| `node --test scripts/mobile/tooling.test.mjs` | Initial 16, then 17 passed; final regression inventory **21 passed / 0 failed / 0 skipped**, 0.579 s; tooling unit tests only |
| `node scripts/mobile/run-native.mjs android --collect` | Exact **6 intended = 6 discovered** |
| `node scripts/mobile/run-native.mjs ios --collect` | Exact **6 intended = 6 discovered** |
| `node scripts/mobile/run-native.mjs android` | Exit **1**; `ISOLATED_FIXTURE_MISSING`; six failed setups, six explicitly unexecuted calls, six passed no-session teardowns |
| `node scripts/mobile/run-native.mjs ios` | Exit **1**; `IOS_REQUIRES_OWNER_MACBOOK_XCODE`; same phase inventory, zero native calls |
| `node scripts/mobile/reconcile-native.mjs android <retained events>` | Exit **1**; zero native passes / six failed phases / six unexecuted calls |
| `node scripts/mobile/source-snapshot.mjs` | Exit 0; source `e3b20ee648bf0d6bb20546a64b51a6afba5c2423`, dirty app inputs explicitly true; fingerprint is time-specific, not a built binary |
| `git diff --check -- apps/mobile/e2e scripts/mobile docs/mobile/NATIVE_TOOLING_EVIDENCE_2026-10-24.md` | Exit 0; not execution or native build proof |

Retained native prerequisite failures (not overwritten):

- Android: `C:/Users/mishr/.cache/caseops-mobile/evidence/2026-10-24T15-30-05-732Z-android-3756c015/`.
- iOS: `C:/Users/mishr/.cache/caseops-mobile/evidence/2026-10-24T15-30-06-107Z-ios-190ca266/`.

After adding the source-postflight reconciliation guard, the expanded 17-case
self-test inventory passed and one fresh prerequisite check per platform retained
the same honest zero-native-call verdict:

- Android: `C:/Users/mishr/.cache/caseops-mobile/evidence/2026-10-24T15-38-24-175Z-android-4fc3a32c/`.
- iOS: `C:/Users/mishr/.cache/caseops-mobile/evidence/2026-10-24T15-38-26-032Z-ios-5f1ee4f3/`.

Each has `events.jsonl` and `summary.json`. Earlier failures remain failures;
source/tooling self-tests do not supersede them as native acceptance.

## Harness Review Regressions

Parent identified retained-stack and post-logout assumptions in `core.mjs`.
Fresh deterministic doubles reproduced **five failing assertions among 21 tests**
(16 pass / 5 fail / 0 skip). All five full details were inspected: inventory
ordered the traffic case after logout; retained Matter details hid the search
field; depth and missing-Back paths lacked explicit bounds; traffic inspection
incorrectly attempted tab interactions. These are harness defects, not product
auth failures or native-device reproductions.

The corrected core unwinds at most four actual visible Back controls before
search and fails closed when unavailable. The traffic case reads retained proxy
evidence without UI access and runs **before sign-out** in both inventories.
Canonical order is now `CORE-01,02,03,04,06,05`; current collection must preserve
that exact order. Older prerequisite receipts retain their old inventory and
must not be reused as current-source certification.

The unchanged complete 21-case replacement passed, zero skips. Both Android and
iOS locator paths are exercised by deterministic driver doubles. Preserved:

- RED: `C:/Users/mishr/.cache/caseops-mobile/evidence/tooling-red-20261024T1553.tap` (exit 1).
- GREEN: `C:/Users/mishr/.cache/caseops-mobile/evidence/tooling-green-20261024T1554.tap` (exit 0).

Retained-stack defect verdict: **Partially fixed**, proven at harness level by
the three Matter-search unit cases; actual Appium interaction remains blocked.
Post-logout evidence defect verdict: **Partially fixed**, proven by the ordering
and no-UI traffic tests; no native pass is claimed. Parent states `note-latest-body`
uses canonical server note order `created_at, id DESC`, and the confirmed-state
ID is present only after persisted reload. Those native surfaces still need
actual accessibility-ID inspection.

## Handoff And Remaining Gates

See `scripts/mobile/README.md` for Windows setup and
`scripts/mobile/MACBOOK_RUNBOOK.md` for detailed owner MacBook build/XCUITest
commands, exact fixture properties, gateway admission and reconciliation.
The owner said they **will** accept SDK terms in Android Studio; this is future
action, not evidence of acceptance or installed SDK readiness. No SDK package
installation or license acceptance followed that message. Native binaries and
isolated auth fixtures are still required.
Parent subsequently reported Android prebuild success and both Hermes exports;
those are parent-owned scaffold/bundle results, not APK or native E2E proof.
Use `apps/mobile/node_modules/expo/bin/cli` from that independent project once
parent/UI confirms it is safe to prebuild. iOS instructions are ready; iOS build
and native execution remain **Not run** until the MacBook produces receipts.

No native app build/install/workflow, Docker integration, physical device,
MFA/refresh/PKCE, upload/scanner, push, accessibility, full-matrix, signed/store or
production pass is claimed. No deployment, commit, push, root lock edit or CI
mutation was performed. Broader PRD/ledger status updates belong to parent.

Official references: [Appium requirements](https://appium.io/docs/en/3.0/guides/migrating-2-to-3/),
[UiAutomator2 requirements](https://appium.github.io/appium-uiautomator2-driver/latest/getting-started/),
[Android downloads and terms](https://developer.android.com/studio),
[Android acceleration](https://developer.android.com/studio/run/emulator-acceleration),
[Temurin archive verification](https://adoptium.net/installation/archives).

## Changed Files

Only the assigned paths were written:

```text
apps/mobile/e2e/core.mjs
apps/mobile/e2e/inventory.json
apps/mobile/e2e/support.mjs
apps/mobile/e2e/testids.json
scripts/mobile/MACBOOK_RUNBOOK.md
scripts/mobile/README.md
scripts/mobile/no-paid-gateway.mjs
scripts/mobile/probe-native.ps1
scripts/mobile/reconcile-native.mjs
scripts/mobile/run-native.mjs
scripts/mobile/setup-open-source-tooling.ps1
scripts/mobile/source-snapshot.mjs
scripts/mobile/tooling.json
scripts/mobile/tooling.test.mjs
docs/mobile/NATIVE_TOOLING_EVIDENCE_2026-10-24.md
```
