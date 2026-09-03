# CaseOps Coding Guidelines

This project follows the Karpathy-inspired coding guidance from:

- https://github.com/forrestchang/andrej-karpathy-skills

These rules are the default coding behavior for all implementation work in this repository.

---

## Core Principles

### 1. Think Before Coding

- Do not silently guess when requirements are ambiguous.
- State assumptions explicitly.
- Surface tradeoffs before committing to a complex design.
- If a simpler architecture solves the problem, prefer it.
- Stop and ask when ambiguity would create rework or hidden risk.

### 2. Simplicity First

- Write the minimum code that fully solves the problem.
- Do not add speculative abstractions.
- Do not introduce configurability that is not requested.
- Do not build framework-like layers for single-use logic.
- Prefer clear data flow and explicit contracts over cleverness.

### 3. Surgical Changes

- Touch only the code required for the task.
- Do not refactor unrelated code.
- Do not reformat or rename unrelated code opportunistically.
- Remove only the dead code created by your own change.
- If you notice adjacent issues, mention them separately instead of folding them into the diff.

### 4. Goal-Driven Execution

- Convert requests into verifiable success criteria.
- Prefer tests or checks that prove the change works.
- For multi-step work, state the plan and verify each step.
- Do not stop at implementation if verification is feasible.
- For bug work, fail closed: if the intended workflow is not proven to work, do
  not call it fixed.

---

## CaseOps-Specific Engineering Rules

### Product and Architecture

- Build CaseOps as a `matter-native legal operating system`, not a generic chatbot.
- Preserve strict multi-tenant isolation in every service and data design.
- Keep the architecture `enterprise-shaped` even when using lightweight founder-stage infrastructure.
- Design so the move from Cloud Run to GKE is a deployment migration, not an application rewrite.
- Treat `Grantex` as the trust plane for agent identity, scoped delegation, revocation, budgets, and audit.
- Use `Temporal` for durable workflow orchestration; do not build critical workflows as ad hoc background logic.

### AI and Legal Safety

- Keep legal knowledge in retrieval and source systems, not baked into model weights by default.
- Require citation-grounded outputs for substantive legal answers.
- Do not implement black-box judge favorability or unsupported legal risk scoring.
- Default to human review for critical legal outputs and external actions.
- Never design agent actions that can exceed tenant, role, or matter scope.

### Dependency Policy

- Use the latest stable production-ready version of every approved framework, SDK, library, runtime, and database.
- Do not intentionally pin to older major versions unless a blocking issue is documented.
- Avoid beta, preview, nightly, or experimental releases in production paths unless explicitly approved.
- Prefer permissive licenses:
  - MIT
  - Apache-2.0
  - PostgreSQL License
  - BSD-2/3-Clause
- Avoid AGPL, SSPL, BSL, BUSL, and similar restrictive licenses unless explicitly approved.

### Data and Security

- Every persistent business object must be tenant-aware.
- Every sensitive action must be auditable.
- Matter-level permissions and ethical walls must override broad role access.
- Never assume public legal data is safe to use without source, lineage, and access-boundary checks.
- Customer data must not be used for cross-tenant training without explicit opt-in.

### APIs and Schemas

- Use explicit typed schemas for requests, responses, events, and agent/tool contracts.
- Favor backward-compatible API changes where possible.
- Validate inputs strictly.
- Make failure states explicit and observable.

### Frontend

- **Before any frontend work**, read `.impeccable.md` (the CaseOps design
  context) and `.codex/skills/impeccable/SKILL.md` (the vendored
  `impeccable` skill, Apache-2.0, © Paul Bakaus 2025). The skill's
  heuristics are the house style for typography, colour (OKLCH only),
  spacing, and interaction. This rule is mandatory, not advisory.
- Prefer straightforward screens and workflows over UI cleverness.
- Optimize for dense, professional workflows used by lawyers and legal
  ops teams. The product sits next to Bloomberg Terminal and Linear in
  tone — never next to a consumer SaaS landing page.
- Keep important actions obvious:
  - research
  - drafting
  - hearing prep
  - recommendations
  - approvals
- Do not introduce ornamental complexity. No glassmorphism, no neon
  gradients, no emoji in UI, no "AI" purple-to-pink gradients.
- When in doubt, run the `audit` or `critique` references inside the
  impeccable skill against the target surface before shipping.

