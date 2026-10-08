# Private Authority Follow-Up - October 8

## Current Verdict

**Not fixed** on serving API/web release
`b20f86bddeecf985fc961012bb93fa2c41889c49`. This record supplements the
two Calendar workbook rows; it does not invent additional workbook issues.
Scope: existing private retrieval/IPLF-066 source integrity and UJ-29/PAT-01
source writers, shared Matter lifecycle/access and client KYC. No new product
capability, legal-source policy or provider activation is introduced.
Adjacent upload acceptance maps to J03/J04, M02/M03 and US-007/008/036/051:
retain readable, authorized document bytes without holding database locks
over scanner/storage I/O. Calendar remains J08/M08/MOD-TS-006.

The Calendar repair is deployed. Production verification `37716144183`
failed a real immediate patent source-save deadlock. PR #524 repairs that
document-version/Company inversion. Its exact `506e1479` candidate passed
565 PostgreSQL tests and all 467 collected browser identities (459 passed,
eight known skips), with green PR CI. It merged as `f146ad8c` with an identical
tree. Merged-main CI `37728861237` also passed; deployment is a separate gate
and production remains `b20f86bd`. This follow-up records additional causes that the source-version
patch cannot close.

## Whitespace Hash Mismatch

An exact-image maintenance execution,
`caseops-private-projection-maintenance-kxm4s`, ran at
2026-10-08 03:42:16-03:45:01 UTC, with no overlapping production verification.
It remained blocked. Two newly rebuilt tenants immediately reported
`stale_or_ineligible_sources`; other tenants retained older manifest/repair
blockers. This is not sufficient evidence to blame concurrent writes.

The persistence path normalizes projection text with Python's
`" ".join(text.split())` before hashing. The source-text helper, integrity
verifier and retrieval currentness path hash unnormalized source fields.
An otherwise valid multiline or repeated-whitespace source can therefore
activate successfully and fail its next integrity check. Another rebuild
repeats the disagreement rather than repairing it.

The shared source-text/content-version implementation was introduced by
`c768a52ec` on October 5. That establishes this release's cause, not a claim
that every earlier private-projection alert had the same origin. Historical
concurrency, access, tombstone and manifest incidents retain their own evidence.

A bounded production diagnostic used six separate REPEATABLE READ READ ONLY
transactions, checked `transaction_read_only = on`, applied statement/lock
timeouts, capped each tenant at 20,000 rows plus an overflow sentinel, and
explicitly rolled back. Credentials and legal text were processed only in
memory. Across six non-truncated snapshots it scanned 22,640 live projections.
Only counts and bounded record identifiers were exported.

| Tenant prefix | Matter raw-hash mismatches | Match after exact whitespace normalization | Current raw source version and security state |
| --- | ---: | ---: | --- |
| `35232ec0` | 2 | 2 | Both current; generation rebuilt in this execution |
| `4e798318` | 6 | 6 | All current; generation rebuilt in this execution |
| `b9de7c48` | 18 | 18 | Older source versions; separate legacy-state boundary |
| `d52d98c9` | 16 | 16 | Older versions and generation epochs; separate blocker |

No inspected metadata source had a hash that matched neither representation.
No private-source events were recorded after maintenance started in these
snapshots. Document-source currentness was intentionally not evaluated by
this narrow diagnostic; it is not a whole-integrity certification. The other
two tenants' metadata hashes matched, but `6d610b43` retained an invalidated
manifest and old source versions/epochs. Those findings remain distinct.

Evidence in the frozen PR #524 checkout:
`.tmp/calendar-oauth-20261008/b20-pre-cert-maintenance-kxm4s.json`,
`b20-projection-readonly-01.json` and the inspected `projection-readonly.py`.
The temporary loopback Cloud SQL proxy was terminated after the diagnostic.

