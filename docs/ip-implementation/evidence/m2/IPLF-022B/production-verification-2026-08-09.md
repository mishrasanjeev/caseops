# IPLF-022B production verification — 2026-08-09

## Release identity

- Pull request: `#186`
- Canonical merge SHA: `592502c40221374cee52e00ea40e0e7e11b96251`
- API revision: `caseops-api-00255-87m` at 100% traffic
- Web revision: `caseops-web-00235-84p` at 100% traffic
- Migration execution: `caseops-migrate-job-n4n2w` completed successfully
- Independent release verifier: passed for the exact 40-character SHA and both serving revisions
- Scheduler reconciliation: all six required schedulers passed identity, image, schedule, time-zone, state, and job-target checks
- Runtime probes: API health passed; the ClamAV sidecar and immediate two-second startup probe were present

## First exact-release production run

Automatic push-triggered workflow `31286492756` checked out the exact serving
release and passed the release-identity gate. The RAM batch finished with 57
passing tests, three skips, and one failure. The Notice module did not run after
the RAM gate failed.

The single failure was the pre-existing IPLF-007C notification-convergence
journey, not the IPLF-022B prosecution workflow. The self-test API committed and
returned a delivered in-app intent, and the administrative API immediately
confirmed the same intent. The 360px UI did not render it because the initial
notification-list request could still be in flight when the self-test was
clicked; that older response could then overwrite the committed intent in the
React Query cache.

## Corrective regression

The production-gate hotfix disables only the self-test action while the initial
authoritative intent snapshot is pending. It becomes usable as soon as the
snapshot succeeds or fails, so an error does not block recovery. This removes
the stale-overwrite window and keeps the existing committed-intent cache update.

Regression coverage proves that:

1. the control is disabled while the initial intent request is unresolved;
2. an attempted click in that state cannot create an intent;
3. the control becomes enabled after the initial snapshot resolves; and
4. the committed self-test intent remains visible before a later authoritative
   refetch completes.

Local corrective validation:

- notification page: 5/5 tests passed;
- complete web suite: 121 files and 577 tests passed;
- TypeScript: passed;
- Next.js production build: passed with 65 routes;
- `git diff --check`: passed.

## Corrected exact-release acceptance

Pull request `#187` passed all eight API shards, aggregate coverage, PostgreSQL
and pgvector validation, the web test/typecheck/build job, the app Playwright
suite, security audits, gitleaks, OpenAPI cleanliness, CodeQL, and automated
review. It merged to canonical `main` as
`35aa37fa740136d0adcf0f1eca62654fb03bf0b6`; local `main` and `origin/main`
were verified at that same commit before deployment.

The exact corrected release produced:

- API image digest `sha256:cf176d3bb89767741fde54f038d7ef504026b0f6ef4d70d66a430a3710bbc0f2`;
- web image digest `sha256:d53498478fbab123868ac2a9da461564dde78d180be71712d0469ffe6bb5de84`;
- migration execution `caseops-migrate-job-695jf`, successful;
- API revision `caseops-api-00256-s8b` at 100% traffic;
- web revision `caseops-web-00236-zfm` at 100% traffic;
- independent exact-40-character-SHA release verification, passed;
- all six scheduler bindings and runtime health/ClamAV probes, passed.

Automatic push workflow `31288756334` passed in 24m16s against the exact
serving release. The RAM batch ran 61 tests: 56 passed and five were expected
skips. The formerly failing IPLF-007C committed-intent/360px journey passed in
5.2s. The separate Notice production module passed 2/2 in 18.9s, including
received, reply, sent, attachment, and filter behavior. Duplicate scheduled
workflow `31289051359` was cancelled so only the canonical push run used the QA
tenant.

IPLF-022B and its release-gate correction are therefore
`deployment_verified`. Overall program status remains **PROGRAM INCOMPLETE**;
later IP slices and human/provider/legal approval boundaries remain outstanding.