### Corpus ingestion and vector embedding quality

- **Before any SC / HC corpus ingest, re-embed, backfill, or retrieval
  quality work**, read `.codex/skills/corpus-ingest/SKILL.md` and
  `.codex/skills/corpus-ingest/SKILL.md`
  (personal memory). Both are mandatory, not advisory.
- Current production truth for this repo is **Voyage `voyage-4-large` on GCP**.
  Do not describe `BAAI/bge-small-en-v1.5` as the live production embedding
  model unless the user explicitly scopes the discussion to historical, local,
  or offline-only behavior.
- OpenAI-backed cleanup or evaluation steps that materially affect corpus
  quality are part of the production-quality path when the workflow uses them.
- Per-bucket pipeline order is **ingest → Layer-2 metadata → title-chunk
  embed → HNSW probe → 0-5 rating**. Never batch Layer 2 at the end of a
  multi-bucket sweep — it poisons embeddings with filename-derived
  placeholder titles and costs Voyage twice.
- Rate retrieval quality from `caseops-eval-hnsw-recall` only. Never from
  Layer-2 extraction samples — they diverge wildly (4.7 extraction / 2.5
  retrieval, 2026-04-19 incident).
- Target rating is **4.8+ / 5**. Report after every bucket as
  `rating: X.Y/5 (recall@10=…, MRR=…, rank=…)`. A bucket-over-bucket
  drop is a stop-the-line signal.

---

## Testing Expectations

- Every meaningful feature should include functional verification.
- Security-sensitive paths require authorization and isolation tests.
- Multi-tenant features require tenant-leakage tests.
- AI features require:
  - citation checks
  - refusal/uncertainty checks
  - prompt-injection checks
  - data-leakage checks
- Workflow changes should be verified end to end when practical.

### Mandatory Bug-Fixing Protocol

- Before any bug triage, bug fix, bug verification, or reopen analysis, read
  `.codex/skills/bug-fixing/SKILL.md`. This is mandatory, not advisory.
- Use only these verdicts for bug status:
  - `Properly fixed`
  - `Partially fixed`
  - `Not fixed`
  - `Inconclusive`
- Do not call a bug fixed because the copy improved, the route redirects, or
  the backend explains the failure better while the UI still invites failure.
- For schema, enum, or status bugs, inspect backend schema, frontend schema,
  endpoint typings, create forms, update forms, and read-path parsing before
  closure.
- For mobile or responsive bugs, desktop-only proof is insufficient.
- Reopened bugs require fresh end-user verification before closure.
- If the environment blocks the strongest verification, say so explicitly and
  lower confidence.
- Keep `docs/STRICT_BUG_TASKLIST_2026-04-22.md` current for any Hari or Ram bug,
  reopen, or adjacent defect found through the same audit.

### Mandatory Release Sign-Off Hygiene

- For release sign-off or post-deploy reopen analysis, treat remaining work as
  operational verification hygiene unless fresh verification reveals a new
  product defect.
- Prefer deployed build fingerprints that prove exact commit SHA, build time,
  and environment. If the deployed surface cannot prove commit identity, say so
  explicitly and lower confidence.
- Verification must be repeatable. Do not normalize temp/cache permission
  failures, flaky test harnesses, or one-off local workarounds as clean proof.
- Provider- or payment-dependent flows need a real verification path. A skipped
  E2E is not clean sign-off unless equivalent automated or documented manual
  evidence exists.
- Use `scripts/verify-release.sh` or `scripts/verify-release.ps1` to capture
  canonical release evidence where possible. For manual or partial sign-off,
  start from `docs/runbooks/release-signoff-template.md`.
- Persist release evidence: target commit, environment URLs, commands run,
  results, skipped checks, and explicit caveats.
- Use only these release verdicts:
  - `GO`
  - `GO with caveat`
  - `NO-GO`
- Do not issue a clean `GO` if commit identity is unproven without fallback
  evidence, if a required smoke test is skipped without equivalent proof, or if
  the environment is too broken to run the strongest practical verification.

### Mandatory Enterprise Hardening Protocol

- Before any enterprise-readiness audit, scale-hardening review, architecture
  risk scan, security-hardening review, or analysis of
  `docs/WORK_TO_BE_DONE.md`, read
  `.codex/skills/enterprise-hardening/SKILL.md`. This is mandatory, not
  advisory.