The unmodified runtime reproduced 12 failures across Client, Matter and IP
docket for double spaces, CRLF, tabs and NBSP. Six ordinary-text/substantive-
change controls passed. All 18 identities and phase records completed.
Original evidence is retained in `.tmp/private-whitespace-20261008/baseline-01.*`.
The repair must share exact normalization across source text, source versions,
stored projections, vector reuse and currentness. It must not rewrite retired
projections or authorize a saved manifest with a different source version.

## Actor Lock Inversion

Real PostgreSQL interleavings separately reproduce Company -> actor and
actor -> Company cycles. An IP worker holds Company and inserts a private
event whose non-null membership FK needs KEY SHARE. A same-actor Matter
metadata/disposal writer holds Membership FOR UPDATE and waits for Company.
A patent correction can form the same cycle through its explicit actor lock,
without relying on event insertion. Both exist on `b20f86bd` and `506e1479`.

Each final 16-case audit had eight real deadlocks and eight passing
different-actor controls, with production/autoflush variants and a repeated
candidate run. An earlier observer-harness failure remains recorded as
incomplete evidence. Full SQLSTATE 40P01 graphs, source identities, rollback
outcomes and cleanup are retained in
`docs/audit-private-event-actor-lock-2026-10-08.md`.

The repair's dependency boundary includes Matter entry points and outer
bulk/import callers, post-I/O document-worker finalization, client/portal KYC,
and private-event-emitting IP lifecycle/source writers. Preserve Company ->
actors -> lifecycle parents -> children and Company -> generations. Existing
access-review/access-management/disposition entry points already take Company
before actor/parent locks; their caller contracts still require review.
Do not alter the global assignment helper, null historical actor provenance,
weaken authorization locks or retry failed browser mutations.

## Upload Admission

Moving primary Matter writes and document workers to tenant-first admission
exposed an existing reverse upload order: Membership/parent -> Company quota.
Four retained PostgreSQL interleavings in
`.tmp/actor-repair-20261008/upload-quota-before.*` reproduced actual deadlocks.
Adding Company first while retaining scanner/storage I/O under that lock
would serialize a tenant behind external work, so that is not the repair.

The upload now validates current authority and references, releases the
transaction, scans/stores one unique transient attachment, then reacquires
Company quota -> current actor -> lifecycle parent and revalidates references
before publishing. The early quota check is advisory and releases its own
transaction; final quota admission counts incoming bytes once under the lock.
Rejected admission rolls back before removing its unpublished storage object.
The real scanner's infection/outage fence is unchanged.

Independent review additionally reproduced two employee-update/upload deadlocks
and four unsafe post-I/O admissions (workspace disabled or session revoked,
both autoflush settings). Company FOR UPDATE blocked an employee audit's FK
KEY SHARE while upload waited for that employee's membership. Quota admission
and quota-only edits now use NO KEY UPDATE: quota writers still exclude each
other and quota changes, while unrelated FK references can finish. Current
Company, Membership/User, capability and token-cutoff checks run after I/O.
No global actor-lock default or authentication policy was weakened.

The final focused run has **31 passed, zero failed/skipped**, reconciled across
31 collected identities, 93 setup/call/teardown results and XML. It includes
both primary/upload acquisition orders, employee audit overlap, parallel
quota admission, post-I/O lifecycle/access/session rejection, exact stored
bytes/hash, infected content, scanner outage, and the existing notice worker/
reply/disposal journey. Notice's observer now proves waiting at Company before
owning the actor; immediate completion while another writer owns Company is
not a valid contract for the required tenant serialization.

Evidence: `.tmp/upload-admission-20261008/review-fixed-r1.*` and
`review-baseline-r1.*`. The latter's six failures all have complete structured
details, including two SQLSTATE 40P01 cycles. The separate `baseline-io.*`
run against unchanged `506e1479` fails all 14 selected scanner callbacks
because the transaction remains open; it is not proof of later negative
branches it never reached. Earlier incomplete/failed setup and assertion runs
remain retained. Broad affected-file, Docker and production proof are pending.

