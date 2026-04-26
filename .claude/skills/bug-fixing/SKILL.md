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
