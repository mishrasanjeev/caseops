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

- Prefer straightforward screens and workflows over UI cleverness.
- Optimize for dense, professional workflows used by lawyers and legal ops teams.
- Keep important actions obvious:
  - research
  - drafting
  - hearing prep
  - recommendations
  - approvals
- Do not introduce ornamental complexity.

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

When fixing a bug:

- first reproduce it with a test or a concrete verification step
- then fix it
- then prove the fix works

---

## Code Review Standard

Before considering a change complete, ask:

- Is this the simplest implementation that satisfies the requirement?
- Does every changed line trace directly to the task?
- Did we preserve tenant isolation and auditability?
- Did we avoid speculative abstractions?
- Did we verify the change with tests or concrete checks?

If the answer to any of these is no, revise before shipping.

