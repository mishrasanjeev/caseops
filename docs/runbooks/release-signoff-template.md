# Release Sign-Off Evidence

- Generated at: `YYYY-MM-DD HH:MM TZ`
- Reviewer: `name / agent`
- Environment: `prod / staging / preview`
- Target commit: `abcdef1`
- Deployed build fingerprint URL: `https://...` or `not available`
- Verdict: `GO` | `GO with caveat` | `NO-GO`

## Scope

- Release or change set under review:
- Bug sheet or ticket scope:
- Declared exclusions:

## Build Identity

- Expected commit:
- Observed commit or build id:
- Proof:
- If exact commit identity cannot be proven, state that explicitly here.

## Checks

| Check | Command / URL | Result | Notes |
| --- | --- | --- | --- |
| Backend verification | `scripts/verify-backend.ps1 ...` | pass/fail/skipped | |
| Web verification | `scripts/verify-web.ps1 ...` | pass/fail/skipped | |
| API health | `https://...` | pass/fail | |
| Web root | `https://...` | pass/fail | |
| Auth-gated endpoint | `https://...` | pass/fail | |
| Billing or provider-dependent proof | `manual / automated path` | pass/fail/skipped | |
| Public claim classification | landing / pricing / guide / README / llms | pass/fail | Every claim is live, review-first, provider-gated, founder-only, disabled until UAT, or planned |
| Production readiness gate | `/api/platform-admin/production-readiness` | pass/fail/skipped | Founder-only; list not-ready reasons |
| Secret rotation proof | `/api/platform-admin/secret-rotation-readiness` | pass/fail/skipped | No secret values stored or displayed |
| Provider/UAT blockers | Pine Labs / connectors / notifications | pass/fail/skipped | Explicitly blocked, provider-gated, or disabled until UAT |
| Workbook acceptance-contract trace | source row -> API/UI/E2E assertions | pass/fail | Prove every boundary word such as global, standalone, optional, multi-link, assigned, tracked |
| Lifecycle concurrency | two-session stale edit + final read-back | pass/fail/not-applicable | Stale metadata writes cannot replay terminal status |
| Terminal side effects | Today/calendar/reminders/provider jobs | pass/fail/not-applicable | No operational work or background mutation after disposal/archive |
| Operational writer inventory | portal/integration/AI/metadata/bulk/link writers | pass/fail/not-applicable | Shared fresh-parent guard covers every operational writer; read/cleanup/settlement exceptions are explicit |
| Provider/commit race | forced interleaving after I/O or intermediate commit | pass/fail/not-applicable | Parent is refreshed and re-locked before output; losing disposal leaves no child, final ModelRun, notification, or audit |
| Legacy reopen data | migrate terminal row with open children/provider event, then reopen | pass/fail/not-applicable | Upgrade and pre-reopen neutralization prevent old tasks/deadlines/hearings or synced calendar artifacts from resurrecting |
| Database integrity | SQLite FK-on negative controls + fresh PostgreSQL proof | pass/fail/not-applicable | No dangling fixture shortcuts; migrations, constraints, and lock shape pass on the production dialect |
| Mutation contract propagation | API/UI/worker/import/E2E call-site inventory | pass/fail/not-applicable | New CAS/version/source-state requirements reached every caller; omissions are intentional negative tests only |
| Terminal entry paths | create/import/generic PATCH denial | pass/fail/not-applicable | Terminal states and aliases are reachable only through the dedicated lifecycle service |
| Regression discovery | normal local + production Playwright configs | pass/fail | New dated specs are selected; no unregistered allowlist entry |
| Deployed user workflow | committed `tests/e2e/*.spec.ts` on observed build | pass/fail/skipped | Name the exact spec/test and result; local-only evidence is insufficient |

## Caveats

- List every skipped check and why it still provides enough confidence, or say `None`.

## Commands Run

```text
scripts/verify-release.ps1 -ExpectedCommit abcdef1 ...
scripts/verify-backend.ps1 ...
scripts/verify-web.ps1 ...
```

## Reviewer Notes

- Record any manual observations, screenshots, deployment console metadata, or links to CI runs here.

## Fail-Closed Reminder

- Do not issue a clean `GO` if the deployed commit is unproven without fallback evidence.
- Do not issue a clean `GO` if a required smoke test was skipped without equivalent proof.
- Do not issue a clean `GO` for a lifecycle change without stale-session and
  post-terminal background-path proof.
- Do not call a scoped subset complete when the source acceptance contract asks
  for a global or independent workflow.
- Do not accept a positive-path test that relies on a dangling foreign key or
  another state the production database rejects.
- Do not approve a shared mutation-precondition or lifecycle change from
  targeted tests alone; prove repository-wide caller propagation and deny every
  create/import/generic-PATCH terminal shortcut.
- Do not trust a request-entry lock after provider I/O or an intermediate
  commit; require a forced-interleaving test at the final persistence boundary.
- Do not reopen legacy terminal data until its old operational children have
  been neutralized under the authoritative parent lock.
- If the verification environment was too broken to run the strongest practical checks, downgrade the verdict.