An intermediate full-file run passed **212 tests across 12 affected files**,
with all 636 phase reports and XML reconciled. The subsequent combined Matter
and notice run passed **111 tests** (98 new PostgreSQL cases plus the complete
13-case existing notice suite). These are separate overlapping inventories,
not additive product-wide coverage. Final formatting and additional adjacent
repairs still require one fresh combined acceptance snapshot.

The subsequent main-owned full-file gate, `final-main-r1`, passed **280 tests
across 13 complete files**, with 840 phase reports and XML identities
reconciled. Independent review found no additional actionable defect in that
snapshot. Four more uncertain notice-replacement outcomes were then added:
both old and new bytes survive a lost acknowledgement, while the database
retains its actual before/after-commit reference. The full notice and production
workflow suites passed **88 tests**, 264 phases, in `replacement-ci-r1`.
The later shared IP-storage accounting extension has its own acceptance;
these overlapping runs are not a combined release certification.

The integrated main gate `final-main-r2` passed **302 tests across 14 complete
files**, with 906 phase reports and XML identities reconciled. It includes
the shared IP accounting extension and the complete production-workflow tests.
Before this gate, two candidate-only regressions demonstrated an admission
risk introduced by unlocking upload I/O: a real dedicated dispose/reopen cycle
could allow the old request into Intake. Comparing the captured lifecycle
version now rejects that request, removes its unpublished bytes, leaves the
old job neutralized and permits a genuinely fresh upload after explicit reopen.
`reopen-before-r1` retains both failed results. This is not evidence of an
automatic production Matter reopening.

## Standalone Notice Access and File Safety

The same audit found standalone first/replacement uploads retaining their
notice row transaction through scanning/storage. Four corrected baseline
cases reproduce the open transaction; one earlier fixture reused a globally
unique storage key and remains explicitly non-reproduction evidence.
The repaired path captures scalar identities, releases preflight and advisory
quota transactions, and admits after I/O with fresh tenant/actor/capability,
visibility, notice-version and replacement-quota checks. It retains the
independent standalone notice lifecycle; it does not mutate/reopen linked
Matters. Real simultaneous edits and uploads prove audit FK completion and
stale-write rejection. Parallel uploads prove one OCC or quota winner, with
the loser's unpublished object removed and any old file preserved.

An additional visibility regression is independently confirmed, not a test
fixture error. A restricted Matter with a NULL assignee and no grant yields
SQL NULL for its permission expression. Negating that expression in a hidden-
link EXISTS does not produce TRUE, so a linked notice could be listed, read,
updated or resolved for download. The shared notice predicate now treats every
result other than explicit TRUE as hidden. All four unauthorized operations
failed on the prior predicate; all four owner controls passed. The final
eight-case matrix and four post-I/O visibility revocation cases now pass.
The source audit found no other negated visibility/access filter using this
pattern. Fresh Docker acceptance and production replay are still required.

The shared dated notice journey now passed both **1280px and 393px** locally,
with zero skips/retries, a fresh same-source Next build and isolated API/data.
It creates/uploads/replaces/reloads/downloads exact bytes and proves the
restricted unassigned notice is hidden beside readable/editable siblings.
Screenshots were inspected. The first cleanup expectation assumed 401 for an
inactive actor; the actual contract is 403 and that failed evidence is retained.
Final evidence: `.tmp/notice-browser-20261008/run-3/results.json`.
The normal production tester inventory includes this exact-release-owned spec,
with explicit test-legal credentials from the existing secret and one dedicated
managed partner. Missing configuration fails, the password is derived only in
memory, no existing password is rewritten, and teardown deactivates the actor
and retains terminal fixture records. Production replay is still pending.

Independent review also injected an exception after a real successful
PostgreSQL commit: attachment/job rows survived while cleanup deleted their
bytes. Matter and standalone notice uploads now distinguish pre-commit
rejection from an uncertain commit acknowledgement. Eight before/after-commit
response tests preserve stored bytes, including the four with durable rows.
An uncertain outcome is not a successful response or an automatic replay;
unreferenced objects from genuinely failed commits remain for authoritative
reconciliation rather than risking deletion of committed records.