- Use only these statuses for roadmap or hardening items:
  - `Implemented`
  - `Partially implemented`
  - `Missing`
  - `Stale-doc`
- Do not treat `docs/WORK_TO_BE_DONE.md` as authoritative until it has been
  cross-checked against current code, tests, and deploy manifests.
- Separate "landed in code" from "deployed, enforced, and verified".
- Security or operations controls are not `Implemented` without the strongest
  practical infrastructure or runtime proof.
- Giant hotspot modules, manual client drift, broad exception handling, raw
  exception leaks, and fail-open controls count as enterprise hardening gaps
  even when no user bug report exists yet.
- Keep `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` current for every enterprise
  audit, scale review, or `WORK_TO_BE_DONE.md` scan.

### Mandatory Product PRD Protocol

- Before any CaseOps feature planning, implementation, UX redesign, module-gap
  analysis, or PRD update, read
  `.codex/skills/caseops-prd-execution/SKILL.md`. This is mandatory, not
  advisory.
- Treat `docs/PRD_CODEX_2026-04-23.md` as the execution PRD for this
  repo. Do not rely on `docs/PRD.md`, `docs/WORK_TO_BE_DONE.md`, or external
  feedback files in isolation.
- Every substantial feature task must map back to:
  - journey IDs
  - module IDs
  - user story IDs
  - test IDs
- Do not do random work. If a requested feature is genuinely outside the PRD,
  update the PRD first or in the same task before implementation.
- For retrieval, corpus, statute, tribunal, or judge-intelligence work, follow
  the PRD's production data rules: current production default
  `voyage-4-large`, OpenAI high-reliability enrichment where required, reranking
  where required, and the 4.8+/5 corpus quality bar before calling a slice
  production-ready.

### Mandatory Strict Quality Review Protocol

- Before any whole-repo scan, strict QA review, exhaustive test-matrix task,
  security review, release-readiness audit, or request to make quality gates
  stricter, read `.codex/skills/strict-quality-review/SKILL.md`. This is
  mandatory, not advisory.
- Start from `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md` and keep it current
  or create a dated successor audit when findings materially change.
- Do not issue a clean `GO` while P0 findings are open, canonical verification
  scripts fail, provider checks are skipped without equivalent evidence, or a
  security control can fail open in staging or production.
- Every backend route, frontend page, database constraint, provider callback,
  documentation claim, and deploy/runtime control needs either explicit test
  evidence or an explicit tracked exemption.
- Strict reviews must include command evidence. If a command cannot run, record
  the exact command, exact failure, and next strongest proof.
- Keep `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` aligned when strict quality
  findings touch security, operations, deploy, scale, verification, or doc drift.

When fixing a bug:

- first reproduce it with a test or a concrete verification step
- then fix it
- then prove the fix works
- then record whether it is `Properly fixed`, `Partially fixed`, `Not fixed`,
  or `Inconclusive`

### Canonical backend verification recipe

The local backend `uv run` path is fragile on Windows when long-running
processes (notably the corpus sweep) hold a lock on
`.venv/Scripts/*.exe`. Use `scripts/verify-backend.sh` (or the `.ps1`
equivalent) for every backend verification — it bypasses `uv run`,
calls `uv sync --frozen --no-install-project` only when the venv is
missing (which doesn't rebuild the locked entry-point exes), runs an
import sanity check that fails loudly on a partial sync, then runs
ruff + targeted pytest:

```bash
scripts/verify-backend.sh                                    # full suite
scripts/verify-backend.sh tests/test_intake.py               # one file
scripts/verify-backend.sh -k "reminders or intake"           # by keyword
```

This is the recipe an outside reviewer (Codex, second agent) should
use. If `uv sync --frozen` fails on a locked exe, stop the process
holding it (typically the GCE-VM corpus sweep is **not** the local
problem — it runs on `caseops-ingest-vm`, not the workstation). For
local sweeps, use `Stop-Process -Name caseops-ingest-corpus` first.

---

## Code Review Standard

Before considering a change complete, ask:

- Is this the simplest implementation that satisfies the requirement?
- Does every changed line trace directly to the task?
- Did we preserve tenant isolation and auditability?
- Did we avoid speculative abstractions?
- Did we verify the change with tests or concrete checks?

If the answer to any of these is no, revise before shipping.
