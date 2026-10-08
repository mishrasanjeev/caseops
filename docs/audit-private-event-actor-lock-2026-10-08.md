# Private Event Actor Lock Audit - October 8

Historical baseline: the verdict and diagnostic matrix below describe the
initial tests-only investigation. Subsequent authorized implementation and
expanded successful-serialization coverage are recorded separately in
`docs/audit-private-event-actor-repair-2026-10-08.md`. The original 16-case
journals, lock graphs and pre-repair test copy have not been overwritten.

## Verdict And Boundary

**Not fixed.** Two same-actor deadlocks are deterministically reproduced on
real PostgreSQL, with real service contenders. No runtime repair was made.
This is a separate pre-existing defect, not a falsification of the
Company-before-source-version repair in PR #524.

All writes for this investigation are confined to
`C:/Users/mishr/.codex/worktrees/oauth-workspace-prod/CaseOps`, branch
`codex/private-event-actor-lock-audit-20261008`, HEAD
`506e1479fb257c5218913d9e9345660e8c3d5bc0`. The
`google-oauth-refresh-recovery` checkout, its Docker/CI gates, production,
Git refs and remote branches were not changed. Nothing was committed,
pushed, merged or deployed.

Source context: `docs/bugfix-patent-source-deadlock-2026-10-08.md`;
UJ-29 / PAT-01 / IPLF-080 source corrections and the shared Matter lifecycle
and private-authority boundary. This is not a new patent product feature.

## Reproduction

`apps/api/tests/test_private_event_actor_lock_postgres.py` invokes:

- `run_document_processing_job` and its real IP version indexing/event path;
- `correct_patent_family`, including its explicit actor authorization fence;
- `update_matter` with a title-only optimistic-concurrency request;
- `transition_matter_lifecycle_status` with a genuine Active -> Disposed request.

The 16-case matrix is two IP producers, two Matter mutations, same/different
actors, and production `autoflush=False` / `autoflush=True`. Each fixture has
a real active private generation and non-null, tenant-valid actor provenance.
The Matter is independent of the patent family/document: shared source locks
cannot manufacture this result. Only local document parsing is deterministic
input; no service, lock, event insertion, commit or authorization is replaced.

SQL hooks pause the IP producer after Company acquisition, immediately before
the event INSERT (worker) or explicit Membership SELECT (patent correction).
The real Matter service then acquires its actor and parent fences and reaches
its real Company wait. An observer proves that wait before releasing the IP
producer. It then records reciprocal `pg_blocking_pids`, transaction IDs,
queries and `pg_locks` before PostgreSQL resolves the deadlock. This does not
depend on a sleep establishing the interleaving.

The diagnostic test deliberately remains red for a deadlock. It is not an
xfail, retry, or passing assertion of a failed operation. Its cycle-specific
diagnostic expectations must become successful-serialization assertions when
a repair is separately authorized.

## Exact Graphs

Worker, candidate run `candidate-matrix-r2`, production session / metadata:

```text
PID 153 / xid 1538:
  owns Company FOR NO KEY UPDATE
  INSERT private_projection_events, actor = document uploader (non-null)
  waits for xid 1539 on company_memberships composite actor/company FK

PID 154 / xid 1539:
  owns CompanyMembership FOR UPDATE, User FOR UPDATE and Matter FOR UPDATE
  SELECT companies ... FOR NO KEY UPDATE OF companies
  waits for xid 1538
```

PostgreSQL's producer error is SQLSTATE `40P01`. Its internal constraint
context explicitly identifies:

```sql
SELECT 1 FROM ONLY "public"."company_memberships" x
WHERE "id" = $1 AND "company_id" = $2 FOR KEY SHARE OF x
```

The retained error includes the full PostgreSQL casts/operators and tuple
identity, not just this shortened display. The migrated constraint is
`fk_private_projection_event_actor_company`, `ON DELETE RESTRICT`;
`actor_membership_id` is NOT NULL.

