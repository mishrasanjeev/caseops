# Private Event Actor Ordering Repair - October 8

## Scope And Status

Local, uncommitted repair in the separate checkout
`C:/Users/mishr/.codex/worktrees/oauth-workspace-prod/CaseOps`, branch
`codex/private-event-actor-lock-audit-20261008`, base
`506e1479fb257c5218913d9e9345660e8c3d5bc0`.
No production action, commit, push, merge, release-checkout edit or release
Docker operation was performed by this audit owner.

This follows the baseline in `audit-private-event-actor-lock-2026-10-08.md`
and the PR524 source-order investigation in
`bugfix-patent-source-deadlock-2026-10-08.md`.
Product mapping remains UJ-29 / PAT-01 / IPLF-080, private authority and Matter
lifecycle integrity; no new product capability or authorization policy.

**Owned local repair verified:** the complete replacement PostgreSQL inventory
passed 182/182, with all 546 setup/call/teardown records and a completion event;
the final document-worker unit file passed 7/7. All 162 owned structured race
graphs have complete cleanup, zero database errors and no open transactions.
Twelve owned runtime/test source hashes were unchanged across the final PG gate.
Upload/quota runtime and the existing Notice regression are now owned by main,
with independent PostgreSQL at port 55521. Their acceptance is not inferred from
this owner's worker results. Combined review/release acceptance remains separate.

## Ownership And Call Chain

Runtime files owned by this audit:

- `services/matter_write_fence.py`: new explicit scoped boundary, no global defaults.
- `services/matters.py`: primary create, metadata update, lifecycle transition only.
- `services/document_jobs.py`: Matter and IP document finalization.
- `services/matter_bulk_updates.py`: preview/apply, including savepoint admission.
- `services/matter_imports.py`: outer claim and every per-row transaction.
- `services/assistant_actions.py`: confirmation before actor/command locks.
- `services/ip_watch.py`: handoff before actor/docket and nested Matter creation.
- `services/intake.py`: direct Matter creation/promotion before source writes.

All paths above are under `apps/api/src/caseops_api/`.
Main later owns the attachment upload/finalization range in `matters.py`;
this owner did not modify that function or `storage_governance.py`.
Galileo owns private retrieval normalization; Kepler owns client/portal
emitters; Fermat owns the named IP workflow admissions. Their edits were not
reverted or included as work performed by this owner.

Direct routes call the primary Matter services. Bulk preview reaches mutation
validation inside savepoints; apply repeats validation, and access-denial audit
can commit, so admission is repeated before mutation/savepoint entry. Import
commits its claim and individual rows, requiring fresh admission each time.
Assistant confirmation already owns actor and command locks before its nested
update unless admitted at the outer boundary. Watch handoff likewise owns IP
actor/docket locks before nested creation. Intake directly constructs Matter
and emits a private source event without calling `create_matter`.

`auto_link_matter_case_tracking` is local database work here, not provider
transport. Case-number advisory locks occur after admission. Assistant confirm
creates database drafts or performs field/task actions; model generation is a
separate path. Bootstrap and IP import outer callers are main's adjacent audit.
No changes to assignment helper defaults, matter_access, access_reviews or
data_disposition were made by this owner.

## Repair Protocol

Primary and outer interactive writer order:

```text
Company FOR NO KEY UPDATE
  -> existing sorted Membership FOR UPDATE
  -> existing sorted User FOR UPDATE / fresh capability checks
  -> Matter/source/command locks and writes
  -> private generation/event propagation
```

The explicit boundary uses `no_autoflush`, enters before actors/source locks,
and is repeated after transaction boundaries. It does not cache admission,
weaken FOR UPDATE, add retries, or reverse only the worker.

Worker finalization after parse/embedding:

```text
Company FOR NO KEY UPDATE
  -> sorted historical Membership FOR KEY SHARE (at most three identities)
  -> Matter FOR SHARE for Matter attachment lifecycle recheck
  -> source/chunk/job persistence
  -> private event with original non-null historical actor
  -> commit before compliance/provider work
```

IP retains PR524 Company-before-version-flush. Both workers suppress autoflush
until the admission/provenance boundary is acquired. Parse/embed provider
callbacks in the races assert that Company has not been acquired. The worker
does not acquire User locks or require historical actors to remain active.
Disposal winning before finalization rejects the worker without source/chunk
or event persistence. No disposed Matter is reactivated.