Retained main evidence: `.tmp/upload-admission-20261008/affected-files-r1.*`,
`notice-before-r1.*` (three IO failures, one fixture uniqueness failure),
`notice-before-r2.*` (four IO failures), `notice-null-before-r1.*` (four
unauthorized failures/four controls), `commit-before-r1.*` (eight failures),
`notice-after-r3.*` (111 passing cases), plus independent commit proof and
the review reconciliation. `notice-after-r2` retained four observer failures
because PostgreSQL truncated its displayed query before FROM; the replacement
asserts the visible SELECT prefix and the complete captured locking SQL.
The prior 509-case IP snapshot remains 507 passed/two failed. Its real Notice
membership wait and obsolete worker compliance/no-contention contract are
mapped to current passing nodes, not retroactively relabeled green.

Other affected storage callers have bounded adjacent repairs with their own
failure/replacement evidence. No production deployment or product-wide closure
is claimed while the integrated gates remain open.

## Atomic Inbound and Outside-Counsel Uploads

Inbound import now retains one atomic admission for communication metadata,
attachments, processing jobs and audits, while real scan/storage callbacks run
outside a transaction. Outside-counsel work product rechecks the current user,
grant, lifecycle and aggregate quota after I/O. Neither service commits staged
caller work to release its locks. Preexisting writes, including flushed ORM
and Core SQL writes, are rejected without rolling back the caller's transaction.
The audited runtime callers are direct read-only request paths; this is not a
claim that a deployed nested caller was already losing writes.

Independent review confirmed **12 real SQLSTATE 40P01 failures** against
ordinary communication, outside-counsel time-entry and invoice writers. Their
actor FK KEY SHARE checks conflicted with upload authority locks. Scoped
NO KEY UPDATE locks permit those FK references while continuing to exclude
revocation, disablement and capability changes; the global helper defaults
and ordinary writers are unchanged. All 24 replacement interleavings pass in
both acquisition orders. Twenty previously unsafe caller-write cases also
have passing replacements.

The final complete gate passed **173 tests**, comprising 132 PostgreSQL cases
and all 41 existing communication/outside-counsel HTTP cases. All 519 phases,
canonical collection, source hashes and cleanup reconcile. The intermediate
121-pass snapshot and failed baselines remain retained, not relabeled green.
Evidence: `.tmp/outer-upload-20261008/REVIEWED-HANDOFF.md`,
`reviewed-full-files-r3.*` and `reviewed-reconciliation.json`.

## Client Current-Actor Admission

Historical creator/reviewer Membership KEY SHARE references are provenance,
not proof that the interactive caller is still authorized. An independent
PostgreSQL matrix confirmed 64 unsafe admissions after a real tenant/actor
wait, while four inactive-historical-provenance controls passed. The repaired
client entry points retain sorted historical FK references, fence the current
Membership/User, reload the original token issuance context and enforce each
command's existing capability after the wait. No historical actor is replaced
or made subject to current-user activity checks.

All **229 tests across four full client/portal files** passed, including 175
real PostgreSQL cases and all 687 phase reports. This inventory contains every
prior accepted client/portal identity. Evidence:
`.tmp/client-current-actor-20261008/handoff-evidence.json` and `handoff.md`.

## Shared Storage Accounting

Two real simultaneous-IP-upload regressions found that quota serialization
alone was insufficient: the shared counter omitted persisted IP document
versions. Both uploads could pass a serialized check against zero accounted
IP bytes. The narrow repair includes every tenant-scoped retained version,
without multiplying links or excluding historical/terminal documents whose
bytes remain stored. Matter attachments already include inbound email and
outside-counsel artifacts; they must not be counted a second time.
The original two failures remain retained. The complete replacement storage
and IP upload gate, `affected-final-r2`, passed **599 tests across 18 complete
files**, including all existing PostgreSQL validation tests. All 1,797 phase
reports, exact ordered collection, final completion and XML reconcile. Runtime
and test hashes match the frozen snapshot. Independent review found no new
blocker in request-transaction ownership, target lifecycle capture, final locks
or quota/naming lock reuse; it did not substitute for the completed run.

