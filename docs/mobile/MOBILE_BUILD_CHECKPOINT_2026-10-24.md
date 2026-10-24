# Android And iOS Build Checkpoint

Date: 24 October 2026. Scope: J20/M22, US-MOB-01..08; existing J01/J03/J04/J08/J14
owners remain authoritative. Status: **Partially implemented**. Release verdict:
**NO-GO**. This is the first implementation, not completed MOB-01..40 acceptance.
The five prior desk-review rounds and the owner-approved interactive designs
precede this work; neither is native-device evidence or participant research.

## Source And Platform Decisions

Development starts from `e3b20ee648bf0d6bb20546a64b51a6afba5c2423`, with explicit
uncommitted implementation changes at this checkpoint. That base SHA does not
identify these new app bytes or claim they are serving production. No production
deployment, signing, entitlement change or paid-provider call occurred.

Development publication branch: `codex/mobile-app-build-20261024`. Its first
implementation commit is a handoff point, not permission to merge/deploy. Main
remains the independently serving source; native release is still NO-GO.

The independent `apps/mobile` package pins Expo58.0.19, React Native0.88.0,
React19.3.0 and Expo UI58.0.23 using current official template/npm metadata.
It does not change the web's React dependency graph. Android's installed
`@expo/ui/android/.../HostView.kt` actually invokes `MaterialExpressiveTheme`;
the platform adapter uses real Compose buttons/segmented controls and the
Expressive loading indicator. iOS uses SwiftUI buttons and pickers. These are
not MUI DOM components or a claim that React Native Paper implements Expressive.

The SDK's native Material3 dependency is **1.5.0-beta01**, despite the public Expo
UI package being stable. Retain that production-dependency review gate; do not
silently treat every transitive native API as stable/approved. The current app
is light-theme only. Both dark native appearance and true native-stack iOS
navigation remain unimplemented, not inherited from the conversation preview.

## Implemented Components

1. Real API repositories and response validation for Today, 25-row Matter
   continuation/search, exact-parent workspace, notes, calendar agenda and
   current-version read-only drafts. Larger unsupported server collections fail
   explicitly, not as empty results or silently truncated complete feeds.
2. Four fixed destinations, per-destination route state, Matter local sections,
   source/manual/unknown date labeling, unsaved-note guard, typed failure states,
   canonical redirect-free API paths and actionable explicit retry for reads.
3. Save-once note operation with exact parent/body acknowledgement and reread by
   returned note ID. Known rejection permits a new explicit corrected operation;
   unknown/malformed/transport outcomes never replay. Native writes carry the
   observed lifecycle version for the server-locked precondition.
4. Separate native PKCE S256 handoff, rotating refresh, per-device server
   revocation and existing-tenant authorization integration. Browser cookies,
   platform/portal realm boundaries and CSRF are not native shortcuts.
5. Access credentials remain in the session client, not UI identity props;
   only refresh/session identity use OS-backed SecureStore. Background hides and
   unmounts private surfaces; foreground revalidates before showing them. A
   missing app-owned installation marker invalidates surviving Keychain data.
6. Appium/UiAutomator2/XCUITest core inventory, marker-enforcing loopback gateway,
   source/binary binding and incrementally retained test results. These controls
   are test infrastructure, not a native workflow pass.

## Actual Verification

Component observations so far, not full-release certification:

| Gate | Actual result / boundary |
| --- | --- |
| Mobile source unit inventory | Fresh replacement52 passed, zero failures/skips, five files reconciled from JUnit. Includes21 auth/HTTP/handoff and31 domain/repository cases. Earlier51-case proof retained separately |
| Native TypeScript | Fresh no-emit/unused-local/unused-parameter checks passed after final screen split and concurrency/transport/test-ID changes |
| Expo compatible pins | `expo install --check`: dependencies up to date |
| Android Hermes export | Post-writer replacement succeeded,844 modules, about2.1MB, `dist/android-closed`; not an APK |
| iOS Hermes export | Post-writer replacement succeeded,869 modules, about2.1MB, `dist/ios-closed`; not an Xcode build |
| Android prebuild | Succeeded with `--no-install`; generated ignored native project, not compiled/installed APK |
| Browser handoff units | Three files,41 passed after correcting a split-text identity assertion; earlier incomplete/root-filter and worker-start failures remain non-passing evidence |
| Browser full typecheck/build | Initial stale install lacked `qrcode.react`; after root `npm ci`, TypeScript and fresh Next16.4.2 production build passed, including the native handoff route |
| Local built-browser handoff | Six Playwright cases passed at390px and1280px with deterministic API mocks, zero retries/skips. This is browser layout/consent/recovery proof, not real native authentication. Original six failed test attempts are retained: four ambiguous Next-announcer locators and two assertions that missed the actual correct401 login redirect |
| Native harness self-tests |21 passed/zero skips; earlier five-failure RED retained by tooling agent |
| Appium intended inventory | Android6=6; iOS6=6. These are a core subset, not all40 MOB groups |
| Android native execution | No APK/emulator execution; SDK absent and owner will review/accept terms in Android Studio |
| iOS native execution | Not run; owner will use a separate MacBook. No cloud Mac spend or manufactured simulator evidence |

