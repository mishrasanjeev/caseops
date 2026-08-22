# IPLF-026B mobile production-regression correction - 2026-08-23

## Verdict

The 360 px production failure in exact-release workflow `32596300438` was an
acceptance-harness timing defect, not an access-control or UI-functionality
failure. The deep-linked IP page exposed the same `ip-access-workspace` test
identity while it was loading and after the real access workspace resolved.
Under a cold/high-parallel production read, the real workspace resolved about
20.4 seconds after navigation, beyond the prior assertion window. The access
API returned HTTP 200 and the deployed client bundle contained the expected
`Preview grant` control.

This correction gives the loading placeholder its own test identity, waits up
to 45 seconds for the real production workspace, and guarantees deactivation
of the temporary production admin in `finally`. It does not weaken any access,
ethical-wall, preview, grant, revoke, independent-Matter, audit, or responsive
assertion.

## Bounded production investigation

- Exact release under investigation:
  `bc171a43f9f67917fef3eb1afcfad5ff765721ec`.
- Exact-release workflow: `32596300438`; broad RAM result was 77 passed,
  1 failed, and 4 skipped.
- Failing assertion: the IPLF-026B 360 px canary did not observe
  `Preview grant` within the previous expectation window.
- The canary docket access request returned HTTP 200.
- A read-only reproduction against the same QA tenant observed sign-in at
  5.3 seconds, navigation completion at 5.65 seconds, the docket response at
  18.0 seconds, the access response at 25.7 seconds, and the real button at
  26.0 seconds. The control therefore appeared about 20.4 seconds after page
  navigation.
- Six active users matching both reserved synthetic constraints
  `ip-access-prod-*@example.com` and `IP Access Production Reviewer *` were
  deactivated. No wider directory record was changed.

No real client record, recipient, provider operation, filing, fee, payment,
external message, or legal act was created by the investigation or cleanup.

## Source correction

1. `IpAccessWorkspaceLoading` now uses
   `data-testid="ip-access-workspace-loading"`; only the resolved component uses
   `data-testid="ip-access-workspace"`.
2. The focused page test asserts the loading identity while the deep-linked
   docket request is outstanding; the existing resolved-state test continues
   to assert the real workspace identity.
3. The production IPLF-026B journey waits explicitly for the resolved
   workspace for up to 45 seconds, retaining the 360 px viewport and every
   subsequent workflow assertion.
4. The production journey records its synthetic membership immediately after
   creation and deactivates it in `finally` when any earlier assertion fails.
   Teardown failure is itself a test failure.

## Local verification

| Gate | Result |
|---|---|
| IP page focused Vitest suite | 24 passed |
| Generated Next route types and TypeScript | passed |
| IPLF-026B local 360 px Playwright journey | 1 passed in 14.0 seconds |
| Production IPLF-026B Playwright compile/discovery | 1 test discovered |
| Diff/whitespace integrity | passed |

The local Playwright journey still covers preview, grant, revoke, linked-Matter
non-broadening, explicit exclusions, direct/list denial after revoke, and the
responsive user workflow. Production deployment and exact-release rerun remain
required before this correction can be called deployment-verified.

## Unchanged boundaries

- The existing live-provider quota blocker remains separate and is not closed
  by this acceptance-harness repair.
- The four missing IPLF-037B governed renewal calendar/rule version IDs remain
  separate external inputs. No IDs are fabricated and IP rule governance stays
  disabled.
- No portal, access-review, emergency-access, or parallel IP-access owner is
  introduced.
- Repository automation does not infer professional, legal, security, pilot,
  provider, or UAT approval.
