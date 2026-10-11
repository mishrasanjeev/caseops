# AI Budget Candidate Evidence

## Release Verdict

**NO-GO pending complete release gates.** This is not a production deployment
receipt, provider activation or legal-quality certification. Canonical source
base: `dfda0eb3ee3d109f86092962a08d125878b24932`. Candidate branch:
`codex/ai-budget-release-20261011`.

The owner superseded the earlier INR 5,000/pause instruction: October continues
unchanged, and the new shared AI allowance is INR 10,000 per month. The candidate
defaults to enabled from November 2026. No production provider, secret, balance
or October pause was changed during local implementation.

## Completed Local Evidence

- Python 3.13.14, repository locked API dependencies; incompatible OneDrive
  hardlink installation was retained and replaced by a successful copy-mode sync.
- Node 22.14.0 fresh production build passed. Earlier Node 24 type checking was
  static evidence only and was not substituted for the pinned build.
- Four selected web unit files: 13 passed, including the new page's eight
  content/metadata/nonce contracts and historical resource/ownership/discovery.
- Complete public-content inventory: 26 passed, zero skipped or flaky. All 23
  historical identities remain, plus three article identities. Metadata,
  canonical/sitemap, link fragments, noindex, desktop/mobile accessibility,
  layout, article source caveats and absence of model names were exercised.
- A second unchanged public run retained JSON results and desktop/mobile source
  caveat screenshots, both visually inspected. No demo leads were submitted.
- Backend initial gates retained 289/289 passes each in separate r1/r2 journals.
  Expanded r3 gate: **339 collected, 339 passed, zero missing call results**, with
  setup/call/teardown and `session_finished: exitstatus 0` retained.
- Final r4 gate: **343 collected and passed**, no skipped or missing results,
  including the caller-held SQLite writer mutex and three actionable HTTP-copy
  controls. Whole API source/test Ruff and `git diff --check` passed.
- Five new money test files contributed 204 cases: budget primitive 46,
  dispatch/process/migration 13, LLM boundary 61, native LLM SDK transport 37,
  embedding boundary 47. The expanded gate contained eight historical
  adapter/settings files, 135 cases.
- PostgreSQL money-lock controls prove both directed lock orders using separate
  backend PIDs and owned UUID schemas; teardown proved those schemas absent.
- Native SDK controls use pinned OpenAI 2.32.0, google-genai 1.73.1 and HTTPX
  0.28.1 with verified inert MockTransport bindings. These are offline request,
  retry, structured-schema and pre-transport accounting tests, not paid legal
  quality samples. No billable provider was invoked.
- A fresh owned PostgreSQL 17 container upgraded to `20261011_0001`; empty
  downgrade to `20260928_0001` removed both financial tables, then upgrade restored
  them. The initializer admitted an explicitly fictitious local policy once and
  replayed without change. Populated downgrade correctly refused, retaining head,
  both tables and the exact opening/admitted amounts. No production policy was
  initialized, and these fixture amounts are not account billing evidence.
- Governance map/runtime projection generation and validation passed. Migration
  graph has one head. Change-relative validation remains required after commit.

Local retained artifacts are in this worktree's `.tmp/ai-money-native-20261011-r1`,
`r2`, `r3`, `.tmp/ai-money-web-20261011-r2` and
`.tmp/ai-money-migration-20261011`. Earlier incomplete/misspelled lint selection
was retained and corrected; it was never full-coverage evidence.

## Remaining Gates

1. Pass change-relative governance and migration contracts after commit.
2. Run committed clean-image Docker acceptance: full PostgreSQL inventory,
   migration rehearsals, release catalogue reseeding and complete browser phases.
   Earlier broader release failures remain open until full replacement evidence.
3. Require green CI/security on this PR, merge canonical main and verify the
   exact validated release tree. Do not merge an unrelated draft with open gates.
4. Guarded canonical deployment only; exact API/web/job identity, live replay,
   QA certification and quiescent private-projection cadences remain required.
5. Reconcile the November opening liability and pinned all-in pricing before paid
   admission. Use one authoritative database for every executor. Conservative
   admissions are not external invoices or protection against calls outside
   CaseOps. Missing monthly reconciliation fails closed, not zero-funded.
6. Gemini managed access/privacy/region, native strict contract parity and retained
   legal benchmark remain open. No full migration or automatic fallback is live.
   A paid fallback cannot exceed the aggregate INR 10,000 allowance.

## User Documents

- [Recommendations user guide](../AI_RECOMMENDATIONS_USER_GUIDE.md)
- [Shared spending reconciliation](ai-spending-reconciliation.md)
- [Gemini assessment and official sources](../AI_PROVIDER_BUDGET_GEMINI_ASSESSMENT_2026-10-11.md)
- Public article candidate: `/resources/source-grounded-legal-recommendations`.
  It contains no model name and makes no guarantee of legal accuracy or outcomes.
