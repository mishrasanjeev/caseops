# IPLF-027A case-tracking production follow-up - 2026-08-14

## Verdict

The dated exact-release production workflow `31797818564` reran the same
case-tracking canary that had failed in workflow `31661191199`. Against exact
serving revision `52cb925d3dacd74890b607208588d95fb6000473`,
`tests/e2e/ram-2026-08-05-prod.spec.ts:358` passed in 10.3 seconds: the approved
QA case freshened and its protected source opened at 360 px. This is sufficient
to remove the historical IPLF-027A case-tracking-provider blocker.

This is not a green complete-production result. The RAM/IP batch finished with
`70 passed`, `3 failed`, and `3 skipped`; the Notice batch finished with
`2 passed`. All three failures were live recommendation/citation tests receiving
the existing typed OpenAI quota-exhausted response. The separate AI quota
blocker therefore remains open, and `PROGRAM INCOMPLETE` remains the only
accurate program state.

## Exact lineage and serving identity

| Control                         | Exact result                                                                                                                                                                                                                 |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Canonical main                  | `52cb925d3dacd74890b607208588d95fb6000473`, merge commit for PR #224                                                                                                                                                         |
| Exact-main CI                   | [31797818533](https://github.com/mishrasanjeev/caseops/actions/runs/31797818533) passed all ten API coverage shards, aggregate API coverage, PostgreSQL + pgvector, web typecheck/Vitest/build, and the Playwright app suite |
| Exact production workflow       | [31797818564](https://github.com/mishrasanjeev/caseops/actions/runs/31797818564), completed at `2026-08-14T17:44:08+05:30`                                                                                                   |
| Exact checkout and release wait | The workflow fetched and checked out full SHA `52cb925d3dacd74890b607208588d95fb6000473`, then verified that exact serving SHA before running Playwright                                                                     |
| API                             | `caseops-api-00291-62b`, 100% traffic, immutable digest `sha256:c09eb2bf26b0af10ed9d4b8fdf692c9995d41c8e2282ce765617436ef0707684`                                                                                            |
| Web                             | `caseops-web-00269-pxc`, 100% traffic, immutable digest `sha256:31b90db5f8f4afd0ce4e55865ad7356004e018410d1027b8644f6411d0d33025`                                                                                            |
| Migration                       | `caseops-migrate-job-6wsx4`, successful                                                                                                                                                                                      |
| Case-tracking canary            | `ram-2026-08-05-prod.spec.ts:358` passed in 10.3 seconds against the approved production-QA fixture                                                                                                                          |
| Complete production result      | RAM/IP `70 passed, 3 failed, 3 skipped`; Notice `2 passed`; only the three OpenAI-quota failures remain                                                                                                                      |

## Scope and safety boundary

- The canary used the approved synthetic production-QA case and the existing
  protected-source workflow. It does not establish a general provider SLA or
  authorize an unreviewed replay against client matters.
- No case-tracking assertion was weakened or skipped to obtain the pass. The
  exact dated spec that previously reported HTTP 409 passed against the exact
  serving release.
- Historical August 13 evidence remains historically correct for its release.
  This later descendant-release evidence resolves only the case-tracking
  condition; it does not rewrite the earlier record.
- The three quota failures remain visible. No synthetic recommendation,
  provider switch, quota waiver, or named human acceptance is inferred.