Interactive patent correction, same candidate matrix:
PID 208 waits on PID 209's Membership; PID 209 waits on PID 208's Company.
The producer's blocked statement is the real
`SELECT company_memberships ... FOR UPDATE OF company_memberships` in
`_lock_ip_writer_context`, before any private-event INSERT. Therefore an
event-FK-only repair cannot close the actor/tenant ordering defect.

## Prior Source Versus Candidate

An unmodified Git archive of
`b20f86bddeecf985fc961012bb93fa2c41889c49` was extracted **inside this checkout**.
Only the audit test was copied into it. Pytest ran from that snapshot with
PYTHONPATH pinned to its own `apps/api/src`, using this audit's local venv.
The fixture records resolved source paths and SHA-256 hashes.

The old worker's trace shows its version UPDATE before Company acquisition;
the candidate shows Company before that UPDATE. Nevertheless, both reach
Company -> actor FK, and both reproduce the identical actor cycle. On the
prior source, changing processing fields on an existing version did not
pre-acquire a protective uploader FK lock before the later event insertion.
This is observed SQL ordering, not an assumed effect of the new worker fence.

The prior-source interactive patent correction also deadlocks. Its explicit
Company -> Membership fence predates PR #524. Keep the candidate's 12 runtime
lines and its separate source-version/adjacent-writer tests intact; neither
reverting them nor declaring them a global deadlock fix is justified here.

## Evidence

Owned fresh container: `caseops-actor-audit-20261008-506e-pg`, loopback port
55507, image ID
`sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`.
Independent empty databases `actor_audit` and `actor_audit_prior` each migrated
to `20260928_0001`; neither was cloned from an application or release database.
There were no external provider calls. The fresh venv uses the frozen API
lockfile; Windows required `uv sync --link-mode copy` after a hardlink error.

All paths below are under `.tmp/actor-audit-20261008/` in this checkout:

| Run | Collected | Result | Phases | Completion |
| --- | ---: | --- | ---: | --- |
| `initial` | 1 | 1 actual deadlock; Matter chosen as victim | 3 | exit 1 |
| `candidate-matrix` | 16 | 8 deadlocks; 8 observer-harness failures | 48 | exit 1 |
| `candidate-matrix-r2` | 16 | 8 deadlocks; 8 passing controls | 48 | exit 1 |
| `prior-matrix` | 16 | 8 deadlocks; 8 passing controls | 48 | exit 1 |
| `candidate-repeat` | 16 | 8 deadlocks; 8 passing controls | 48 | exit 1 |

The first matrix's different-actor services returned successfully, but its
observer borrowed a labelled pooled backend and counted its own query as a
pending transaction. Those eight controls were **incomplete**, not passes or
product defects. A dedicated NullPool observer fixed the harness; the entire
16-case inventory was rerun. Original evidence remains unchanged.

Every run has a structured setup/call/teardown journal and JUnit file.
`initial-graphs/`, `candidate-graphs/`, `candidate-r2-graphs/`, `prior-graphs/`
and `candidate-repeat-graphs/` retain full per-case SQL/graphs/errors/readback.
`earlier-run-classification.json` classifies every earlier failure.
`reconciliation.json` verifies the exact ordered 16-node inventory, all 48
phase results, eight reciprocal graphs/40P01s, eight controls, source import
identity, source-write ordering and all per-case cleanup for each final run.
`postgres-final.log` retains PostgreSQL's own deadlock diagnostics.

Producer-victim runs roll back source/family changes; the worker records its
normal failed job rather than leaving it processing. The Matter mutation then
commits, including Disposed/inactive/lifecycle-version persistence. The initial
Matter-victim run retains the unchanged Matter and a successfully indexed
source. Retained successful events have their correct non-null actors and
applied status; generation epoch increments match committed events only.

