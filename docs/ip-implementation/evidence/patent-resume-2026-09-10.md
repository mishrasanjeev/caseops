# Patent Track Resumption, 2026-09-10

Overall: **Partially implemented; not complete. Release verdict: NO-GO.**
This report does not close IPLF-079A/B or IPLF-080A/B. No commit, push,
production call, deployment, provider spending or canonical-candidate edit
was performed. The parent owns integration, September 10 bugs and deployment.

## Scope And Identity

- Worktree: `C:/Projects/CaseOps/caseops/.worktrees/codex-patent-closure-20260909`.
- Baseline: `5145fb3a4b51b26af116220ff10a7389bde6324d`.
- Migration `20260909_0004` remains reserved and unchanged. Integration must
  preserve its additive/restore-forward contract and reconcile its predecessor.
- Read retained handoff, worktree AGENTS, PRD-execution/bug-fixing skills,
  unified PRD, all five status ledgers, program manifest and patent child PRD.
- Mapping: PAT-01..04, IP-SCOPE-01..10, UJ-29/39/40, shared UJ-60/61,
  M02/M08/M13/M14. Original milestone and journey scope is not narrowed.
- This resumption changes two patent test files and three patent evidence
  files. Previously implemented product files are unchanged. The September 09
  checkpoint manifest still matches every product file, client and browser spec.
  Its handoff markdown has a later historical update; it was not rewritten here.

## Retained Attempts

Original evidence remains at `C:/tmp/caseops-patent-closure-20260909`.
New evidence is in this worktree's `.tmp/patent-resume-20260910`.
`patent-reconcile.ps1` generates create-new-only JSON containing complete
historical failure details, source hashes, Docker state/logs, every replacement
phase and exact old-to-new node reconciliation. Progress dots are not diagnoses.

| Attempt | Reconciled outcome |
| --- | --- |
| `patent-focused-01` | 28 passes, two inspected call failures: invalid `draft` reopen target and a duplicate-upload fixture expecting a new source. Neither is a successful product-bug reproduction. Corrected existing fixtures pass in `resume-01`. |
| `patent-pg-01` / `patent-pg-02` | Completed 41/43-pass historical runs, no failed phases. They are not additive to the new inventory. |
| `patent-pg-03` | 351 retained phase rows, 117 complete passing observations, no failure or completion event. Container exited 255 at Docker restart, not OOM. No collection event was retained under xdist, so the exact unfinished node cannot be inferred. Remains interrupted; its 12-module selection is replaced by `resume-01`. |
| First web runner | Unsupported BusyBox `tar --null`; setup failure, no passing browser assertion. Existing corrected inventory conversion produced the later complete web runs. |
| `web-patent-draft-fail01` | Six reported passes from a premature assertion; explicitly not accepted as a regression reproduction. |
| `web-patent-draft-fail02` | Inspected real draft-loss reproduction: a failed background read unmounted the hydrated form. Retained fix preserves the draft; historical `web-patent-final02` and fresh `web-resume-03` pass all 16 tests. No new frontend change in this resumption. |
| Browser final01 / final02 | Missing root TypeScript config, then zero selected tests. Both incomplete setup attempts. |
| Browser final03 | Three separately inspected strict-locator collisions between saved status and offline banner. Scoped work-product status is retained. |
| Browser final04 | Three separately inspected global alert-count failures. |
| Browser final05 | Two passes; tablet failure from the framework route announcer. Retained correction checks application-content alerts, without dropping product error assertions. |
| Browser final06 | All three individual timeout records inspected: mobile post-reopen replay, tablet post-close replay, desktop retained-event read. Different late operations do not establish one API root cause. Historical trace/storage diagnosis and failed artifacts remain retained. |
| Browser final07 | Three complete historical passes at 393/768/1280px with the same assertions, 120-second budget, one worker and zero retries. Container-local capture storage was the only final runner change. This is historical unchanged-product evidence, not a fresh September 10 browser run. |
| Historical lint attempts | Full logs retained: formatting/line-length findings and read-only Ruff cache failures. Runtime-inventory exit 2 is a tool probe, not a test verdict. Current focused Ruff check and whitespace check pass. |

Stopped historical API/web processes are servers, not failed pytest runs;
their exits do not create test passes. No old container or evidence was deleted
or restarted. In particular the interrupted PostgreSQL namespace was not reused.

