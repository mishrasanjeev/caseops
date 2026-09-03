---
name: enterprise-hardening
description: Use this skill for any CaseOps enterprise-readiness audit, scale-hardening review, architecture or security gap review, or any scan of docs/WORK_TO_BE_DONE.md. Enforces fail-closed gap classification, code-vs-doc proof, and durable ledger updates.
---

# Enterprise Hardening

This skill is mandatory for any CaseOps request about enterprise readiness,
scale hardening, architecture risk, operational maturity, or backlog-gap review
against `docs/WORK_TO_BE_DONE.md`.

## Allowed gap statuses

- Implemented
- Partially implemented
- Missing
- Stale-doc

Use exactly one status per gap. If the evidence is mixed, prefer
`Partially implemented` over upgrading prematurely.

## Fail-Closed Rules

- Never mark a roadmap item closed from comments, TODOs, commit messages,
  marketing copy, or a planning document alone.
- Separate "code exists" from "deployed, enforced, and verified".
- Security and operations items need infrastructure or runtime proof, not only
  local code.
- If `docs/WORK_TO_BE_DONE.md` says something is missing but the code already
  exists, mark it `Stale-doc` and record the newer evidence.
- If code exists but key enforcement, rollout, coverage, or runtime wiring is
  absent, mark it `Partially implemented`.
- Treat giant hotspot modules, manual client drift, broad exception handling,
  raw exception leakage, and best-effort security controls as enterprise gaps
  even when there is no currently reported end-user bug.

## Required audit surfaces

- Browser auth and session handling
- API authz, rate limits, and expensive-route abuse controls
- Deploy manifests, migrations, secrets, backups, and restore paths
- File-upload hardening and malware scanning
- AI governance: policy enforcement, auditability, caching, quotas, fallbacks,
  and cost controls
- Durable workflows, notifications, and retry behavior
- Observability, logging, tracing, and supportability
- Test matrix quality, E2E gaps, and provider-dependent verification blind spots
- Largest or highest-churn modules that create change-risk
- `docs/WORK_TO_BE_DONE.md` drift against current code and tests

## Mandatory workflow

1. Read `docs/WORK_TO_BE_DONE.md` and `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`.
2. Scan hotspot code, tests, and deploy manifests before making claims.
3. Classify every claimed gap or landed item with one allowed status.
4. Separate findings into stop-ship control gaps, scale-hardening gaps, and
   stale-doc items.
5. Record evidence for each item: code refs, tests, and deploy/runtime proof
   when relevant.
6. Update `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` during the same task.
7. In the final answer, present findings first by severity, then missing-gap
   extraction from `WORK_TO_BE_DONE.md`, then the overall readiness verdict.

## Closure Evidence

- `Implemented` requires code evidence and the strongest practical verification
  for that kind of item.
- `Partially implemented` must name the missing enforcement, rollout, or
  verification layer explicitly.
- `Missing` means there is no meaningful usable path yet.
- `Stale-doc` means the backlog or roadmap text is wrong; point to the live code
  that supersedes it.

## CaseOps Enterprise Gap Ledger

- Keep `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` current for every enterprise
  audit, scale-readiness review, or `WORK_TO_BE_DONE.md` scan.
- Do not treat `docs/WORK_TO_BE_DONE.md` as the source of truth until it has
  been cross-checked against code, tests, and deploy manifests.
- If a bug audit reveals a broader platform or control weakness, record it in
  the enterprise gap ledger in addition to the bug ledger.

## Overall Verdicts

For overall readiness or sign-off language, reuse the repository release
verdicts:

- GO
- GO with caveat
- NO-GO

Fail closed:

- If a stop-ship control gap remains, do not issue a clean `GO`.
- If the code and the backlog disagree, call out the drift instead of averaging
  them together.
- If runtime or deploy proof is unavailable for an operational control, lower
  confidence and downgrade the verdict.
