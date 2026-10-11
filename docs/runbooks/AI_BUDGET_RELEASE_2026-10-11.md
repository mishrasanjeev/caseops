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
- Five new money test files contributed 205 cases in r4: budget primitive 47,
  dispatch/process/migration 13, LLM boundary 61, native LLM SDK transport 37,
  embedding boundary 47. The expanded gate contained eight historical
  adapter/settings files, 138 cases. Earlier r3 had 204 new/135 historical;
  those smaller inventories are retained, not substituted for r4.
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

## Adjacent Denial Amendment

Independent review of the first candidate found that the shared SDK denial
could still be treated as an ordinary failed document by operational callers.
The amendment stops metadata/backfill/statute batches, retains denied ingest
inputs, preserves accepted predictive classifications, cools down summaries
without exhausting transport attempts and distinguishes compliance's deferred
AI phase from its completed deterministic work. Provider I/O in the amended
corpus paths owns no source transaction, and publication rechecks frozen source
identity. Remote retained staging is bounded to one owned slot per temp root.

Retained red evidence includes 13 failures/eight controls for metadata and
structured backfill; 21 failures/three controls for corpus money stops and
transaction ownership; five additional title/source/timestamp failures; two
repeated remote-staging failures; and two original summary financial-denial
failures. Early collection/fixture defects are explicitly NOT RUN, not product
reproductions. Initial amended summary runs still failed before the complete
55-case replacement passed; the failed receipts remain available.

Agent-scoped replacement evidence: corpus 157 passes/471 phases, summary
55 passes/165 phases and classification/statute 38 passes/114 phases, zero skips.
These do not certify the combined tree. Parent r5 selected 27 exact files and
collected 714 identities, including PostgreSQL: **708 passed, six explicit
Windows title-extraction skips, zero failures/errors**, pytest completion exit 0,
714 JUnit identities and 2,136 setup/call/teardown reports. Independent native
reconciliation proves the exact requested file inventory, each permitted skipped
phase, no duplicate/missing result and unchanged API source hashes. Both owned
runner/pytest PIDs are absent. The outer console tee failed after pytest completion
with a Windows UnicodeEncodeError (caller exit 1); its failed receipt is retained,
not relabeled clean wrapper acceptance. Six skipped identities still require
positive Linux replay; the canonical amended planner selects their module in
coverage shard 7/13. Evidence: `.tmp/ai-money-native-20261011-r5/results.jsonl`,
`results.xml` and `independent-reconciliation.json`. The compliance red control reproduced one
missing deferred-phase annotation while the ordinary failure control passed;
its first replacement exposed a test assertion treating serialized audit JSON
as a dictionary. That test defect was corrected without changing the API.

CodeQL's side-effect-in-assert finding and mixed implicit return were corrected
in source. Alerts 541/542 (Alembic reflective metadata) and 543 (ORM registration)
were individually dismissed as false positives; 546 is an isolated test-worker
failure receipt, individually classified as used in tests. No scanning rule or
security boundary was relaxed. Fresh amended analysis is still required.

The terminated ingest VM was not resumed. Its legacy sweep wrapper tolerates
nonzero stage exits, and dormant pre-guard images cannot be certified as guarded
executors. Upgrade and prove the authoritative database/adapters before any
resumption; do not infer a global account cap from the API alone.

## Remaining Gates

The first Docker run at `ab07681ecbd27f9ce110f73ec664ec9c5fe74a5d` was
intentionally interrupted after independent review found missing corpus-driver
money-denial halt handling. Its journal retains 2,237 collected identities and
27 completed calls, no completion event: **incomplete, not acceptance**.
The owned Python child was confirmed absent, and only its exact Compose project
`caseops-acceptance-ab07681ecbd2-a27280ba9b78` was removed, including the
acceptance emulator, both networks and owned volumes. Replacement evidence is
required for the amended commit. The full web unit suite independently passed
1,242 tests across 198 files. Hosted CodeQL, security and web checks passed on
the earlier candidate, but are not closure evidence for the amendment.

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
