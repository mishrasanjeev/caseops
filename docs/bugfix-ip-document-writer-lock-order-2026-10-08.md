# IP Document Writer Lock Order - October 8

## Scope And Verdict

This is the independent audit checkpoint before candidate commit. Later
release evidence belongs to `docs/bugfix-patent-source-deadlock-2026-10-08.md`
and the owning release PR; the checkpoint below is not a live deployment label.

Verdict: **Inconclusive for production closure**. This is a locally verified,
uncommitted adjacent-path candidate. Production mutations, commits, deployment,
and production Playwright were explicitly outside this task.

Worktree: `C:/Users/mishr/.codex/worktrees/google-oauth-refresh-recovery/CaseOps`.
Branch: `codex/document-processing-lock-order-20261008`.
Base HEAD: `b20f86bddeecf985fc961012bb93fa2c41889c49`.

The supplied production incident at that release is retained in
`.tmp/calendar-oauth-20261008/patent-correction-cloudsql.json`. Its October 8
02:54:46 UTC deadlock identifies patent correction waiting for the document
version while the indexing worker waits for Company authority. This task owns
only the adjacent interactive document link/state writers. The worker and
`tests/test_ip_patent_postgres.py` are owned by the other agents and were not
edited here. Related incident/release tracking remains in
`docs/bugfix-patent-source-deadlock-2026-10-08.md`.

## Root Cause And Narrow Repair

`add_ip_document_links` locked `IpDocument`, created links, then propagated a
private access event that acquired Company. `transition_ip_document_state`
locked `IpDocument` and `IpDocumentVersion`, then propagated a source event that
acquired Company. Both invert patent correction's Company-before-source order.

The five-line production change is in
`apps/api/src/caseops_api/services/ip_document_workflow.py`, inside
`_document_or_404(for_update=True)`: acquire the existing
`lock_private_authority_writer` before the source SELECT FOR UPDATE. This uses
the canonical Company `FOR NO KEY UPDATE OF companies` fence, not a new lock
implementation. The lazy import preserves the existing module dependency shape.
There are no new commits, retries, timeout changes, intermediate transaction
boundaries, or changes to capability, target ACL, terminal lifecycle, version,
state-transition, source hash, or projection-event policies.

### Adjacent-Path Inventory

| Path | Audited ordering / result |
| --- | --- |
| Add document links | New shared tenant fence precedes document lock and link flush. |
| Transition document state | New shared tenant fence precedes document and version locks. |
| Upload document | Existing name allocator already locks Company before document/version insertion. Unchanged. |
| Upload replacement version | Existing allocator already locks Company before document/version locks. Shared hook is a same-transaction reacquisition. |
| Bulk rename/taxonomy apply | `_bulk_material` already takes Company before sorted document/version locks; apply also uses the shared hook. |
| Patent disclosure source linking | `_lock_sources_and_dockets` already takes canonical authority before actor, docket, document and version locks, before direct `_create_link` / propagation. Unchanged. |
| Reads, policy lookup, download | Do not request `for_update`; no new tenant fence. Explicit patent-history read allowance remains read-only. |
| Indexing worker | Separate agent ownership; no worker changes or worker-regression claims from this task. |

## Deterministic PostgreSQL Evidence

New normally discovered file:
`apps/api/tests/test_ip_document_workflow_postgres.py`.

Four overlap cases cover links/state with autoflush disabled/enabled. The real
patent correction transaction holds Company while the competing document writer
starts. `pg_stat_activity` and `pg_blocking_pids` establish that the writer is
waiting for that transaction's Company fence. While the same fence remains held,
NOWAIT probes require both source rows to remain available. The real correction
then pins the exact source and commits, followed by the real document mutation.
Fresh reads assert both outcomes, the original immutable patent version, source
hash, document state/links, and exactly one applied document projection event.
Read-only document access is also exercised while Company remains locked.

Ten additional PostgreSQL cases cover both writers against stale document
version, missing document-management capability, actual lifecycle closure,
revoked source grant, and an independently seeded foreign-tenant context. Rejections
retain document/version/link state and create no projection events. Two complete
existing HTTP journeys are also replayed on isolated PostgreSQL: version/state/
approval and duplicate-document/link reuse.

The database was a fresh dedicated `pgvector/pgvector:pg17` container named
`caseops-oct08-ip-doc-workflow-pg`, bound only to `127.0.0.1:55490`, database
`ip_document_workflow_test`. The other agent's port 55489 was never used.
PostgreSQL reported 17.11; Alembic head was `20260928_0001`. Image identity:
`sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`.
HTTP fixtures independently migrated their connection-disabled template and
cloned only that template. Cleanup left zero HTTP/template databases and zero
other sessions; the task's container was stopped after verification.

All following artifacts are retained under `.tmp/ip-document-lock-20261008/`.
Every executed run has an exclusive structured journal (`.jsonl`) and JUnit
(`.xml`), with a completion event and all setup/call/teardown phases reconciled.

| Artifact stem | Collected | Passed | Failed | Skipped | Phase reports | Exit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline-01` | 4 | 0 | 4 | 0 | 12 | 1 |
| `fixed-01` | 4 | 4 | 0 | 0 | 12 | 0 |
| `expanded-01` | 16 | 16 | 0 | 0 | 48 | 0 |
| `targeted-01` | 50 | 50 | 0 | 0 | 150 | 0 |

Each of the four baseline failure details was inspected separately: all failed
at the document NOWAIT probe with PostgreSQL `LockNotAvailable`, proving the
Company waiter retained the source lock. Setup and teardown succeeded in each
case. These are lock-order invariant reproductions, not fixture failures and
not claims of four newly emitted deadlock diagnostics. The unchanged original
four-case replacement inventory passed before the test file was expanded.
Failed evidence was not overwritten.

`discovery-01.jsonl` records normal root discovery using
`python -m pytest --collect-only -m postgres -k test_ip_document_workflow_postgres`:
16 selected from 5,828 collected. Its exact identity set matches all 16 new-file
cases executed in `targeted-01`. The collection-only XML is not execution proof.

The final targeted inventory was reconciled against all five intended files:

- `test_ip_document_workflow_postgres.py`: 16.
- `test_ip_document_workflow.py`: 6.
- `test_ip_document_foundation.py`: 6.
- `test_ip_patent_families.py`: 20.
- `test_private_authority_lock_postgres.py`: 2.

The final run took 81.36 seconds; warnings were the existing Starlette TestClient
and SQLite datetime deprecations. Ruff and scoped `git diff --check` passed.
No complete repository, Docker application, CI, or deployed-browser gate is
claimed. All provider-capable HTTP fixtures used deterministic local settings
and the no-paid-provider marker.

## Tested File Fingerprints

SHA-256 of final files, unchanged across the final targeted run:

- `apps/api/src/caseops_api/services/ip_document_workflow.py`:
  `b3a6391ad28be33f6b8e1459b91acedca59ed2fa4ecdb4799982bbb39d7ddaa2`.
- `apps/api/tests/test_ip_document_workflow_postgres.py`:
  `60e533a8e9af5d24a9126ad1633b10d8edeb93717ffb50bdbc91564ec386eb9f`.

## Remaining Release Work

The owning release task must combine the independently owned worker repair,
run its full exact-candidate gates, publish through canonical main, and rerun
the dated production patent journey before closing the production finding.
This handoff does not authorize production mutations or claim that the serving
release contains the adjacent-path change.