Matter event actor is requester, falling back only to attachment uploader.
The nonexistent `Matter.created_by_membership_id` fallback was removed.
Job requester and Matter uploader really are nullable `ON DELETE SET NULL`.
With no active generation, a legacy job with neither actor completes normally
without a private event. With an active generation, finalization fails with an
explicit provenance error before source/chunk persistence. There is no invented
actor, null private-event actor, or silently skipped required invalidation.
Cross-tenant historical membership references fail closed.

## Retained FK Inventory

The historical fence includes the job requester plus the source uploader and,
for IP versions, `locked_by_membership_id`. The event actor must belong to that
retained set. Memberships are deduplicated, sorted, tenant-scoped and locked at
FK KEY SHARE strength, including default-off processing. Inactive historical
identities remain valid. Interactive auth/revocation fences remain FOR UPDATE.

Complete model FK inventory is retained in each new race's
`retained_fk_flush_inventory` event, not inferred from event provenance alone:

- Job: Company and nullable requester Membership.
- Matter attachment: Matter, uploader Membership, portal user, court order,
  hearing. The latter references are unchanged by processing.
- Matter chunk: attachment. Real replacement INSERT and embedding writes run.
- IP version: document/company, uploader/company, locker/company composites.
- Worker activity: Matter, with existing system activity actor unset. This is
  distinct from the non-null private projection event actor.

Real worker SQL shows exactly one attachment/version UPDATE and two job UPDATEs
separated by the durable claim commit. It does not show a same-transaction
second source UPDATE analogous to Kepler's Client path. No artificial extra
dirty flush was introduced to claim such a cycle. The nine selected pre-change
retained-reference assertions fail because the required early Membership wait
is absent; their graphs contain zero database errors, not a new 40P01 proof.
The bounded historical fence nevertheless closes that explicit worker protocol
gap and protects later unchanged-FK rechecks without broad authorization changes.

Real employee offboarding locks participant Membership/User before Matter/IP
parents. The worker tests race that actual service, not manual substitute locks.
`identity.update_company_user` has its real Membership/User fence; its
operational-IP guard reads/counts operational work, rather than taking the
worker's source lock. Live role revocation, membership deactivation with another
active tenant membership, and global user disablement are separately raced.

## Evidence And Open Ownership

All evidence is under `.tmp/actor-repair-20261008/`, with fresh files per run.
Earlier 16-case baseline evidence remains under `.tmp/actor-audit-20261008/`.
The original diagnostic test is retained there as `baseline-actor-test.py`.
Baseline same-actor deadlocks occurred on both the prior production source and
PR524 candidate. The old pre-Company IP flush changes where source locks occur;
it does not remove the later actor-FK edge. PR524 is preserved, not invalidated.

The baseline 16 identities expand to 32 by testing both acquisition orders;
same and different actors, two IP producers, metadata/disposal and both
autoflush modes remain represented. Acceptance requires successful serialization
and persisted business outcomes, not deadlock retries or expected 503s.

Intermediate worker-only Company-before-parent was insufficient:
`worker-note-before` has two worker-first reciprocal parent/actor cycles and
40P01; two note-first cases fail the early-actor-order assertion. Historical
KEY SHARE before parent removes the demonstrated reverse edge.

`upload-quota-before` has four additional real 40P01 failures:

```text
primary Matter writer: Company NO KEY UPDATE -> waits Membership FOR UPDATE
attachment upload:     Membership/User FOR UPDATE + Matter FOR SHARE
                       -> waits Company FOR UPDATE in quota check
```

The upload contender calls `create_matter_attachment` and the real quota
callback. Only storage bytes are local/deterministic. The tests record reciprocal
blocking PIDs and PostgreSQL deadlock details; this is not a timeout-only theory.
Main owns the scoped two-phase upload repair, current-auth/lifecycle/quota
revalidation, and the Notice serialization test. Moving Company earlier while
retaining scan/storage provider I/O under that lock would not meet the required
boundary. Do not claim a global fix from worker-only success.

Exact independent handoff targets:

```text
tests/test_matter_upload_admission_postgres.py
tests/test_postgres_validation.py::test_notice_reply_upload_shares_worker_lifecycle_fence_on_postgres
```

The old Notice test attempted synchronous reply upload while explicitly holding
the worker's Company fence. Its original failure in `outer-and-existing-r1` is
retained; main owns its conversion to one-way waiting followed by persisted
reply and lifecycle neutralization, independently reviewed by Galileo.