Both IP upload paths release the request transaction before real storage,
then reload current authority, linked target lifecycle, taxonomy, version,
naming and duplicate decisions under final locks. Pending, flushed and Core
SQL caller writes are rejected without being discarded. Historical bytes and
uncertain commits retain the same safety boundaries as the other repaired
uploads. Evidence: `.tmp/ip-upload-io-20261008/affected-final-r2.*` and
`final-r2-source-hashes.json`. Earlier 429/437-case snapshots are historical;
the 599-case replacement includes the later caller-transaction guard and
isolated patent migration test. Full Docker and production proof remain open.

## Why Earlier Evidence Was Insufficient

1. A rebuild's valid internal manifest does not prove equivalence to the
   canonical source. Ordinary single-line fixtures concealed the text/hash
   disagreement, while repeated rebuilding could never change the outcome.
2. Sequential save and indexing tests did not force the production overlap.
   Repairing the source-version cycle alone does not prove actor-FK ordering.
3. Green CI, deployment health and safe OAuth rejection are separate evidence
   from a successful Google grant and complete exact-release production E2E.
4. Old-generation/epoch blockers cannot be collapsed into the newly confirmed
   whitespace cause. Preserve their fail-closed state and verify recovery
   independently after the repaired release.
5. Upload safety requires actual post-I/O authority and lifecycle changes,
   uncertain commit outcomes and ordinary-writer FK overlap. Sequential happy
   paths and ORM dirty-set inspection alone missed those boundaries.

## Migration Test Isolation

The patent downgrade rehearsal used a shared PostgreSQL database. Running
specialist fixtures first made their legitimate preservation guard fire before
the expected patent guard. The retained baseline has one real fixture pass
and one patent assertion failure, not a production migration failure.
The single test now uses the existing independently fresh migration fixture.
Both specialist/patent orders pass (two cases each), and the complete patent
file passes all eight cases. All 36 positive phase reports, ordered identities
and XML reconcile. Both orders leave two specialist records and zero patent
families in the shared source database. The exact patent rejection text and
both downgrade/recovery iterations are unchanged; no migrations changed.
Evidence: `.tmp/patent-migration-isolation-20261008/handoff-evidence.json`.
The earlier zero-test argument failure and initial DB-role setup failure remain
incomplete infrastructure evidence, not acceptance. The isolated container is
stopped and its temporary databases and sessions are drained.

## Remaining Gates

PR #525 first candidate `f076acfc` failed CI `37734976322` because the
inbound-communication storage boundary lacked its required governance-map
change note. The pre-commit local change gate compared base...HEAD and did not
include the dirty diff, so its green result was insufficient. The committed
candidate reproduces the failure. The canonical note now records atomic
admission, transient objects, unknown-commit retention, quota and private hash
handling without claiming new retention or disposition authority; its human
view is regenerated. The actual gate is retained, not bypassed.

The `docker-f076acfc-r1` run was deliberately interrupted during PostgreSQL
execution so the corrected committed candidate can receive a fresh complete
run. It has no final pytest completion and is **incomplete**, not an application
failure or acceptance pass. The wrapper completed cleanup of its isolated
containers, volumes and networks. Its logs and incremental journal remain in
`.tmp/release-followup-20261008/`; CI's original failing job log is retained there.

The earlier scoped affected-file regressions completed. Their
overlapping inventories must not be added together as one full-suite result.
The second candidate `b7a61163` passed the map change gate but CI `37736110499`
correctly rejected the stale generated runtime data-class projection. Updating
the reviewed map requires both its human view and its compiled runtime
fingerprint to be regenerated. The compiler now refreshes that fingerprint;
the reviewed admitted classes and dispositions are unchanged. The complete CI
preflight, rather than a selected subset, must pass before the next freeze.
`docker-b7a61163-r1` was deliberately interrupted during PostgreSQL execution
and is also incomplete, with its incremental journal and original CI failure
retained. Neither interrupted run certifies the release.
### Third Candidate Findings

