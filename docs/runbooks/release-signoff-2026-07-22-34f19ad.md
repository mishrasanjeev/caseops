# Release Sign-Off Evidence - Ram 2026-07-22

- Generated at: `2026-07-22 20:28 Asia/Kolkata`
- Reviewer: `Codex release verification`
- Environment: `production`
- Target/deployed commit: `34f19ad2bc0a5b48398144998cf546cc9e7a815a`
- Verdict: `GO with caveat`
- Bug verdict: `BUG-001 Properly fixed`

## Scope

- Release: optional, auditable conflict review decoupled from matter creation
  and Intake/On-hold to Active status changes.
- Source workbook: `CaseOps_Bugs_Ram22Jul2026.xlsx`.
- Required regression: committed
  `tests/e2e/ram-2026-07-22-prod.spec.ts` against the exact deployed build.
- Credentials were supplied only at runtime and are not stored in source,
  logs, or this evidence file.

## Build Identity

- Git commit, local HEAD, and `origin/main` at verification time:
  `34f19ad2bc0a5b48398144998cf546cc9e7a815a`.
- API revision: `caseops-api-00210-fnv`, 100% untagged production traffic.
- API runtime/registry digest:
  `sha256:23d2e9313cf8a99f538e3dbd5f9a9cfc0533e0559de0fc16f4b02df4a18e3b94`.
- Web revision: `caseops-web-00189-k9f`, 100% untagged production traffic.
- Web runtime/registry digest:
  `sha256:7ffd1277b78d352539e0a4eeef83e320b3a396227b0c7ad3128f123ba4f15745`.
- `caseops-migrate-job` and all four recurring API jobs were independently
  read back at the API digest above.

## Checks

| Check | Result | Evidence |
| --- | --- | --- |
| Exact candidate integrity | pass | 53 intended paths, clean diff, secret scan clean, exact match to validated candidate copy |
| Backend affected regression | pass | Ruff plus 59 affected conflict/lifecycle/intake/import tests |
| Web affected regression | pass | 19 React tests, TypeScript, 64-route production build |
| Local lifecycle Playwright | pass | July 15 + July 22 combined 5/5; July 22 2/2 |
| Canonical production deploy | pass | `scripts/deploy-prod.sh 34f19ad2bc0a5b48398144998cf546cc9e7a815a` exited 0 |
| Database migration | pass | `caseops-migrate-job-ggqwz`, 1/1 task succeeded |
| Scheduled/background jobs | pass | migrate plus four recurring jobs pinned to exact API digest |
| API/web rollout | pass | latest-ready revisions above, exact digests, 100% production traffic |
| Public health | pass | API status `ok`; web HTTP 200; ClamAV sidecar present |
| Supplied-tester production workflow | pass | committed July 22 spec 2/2 in 71.6s; no-check activation 6.5s, controlled reopen/historical-clearance 57.0s; cleanup passed |
| Independent QA production workflow | pass | GitHub run `29929098217`; both July 22 cases passed (8.9s, 14.4s), RAM 46 passed with four expected conditional skips, notice module 2/2 |
| Repository and deployment identity | pass | deployed SHA was pushed fast-forward to `origin/main`; workflow checked out the same full SHA |

## Conditional Skips

The four RAM skips were data-conditional legacy probes, not skipped July 22
acceptance evidence: real-tenant empty calendar, real-data invoice dialog,
forced recommendation-failure UI, and real-data garbled OCR. Their synthetic or
equivalent guards passed in the same workflow. Both July 22 acceptance tests
ran and passed without mocks or skips.

## Caveats

- The existing web Dockerfile runs `npm install` without the monorepo lockfile.
  The image tag and digest are immutable and verified, but dependency
  resolution is not fully reproducible from Git alone. This predates the July
  22 candidate and needs a separate build-hygiene correction.
- Root `npm audit` reported two high findings (`next` direct and `sharp`
  transitive) and no critical findings. The available automated remediation is
  a semver-major Next change, so it was not mixed into this lifecycle release.

## Release Decision

`GO with caveat` for the deployed release. The requested workflow is formally
`Properly fixed`: exact build identity is proven, both committed July 22 tests
passed twice on independent production tenants, cleanup passed, adjacent
conflict review remained operational, and the broader production suites are
green. The caveats are pre-existing supply-chain/build-hygiene work and do not
invalidate this bug verdict.
