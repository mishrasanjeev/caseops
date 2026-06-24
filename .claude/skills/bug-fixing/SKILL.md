---
name: bug-fixing
description: Use this skill for any CaseOps bug triage, verification, reopen analysis, or review of another agent's bug-fix claim. Enforces fail-closed bug handling: reproduce, root cause, adjacent-path audit, regression coverage, strongest verification, and honest verdicts.
---

# Bug Fixing

This skill is mandatory for all CaseOps bug triage, bug fixing, verification,
reopen analysis, and reviews of another agent's claim that a bug is fixed.

## Allowed verdicts

- Properly fixed
- Partially fixed
- Not fixed
- Inconclusive

Use exactly one verdict per bug. If verification is blocked or incomplete, do
not upgrade the verdict.

## Fail-Closed Rules

- Never call a bug fixed without proof on the user-visible workflow.
- Better copy, redirects, or cleaner errors are not "Properly fixed" if the
  workflow still fails or still invites failure.
- If only the read path is fixed but create, update, parse, or mutation paths
  still drift, the bug is only partially fixed.
- Desktop-only verification is insufficient for a mobile or responsive bug.
- Reopened bugs require fresh end-user verification before closure.
- If the environment blocks the strongest verification, say so explicitly and
  lower confidence.

## Mandatory Workflow

1. Parse the reported bug precisely.
2. Reproduce it with a test or a concrete verification step.
3. Identify the root cause, not just the visible symptom.
4. Audit adjacent paths that can fail the same way.
5. Implement the smallest complete fix.
6. Add regression coverage for the original bug and the highest-risk adjacent
   path.
7. Run the strongest practical verification.
8. Classify the outcome honestly using the allowed verdicts.

## Adjacent-Path Audit Requirements

- Schema, enum, or status bugs:
  - inspect backend schema
  - inspect frontend schema
  - inspect endpoint typings
  - inspect create and update forms
  - inspect read-path parsing and fixtures
- Workflow gating bugs:
  - remove or disable impossible actions before submit, not only after failure
- AI or provider failure bugs:
  - check happy path
  - check timeout, empty response, unsupported capability, and fallback behavior
  - confirm the user-visible error remains actionable
- Mobile or responsive bugs:
  - verify on an actual mobile viewport, not desktop only

- Catalog-backed selector bugs:
  - assert the complete user-facing invariant, not only seeded examples
  - provide a fail-open path when catalog completeness can block workflow completion
  - audit every consumer of the shared selector or catalog endpoint
  - inspect defaulting and hydration effects that can overwrite a fallback selection
## Forbidden Closure Patterns

- "Fixed" because the copy improved.
- "Fixed" because the route redirects somewhere else.
- "Fixed" because the backend now explains the failure better, but the UI still
  invites the invalid action.
- "Fixed" after checking only one path while related read, write, or parse
  paths still drift.
- "Fixed" on desktop only for a mobile or responsive issue.
- "Fixed" without rerunning the strongest practical regression.
- "Fixed" before a Playwright probe (or equivalent end-user-visible workflow
  run) on the **deployed production surface** PASSES with real credentials.

## Brutal Honest Testing — No Manual QA Dependence (added 2026-04-26 PM)

**This rule binds every CaseOps bug fix, feature ship, refactor, and
release sign-off. It is non-negotiable.**

The repo MUST NOT depend on a human (Ram, Hari, Mishra, anyone) clicking
through a workflow to discover whether it's broken. Every shipped change
needs automated end-user-visible proof against the **deployed
production surface**, written by the agent that shipped the change,
committed to `tests/e2e/`, and runnable on demand.

### What "brutal honest testing" means

1. **End-user verification, not developer-internal verification.** A
   curl that returns 422 in 83 seconds is NOT "fixed" if a lawyer in
   the UI sees a broken page. Type-checks, vitest with mocked wrappers,
   build success, deploy-script exit 0, job-log "updated=N" lines —
   none of these are end-user proof. They are necessary but not
   sufficient.

2. **Per-deliverable verdict honesty.** Every bug-fix verdict in any
   deliverable (spreadsheet, status update, commit message, memory
   entry, release sign-off, hand-off to user) MUST be paired with the
   exact proof artifact that satisfied the verdict. Allowed phrasing:
   "Properly fixed (tests/e2e/X.spec.ts:Y PASSED on commit SHA Z)".
   Forbidden phrasing: "Properly fixed", "Looks good", "Should work
   now", "Tests pass" without naming WHICH tests against WHICH
   environment.

3. **Skipped is not verified.** A test that `test.skip()`s due to
   capability gates, missing tenant data, or environment block is at
   most `Inconclusive`. Document the skip reason and lower confidence
   IN THE DELIVERABLE. Do not silently upgrade.

4. **Sister-test attribution.** When a base-primitive fix is verified
   on a sister surface but not the originally-reported one, the verdict
   names the sister surface explicitly: "Properly fixed at the base
   primitive (verified via tests/e2e/X.spec.ts:sister-test-Y)". Do not
   imply the original surface itself was probed.

5. **No "done by user" sign-off.** It is forbidden to write "user can
   verify in UI" or "should work — please confirm" as the closure.
   The agent that shipped the change is responsible for proving it
   works before the deliverable goes to the user. If the agent cannot
   prove it (capability-blocked, env-blocked, provider-blocked), the
   verdict is `Inconclusive` and the deliverable says so.

### Mandatory pre-deliverable checklist

Before any deliverable goes to the user with a "fixed" claim, the
agent MUST be able to answer YES to all of these:

- [ ] Is there a Playwright spec in `tests/e2e/` that exercises the
      reported workflow on the deployed surface, signed in as a
      representative user?
