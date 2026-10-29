# Matter Update Response Hydration

Status: Inconclusive / release NO-GO pending actual replacement acceptance.
Ownership: J04/M03/US-007..009/FT-011..015, existing Matter mutation and
workspace contracts; NFT-005 bounded work, plus unchanged tenant/access,
lifecycle, stale-write, audit and private-projection security requirements.

## Reproduction

Docker17 on bffedefc73136962d1c93af1bce6a4b19496df30 completed3483 native
PostgreSQL cases:3482passed/1failed/0skipped,10449setup/call/teardown phases.
The actual metadata-IP finalizer overlap failed writer.result(timeout=5) at
test_document_finalizer_overlap_20261009_postgres.py:1241. Its whole-call
duration23.984195s is not an individual SQL or hashing measurement.

The closed fixture proves same-uploader HTTP200 and the actual directed
PostgreSQL wait, finalizer release03:27:59.839Z, workerreturn59.916Z, durable
Matter mutationcommit03:28:01.561Z, and response return06.353Z. All joined
actors eventually completed; cleanup found no retained transactions/locks or
database errors. Eventual completion does not satisfy the five-second oracle.

## Source-Backed Waste

update_matter commits and refreshes a Matter previously loaded with the broad
workspace profile. All four siblings capture the same ordered postcommit
root plus twelve collection queries. MatterRecord consumes scalar fields,
tags/tag and court orders; ten other collections are unused by this DTO.
Their failed-case engine intervals total0.9311781s. Both session factories
disable commit expiry: this is explicit sticky eager-profile rehydration,
not a mapping-level eager default or proven automatic-expiration problem.

The response took4.792153s after the commit event. SQL intervals, ORM work,
connection/hooks, scheduling and process-wide GC are not independent CPU
measurements. Do not attribute the historical delay to a host/GC cause or
promise sufficient savings before replaying the unchanged failing oracle.

## Narrow Candidate

Limit the first candidate to update_matter(commit=True)'s response read.
Capture authorized scalar tenant/Matter IDs before commit, then reselect the
same tenant/ID with populate_existing, raiseload('*'), tags/tag and court
orders only. Preserve all scalar DTO fields and current relationship values.
Missing targets remain404. No stale DTO snapshot, ACL cache, truncation,
extra commit or changed mutation transport/retry is allowed.

Keep commit=False/no-op, parent/Company lock ordering, current actor/access/
capability checks, expected_updated_at, linked-IP fences, private tombstones,
audit and lifecycle behavior unchanged. Do not shrink the shared workspace
loader: workspace and operational consumers have different contracts.
Lifecycle/get_matter contain adjacent broad reads; their independent contracts
must be reviewed before any future reuse, not silently changed in this fix.

## Regression Inventory

MRH-01..02: retained and expiring sessions select exactly the response-owned
three-query graph after commit, with explicit tenant/ID predicates and full
scalar/tag/stay/interim parity.
MRH-03..10: a separate valid writer changes scalar/tag/order rows after commit;
both session policies must return current data for stay, interim-flag,
interim-kind and neither states. populate_existing must replace cached values.
MRH-11: foreign-tenant mutation fails closed without a commit or changed row.
MRH-12..15: commit=False preserves caller-owned uncommitted work and transaction;
retained/expiring sessions independently prove rollback and explicit commit.
MRH-16: the same session can still load the complete workspace after the narrow
response; its full DTO equals an independent fresh-session read.

The existing finalizer test remains byte-identical, including real HTTP login,
hashing, directed PostgreSQL races,5/8second bounds, private-output revocation,
idempotent replay and cleanup. A query-count reduction cannot replace that
oracle.

## Actual Local Components

At2026-10-29T05:03:49.142315Z the independently migrated GREEN component
completed45passed cases/135phases: all15new cases and the complete30-case
unchanged original finalizer module, without skips or retries. All ten positive
response receipts have exactly3SELECTs; the five tenant/commitFalse cases
have no implicit commit. Complete DTO and separate-writer field/tag/order
freshness assertions pass. Before/after source snapshots agree for that
dirty-source component, not a clean new release commit.

The preceding valid RED completed1case/3phases with actual pytest exit1 at
the query-count oracle, setup/teardown passed, product unchanged, and13actual
response SELECTs. Both original failed Docker17 and RED artifacts remain intact.
Product matters.py hash is70bc943aca65bab45d386c37e5b202bb5de4b19b56f1797479969be163138984;
unchanged finalizer oracle hash is901fc7b91715130c3fee308f7bbe07d7f8dee74db40ffa5619fcc531538150e1.
Evidence is under outputs/fix-561-20261026/portfolio-export-worker/
docker17-finalizer-failure-20261029/{red-01,green-01}/reconciliation.json.
This component does not establish production latency, a historical host/GC
cause, full current-source acceptance or permission to promote a workbook row.

