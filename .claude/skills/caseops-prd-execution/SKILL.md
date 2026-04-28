---
name: caseops-prd-execution
description: Use this skill for any CaseOps feature planning, implementation, product-gap analysis, module review, UX redesign, or PRD update. Forces every task to map to the unified PRD, current repo truth, source-data rules, user stories, and test IDs before work begins.
---

# CaseOps PRD Execution

This skill is mandatory for any CaseOps feature work, product planning, UX
revision, roadmap review, or module-gap analysis.

## Read first

Before doing substantial work, read:

1. `docs/PRD_CLAUDE_CODE_2026-04-23.md`
2. `docs/WORK_TO_BE_DONE.md`
3. `docs/PRD_COVERAGE_MOD_TS_2026-04-20.md`
4. `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`
5. `docs/STRICT_BUG_TASKLIST_2026-04-22.md` when the task touches a bug,
   regression, or reopen

## Mandatory workflow

1. Identify the journey ID or IDs affected.
2. Identify the module ID or IDs affected.
3. Inspect the current routes, services, pages, schemas, and tests before
   claiming a gap or proposing a rewrite.
4. Classify the work honestly against the current repo state.
5. Map the task to user stories and test IDs from the PRD.
6. Only then plan or implement the change.
7. Update the PRD or the strict ledgers when the repo truth changes.

## No-random-work rule

- Do not invent new modules, workflows, routes, or marketing claims that are
  not grounded in the PRD.
- If the user asks for a genuinely new feature, update the PRD first or in the
  same task.
- Do not mark a module "missing" just because one expected UX surface is absent
  if the backend or an adjacent UI already exists.
- Do not mark a module "done" just because some code exists if the key journey
  is still broken, partial, or unverified.

## Vector and AI quality rules

For any retrieval, corpus, statute, tribunal, judge-intelligence, or
document-intelligence work:

- Production vector data must use the PRD's Voyage-based production path.
- Current production truth for CaseOps is **Voyage `voyage-4-large` on GCP**,
  not the historical `BAAI/bge-small-en-v1.5` baseline.
- Corpus enrichment that materially affects retrieval quality must use the
  high-reliability Opus-assisted normalization path or an explicitly approved
  equivalent.
- Anthropic-backed enrichment, cleanup, or evaluation paths that are part of
  the production corpus workflow must not be described as optional if the task
  is about production readiness or production truth.
- Production retrieval must keep reranking enabled where the PRD requires it.
- No corpus slice may be called production-ready without the PRD's 4.8+/5
  quality gate and benchmark evidence.
- Treat `bge-small`, `fastembed`, or other local/offline models as dev,
  smoke-test, or fallback paths unless explicit benchmark evidence says they
  are the chosen production path.
- If older docs, notes, or spreadsheets still describe `bge-small` as current
  production, call that out as stale-doc drift instead of repeating it.

## Bench-aware drafting rules

For any judge-profile, bench-match, appeal-drafting, recommendation, or hearing
strategy work:

- Inspect the current judge/court routes, `services/bench_matcher.py`, drafting
  templates, drafting prompts, and tests before claiming the feature is missing
  or complete.
- Treat judge profile plus bench-match as foundation only. The feature is not
  end-to-end unless drafting or recommendation generation consumes cited judge
  or bench history.
- Add or update a task brief when bench-aware drafting scope changes. Current
  queued brief: `docs/BENCH_AWARE_APPEAL_DRAFTING_TASKLIST_2026-04-24.md`.
- No judge favorability scoring, win/loss prediction, reputation claims, or
  uncited "judge tendency" language is allowed.
- Bench-aware output must use evidence phrasing: "in the indexed decisions
  provided, the bench emphasized..." and must cite the supporting judgments.
- Weak or absent judge-history coverage must degrade to normal drafting with a
  visible limitation note, not to invented strategy.
- Required tests include tenant isolation, weak-evidence fallback, no
  favorability labels, citation verification, prompt-injection resistance, and
  UI rendering of context quality.

## UX rules

- Prefer simple, lawyer-friendly flows over feature density.
- One screen should have one obvious job and one obvious primary action.
- Error copy must be actionable and plain-language.
- Desktop-only proof is insufficient for surfaces lawyers will use on laptops,
  tablets, or phones in real practice.

## Documentation rules

- Keep `docs/PRD_CLAUDE_CODE_2026-04-23.md` current when scope, sequencing, or
  module status changes materially.
- Keep `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` current when a feature task
  exposes a broader platform or hardening gap.
- Keep `docs/WORK_TO_BE_DONE.md` and `docs/PRD_COVERAGE_MOD_TS_2026-04-20.md`
  aligned with live code when they drift.

## Minimum output standard

Any substantial CaseOps feature answer should be able to state:

- affected journey IDs
- affected module IDs
- current status in the repo
- required user stories
- required functional tests
- required non-functional tests
- required security tests

If you cannot state those, you have not done enough context work yet.
