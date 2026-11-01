# PR 558 native completion evidence

J20/M22 and US-MOB-01..08 remain **Partially implemented; release NO-GO**.
This checkpoint supersedes older pending-artifact descriptions while retaining
all original failed and incomplete evidence. It is not store acceptance.

Public branch `codex/mobile-app-build-20261024`, revision
`17113fbcc6d29dba4705f3e25702bccb98ae2239`, has 70 completed hosted checks:
68 successful and two explicit skips (staging deployment and post-Codex feedback).
A new published revision requires fresh CI; neither skip proves deployment.

## Actual artifacts and their limits

These artifacts were built from 17113fbc, with native source fingerprint
`dafcb5e8565ad9ba8369277149c646d3a2506882912316297c7c97fd03d9a2f6`
and 226 clean selected inputs. Evidence is retained outside Git beneath
`~/.cache/caseops-mobile/claude-pr558-20261101/`.

| Artifact | SHA-256 | Scope |
| --- | --- | --- |
| OnePlus APK, `android-builds/android-arm64-UuaNNs1W/caseops-local-acceptance-arm64.apk` | `006db3f8970a5c0c15ce44ff7442cca30bafffc6c5eeeba3e72b1f59817f4b5a` | Installed base APK hash, cold MainActivity launch and signed-out UI XML independently reconciled |
| 16 KiB emulator APK, `android-builds/android-arm64-8bWL10Yd/caseops-local-acceptance-arm64.apk` | `f37e18427b877baad9f530fe7d5daa0fdefd5f98a1f24e3b456753f181e169a2` | Build exited zero; installation/startup and Appium sign-in-control smoke reported; complete native inventory unexecuted |
| Simulator app, `ios-builds/ios-sim-lKnxZsbm/DerivedData/Build/Products/Release-iphonesimulator/CaseOps.app` | `7c29262dd95aca2e53bbba3056432d64b6dc588fb9566795db2f720452a3e017` | Canonical hash and nine signing references independently reconciled; complete installed-UDID/session binding and inventory pending |

R's installed mobile graph later exposed glob 13.0.6 while its committed lock
requires 14.0.2-caseops.1. Preserve these binaries as historical build/startup
evidence. Exclusively install the canonical graph, publish reviewed repairs,
and build/test the actual public revision afresh. A tree-equivalent unpublished
commit is a separate identity and cannot replace receipt provenance.

The OnePlus is personal: the owner declined QA CA installation and no phone
certificate-store trust was added. Browser acceptance uses an isolated emulator.
The physical iPhone connection remains unreliable. Emulator camera/biometric
controls do not establish physical-sensor acceptance.

## Fixture and tooling repairs

The V1 host composes the existing base, viewer, Inbox and read-through producers
under their original four-stage, 510-second aggregate contract. Source/build/
installed-device/API/web admission precedes credentials. Normal login/MFA,
exclusive claims, immutable receipts and uncertain-outcome refusal remain
required. Private publication comes from the canonical writer's held descriptor;
the Inbox command executes retained verified worker bytes and preserves actual
cloud/nonlocal refusal inputs.

Queue/privacy uses the existing complete 74-request recipe. Emulator build
origins remain `10.0.2.2`; host API calls use separately bound Docker loopback
origins. Expired admission refuses before charges or HTTP dispatch. Registration
composition consumes independently acquired mount metadata; it does not itself
establish an actual mount. Runtime readers still verify credential bytes/UID.

Closed-source offline results:

- V1 Node 70/70, canonical Python fixture 101/101, independent V1 inventory 7/7
  and existing CI module selection 1/1. Complete Node/Python log hashes:
  `7e38aa345683f3222ae7850f4352e007d3dd61308ebf51af54c43cd834f472b8` and
  `625c11a75b13a63d33ecd5e7523c4b07d4fe6dd644b645b0a426d5c9df2c9dc4`,
  under `/private/tmp/caseops-native-producer-verify-20261101-01/`.
- Queue/privacy Node 29/29, complete client-extension Node 141/141, Python
  queue inventory 8/8, controls 23/23 and client-extension producer 6/6.
  All 438 guarded source entries remained byte/metadata identical. Summary:
  `codex-pr558-readonly-review-20261101/pr558_ci_review/producer-verification-20261101T060019Z/summary.json`
  beneath the mobile cache; SHA-256
  `d2f4e68d47dee7257672c7f165066e85d87beeb20bb2cb99a9c84ec6fa189c36`.

These are fixture/tooling checks, not native passes. Earlier runtime,
missing-dependency and review failures remain retained. Appium core and both
drivers' bundled glob/minimatch repairs are under additional inventory/download
review; initial local passes do not close current release acceptance.

## Unchanged acceptance inventory

| Suite | Cases per OS | Setup/call/teardown phases per OS |
| --- | ---: | ---: |
| Core | 23 | 69 |
| Files | 17 | 51 |
| V1 | 17 | 51 |
| Queue/privacy | 2 | 6 |
| Client extensions | 24 | 72 |
| Total | 83 | 249 |

No complete current-source suite has executed at this checkpoint. Retain every
failed, blocked and unreached phase. CAM-02..06, LOCK-01..05 and LINK-05 have
separate physical/signing qualifications. Production HTTPS associations and
signed profiles cannot be fabricated for LINK-05.

Organization enrollment, D-U-N-S issuance, distribution signing, actual AAB/IPA
archives, verified production links, public support/privacy/deletion surfaces,
reviewer access and store declarations remain separate submission work. The
company website preview stays private under the owner's instruction. No merge,
production deployment, store submission or launch date is claimed.
