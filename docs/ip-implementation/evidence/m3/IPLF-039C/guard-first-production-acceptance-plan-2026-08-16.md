# IPLF-039C — guard-first production acceptance plan

- **Prepared:** 2026-08-16
- **Artifact state:** local only; not run against production; not release evidence
- **Candidate worktree HEAD:** `956154799e6f2657c70634a482d0598db7f3cc30`
- **Required exact deployed guard-first `main` SHA:** pending
- **Migration `20260816_0001`:** pending and nondeployable until this acceptance passes

## Purpose and release order

This is the dated API acceptance required by the mixed-revision fence in
`coverage-distinct-role-contract-2026-08-16.md`. It verifies the already
deployed guard-first API before `ck_ip_deadline_coverage_distinct_roles` may be
installed. It does not query PostgreSQL, inspect the check constraint, or treat
the migration as deployed evidence.

The run is eligible only when the API and web release-identity endpoints both
equal one exact 40-character `main` SHA before the first write and again after
the final assertion, and the API revision carries 100% of traffic. A passing
run is necessary but is not by itself authority to replace the fence's
`pending`: the Cloud Run revision/traffic capture and reviewed run output must
be recorded beside it first.

## Mechanically enforced production boundary

The spec refuses its first mutation unless all of the following are explicit:

1. `CASEOPS_IP_GUARD_PROD_MODE=verify`;
2. `CASEOPS_IP_GUARD_QA_ACK=dedicated-qa-disposable-fixtures-only`;
3. exact QA company UUID, slug, owner email, and owner password;
4. exact API and web HTTPS URLs (loopback and non-HTTPS URLs are rejected);
5. exact deployed API/web SHA equality;
6. owner authentication resolves to that exact company UUID and slug;
7. the QA IP workspace is enabled with **no provider keys** and **no enabled
   automations**; and
8. one exact active QA rule version and compatible calendar version are
   supplied for the critical-confirmation fixture; and
9. `CASEOPS_IP_GUARD_RUN_ID` is an operator-chosen, non-secret recovery key in
   the form `20260816-` plus 6-16 lowercase letters or digits.

The test creates two uniquely named users through
`POST /api/companies/current/users`. That supported endpoint accepts an
explicit password and does not invoke the employee mailer. Do not substitute
`POST /api/companies/current/employees`: in production it can send a real
SendGrid setup email. The company-user quota check reads an existing
subscription and user counts; it does not create a billing account, grant or
expire credits, or contact the payment provider.

All generated emails end in the reserved `example.com` domain. Generated users
have no calendar connections. The spec never calls billing, integrations,
providers, delete endpoints, employee invites, or database helpers. Failed
critical confirmation stops before operational deadline, coverage, reminder,
or notification-intent creation.

Every user, Matter, and docket request carries a deterministic name derived
from that run id. A successful response is registered before its assertions;
if a response or docket assertion fails after the server commits, the teardown
also searches the exact reserved emails, Matter codes/markers, and linked
docket titles. Retries are disabled.

Every generated Matter is disposed through
`PATCH /api/matters/{id}/lifecycle/status`. The spec verifies every coverage is
removed from operational access when the retired docket becomes a fail-closed
404; the focused lifecycle service regression proves the exact retained child
status is `inactive_lifecycle`. Only then are disposable users deactivated
through the supported company-user endpoint. Audit and lifecycle history are
retained; no row is deleted or rewritten as if the test never happened. If
Matter discovery or cleanup fails, user deactivation is deliberately withheld
so operational work is not stranded, and the run fails with the cleanup error.
Cleanup runs in an independently timed `afterEach` hook with a 180-second hook
budget, at most two 50-row Matter-list pages, and a 10-second timeout on every
cleanup API call. The hook emits only the non-secret run id and the path to the
manual recovery procedure; it never prints credentials or bearer tokens.

## Writer and assertion matrix

| Required writer | Fixture / request | Required proof | Cleanup |
| --- | --- | --- | --- |
| Create | New QA Matter, docket, operational deadline; primary equals backup | Typed `409 ip_coverage_distinct_backup_required`; docket still has no coverage | Dispose Matter |
| Direct proposed reassignment | Valid A-primary/B-backup row; proposal would make current A the backup | Typed 409; complete coverage record byte-for-byte equal after reload | Dispose Matter |
| Direct immediate reassignment | Valid A-primary/B-backup row; immediate replacement is QA owner and decline escalation is B | Typed 409; complete coverage unchanged | Dispose Matter |
| Bulk reassignment | Portfolio A -> B where B is already backup | Typed 409; no partial mutation of the accessible row | Dispose Matter |
| Portfolio preview/proposal | Same collision portfolio | Preview is `transfer_allowed=false`; proposal is typed 409; row unchanged | Dispose Matter |
| Ordinary proposal/acceptance | Fresh A-primary/no-backup row, proposal A -> B, B accepts | Responsibility moves only after B's own action; final B primary/null backup | Dispose Matter |
| Immediate rejection escalation | Fresh A-primary/no-backup row, immediate A -> B with owner escalation, B rejects | Final owner primary/null backup, rejected/escalated state; never unowned | Dispose Matter |
| Critical deadline confirmation | Fresh candidate from exact active rule/calendar, same A as accepted primary and backup | Typed 409; candidate record and all docket coverage unchanged after reload | Dispose Matter |
| Employee offboarding preview/commit | Historical A-primary/B-backup QA coverage, offboard A to B | Preview 200 with `can_commit=false` and the distinct-backup blocker; commit 400 with the same blocker identity; employee and coverage unchanged | Dispose Matter, deactivate users |

## Exact seeded prerequisites

