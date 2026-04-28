---
name: strict-quality-review
description: Use this skill for whole-repo quality audits, release-readiness reviews, exhaustive test-matrix planning, security reviews, or requests to make CaseOps quality gates stricter. Forces evidence-backed inventory, route/page/test matrices, verification results, and durable audit docs.
---

# Strict Quality Review

Use this skill whenever the task asks for a deep repo scan, exhaustive tests,
strict release quality, security review, QA hardening, or a Claude Code fix
brief. This skill is additive: also use `enterprise-hardening`,
`caseops-prd-execution`, `bug-fixing`, or `impeccable` when their trigger
conditions apply.

## Mandatory Inputs

Read these before issuing a verdict:

- `CLAUDE.md`
- `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`
- `docs/PRD_CLAUDE_CODE_2026-04-23.md`
- `docs/WORK_TO_BE_DONE.md`
- `.claude/skills/enterprise-hardening/SKILL.md`
- `.claude/skills/caseops-prd-execution/SKILL.md`

If any file is missing, say so and continue with the strongest available repo
truth.

## Required Inventory

Collect current evidence before recommending fixes:

- Backend OpenAPI path and operation count.
- Backend route modules and largest service hotspots.
- Backend pytest module count and targeted security/contract tests.
- Frontend `page.tsx` route count.
- Frontend direct page-test coverage.
- Playwright spec count, skipped tests, and provider-gated paths.
- CI workflows and quality/security gates.
- Deploy manifests, secret references, backup/restore runbooks.
- Current dirty worktree status, without reverting user changes.

## Required Verdicts

Use only these release-quality verdicts:

- `GO`
- `GO with caveat`
- `NO-GO`

Use only these implementation statuses:

- `Implemented`
- `Partially implemented`
- `Missing`
- `Stale-doc`

Do not issue `GO` if any of these are true:

- A P0 issue is open.
- Canonical verification scripts cannot run and no stronger alternate proof is
  provided.
- Provider, deploy, backup, or restore checks are skipped without equivalent
  evidence.
- A security control fails open in staging or production.
- Route/page coverage is materially unknown.

## No-Manual-Tester Replacement Standard

Manual testers may be treated as optional only when automation has proven the
release across backend, frontend, database, provider, security, and deployed
smoke surfaces.

Before recommending reduced manual QA, Claude must verify and report:

- Full backend coverage completion, not only selected per-file gates.
- Full frontend coverage completion with thresholds and artifact output.
- API route matrix with happy, validation, 401, 403, tenant isolation, audit,
  pagination/filtering, rate-limit, timeout, and idempotency classifications.
- Frontend page matrix with loading, empty, success, error, permission, mobile,
  keyboard, accessibility, and dead-CTA checks for every page.
- Postgres-backed validation for critical DB behavior.
- Provider-gated release/UAT tests for payment, email, storage, OCR, LLM,
  embedding, court sync, and malware scan paths.
- Playwright coverage for every PRD-critical journey and mobile surface.
- Prod smoke evidence that includes deployed commit identity.

If any item is blocked, skipped, timed out, or covered only by a baseline waiver,
the verdict must remain `NO-GO` or `GO with caveat`; never tell the user manual
testers are unnecessary.

## Strict Coverage Rules

Every backend route must have, or be explicitly exempted from:

- Happy path.
- Validation failure.
- 401 unauthenticated.
- 403 missing capability or wrong role.
- Tenant isolation.
- Pagination, filtering, and sort bounds for list routes.
- Audit event tests for governance/security mutations.
- Rate-limit and timeout tests for expensive, AI, upload, webhook, and provider
  routes.
- Idempotency tests for webhook/provider callbacks.

Every frontend route must have, or be explicitly exempted from:

- Unit/component coverage.
- E2E smoke or workflow coverage.
- Loading, empty, success, and error states.
- Permission-denied state where applicable.
- Mobile, tablet, and desktop layout checks.
- Keyboard and accessibility checks for interactive UI.
- No dead primary CTA, misleading placeholder, or unlabelled roadmap state.

Every database-backed feature must have:

- PostgreSQL-backed constraint tests for critical constraints.
- Tenant-key validation.
- Migration upgrade proof.
- Soft-delete and cascade/restrict behavior proof where applicable.

Every documentation-sensitive change must update:

- Relevant PRD or gap ledger.
- OpenAPI/generated client if route contracts change.
- Runbook if deploy, provider, backup, restore, or operational procedure changes.

## Required Output

For repo-wide audits, create or update a Markdown file under `docs/` containing:

- Verdict.
- Scope.
- Evidence snapshot with commands and results.
- Critical findings ordered by severity.
- Exhaustive test case list with stable IDs.
- Claude Code fix order.
- Required verification commands.
- Do-not-close checklist.

Also update `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` when enterprise, security,
deploy, verification, or operations gaps are found.

## Closure Discipline

Do not close an item because code "looks right". Closure requires:

- Code reference.
- Test reference.
- Passing verification command.
- Runtime/deploy evidence when the claim depends on infrastructure, provider,
  backup, restore, or production configuration.

If the environment blocks the strongest verification, record the exact command,
the exact failure, and the next strongest proof. Lower the verdict accordingly.