Candidate `e9faae03` passed the complete hosted static/governance gate, web
typecheck/unit/build and security workflow, but is not release-ready. All four
PostgreSQL shards finished: **1,439 passed, 20 failed, zero errors/skips across
1,459 collected cases**. Every failed XML result was read and reconciled:

- Twelve communication/outside-counsel revocation cases and four notice-edit
  cases found the race harness's own JSONL in the upload root. Prior scoped
  runs supplied a separate evidence directory; CI's unset default exposed this
  test-harness defect. Diagnostics now use independent temporary storage by
  default. Original no-orphan-file assertions remain unchanged.
- Four provider-parametrized OAuth/disposal tests incorrectly expected Company
  to be unlocked while the newly corrected tenant-first lifecycle writer was
  paused holding it. The replacement must prove the callback's rollback and
  absence of locks through independent PostgreSQL backend observations, retain
  the legitimate disposal ownership, and prove both operations complete with
  the Matter still disposed and its private tombstone applied.
- API coverage shard 5 finished with 552 passes, 47 skips and one failure: its
  static private-acceptance inventory still expected two search calls after
  fresh and retained metadata revocation coverage added two more. Reconcile
  the actual probes and both branches, not an unexplained numeric allowance.
- API coverage shard 9 finished with 560 passes, 45 skips and one real Gmail
  attachment-review failure (502). Its caller still used the old inbound
  helper signature and tuple return, after that helper became an outer-owned
  transient staging operation. Correcting only arguments would still omit
  atomic attachment/job/candidate admission and could retain locks through I/O.
  Repair and regress the complete Gmail caller boundary before release.

The hosted CodeQL check also flagged two notice error logs carrying a request
identifier and ambiguous local assignments. Error messages now contain fixed
text rather than user-controlled identifiers. The read-only session guard has
explicit success returns and still rejects pending, flushed, Core-written and
nested caller transactions without rolling them back. Cleanup-failure and
unknown-commit tests assert fixed log arguments alongside retained bytes and
the original authorization/stale-write result. No analyzer suppression or
security relaxation is used. Existing cyclic-import notes are not a reason
for an unrelated service refactor.

The first replacement launch (`codeql-affected-r1`) used a missing Docker
POSTGRES_USER value, causing database-role authentication setup failures. It
was stopped and is incomplete infrastructure evidence, not a reproduced
product defect. The complete six-file `codeql-affected-r2` run collected 531
cases and finished with 521 passes and ten new log-capture assertion failures:
Alembic disables preexisting loggers in this harness. Those tests now configure
the specific logger explicitly, following the existing IP regression pattern;
the complete replacement `codeql-affected-r3` passes **531 cases** with all
1,593 setup/call/teardown reports, ordered collection, matching XML identities
and successful completion. The evidence-directory override is deliberately
unset, proving the CI-default harness correction. Preserve both failed journals
and the original hosted job logs under
`.tmp/release-followup-20261008/`.

PR review separately identified missing caller-transaction ownership guards in
Matter and standalone-notice uploads. Twenty-four PostgreSQL cases reproduce
the defect before the guard: new, dirty, flushed, Core-written, deleted and
nested sessions each reached forbidden scanner/storage transport with both
autoflush settings and both upload surfaces. A shared early guard now uses
the nonassigning PostgreSQL transaction-ID probe and SQLite's actual driver
state, preserving the original transaction on rejection. The first replacement
correctly rejected and preserved caller work, but its final zero-attachment
assertion overlooked the shared fixture's existing attachment. Preserve that
failed report as a test-inventory mistake; the replacement requires the exact
original attachment identity and no additional row, not an empty-fixture claim.
The complete fifteen-file replacement passes **470 cases**, with 1,410 phase
reports, ordered collection, matching XML identities and successful completion.
This is scoped evidence, not final committed-candidate release acceptance.