## Fresh Verification

The new PostgreSQL container starts from an independent empty database, with
network `none`, 0.25 CPU and 512 MiB. One serial test container joins only that
network namespace, capped at 0.75 CPU and 1,536 MiB. Combined limit is exactly
1 CPU / 2 GiB; there is no parallel heavy patent gate. No published ports,
external network, paid-provider calls or shared-application database cloning.

`patent-resume-tests.sh` snapshots the complete Git-selected source and root
fixtures, records archive and per-file SHA-256, independently migrates the
base database, and invokes `-n 0 -p tests.retained_results` with
`CASEOPS_TEST_RESULT_JOURNAL`. Collection and setup/call/teardown results are
flushed as they occur. Existing journal/XML names are refused. A 30-minute
outer bound plus 90-second diagnostic stack dump prevents a silent day-long
wait; neither changes a product deadline or converts interruption into success.
HTTP fixtures retain their separately migrated, connection-disabled template;
dedicated migration rehearsals still start independently fresh.

- `resume-01.jsonl` / `resume-01.xml`: **210 passed**, zero skips/errors/failures,
  630 complete phase reports, collection and session-finished exit 0,
  549.279 seconds. Exact 12-module replacement for the interrupted `pg-03`.
- `resume-02.jsonl` / `resume-02.xml`: **51 passed**, zero skips/errors/failures,
  153 complete phase reports, collection and session-finished exit 0,
  135.344 seconds. Includes all updated prosecution tests and all 25 catalogue
  cases. All six added test identities passed, including both PostgreSQL races.
- The two completed runs cover **216 distinct identities** (65 PostgreSQL,
  151 other backend tests), not 261 different tests. This is composed evidence:
  the second snapshot contains only test/evidence additions, no product change.
- Source archives: `resume-01-source.tar` SHA-256
  `40496404ea541cef936cf09d61eeed99666bc0facf260dc1851c77cadfa8746a`;
  `resume-02-source.tar` SHA-256
  `d837ccb9d9eb332c5313e35c9d2c2582e9fd161414fd541f012c38b02899c482`.
- `web-resume-03.xml`: **16 passed**, zero skips/failures/errors across the
  application workspace, prosecution workspace and strict nested client schema.
  TypeScript passed (`typecheck-resume-03.log`, empty successful output).
  PostgreSQL was stopped first; this separate network-none container was capped
  at 1 CPU / 2 GiB, with one Vitest worker. This is frontend unit acceptance,
  not a Playwright or production replay.
- Focused Ruff check covers domain catalogue, model/schema/service, reserved
  migration and all three focused test modules. Passed. `git diff --check`
  passed; existing LF/CRLF warnings are not whitespace failures.

One non-test formatting invocation encountered the inherited read-only cache
path; the task's tool output retains that diagnostic. The explicit
`ruff format --no-cache` replay and complete focused `ruff check --no-cache`
passed. This did not interrupt, skip or change any pytest gate.

`resume-01` includes all prior patent family/application/party/priority/domain
tests, deterministic lifecycle races, 10,000-application/1,000-family graph
bounds, 500-edition history bounds, independent migration roundtrips and
source-preserving downgrade refusals. It is a focused patent inventory, not
the full repository PostgreSQL or Docker acceptance gate.

## New Regression Coverage

- `test_every_patent_document_kind_retains_exact_source_and_edition_history`:
  every schema-admitted document kind, original/replacement lineage, immutable
  source hash, replay and persisted historical read. Runs on SQLite and PG.
- `test_every_admitted_prosecution_event_preserves_sibling_and_audited_history`:
  all ten admitted events, saved phase readback, exact receipt replay,
  unchanged independent sibling detail/history, one audit per event, explicit
  close/reopen before restoration and retained earlier events. No deadline or
  legal acceptance is inferred. Runs on SQLite and PG.
- `test_different_actor_closure_wins_waiting_patent_prosecution[False/True]`:
  deterministic PostgreSQL create/replay overlap with a different actor's
  closure. Verifies terminal state, unchanged work sequence/phase and no late
  event insertion. Existing manifest race identities and assertions remain.

All new tests above passed. UJ-39-EXC-01 now has explicit unchanged sibling
detail/history assertions for every admitted event; its complete browser journey
is still not certified. UJ-39-EXC-02/PAT-04 now cover every admitted document kind
on both databases; complete prepared/filed/granted role UX remains separate.

