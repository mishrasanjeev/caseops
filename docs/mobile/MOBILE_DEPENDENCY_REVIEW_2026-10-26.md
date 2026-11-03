# Mobile Dependency Review

Date: 26 October 2026. Scope: J20/M22, the isolated `apps/mobile` dependency
graph and its transitive Android UI dependencies. **Release NO-GO. This record
grants no production approval, prerelease approval, security exception or waiver.**

Source inspected: PR558 head `762980ab4b5ad6a5c7b8df95764d03a0c3a59455` and
recovery branch `codex/mobile-current-recovery-20261026` at descendant
`694eec9289f2622c7feee3af355464904d764595`. Neither identity establishes a deployed
native release. The review does not change any manifest, lock, installed package,
audit threshold, CI ordering or production service.

## Unchanged High-Severity Blocker

The mobile lock still contains `node-forge` 1.4.0, reached through Expo 58.0.19,
`@expo/cli` 58.1.15 and `@expo/code-signing-certificates` 0.0.7. The four high
affected package entries in Mobile source gates run `40277816119` share the
underlying advisory; they are not four independent vulnerabilities. That run
executed PR merge commit `7e09b2af3f862290eb36b2fdcb0d9f754fe51679` and failed
`npm audit --audit-level=high` before either platform export.

[GitHub's reviewed GHSA-86w9-cpqp-85rv](https://github.com/advisories/GHSA-86w9-cpqp-85rv),
CVE-2026-85393, still covers versions through 1.4.0 with no published patched
version. [Official npm latest metadata](https://registry.npmjs.org/node-forge/latest)
was rechecked today and still returns 1.4.0. The proposed
[upstream fix PR1152](https://github.com/digitalbazaar/forge/pull/1152) is open,
not an approved, published dependency update. No exploitability assessment of the
shipped native app was established by this review.

The hosted force-fix suggestion would install Expo 44.0.6, a breaking downgrade,
not a supported repair of the pinned SDK58 graph. Do not use that downgrade,
an unsupported crypto fork, an advisory exclusion, `continue-on-error`, or a
modified audit threshold. Root/web graph success and backend fixture tests cannot
clear the independent mobile audit. Keep the high-severity gate fail-closed.

## Native Material3 Prerelease Review Remains Open

The npm dependency `@expo/ui` is pinned to 58.0.23. Its installed Android
`build.gradle` declares both `androidx.compose.material3:material3` and
`androidx.compose.material3:material3-android` at **1.5.0-beta01**. A stable npm
wrapper does not make those native dependencies stable or approved.

[Official Android release notes](https://developer.android.com/jetpack/androidx/releases/compose-material3)
list stable Material3 1.4.0, beta01 dated October 7, and beta02 dated October 21.
[Google Maven metadata](https://dl.google.com/dl/android/maven2/androidx/compose/material3/material3/maven-metadata.xml)
was rechecked today: latest/release is 1.5.0-beta02, updated `20261021170819`.
There is still no stable 1.5 release in that metadata. A newer beta is neither
approval of the existing beta nor an instruction to override Expo's native pins.

Retain the production-dependency review gate recorded in
`MOBILE_BUILD_CHECKPOINT_2026-10-24.md`. An explicit supported decision, exact
resolved native graph, provenance and compatible same-source native evidence are
still required. No new Material3 security advisory is asserted here. Forcing
stable 1.4 may remove Expressive APIs and is not an equivalent accepted change.

## Boundaries

A public-lead test-fixture isolation repair does not remediate either dependency
gate. Supported future remediation must preserve the actual nested/installed
inventory, official patch provenance, fresh mobile audit and matching native
acceptance. No install, build, Docker/emulator operation, paid-provider probe,
production request, signing workflow or store submission was performed for this
review. No dependency approval or waiver is granted.

## Separate Fixture And Harness Corrections

The current recovery branch retains harness-only commit
`694eec9289f2622c7feee3af355464904d764595`:285 focused cases pass, with17 native
Files cases collected but zero executed. Prior upload evidence is preserved.

The notification-test fixture inherited `CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL`,
selecting the separate e2e transport before its mocked SendGrid seam. Clear that
ambient setting and cached settings in this fixture only; unmocked HTTP transport
is rejected. Production admission, authentication and no-paid fences are unchanged.
The original selection failed16/passed33; replacement49 selected cases pass with
all147 phases, zero failures. All53 module identities were collected, but four
PostgreSQL cases were initially deselected; preserve that component-only receipt.
The five new ambient-setting/transport regressions pass; two originally failed.

The subsequent full module on unchanged test bytes at8d89ceb2 passes53/53,
all159 setup/call/teardown phases, zero failures/skips/deselections. Independent
collection, live journal and final JUnit agree, including all four PostgreSQL
claim/transport/stale-completion races. This replay used a fresh owned PostgreSQL
server and separately migrated, connection-disabled HTTP template; no retained
application rows were cloned. Original catalogue rows were checked unchanged.
Owned containers/network were removed. The first internal-network connection
timeout is retained as failed setup, not a product reproduction or test pass.

Evidence: primary Windows workspace outputs/fix-561-20261026/mobile-backend-fixture
and mobile-current-recovery. These source results do not clear the dependency
gate, hosted CI, complete native acceptance, store release or production rollout.
Full-module proof: outputs/fix-561-20261026/mobile-leads-full-02-validation.json.