Independent review found a second ownership boundary: a fresh Session bound to
an externally transacted Connection could release work it did not own. This is
a reproduced latent defect, not a claim that a current production caller uses
that binding. The initial 48-case baseline has 36 failures: 30 reach forbidden
transport and six hit an existing notice stale-write check first; twelve are
already rejected by the xid guard. The expanded replacement passes **120
PostgreSQL cases** across five upload boundaries, three join modes, both
autoflush settings, fresh/begun Sessions and read/write external transactions.
It requires unchanged Session/outer-transaction state, no transport and a
successful caller commit. The shared guard conservatively rejects an active
externally owned Connection transaction before starting any query.

Gmail's outer admission now stages transient bytes without a transaction and
rechecks current actor, mailbox owner, configuration, connection, message,
candidate and Matter lifecycle before one atomic attachment/job/activity/audit
commit. Refreshed tokens use captured configuration without a database session;
stale authority cannot restore credentials or commit bytes. Known pre-commit
failure compensates its unique object, while an unknown commit retains bytes
for reconciliation. The complete eight-file affected gate passes **425/425**,
including 138 Gmail PostgreSQL cases and thirteen existing Gmail tests, with
1,275 phase reports and matching ordered collection/XML identities. Independent
source review finds no remaining actionable Gmail-specific blocker. Evidence:
`.tmp/gmail-attachment-admission-20261008/affected-final-r1.*`. This is not a
production Gmail workflow acceptance claim.

The OAuth correction reproduces all four original failures against frozen
`e9faae03`, then passes both complete Calendar/workspace files: **216 cases,
648 phase reports, zero skips**, with independent ordered collection and XML
identity reconciliation. The callback is idle without transaction, xid, xmin
or locks during backoff; disposal owns the legitimate tenant/actor fences and
commits first. The callback then completes once, with disposal and the applied
private tombstone retained. Evidence:
`.tmp/oauth-ci-regression-20261008/handoff.json`.

The first and retained private-acceptance branches now share document and
Matter-metadata search/autocomplete/count and desktop/mobile discovery
revocation proof, plus actual retained answers, exports and unchanged terminal
state. Fresh-build loopback PostgreSQL browser runs pass first **1/1**, retained
**1/1** and other shared consumers **3/3**. Six deliberate helper leak injections
prove all six negative retrieval checks are sensitive; the old helper missed
the three metadata probes. Complete offline Linux deploy hardening passes
**189/189**, including 38 negative inventory cases. These local results use a
recorded source fingerprint, not a clean release commit or production proof.
The failed noncanonical webpack build and incomplete earlier attempts remain
retained. Evidence: `.tmp/retained-metadata-20261008-r3/RESULTS.md`.

`docker-e9faae03-r1` was interrupted after these findings and cleaned up. It is
the third incomplete Docker run, never a pass. The retained-Matter branch now
repeats the new metadata invariant so replay cannot omit the originally leaking
source. Its scoped loopback proof above does not replace serving-release proof.
Require fresh exact-tree full PostgreSQL Docker/Playwright, green PR and
merged-main CI, and guarded canonical-SHA deployment. Current independent full
PostgreSQL collection completes with **1,743 selected identities**, including
218 notice-upload and 138 Gmail-admission cases. Collection is inventory, not
test execution; reconcile the final Docker results against it.

Then rerun complete production acceptance, including the original patent
journey without retries, and obtain two later clean exact-image maintenance
runs, with no rebuild on the second. Only the guarded scheduler procedure may
resume private cadence. Do not suppress the 300-second SLO or stale-source
blockers. Google Calendar BUG-003/004 remain **Inconclusive** until the
owner-authorized account completes real consent and the committed positive
connection/reload Playwright journey passes on the serving release.
