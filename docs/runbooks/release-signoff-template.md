# Release Sign-Off Evidence

- Generated at: `YYYY-MM-DD HH:MM TZ`
- Reviewer: `name / agent`
- Environment: `prod / staging / preview`
- Target commit: `abcdef1`
- Deployed build fingerprint URL: `https://...` or `not available`
- Verdict: `GO` | `GO with caveat` | `NO-GO`
- Program verdict: `PROGRAM INCOMPLETE` | `PROGRAM INCOMPLETE - REPOSITORY WORK COMPLETE, EXTERNAL ACCEPTANCE PENDING` | `PROGRAM COMPLETE`

## PRD Traceability and Definition of Ready

- Milestone / epic / slice:
- Requirement IDs and acceptance facets:
- Journey IDs and normal/exception path IDs:
- Actor, capability, and tenant/data scope:
- Dependencies and milestone exit criteria:
- Expected automated, UAT, legal, provider, security, and production evidence:
- Canonical manifest row and evidence path:

## Ownership and Overlap Review

| Component / record / route / page / job | Decision (`NEW/EXTEND/LINK/REPLACE`) | Canonical writer | Existing overlap searched | Compatibility / retirement gate |
| --- | --- | --- | --- | --- |
| | | | | |

- Forbidden-duplicate audit result:
- One-writer reconciliation result:
- Shared Matter/platform owner preserved:

## Data, Schema, Capability, and Migration Review

- Data classes and sensitivity:
- Schema diff or explicit `no schema change`:
- Capability catalogue / API / UI parity diff:
- Expand/backfill/verify/switch/contract plan or `not applicable`:
- Mixed-revision compatibility evidence:
- Backfill dry run, reconciliation, restartability, and row counts:
- Rollback/roll-forward and committed-event preservation:
- Production migration head before / after:

## Threat and Abuse Review

- Tenant isolation and restricted-record tests:
- CSRF/SSRF/source-boundary/webhook/upload/redirect tests as applicable:
- Replay, stale-write, race, idempotency, quota, cost, and poison-record tests:
- Prompt injection, inaccessible citation, and model/provider failure tests as applicable:
- Secrets/logs/screenshots checked for sensitive data:

## Scope

- Release or change set under review:
- Bug sheet or ticket scope:
- Declared exclusions:

## Build Identity

- Expected full 40-character commit:
- Checkout used by production tests:
- API `/api/build` release SHA and Cloud Run revision:
- Web `/api/release-identity` release SHA and Cloud Run revision:
- API/web image digests and immutable job image:
- Migration execution ID:
- Scheduler/job identity, target, cadence, timezone, permission, and canary proof:
- Traffic allocation:
- Proof links:
- If exact API + web + checked-out test-source equality cannot be proven, verdict is `NO-GO`.

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
| Exact API/web release identity | `/api/build` + `/api/release-identity` + test checkout | pass/fail | All three are the expected full SHA; abbreviated tags do not count |
| Case-tracking release canary | approved QA bookmark `/release-smoke` | pass/fail/not-applicable | One idempotent, costed operation for this exact SHA; fresh success/no-change outcome |
| Protected source open | tracked-case update source proxy | pass/fail/not-applicable | API-origin path, provider boundary, bearer proxy, non-empty attachment, audit |
| Narrow responsive actions | dated 360px Playwright | pass/fail/not-applicable | Every grouped action/link visible and in viewport; DOM presence alone does not count |

## Test Inventory and Results

| Boundary | Exact command / run | Tests selected | Passed | Failed | Skipped | Evidence |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Focused unit / integration | | | | | | |
| Full API shards and coverage | | | | | | |
| PostgreSQL / migration | | | | | | |
| Database index health | `caseops-db-index-health` | | | | | |
| Timeout-boundary inventory | repository static contract | | | | | |
| Full web / typecheck / build | | | | | | |
| Local desktop + narrow E2E | | | | | | |
| Exact deployed production E2E | | | | | | |

Required-path skips, `.only`, quarantine markers, stale fixtures, and hidden
allow-list omissions must be listed as failures unless the PRD explicitly permits
the exclusion.

## User-Visible and Documentation Evidence

- Desktop screenshot references (sanitized):
- Narrow/mobile screenshot references (sanitized):
- Product Guide/help/search corpus updates:
- API/OpenAPI/generated client updates:
- Runbook/release notes/public docs/landing/pricing/`llms*.txt` updates:
- Public claim reconciliation result:
- Screenshot omission rationale when the production surface cannot be captured safely:

## External Approval and Fail-Closed State

| Gate | Exact version / fixture / provider | Human owner | Evidence | Status | Fail-closed behavior |
| --- | --- | --- | --- | --- | --- |
| Legal rules/forms/fees/source policy | | | | pending/approved/not-applicable | |
| Provider terms/credentials/sender/template | | | | pending/approved/not-applicable | |
| Security/privacy/data | | | | pending/approved/not-applicable | |
| Product/pilot/UAT | | | | pending/approved/not-applicable | |

No Codex-authored checkbox or elapsed observation period substitutes for required
human approval. Natural scheduler history is monitored operational evidence, not
an arbitrary release-duration blocker.

## Production Acceptance

- Dated production test file and exact test title:
- QA tenant / synthetic fixture (no credential or real-client data):
- Fresh mutation/read-back and cleanup:
- Desktop result:
- 360px result including every grouped action/link:
- Provider/source-open result:
- Production workflow URL and conclusion:
- Post-test persistence/reload result:
- No real legal filing, service, payment, closure, or unapproved message occurred:

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
- Do not issue a clean `GO` when exact-release verification was started by a
  source push instead of the completed canonical deployment.
- Do not route a new API revision when migration or database index health has
  not passed from the same immutable candidate image.
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