At2026-10-29T05:20:08.728736Z fresh GREEN02 completed46passedcases/138phases:
16new plus the same30unchanged originals. All eleven positive response receipts
have3queries. MRH-16 positively proves later full workspace contents in the same
session, including the note deliberately excluded from response hydration.
The independent post-GREEN01 review found no actionable code defect; postcommit
ACL-revocation and missing-row404 branches were noted as coverage gaps, not
demonstrated bugs or completed acceptance. No host/GC cause is inferred.

## Precommit Continuation

The earlier postcommit-only scope did not bound metadata work before commit.
AFBC Docker19 retained three complete groups:1314cases/3942phases,1313passed/
1failed/0skipped, with2189native and640browser cases unexecuted after guarded
owned interruption. All383 retained files were verified before edits. Its
matter-metadata-False upload-order call failed a10second Company lock wait.
The actor trace proves one-way contention, not deadlock; it lacks ordinary
SELECT durations and release clocks. Do not infer a historical host/GC cause.

The assignment fence explicitly populated the full workspace after its parent
lock, including ten collections unused by MatterRecord. New PML-01..06 in
test_matter_metadata_load_profile_20261029_postgres.py measure product work in
the FIRST transaction, not the later response transaction. A valid one-case
RED on unchanged70bc product has successful setup/teardown and a call failure
at the unused-work assertion:14graph/23product SELECTs,11unrelated paths
including attachment chunks,69events, no capture/overflow/pairing errors.

The extension gives the assignment helper an optional child-load flag whose
default preserves other callers. Only update_matter opts out and reselects
exact tenant/ID with populate_existing, raiseload, tags/tag and orders. Keep
all Company/principal/parent/IP locks, current ACL and stale/lifecycle fences,
events/audits, no-op behavior and caller-owned commitFalse semantics. The old
postcommit narrow reload and full workspace loader remain unchanged.

PML-01..06 cross commit/defer/no-op with autoflush off/on. Bounded passive
ORM/SQL receipts check exactly3graph queries before commit, no unused paths,
current previously cached scalar/tag/order values, additional tag membership,
all DTO fields, observer visibility, rollback and later complete same-session
workspace access. They do not cap all authorization/discovery SQL or establish
historical timing causality. The unchanged real upload/writer/finalizer oracles
remain mandatory, not substitutes for this deterministic work assertion.

Fresh GREEN03 genuinely completes all206cases/618phases:6new,16unchanged
response,32upload,122writer and30finalizer cases. No skips/retries/nonpasses.
Native process exited0 naturally/reaped at11:48:28UTC; source-before/after
agree. All six profiles measure3graph queries; four caller-owned modes have
zero commits and two normal modes one. All177 retained files/hash verified.
The supervisor still exited1 because a separate post-test verifier used an
ordinary Windows path for a long retained filename. Its failed logs/result
remain intact. Canonical extended-path replay verifies17long paths without
editing/rerunning tests; this is actual component proof, not an outer0 claim.

Product SHA6121ec270d5bb351fb9631b17f58fdccfa22bb81a48349088f289bdcaff55aac;
new test SHAcec9a071abb6e75981e2518573555d1cc300e93f5a0444dc056ee06d86a00caa.
Evidence: primary outputs/fix-561-20261026/portfolio-export-worker/
docker19-upload-company-lock-failure-20261029-01/profile-green-03/
reconciliation-native-path-01.json
SHA1580e1ef422cef4867f27498bd604bb144d0b996809c13884aed5dbc228945eb.
Independent static review found no blocking change; it is not release approval.

Preserve GREEN01's pre-test Docker address-pool failure and GREEN02's incomplete
206collection/80phase tail (26complete passes, one failed call missing teardown,
179unexecuted). The later container exit255 cannot explain the earlier missed
barrier retroactively. Neither run is acceptance. No unowned resource was pruned,
OS/daemon policy changed, timeout raised or original assertion weakened.
The complete new canonical Docker, CI/main and production gates remain open.

## Closure Gates

Retain the full original RED journals, fixture terminal hash and failed Docker
logs. First establish a valid deterministic RED query-count regression, then
apply the narrow candidate and run all intended new and original overlap tests
on separately migrated PostgreSQL. Reconcile every collected identity and
setup/call/teardown phase; invalid fixture setup is not a product reproduction.
Require the complete new canonical local Docker inventory, fresh CI/security/
CodeQL, canonical main merge/tree proof, guarded exact-SHA deployment and full
live user-visible acceptance. Keep #561/#564 and IP15-018 open until their
separate exact-release export criteria also pass. No production or workbook
promotion is established by this brief.

The existing committed ram-2026-09-05-bugs.spec.ts metadata-edit journey uses
the real Matter editor, consumes its200PATCHresponse, preserves temporary and
final identifiers, reloads visible values and rejects stale/terminal writes.
It is already selected by the canonical local and production configurations;
require its actual desktop/mobile outcomes on the new serving revision. The
native forced-race timing proof and user-visible deployed workflow proof remain
separate; do not substitute client/contact or Notice editing for Matter editing.
