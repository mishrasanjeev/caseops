# IPLF-039C UJ-59 Control Review Evidence - 2026-08-21

## Truth status

- Repository implementation commits: feature `3082506368c8c34807a14d89ffe04f573f7129c8`; final schema-index head `b47724a8171576be9f74f8d5677cdce2a7f10731`.
- Scope verified locally: UJ-59 daily docket control report exception decisions, independent reviewer sampling, two-role signatures, immutable manifest binding, accessible report history, and signed-report deltas.
- Together with the previously recorded UJ-62-EXC-03 increment, the known IPLF-039C repository implementation gap is closed.
- IPLF-039C release remains blocked. Live Microsoft Graph and Google OAuth sandbox verification, hosted exact-candidate CI, exact deployment, and dated production acceptance have not been completed by this record.
- No provider credential, event identifier, docket title, privileged annotation, or client content is copied into this evidence.

## PRD mapping

| UJ-59 contract | Implemented proof |
| --- | --- |
| Dated reproducible report with filters, timezone, freshness, hidden restricted policy, included IDs and hashes | Snapshot schema v2 binds the query contract, review policy, freshness state, included record hashes, exception identities, predecessor, and delta into the manifest SHA-256. Legacy schema-v1 snapshots remain readable and verifiable. |
| Manager resolves or annotates every exception | Each frozen exception requires one append-only `resolved` or `annotated` decision with annotation, evidence reference, actor, and timestamp before signing can start. Duplicate or rewritten decisions are refused. |
| Second reviewer samples source, calculation, and coverage | A reviewer distinct from the preparer records append-only sample evidence against an included docket. The required sample count is policy-bound and final reviewer signature is refused until satisfied. |
| Both reviewers sign the immutable report | Sequence 1 is the preparer; sequence 2 is a different reviewer. Every signature stores the exact manifest hash, role, attestation, actor snapshot, and timestamp. Tenant-correlated and exact-manifest foreign keys enforce the boundary on PostgreSQL. |
| Later changes appear as a delta | A newly generated report links to the latest accessible comparable signed predecessor and records added, removed, changed, and unchanged record IDs without mutating the predecessor. |
| Restricted records never leak | Fetch, history, decision, sample, sign, and export authorization checks include both visible report records and excluded mandatory-exception docket IDs. An inaccessible record causes the whole report to disappear rather than leaking a count. |
| Stale or failed data blocks clean sign-off | Existing completeness and failed-export guards remain enforced. Export cannot be regenerated after signing starts, and a failed export never completes the review. |
| Retained under policy | Review policy, decisions, sample evidence, signatures, predecessor identity, and delta are persisted. PostgreSQL triggers prevent update/delete of evidence and mutation of frozen parent fields; parent deletion is restricted. |

## User journey proof

1. A docketing manager creates a clean standalone docket and generates the dated control report.
2. The manager records a disposition and evidence reference for every frozen exception.
3. The manager generates the export, verifies the manifest, and adds the preparer signature.
4. The manager signs out; an independent administrator signs in.
5. The reviewer opens the report from the accessible history archive, records source/calculation/coverage sample evidence, and adds the second signature.
6. The signed manifest downloads with `2/2` signatures and reviewer-sample evidence.
7. A later report selects the signed predecessor and publishes a delta while preserving the old manifest.

## Negative and security proof

- A preparer cannot record independent sample evidence.
- A reviewer cannot sign first, reuse the preparer's identity, or add the final signature without the required sample.
- Stale optimistic versions are rejected for decisions, samples, exports, and signatures.
- Restricted included records and restricted exception-only records make a report unavailable; history omits it as a whole.
- Direct PostgreSQL attempts to alter parent manifest fields, alter/delete child evidence, use a cross-tenant signer, bind a signature to a different hash, violate policy bounds, or delete the retained parent fail closed.
- Client-side rendering escapes report and evidence content before generating the downloadable manifest.

## Local verification

| Verification | Result |
| --- | --- |
| Control-review API, OpenAPI quality, and route-coverage bundle | `17 passed` |
| Docket control-review component and manifest renderer | `32 passed` |
| Independent two-user Playwright journey and docket regression | `2 passed` |
| PostgreSQL 17 migration plus UJ-59 immutability/tenant test | `2 passed, 93 deselected` |
| Fresh SQLite migration from base through `20260821_0002` | passed |
| Data-governance, migration-order, projection, and foreign-key index gates | passed; focused schema/migration rerun `5 passed` |
| Ruff, web TypeScript typecheck, Alembic single head, and `git diff --check` | passed |

The first PostgreSQL invocation used only `CASEOPS_TEST_POSTGRES_URL`; Alembic deliberately reads `CASEOPS_DATABASE_URL`, so that harness attempt timed out against the repository default before reaching a migration or assertion. The corrected isolated run set both variables and passed. The disposable PostgreSQL container and SQLite file were removed.

## Remaining release work

1. Run the read-only verifier against real Microsoft Graph and Google OAuth sandboxes. Keep Outlook automatic restore disabled unless a guarded conditional-update contract is separately proved.
2. Push the exact candidate and pass every required hosted check, including `postgres-validation`, security, and generated-client drift.
3. Merge through normal review, deploy the exact merge revision, and capture dated production acceptance. No deployment or production claim is made here.

## Parallel ownership

- Codex owns `IPLF-028A/IPLF-028B` evidence; `docs/iplf028a-evidence-20260820` is retained only as historical branch provenance.
- Codex owns `IPLF-039F` cost-item/billing work; `feat/iplf039f-cost-items-20260820` is retained only as historical branch provenance.
- Neither Claude-owned lane was modified by this increment.
