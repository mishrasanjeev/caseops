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

The corrective commit is not accepted until its own CI passes, its exact image
is deployed, and the same dated production RAM and Notice suites pass. Overall
program status remains **PROGRAM INCOMPLETE**; later IP slices and human/provider
approval boundaries remain outstanding.
