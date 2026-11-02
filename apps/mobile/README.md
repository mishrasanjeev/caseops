# CaseOps Native App

Development candidate for Android and iOS. Not a signed beta, store release or
completed native acceptance. Use with the matching isolated backend only.

## Run

This is an independent npm package, deliberately outside the web workspace:
Expo SDK58 requires React19.3/RN0.88, independently of the web's React19.2.
Use Node24 and the checked-in lock. Do not replace the Expo CLI with a global CLI.

```sh
cd apps/mobile
npm ci
npm run typecheck
npm test
```

Development configuration, set before both building and starting Metro:

```sh
# iOS Simulator with the API and web running on the same Mac
export EXPO_PUBLIC_API_ORIGIN=http://127.0.0.1:8000
export EXPO_PUBLIC_WEB_ORIGIN=http://127.0.0.1:3000
export CASEOPS_MOBILE_AUTOMATED_TEST=1
export CASEOPS_MOBILE_RELEASE_SHA="$(git rev-parse HEAD)"
npm run ios
```

On the Windows Android emulator, use `http://10.0.2.2:8000` for the local API and
`http://10.0.2.2:3000` for the local web, or a deliberately configured ADB reverse
on the dedicated device. In PowerShell set the same variables with `$env:NAME`.
The API and web ports are examples: use their actual isolated runtime ports.
Release HTTP and arbitrary LAN HTTP are rejected. Never point automated builds
at production or omit the no-paid-provider marker to make a test pass.

```sh
npm run android
# After a development binary is installed:
npm start
```

Android requires owner-accepted SDK terms, matching SDK/build tools and a usable
device/emulator. iOS requires the owner's MacBook with Xcode/Simulator. See the
[native test runbook](../../scripts/mobile/README.md) and
[MacBook instructions](../../scripts/mobile/MACBOOK_RUNBOOK.md).

## Current Software

- Four stable destinations: Today, Matters, Calendar, Work.
- Bounded existing-API reads, exact Matter identity, Summary/Activity/Files/Work,
  identifier search, date navigation and current-version draft reading.
- Explicit one-shot note save, server lifecycle-version precondition, receipt
  verification and persisted reread. Unknown outcomes never auto-submit again.
- Android native Compose controls use the installed Expo UI
  `MaterialExpressiveTheme`; iOS buttons/pickers use SwiftUI. Layout/navigation
  remain React Native. The custom iOS edge-back handler is not a native-stack
  implementation or verified iPhone behavior.
- System-browser PKCE authentication and MFA, memory-only access credentials,
  OS-backed rotating refresh, foreground reauthorization and private-screen purge.
- No app checkout, paid generation, legal approval, lifecycle command, persistent
  private offline data, marketing telemetry or automatic OTA feature updates.

## Deliberately Not Claimed

This build does not implement the full My/Team/undated assignment queue,
contract/IP source navigation, native private PDF viewing/capture/upload, global
inbox/push or native device-session management UI. Unavailable integrations are
stated explicitly, not represented as successful empty feeds or working buttons.
Native accessibility, safe areas, permissions, device storage and both-platform
end-to-end behavior still need actual native execution.

Production native issuance stays disabled until registered HTTPS app links,
separate signing configuration and the full release gates are established. The
development-only `caseops://oauth/callback` is not a verified production link.

The October24 development checkpoint and unresolved dependency/security findings
are in [the implementation evidence](../../docs/mobile/MOBILE_BUILD_CHECKPOINT_2026-10-24.md).
An Expo Hermes export is not an APK, an Xcode build, native E2E or production proof.