The source-only CI workflow now runs the isolated app typecheck, complete source
tests, harness self-tests, both bundle exports and an unwaived high-severity
audit. It does not pretend an Ubuntu bundle job is Android/iOS device acceptance.
The known node-forge advisory deliberately remains a failing release gate.

### Backend And Database Evidence

The backend agent's final writes are closed. Parent independently reconciled
the final63-case journal:189 setup/call/teardown phases, all passed, explicit
`session_finished` with exit0. JUnit counts below were also inspected directly.

| Receipt in `apps/api/test-results/` | Actual scoped result |
| --- | --- |
| `native-auth-signing-final-20261024-07.{jsonl,xml}` |63 passed, zero skips/failures;38 native auth and25 security-settings cases |
| `native-auth-final-20261024-03.xml` |64 adjacent MFA/revocation/lifecycle checks passed |
| `native-auth-pg-20261024-03.xml` |5 real PostgreSQL races/full HTTP/native note-lifecycle checks passed |
| `native-auth-migration-20261024-03.xml` |1 independent PostgreSQL upgrade/replay/refused-destructive-downgrade rehearsal passed |
| `native-auth-governance-20261024-03.xml` |57 governance checks passed |
| `native-auth-route-contracts-20261024-04.xml` |36 route/OpenAPI/role contracts passed |
| `native-auth-shared-20261024-02.xml` |358 passed,22 explicitly skipped PostgreSQL identities |
| `native-auth-adjacent-pg-20261024-04.xml` |The exact22 skipped PostgreSQL identities passed as a separate supplement; the earlier run still contains its skips |

Enforced-MFA browser handoff, native exchange, `/auth/me` and actual Matter reads
pass, alongside cross-browser proof isolation. Stale close/reopen native note
writes persist no note. Authorization codes last60 seconds; access300 seconds;
device families have a non-sliding30-day expiry. Production signing requires a
separately provisioned CSPRNG secret of at least32 bytes, encoded as64..256
lowercase hex characters; weak/blank/repeating examples are rejected. Both
production issuance/signing flags remain false. This is device-family authority,
not hardware attestation. Disposable PostgreSQL was removed after testing.

All six native OpenAPI paths and the note version precondition were generated
through `scripts/dump_openapi.py`; web `openapi-types.ts` was regenerated using
the CI-pinned `openapi-typescript@7.13.0`. These scoped checks are not the full
canonical Docker/product gate or actual Android/iOS user-visible acceptance.

## Security And Release Gaps

- Mobile `npm audit` initially found five high affected-package entries. Zod is
  now pinned/overridden to4.6.7. Four high entries remain in the Expo CLI signing
  dependency chain, rooted in node-forge1.4.0,
  [GHSA-86w9-cpqp-85rv](https://github.com/advisories/GHSA-86w9-cpqp-85rv).
  The official advisory reports no patched release. OTA is disabled; this is
  not an advisory suppression or an approved production exception.
- Reinstalling the existing web/root lock revealed its separate pre-existing
  nodemailer/undici/Zod audit findings. Do not call the combined release security
  gate green or silently expand this feature into unrelated dependency changes.
- Registered production HTTPS redirects/app associations, app ownership/signing,
  native session retention/security review, physical-device privacy proof, whole
  Docker/backend/web regressions and protected-main gates remain required.
- No native lifecycle commands, paid providers, legal decisions, app telemetry,
  production QA writes or existing tenant entitlements are enabled by this work.

## Remaining Product Scope

Full assignment/My-Team/undated work, GC obligation and IP source navigation,
native private document viewer/capture/upload/scanner journeys, inbox/push,
device-session UI, true native stack/back, dark theme,200% text/VoiceOver/TalkBack,
tablet/device/permission/kill-restart behavior and signed distribution remain
open. The software does not pretend an unavailable path is implemented.

Owner actions: accept Android SDK terms in Android Studio; use the separate
MacBook/Xcode for native iOS build and automation. These actions establish
prerequisites, never waive the agent's E2E responsibility. See
`../../scripts/mobile/MACBOOK_RUNBOOK.md` and `NATIVE_TOOLING_EVIDENCE_2026-10-24.md`.

## Permanent Learning

- A stable public cross-platform SDK can contain experimental native internals;
  inspect the pinned native dependency and actual theme implementation.
- An Android/iOS Hermes export proves platform module resolution and bundling,
  not native compilation, installation, gestures, secure storage or E2E.
- A preflight lifecycle read is not mutation concurrency control: carry and
  check its version under the server's authoritative lock, including reopen.
- Standard browser installs must match the actual lock before certification;
  a missing QR dependency in stale `node_modules` is setup failure, not proof
  that this new handoff page broke MFA.

## Retained Component Receipts

- `C:/Users/mishr/.cache/caseops-mobile/mobile-unit-20261024-01.xml`: earlier51.
- `C:/Users/mishr/.cache/caseops-mobile/mobile-unit-20261024-02.xml`: replacement52;
  exact five source-file identities, no failure/skipped nodes.
- `outputs/mobile-web-auth/results.json`: original six-failure browser attempt.
- `outputs/mobile-web-auth/2026-10-24T16-10-52-*/results.json`: replacement six-case
  built-browser pass; inspect the actual dated directory, not a presumed future run.
- `scripts/mobile/tooling.test.mjs`:21 passed; native prerequisite failures and
  complete tooling receipts are listed in `NATIVE_TOOLING_EVIDENCE_2026-10-24.md`.
