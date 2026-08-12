# IPLF-026B production release attempt - 2026-08-12

## Verdict

IPLF-026B implementation, independent review, canonical merge, exact
production deployment, and its focused dated 360 px production journey are
complete. The complete production release gate is not complete: exact-release
workflow `31565070270` ended with 65 RAM/IP tests passed, 4 documented
conditional skips, and 3 unrelated live-recommendation HTTP 503 failures. One
failure captured the configured OpenAI provider's typed
`llm_quota_exhausted` response; all three occurred in the same recommendation
surface during that run. The dependent Notice suite therefore did not run.

IPLF-026B remains `implemented / passed / blocked / pending`; it is not
`deployment_verified`. Restore available quota/credits for the configured
production OpenAI project, verify its configuration, and rerun the unchanged
complete production workflow against the same exact serving revision before
closing this release gate. Do not turn quota
exhaustion into a release-mode skip, accept a synthetic recommendation, switch
providers without authorization, or infer named legal/security/pilot/UAT
acceptance. The overall verdict remains `PROGRAM INCOMPLETE`.

Only synthetic QA fixtures were used. The focused IPLF-026B journey used the
isolated IP QA workspace; the complete workflow also exercised its standard
`caseops-qa` workspace. No real client record, external recipient, provider
mutation, filing, service, fee, payment, or other legal act occurred.

## Released lineage and independent review

| Control | Exact result |
|---|---|
| Final implementation head | `977acde5d9a1e671fbe7e83b2939e1a5289b6c34` |
| Pull request | #209, expected-head merged with no unresolved review threads |
| Canonical merge and serving SHA | `d97969d1ac8e6cf9da0418f534349257ba487393` |
| CI | `31562902319`, passed |
| Security | `31562902323`, passed |
| CodeQL | `31562902403`, passed |
| Independent automated review | `31562902398`, passed |

The final review found and the implementation fixed two additional bounded
race/semantic defects before merge: linked-Matter team visibility now exactly
preserves the canonical inactive-team rule, and the access response panel is
built while the parent/docket locks remain held so a fallible post-commit
reload cannot report failure after a durable mutation. Focused regressions,
the complete access-workflow file, and the exact-head CI matrix passed after
those corrections.

## Exact production deployment

| Control | Exact result |
|---|---|
| Canonical release | `d97969d1ac8e6cf9da0418f534349257ba487393` (`d97969d` runtime identity) |
| API immutable image | `sha256:91497eb798a7451490bdc216c245f80a74f2528251660fcd7369d5dc4e6217ca` |
| Web immutable image | `sha256:8af58721ef4c43b8d7dd2a12eb2c729b63918350f0bdaadc75c09d6aebe3338e` |
| Migration | `caseops-migrate-job-m6rn4`, completed successfully in 13.14 seconds on the exact API digest |
| API revision | `caseops-api-00281-9bt`, 100% traffic |
| Web revision | `caseops-web-00260-mwh`, 100% traffic |
| Scheduler inventory | all six canonical bindings passed on the exact API digest |
| Public identity | `/api/health` returned `{"status":"ok"}` and `/api/build` returned the exact full SHA and API revision |

The first deploy wrapper invocation timed out locally after one second while
its child process continued. A second invocation therefore submitted a
duplicate set of builds for the same clean source SHA. All four builds
succeeded from the same clean source SHA and pushed the same mutable tags, but
the independent builds produced distinct immutable digests. The deployed
revisions and migration used the exact serving digests recorded above; no
different source was deployed:

- API builds `6eeadfa4-85d0-40a3-930a-b352d7676b5b` and
  `362c4b3f-7fd2-47d5-b3b6-a28cfbf9b6e6`; their digests were respectively
  `sha256:bb64c601b9fc49010e3039f12e8117fb7ccf47da2e650738179ae5738b403f38`
  and the serving `sha256:91497eb798a7451490bdc216c245f80a74f2528251660fcd7369d5dc4e6217ca`.
- Web builds `21abb64d-47f7-4668-81c3-a7a108424b81` and
  `08e4891a-9069-46a6-816b-651703667473`; their digests were respectively
  the serving `sha256:8af58721ef4c43b8d7dd2a12eb2c729b63918350f0bdaadc75c09d6aebe3338e`
  and `sha256:ce65b0d77416532cb43b840bb60d6efb67fdb44e16f000acec903200a31eb51a`.

This slice has no schema migration. Running the canonical migration job still
proved that the deployed application image and current single Alembic head
converged before the new revisions received traffic.

## Focused production acceptance

The unchanged focused case at
`tests/e2e/ram-2026-08-11-prod.spec.ts:334`, “IPLF-026B production previews,
grants, and revokes independent IP access at 360px”, passed in 27.0 seconds
against the exact serving SHA. It proved the responsive preview/apply/revoke
workflow and persistence using the dedicated synthetic IP QA fixtures. This
is valid scoped evidence for the implemented workflow, but it cannot override
the red complete-suite release gate.

## Complete production gate failure

Push-triggered workflow `31565070270` checked out the exact serving SHA and
recorded API `caseops-api-00281-9bt` and web `caseops-web-00260-mwh`. Its
RAM/IP phase ended with 65 passed, 4 documented conditional skips, and 3
failed. The Notice phase was skipped because the preceding phase failed.

All three failures were recommendation probes and returned HTTP 503. The
second failure below explicitly recorded the sanitized problem type
`llm_quota_exhausted` and its statement that no output was saved; the run log
did not print the other two response bodies:

1. `tests/e2e/ram-batch-2026-04-26-prod.spec.ts:1170` could not measure the
   citation-grounding rejection rate without a model result.
2. `tests/e2e/recommendations-grounding-2026-04-29-prod.spec.ts:170` could not
   prove HTTP 200, recommendation options, or at least one verified citation.
3. `tests/e2e/recommendations-grounding-2026-04-29-prod.spec.ts:436` ended with
   HTTP 503 during its bounded HNSW-path probe.

The failure report is GitHub artifact `9129590611`, named
`prod-playwright-report`, with digest
`sha256:bb58312e01da2f8a1c81cf0f0dec6b3c2d7623ccc7d649acab31223038f89da4`.

Production is configured to use OpenAI and the recommendation override
`gpt-5-mini`. No authorized, production-safe alternate provider is configured,
and test-only providers cannot satisfy a live cited-recommendation gate. The
captured typed response demonstrates that the endpoint failed closed rather
than saving ungrounded output.

## Blocker, safe fallback, and next work

- **Blocker:** `IPLF-026B-PROD-GATE-31565070270`.
- **Owner/action:** the production AI provider/account operator restores
  available quota/credits for the configured CaseOps OpenAI project and
  verifies its configuration; Engineering/QA then reruns the unchanged
  exact-release workflow with expected SHA
  `d97969d1ac8e6cf9da0418f534349257ba487393`.
- **Required evidence:** the complete RAM/IP phase and dependent Notice phase
  pass on that exact serving revision, including a real recommendation with a
  verified citation.
- **Safe fallback:** retain the sanitized `llm_quota_exhausted` 503 and save no
  output. Do not weaken release assertions or change provider/cost ownership
  merely to obtain a green workflow.
- **Impact:** IPLF-026B, parent IPLF-026, and M2 release closure remain blocked;
  implementation and focused verification remain valid.
- **Independent continuation:** proceed with IPLF-027A repository foundations
  behind disabled controls while preserving this production-wide blocker.

Named legal, security, pilot, and UAT acceptance and the M0 human program lock
also remain pending.
