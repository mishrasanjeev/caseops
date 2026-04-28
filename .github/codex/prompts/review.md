Review the current pull request for the CaseOps repository.

Start by reading `CLAUDE.md` and follow the repo's review standards. Then review
only the changes introduced by the current pull request against the base branch.
Use the fetched pull request refs and `git diff` if needed to focus on the PR
delta rather than the whole repository.

Priority order:

1. correctness bugs and behavioral regressions
2. security, auth, tenancy, auditability, and data-leakage risks
3. API/schema drift across backend, frontend schemas, and UI write paths
4. release-signoff and enterprise-hardening regressions
5. missing or weak verification for risky changes

CaseOps-specific hotspots to check aggressively:

- multi-tenant isolation and matter-level access
- auth/session handling and secret exposure
- AI safety, provider-failure handling, and citation-grounding regressions
- enum/status mismatches between backend and frontend
- reminder, notification, billing, and contract-extraction regressions
- mobile/responsive regressions when UI behavior changed

Do not spend time on style nits, naming preferences, or speculative refactors.
Do not praise the PR. Do not restate the whole diff.

Output rules:

- If there are no actionable findings, respond exactly with:
  `Codex review: no actionable findings.`
- Otherwise, begin with `Codex review findings:`
- Then list findings as flat bullets, ordered by severity.
- Each bullet must include:
  - severity (`High`, `Medium`, or `Low`)
  - file path and line or area reference when you can infer it
  - the concrete issue
  - why it matters
  - the narrowest recommended fix or verification gap
- End with one short `Residual risks:` line covering any unverified area worth
  human attention.
