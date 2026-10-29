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
