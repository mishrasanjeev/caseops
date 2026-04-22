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

## CaseOps Release Gate

- Keep `docs/STRICT_BUG_TASKLIST_2026-04-22.md` current for any Hari or Ram bug,
  reopen, or adjacent defect discovered from the same audit.
- No agent may claim "all bugs fixed" until stop-ship items are properly fixed,
  schema drift is closed on both read and write paths, and mobile bugs have
  mobile proof.
