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
  context) and `.claude/skills/impeccable/SKILL.md` (the vendored
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
  quality work**, read `.claude/skills/corpus-ingest/SKILL.md` and
  `.claude/projects/C--Users-mishr-caseops/memory/feedback_vector_embedding_pipeline.md`
  (personal memory). Both are mandatory, not advisory.
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
  `.claude/skills/bug-fixing/SKILL.md`. This is mandatory, not advisory.
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