## Run History

| Run | Result | Interpretation |
| --- | --- | --- |
| before-repair | 2 failed | Early actor-lock assertions before admission repair |
| matrix-r1 | 32 passed | Baseline matrix, both acquisition orders |
| worker-admin-r1 | collection error | Missing explicit autoflush fixture dependency; no product conclusion |
| worker-admin-r2 | 60 passed | Initial worker/current-admin matrix |
| worker-note-before | 4 failed | 2 actual deadlocks; 2 early-order failures |
| historical-actor-r1 | 8 passed | Note and real offboarding overlaps |
| full-owned-r1 | 124 passed | Earlier complete owned inventory, before later additions |
| outer-and-existing-r1 | 9 failed, 18 passed | 8 HTTP observer PID errors; 1 genuine Notice quota timeout |
| outer-r2 | 8 passed | Correct per-transaction PID tracking with NullPool |
| legacy-actor-before | 4 failed | Nonexistent Matter creator fallback, including default-off legacy jobs |
| upload-quota-before | 4 failed, 6 passed | Four real quota cycles; six provenance cases successful |
| adjacent-unit-r1 | 147 passed, 1 deselected | Eight complete selected non-PG files; earlier worker helper revision |
| retained-fk-before | 9 failed | Missing early retained-membership waits; no database errors |
| retained-fk-r1 | 30 passed | 24 retained-FK races + six legacy/cross-tenant cases |
| final-owned-r1 | 181 passed, 1 failed | Old same-actor no-wait worker expectation conflicts with required historical FK fence |
| worker-compliance-r1 | 1 passed | Explicit actor wait, then all fences released before downstream compliance |
| final-owned-r2 | 182 passed | Complete replacement inventory, not a failed-test-only rerun |
| final-worker-unit | 7 passed | Entire document-worker unit file on final runtime |

Final PostgreSQL inventory by file: actor matrix 32; Matter admission/worker
122; real assistant/watch outer callers 8; IP document workflows 16; patent
source-order race 2; existing worker/compliance boundaries 2. Both PR524 source
regression selections (18 total) remain green. The earlier 147-test adjacent
run is preserved independently, not added to these overlapping totals.

One old worker test was explicitly renamed, not silently omitted:
`test_document_worker_does_not_contend_with_interactive_actor_fence_on_postgres`
becomes
`test_document_worker_releases_historical_fks_before_compliance_on_postgres`.
It now proves the real historical KEY SHARE wait while the interactive actor
owns FOR UPDATE, absence of a parent lock while waiting, and successful
Company/Membership/User/Matter acquisition while downstream compliance is
paused after the worker commit. Its system activity still has no actor; private
events still require original non-null provenance. Only this separate worker
function was edited by this owner in `test_postgres_validation.py`; main owns
the Notice function. Reconciliation proves the ordered 182-node inventory is
otherwise identical between the failed and complete replacement runs.

The HTTP harness now labels every transaction via Session.after_begin because
NullPool replaces its backend after the worker claim commit. It observes using
a separate NullPool connection, retains SQL/locks/PIDs, releases all pauses,
waits for all contenders and cancels only its own PIDs if needed. Every race
requires no pending transaction at teardown. Failed journals are never replaced.

Final artifacts:

- `final-reconciliation.json`: every run's inventory, phase outcomes, complete
  failure detail, XML count, graph/error/cleanup inventory and explicit node rename.
- `final-owned-r2.jsonl` / `.xml`, `final-owned-r2-graphs/`: complete PG gate.
- `final-worker-unit.jsonl` / `.xml`: complete final unit file.
- `final-r2-source-start.json` / `final-source-end.json`: identical source hashes.
- `final-postgres.log`: preserved complete owned-container PostgreSQL log.
- `final-cleanup-receipt.json`: evidence hashes, worker-test function hash,
  unchanged branch/base, zero open client transactions, zero prepared
  transactions, zero lock waiters, and owned container stopped.

The only remaining databases were the two independently migrated audit databases
and postgres; temporary HTTP clones/templates were removed. The owned container
`caseops-actor-audit-20261008-506e-pg` (port 55507) is stopped, not destroyed.
No owned pytest or command session remains running. Scoped Ruff and git diff
whitespace checks passed. No production/deployment or combined-release claim.

Final release-wide, CI and production acceptance are main's responsibility.
These local results do not establish deployment or authorize a release.
