# IPLF-040B consolidated repository closure - 30 August 2026

## Outcome

IPLF-040B is repository-implemented and locally verified. Its original
opposition workspace baseline was already deployed and remains the canonical
proceeding, identifier, party, event, Matter, access, and audit owner. The
previous manifest blocker was stale: IPLF-041, IPLF-042, and IPLF-043 have
since added the applicant, opponent, and shared-resolution paths on those same
owners.

This record does not upgrade the consolidated release status. The dated
IPLF-041 through IPLF-043 browser journeys still need to be rerun against the
exact production revision serving at the time of acceptance.

## Reconciled journey coverage

| Journey path | Executable proof |
| --- | --- |
| UJ-12 normal | Applicant API journey plus `iplf-041-applicant-workflow-2026-08-23.spec.ts` |
| UJ-12 exception 01 | Explicit pending opposition number API assertion |
| UJ-12 exception 02 | Source, evidence, authority, and confirmation refusal/acceptance API assertion |
| UJ-12 exception 03 | Withdrawal leaves the linked Matter active in the applicant API and browser journey |
| UJ-13 normal | Opponent notice, Rule 45, and Rule 47 API journey plus `iplf-042-opponent-workflow-2026-08-23.spec.ts` |
| UJ-13 exception 01 | Watch hit closes without filing |
| UJ-13 exception 02 | Missing instruction stays in intake and escalates before limitation |
| UJ-13 exception 03 | Rejected filing opens corrective work without falsely advancing the legal stage |

IPLF-043 additionally proves shared evidence packages, extensions, hearing,
order, appeal, settlement, withdrawal, translation, and specialized opposition
paths without creating a parallel legal record.

## Verification boundary

Verification is run on current `origin/main` source anchored at
`820e34bbf71750d9513ba0efbae6ab614963e916`, using only deterministic
synthetic tenant data. Required gates are:

- focused opposition API regression;
- focused opposition web component regression;
- fresh-build Playwright runs for the IPLF-040B through IPLF-043 dated specs;
- canonical program-manifest validation and regenerated views.

No live filing, provider action, client record, external delivery, or legal
conclusion is created by this repository verification.

## Results

- `52 passed` across the focused opposition/post-registration API and manifest
  regression set.
- `43 passed` across the five focused opposition/IP-page web test files.
- The locked web production build compiled, typechecked, and generated all 81
  static pages successfully.
- The dated IPLF-040B baseline browser journey passed in 22.1 seconds.
- The first combined run correctly exposed stale navigation in IPLF-041,
  IPLF-042, and IPLF-043: the IP docket now defaults to the Overview tab, while
  those specs tried to locate Proceedings content without entering that work
  area. The specs now use the durable `view=proceedings` deep link, which also
  preserves the correct work area after reload.
- The repaired IPLF-041, IPLF-042, and IPLF-043 journeys then passed together
  in 1.9 minutes. No product logic was weakened to make the browser tests pass.
- `python scripts/ip_program_manifest.py validate` passed after regenerating
  the canonical views.

## Remaining release-only gate

Do not label the consolidated slice `deployment_verified` until the same dated
IPLF-041, IPLF-042, and IPLF-043 Playwright journeys pass against the exact
immutable production revision and the run records that revision identity.