## Requirement Status

Statuses below cover whole requirements, not only passing subsets. Detailed
original 19-path matrix remains in `patent-closure-2026-09-09.md`.

| Requirement | Status and remaining gap |
| --- | --- |
| IP-SCOPE-01 | Partial. Intake/full-workflow separation and promotion denial verified; full patent qualification is not implemented. |
| IP-SCOPE-02 | Partial. Patent-specific records and admitted event/document kinds exist; proceeding, fee, obligation and completion semantics still missing. |
| IP-SCOPE-03 | Partial. Canonical source/document/access/lifecycle/audit/idempotency owners retained; task/deadline/instruction/cost/notification/title adapters missing. |
| IP-SCOPE-04 | Partial. Exact declared office/jurisdiction gates verified; operative patent rule execution and unsupported-office browser acceptance open. |
| IP-SCOPE-05 | Partial. Current patent backend inventory verified; contested, transfer, maintenance and combined full browser/release journeys open. |
| IP-SCOPE-06 | Not implemented for patent calculation. Five distinct source-fixture checks fail closed; operative rule adapters, executable fixtures and confirmed-obligation update preservation remain missing. |
| IP-SCOPE-07 | Partial. Independent applications/families and source relationships retained; consolidated cross-right ownership/title/encumbrance reports missing. |
| IP-SCOPE-08 | Partial. Restricted disclosure, legacy-route exclusion, source/current-access checks and backend boundaries verified; complete AI/portal/export/delivery and grant-revocation browser replay open. |
| IP-SCOPE-09 | Partial. Server-owned labels and certificate revocation verified; complete public/reporting/packaging/outage/browser matrix open. |
| IP-SCOPE-10 | Partial. Versioned child contract and fail-closed release checks retained; implementation, legal fixtures, support and integrated exact-release evidence incomplete. |
| PAT-01 | Partial. Intake/parties/priorities/claims/manual prosecution implemented; annuities, assignments and complete family reports missing. |
| PAT-02 | Not implemented. Automatic calculation is explicitly unavailable; that safety fence is not a patent rule engine. |
| PAT-03 | Partial. Ten admitted manual event kinds covered by new tests; separate opposition, refusal/appeal, revocation, compulsory licence, working/annuity, recordal and litigation adapters missing. |
| PAT-04 | Partial. Immutable manifest/edition/event relationships implemented; all document-kind backend tests added. Prepared/filed/granted role comparison, 500 distinct byte-version proof and all-kind browser journeys remain open. |

All four slice statuses remain **Partially implemented**. 079A has a locally
verified catalogue foundation; 079B lacks complete cross-surface qualification.
080A lacks proceeding/obligation/title domain implementation; 080B lacks their
complete operational journeys, imports, reporting and integrated acceptance.
Unavailable legal source packs are a separate activation dependency, not an
excuse for these repository implementation gaps. Those product gaps remain
patent-track work, not reassigned to the parent's September 10 bug scope.

## Integration Package

The generated `.tmp/patent-resume-20260910/handoff-owned-files.json` supplies exact raw SHA-256 and byte
length for every owned file. Shared full-file hashes are identity evidence,
not permission to overwrite parent changes. The retained
`patent-shared-hunks-checkpoint.patch` still passes `git apply --check --reverse`
in this tree and contains only the previously reviewed patent shared hunks.
Use its two model hunks, route additions, domain-catalogue changes and workspace
integration, plus the exact owned new files and updated test files. Do not
copy the deliberately dirty tree or inherited tracking/catalogue/deploy changes.
An identical retained patch is available as `owned-shared-hunks.patch` in the
new evidence directory; SHA-256
`b3c851f5ddcd9176883eaf54abeeab525ae2e7247d118a499314896cba9fc7a6`.
Whole-snapshot hash
comparison found only the two intended test-file changes among the files in
`resume-01`; no inherited product or parent-owned ledger file changed.

Parent integration must regenerate OpenAPI, schema/data-governance projections,
release fingerprints and exact-release domain evidence after combining its
current canonical source. Shared status ledgers and program manifest were
intentionally not edited. Production acceptance remains prohibited here and
must not be inferred from historical or local test results.