- [ ] Did that spec PASS on the deployed commit SHA?
- [ ] Is the spec committed (not one-shot manual)?
- [ ] If the spec skipped, is the verdict downgraded to `Inconclusive`
      with the skip reason recorded?
- [ ] Is the verdict in the deliverable paired with the exact proof
      artifact (spec path + line + commit)?

If any answer is NO, the verdict is at most `Inconclusive`.

### What about new features (not bug fixes)?

The same rule binds new feature work. A shipped feature without a
prod-Playwright spec exercising the user-visible workflow is at most
`Inconclusive`, never `Done`. The feature flag, the migration, the
backend route, the frontend page — all four can be green individually
while the user-visible workflow is broken at an integration seam.

### What about backend-only / job-log-passing changes?

Backend job changes (seed jobs, migrations, ingest scripts) often
"prove themselves" via job logs (`updated=N`, exit 0). That's
necessary but NOT sufficient. The test:

- Does the change have a user-facing payoff? (e.g., seed-statutes →
  lawyers see hand-curated section text)
- If YES, the user-facing payoff MUST be probed in prod. Otherwise the
  verdict is `Inconclusive` for the user-facing payoff, even if the
  backend job ran cleanly.

### Anchor incident (2026-04-26 PM)

I shipped 7+ bug fixes today and the statute-completeness loop, then
told the user "all done". The user replied: "Have you done honestly
brutal testing?" Brutal audit:
- 3 bugs Playwright-verified on prod (PASSED): BUG-017, BUG-020, BUG-022
- 1 bug verified via sister-primitive only: BUG-018 (skipped on Ram's tenant)
- 1 bug verified by curl-not-504: BUG-015 (no end-user workflow probe)
- 3 bugs vitest-mocks-only: BUG-016, BUG-019, BUG-021
- 1 backend loop verified by job-log only: statute completeness
- 0 of these were paired with the exact proof artifact in the original
  deliverable

This rule exists because that pattern is unacceptable.

## Playwright-on-Prod Verification Rule (added 2026-04-26)

**Mandatory before marking any bug "Properly fixed" in any deliverable**
(spreadsheet, status update, commit message, memory entry, release sign-off):

1. Write a Playwright spec under `tests/e2e/` that reproduces the original
   user-visible workflow against the **deployed** caseops.ai / api.caseops.ai
   surface, signed in as the reporting user (or a representative test
   account).
2. Run it with the deployed commit SHA. Local-only or mocked-wrapper green
   tests do NOT satisfy this rule — they prove the fix COMPILES, not that
   it works for the user.
3. The probe MUST be committed to `tests/e2e/` so it's repeatable on the
   next reopen. One-shot manual probes are not regression coverage.
4. If the Playwright run **skips** (capability gate, missing tenant data,
   environment block) the verdict is at most `Inconclusive`, never
   `Properly fixed`. Document WHY it skipped in the deliverable.
5. If a fix lives at a base primitive shared across multiple surfaces
   (e.g., `DialogContent`) and a sister-test on a related surface PASSES,
   the verdict can be `Properly fixed at the base primitive (sister-test
   verifies)` for the un-probable surface — but the sister-test must be
   named explicitly in the verdict.
6. Code-level reasoning, TypeScript compile-success, vitest-with-mocks,
   and deploy-script-success are NOT proof. They're necessary but not
   sufficient.

Examples of canonical prod-Playwright specs:

- `tests/e2e/ram-batch-2026-04-26-prod.spec.ts` — sign in as reporting
  user, navigate to the affected page, exercise the broken workflow,
  assert the fix.
- `playwright.prod-ram.config.ts` — standalone Playwright config that
  points at the prod surface (no local webServer pre-flight) and uses a
  single chromium project. Mirror this pattern for new prod-verification
  specs.

## CaseOps Release Gate

- Keep `docs/STRICT_BUG_TASKLIST_2026-04-22.md` current for any Hari or Ram bug,
  reopen, or adjacent defect discovered from the same audit.
- If the audit exposes a broader platform, security, or scale-hardening gap,
  also update `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`.
- No agent may claim "all bugs fixed" until stop-ship items are properly fixed,
  schema drift is closed on both read and write paths, and mobile bugs have
  mobile proof.

## Operational Verification Hygiene

Use this section for release sign-off, reopen analysis after deployment, and any
claim that production now proves the fixes.

- Treat this as verification hardening, not bug reopening, unless the checks
  uncover a new real defect.
- Prove the deployed build identity when possible. Prefer an API or web build
  fingerprint that exposes commit SHA, build time, and environment.
- If commit identity cannot be proven from the deployed surface, say that
  explicitly. Do not silently upgrade confidence.
- Make verification deterministic. Use the strongest repeatable local or CI
  path, and route temp/cache artifacts into writable locations instead of
  accepting flaky permission failures as "good enough."
- Payment or provider-dependent workflows need a real verification path. A
  skipped E2E is only acceptable if there is an automated fallback or a clearly
  documented manual check with equivalent confidence.
- Use `scripts/verify-release.sh` or `scripts/verify-release.ps1` to gather
  canonical release evidence when the repo workflow fits. For manual or partial
  checks, start from `docs/runbooks/release-signoff-template.md`.
- Record release evidence durably: target commit, environment URLs, commands
  run, results, skipped checks, and explicit caveats.

## Release Verdicts

Use one of these for release sign-off:

- GO
- GO with caveat
- NO-GO

Fail closed:

- If the intended deployed commit cannot be proven and no approved fallback
  exists, do not issue a clean `GO`.
- If a required smoke test is skipped without equivalent fallback evidence, do
  not issue a clean `GO`.
- If the environment is too broken to run the strongest practical verification,
  lower confidence and downgrade the release verdict.
