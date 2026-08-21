# IPLF-039C Calendar Reconciliation Evidence - 2026-08-20

## Truth status

- Repository implementation commit: `5af8f032747ca439ae69e8135bf1b6f71f4b6330`.
- Scope verified locally: the UJ-62-EXC-03 provider-snapshot and reconciliation-candidate increment.
- Full IPLF-039C remains `in_progress / not_run / blocked`. This increment does not close UJ-59, hosted CI, live OAuth-provider verification, deployment, or dated production acceptance.
- No provider credential, event identifier, title, body, attendee, or location is stored in this evidence.

## Implemented behavior

- Moved, missing, cancelled, and unreadable projected events are distinguished. Unreadable remains `unknown`, never `matches`.
- Every actionable finding persists an immutable, content-minimised candidate tied to the exact CaseOps projection generation and provider observation hash.
- Candidate listing is bounded and access-filtered in SQL. Restricted docket evidence is not disclosed through the reconciliation endpoint.
- An IP approver with recent step-up can record review evidence. A rejection never imports the provider date into the CaseOps obligation.
- A Google moved-event restore carries the reviewed Event ETag to the worker as `If-Match`. A `412` returns the sync to a safe reviewable state and never overwrites the later provider edit.
- Missing, cancelled, unknown, and unversioned observations cannot queue an automatic provider write. Microsoft Graph drift remains reviewable but has no automatic restore because the documented event-update contract does not expose a verified conditional update.
- Candidate snapshot identity and evidence fields are database-immutable on PostgreSQL; decisions are terminal; candidate parents are retained; repair-claim fields are all-or-none.
- A read-only OAuth sandbox verifier is available as `caseops-verify-calendar-provider-sandbox`. It hashes event identifiers and emits no token or calendar content.

## Local verification

| Verification | Result |
| --- | --- |
| Calendar, sandbox-verifier, and manifest focused bundle | `52 passed` |
| Calendar/offboarding/coverage/control-review API owner bundle | `175 passed, 3 skipped` |
| PostgreSQL 17 + pgvector full validation | `94 passed` |
| Complete web suite | `129 files, 662 passed` |
| IP docket reconciliation component | `21 passed` |
| Web TypeScript typecheck | passed |
| Next.js production build | passed |
| Ruff, `uv lock --check`, Alembic single head, `git diff --check` | passed |

The three skipped API cases are pre-existing environment-dependent tests in the broader owner bundle. PostgreSQL verification used an ephemeral `pgvector/pgvector:pg17` container and the container was removed after the run.

## Remaining work

1. Complete UJ-59 exception annotation/resolution evidence, second-reviewer and multiple-signature policy, reviewer sampling, and subsequent-delta linkage.
2. Run the read-only verifier against both real OAuth sandboxes. Separately prove or reject a guarded Microsoft Graph event-update mechanism before enabling Outlook automatic restore.
3. Push the exact candidate and pass hosted CI, including `postgres-validation`.
4. Merge through normal review, deploy the exact merge revision, and capture dated production acceptance. No production claim is made here.

## Parallel ownership

- Claude remains assigned to `IPLF-028A/IPLF-028B evidence` on `docs/iplf028a-evidence-20260820`.
- Claude remains assigned to `IPLF-039F` IP cost-item/billing work on `feat/iplf039f-cost-items-20260820`; that lane was not modified by this increment.