All futures complete and every final per-case check finds zero pending
transactions/locks. `final-database-cleanup.json` independently records zero
other client backends, zero open transactions and zero prepared transactions
across both owned databases. No other Docker stack was operated on.

## Minimal Complete Repair Recommendation

**Recommendation, not implementation or verified repair:** retain the existing
IP Company-before-source ordering and make the conflicting private-authority
Matter transaction family follow Company -> actors -> lifecycle parents ->
children, with Company -> private generations preserved. Scope this as an
explicit private-authority writer admission contract, not a changed global
assignment helper default or a repository-wide lock-strength edit.

The two reproduced Matter entry points cannot hold Membership while waiting
for Company. Take the existing Company NO KEY UPDATE fence at their outer
transaction boundary with autoflush suppressed, before assignment/actor locks
or any source flush. Retain the existing sorted Membership/User FOR UPDATE
authorization checks, refreshed instances, capability checks and parent locks.
Checking for an active generation before locking is not a durable admission
decision; re-evaluate current authority under the fence.

A complete patch must include the following bounded dependency closure, not
only the two demonstrated calls:

1. Matter create/update/lifecycle paths and their bulk/import callers. Outer
   transactions must enter the order before a helper is called; adding a
   late fence after an outer flush or previously acquired parent is insufficient.
2. Matter document-processing finalization. It currently takes a shared Matter
   lifecycle lock before private propagation. Moving interactive Matter writes
   tenant-first without moving this counterpart creates a Company/Matter cycle.
   Move the worker fence after extraction/embedding I/O but before its existing
   `before_flush` lifecycle callback, then recheck the same operational parent.
3. Other audited Matter-parent -> Company emitters: portal KYC and Matter client
   verification, plus linked-docket lifecycle/access writers. Reconcile those
   callers before choosing a shared local admission helper. They are **source
   audit findings, not additional reproduced failures** in this report.
4. Preserve the already ordered patent/source writers. Patent identity advisory
   locks still precede Company, so an advisory waiter must not own Company.
   Keep the new source-version fix and test it jointly with this actor repair.

This is the smallest defensible *complete ordering design* identified here;
the exact implementation/caller closure requires its own validation before
editing runtime. Changing only the worker, only event insertion, or only the
Matter worker is incomplete. A bounded clean pre-write NOWAIT acquisition
protocol is a possible alternative where transaction-entry ordering cannot be
made uniform, but would need its own entire-transaction release/revalidation
design; do not retrofit rollback/retry around already dirty/flushed state.

## Security And Acceptance

- Keep the actor FK non-null, tenant-composite and RESTRICT. No sentinel actor,
  null provenance, missing event, deferred invalidation or early event commit.
- Provenance is not authorization: an uploader's retained identity does not
  automatically authorize a worker, and an inactive historical uploader must
  not silently become a new interactive-authentication requirement. Preserve
  each worker's existing authority and lifecycle rules explicitly.
- NO KEY UPDATE on all Membership/User locks is not a complete answer. It can
  unblock FK KEY SHARE but still conflicts with the patent's explicit actor
  fence. KEY SHARE alone is not a substitute for a capability/revocation fence.
- Preserve source bytes/hash/version, job/event atomicity, tenant isolation,
  current ACL checks, terminal-state immutability, source tombstones and private
  generation epoch checks. Never solve this with a mutation retry or a 503 test.
- Before accepting any repair, force same-actor worker and interactive patent
  overlap with metadata and disposal in both acquisition orders and both
  autoflush modes; require both services to complete, plus different-actor
  controls. Prove the Company waiter owns no later actor/source lock.
- Add real Matter-worker/upload/disposal and portal/client/linked-docket races,
  current-actor revocation and user disablement, stale versions, cross-tenant
  actor rejection, and exact non-null historical actor retention. Recheck the
  existing source-version races and advisory/idempotency waits together.

No global deadlock closure, repair acceptance, production reproduction, CI
result, or change to the main release decision is claimed by this audit.