No invalid pre-guard coverage row is required or permitted for this run. The
contract requires production proof of the reachable proposal/acceptance and
rejection-escalation paths, and the disposable fixtures exercise both while
asserting the final roles stay distinct. The defensive acceptance and
rejection branches for already-corrupt legacy pending rows cannot be produced
through the guarded API. They remain covered by the canonical service
regressions and, after it is eligible, the hosted-PostgreSQL contract job; they
are not a reason to manufacture invalid production state.

The production run needs two free internal-user seats, an
enabled manual-only IP workspace, and these exact QA governance fixtures:

- `CASEOPS_IP_GUARD_QA_RULE_VERSION_ID`: active and selected for the QA company;
- `CASEOPS_IP_GUARD_QA_CALENDAR_VERSION_ID`: active, compatible with the rule,
  and applicable to the run date.

Those governance fixtures are not created or transitioned by this acceptance.

## Canonical offboarding contract

Offboarding is a two-step aggregate workflow rather than the direct coverage
writer response shape. Its canonical regression requires preview 200 with
`can_commit=false` and a distinct-backup blocker, followed by commit 400 with
the same blocker identity and unchanged employee/coverage state. The dated
spec asserts that documented contract exactly; it does not force the direct
coverage routes' typed-409 envelope onto offboarding.

## Canonical invocation

Required environment variables:

```text
PROD_BASE_URL
PROD_API_BASE_URL
CASEOPS_EXPECTED_RELEASE_SHA
CASEOPS_IP_GUARD_PROD_MODE=verify
CASEOPS_IP_GUARD_QA_ACK=dedicated-qa-disposable-fixtures-only
CASEOPS_IP_GUARD_QA_COMPANY_ID
CASEOPS_IP_GUARD_QA_SLUG
CASEOPS_IP_GUARD_QA_OWNER_EMAIL
CASEOPS_IP_GUARD_QA_OWNER_PASSWORD
CASEOPS_IP_GUARD_QA_RULE_VERSION_ID
CASEOPS_IP_GUARD_QA_CALENDAR_VERSION_ID
CASEOPS_IP_GUARD_RUN_ID=20260816-<6-to-16-lowercase-alphanumerics>
```

Run only after confirming 100% API traffic on the exact SHA:

```text
npx playwright test --config=playwright.ip-guard-first-prod.config.ts --reporter=list
```

The production spec is excluded from `playwright.config.ts`, so neither
`npm run test:e2e` nor a bare `npx playwright test` can collect it. Before the
release run, prove both sides of that boundary without executing tests:

```text
npx playwright test --list
npx playwright test --config=playwright.ip-guard-first-prod.config.ts --list
```

The first listing must not contain
`iplf-039c-guard-first-2026-08-16-prod.spec.ts`; the dedicated listing must
contain exactly its single test.

Production output must be retained as redacted text only. The config disables
trace, screenshot, and video capture because authenticated legal data and
session-bearing requests must not become CI artifacts.

## Manual recovery

The test prints a line beginning `[IPLF-039C] run_id=...` before its first
write. Preserve that non-secret id in the redacted run log. If Playwright is
killed, the worker crashes, or teardown reports `MANUAL RECOVERY REQUIRED`, an
owner of the exact dedicated QA tenant must perform this bounded recovery:

1. Reconfirm the API/web exact release SHA, QA company UUID/slug, and that the
   IP workspace remains provider-free and automation-free. Do not recover in a
   different tenant.
2. `GET /api/companies/current/users` and select only the exact addresses
   `caseops-ip-guard-source-<run-id>@example.com` and
   `caseops-ip-guard-replacement-<run-id>@example.com`. Their full names must
   also equal `IP guard source <run-id>` and
   `IP guard replacement <run-id>`, and their role must be `member`.
3. Page `GET /api/matters/?q=<run-id>&limit=50` (no more than two pages) and
   select only the `IPG-CONFLICT-<RUN-ID>` / `IPG-WORKFLOW-<RUN-ID>` records
   whose exact title, `synthetic_release_canary` type, `CaseOps Synthetic QA`
   client, description, practice area, forum, and company UUID match this
   document and the spec.
4. `GET /api/ip/dockets` and record only the exact `IPGUARDCONFLICT<RUNID>` /
   `IPGUARDWORKFLOW<RUNID>` dockets linked to those Matter ids.
5. For each matching non-disposed Matter, read its current status and
   `updated_at`, then use only
   `PATCH /api/matters/{id}/lifecycle/status` with `to_status=disposed` and the
   optimistic-concurrency fields returned by that read. Confirm each recorded
   docket now returns 404 from the operational endpoint.
6. Only after every matching Matter is disposed and every linked docket is
   non-operational, deactivate the two exact users with
   `PATCH /api/companies/current/users/{membership_id}` and
   `{"is_active": false}`. Never delete rows or use a database helper.

Redact bearer tokens, passwords, and response bodies before retaining the
recovery log. Do not reuse the recovered run id: user records are intentionally
retained inactive, so the next acceptance needs a new run id.

## Local preparation status

The artifact has not been run against production and makes no deployment
claim. From frozen worktree HEAD
`956154799e6f2657c70634a482d0598db7f3cc30`:

- the default Playwright config collected none of this production spec, while
  the dedicated config collected exactly its one test;
- standalone TypeScript checking of the config and spec passed;
- the focused production-config safety contract passed all 6 cases;
- focused Ruff over the guarded services and canonical regressions passed;
- the 11 exact create/reassign/propose/accept/escalation/confirmation/
  offboarding/Matter-lifecycle node selectors passed all 13 cases; and
- canonical web typecheck passed.

Production execution was not attempted because the exact deployed SHA,
dedicated-QA credentials/UUID, and rule/calendar prerequisites were not
provided. Local service evidence cannot substitute for those release
identities, nor can it authorize replacing the fence's `pending` value.
