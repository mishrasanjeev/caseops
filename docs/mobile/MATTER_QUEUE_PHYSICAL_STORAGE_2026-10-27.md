# Matter queue physical storage candidate

This is source preparation, not production or native acceptance. Migration
`20261027_0006` depends on the separately owned counsel `20261027_0005`; no Alembic
execution is authorized until that predecessor is present and reviewed.

`matter_tasks` remains the authoritative source. Groups distinguish a NULL owner
from a retained empty owner key. A page has 25 fixed typed scalar slots, no JSON,
no hidden unpack function and no copied Matter title or lifecycle. Derived tables
have no parent foreign keys. All source INSERT/UPDATE/DELETE statements collect
both old and new scopes, including raw compatibility writes and FK cascades.
PostgreSQL TRUNCATE clears the projection in its original transaction.

The PostgreSQL default deferred finalizer locks all transaction scopes in a
stable order after ordinary source writes. A shared DER1 commit-only gate comes
first in both counsel0005 and queue0006, before deduplicated actual advisory-key
ordering, so projection trigger firing order cannot invert namespaces. This
serializes projection commit refresh. VOLATILE refresh statements must see a
fresh READ COMMITTED snapshot after waiting. They rebuild complete groups from
current source rows and removes dirty scopes. Source rows, existing timestamps,
notification intent and reminder data are not updated by refresh. SQLite retains
its canonical Task query and uses raw SQL triggers to keep the same derived
schema; migration backfill reads source rows without an id=id update.

The packed query applies current actor, company, Matter lifecycle/ACL and current
owner/team rules before any group bound. At most two physical pages contribute
each group's first 26 matches, then the global merge takes 26. Cursor predicates
enter before those bounds. The authoritative current cursor anchor still reads
canonical Tasks. Execution-time current-transaction dirty predicates choose
between the packed branch and an explicit canonical-source branch, so a retained
Select can read its own later uncommitted writes. Every branch is typed and the
pure packed branch contains no `matter_tasks` FROM.

## Required unresolved proof

Default deferred execution has not been tested on PostgreSQL. Canonical writers
use READ COMMITTED and no application/script caller forces constraints early.
Explicit `SET CONSTRAINTS ... IMMEDIATE` followed by later source writes can
acquire projection locks before the last source row lock; this administration
path is not claimed supported. REPEATABLE READ/SERIALIZABLE must retain standard
serialization failures instead of committing a stale aggregate. Mixed queue and
counsel transactions, source/audit locks, actual post-wait snapshot freshness and
rollback remain required real PostgreSQL evidence. No lock-budget, time-budget
or 400-work waiver is proposed.

The retained TEMP prototype measured 24 plans with maximum 327 work and complete
DTO/cursor equality. Its full envelope failed on unknown `.codex` ancestor churn;
that evidence is not acceptance of this production schema, changed UNION fallback,
triggers, concurrency, deployment backfill or all API callers.

Prepared checks cover raw writer composition, long retained SQLite text, nullable
legacy scope, dense pagination, reparent/owner/date/status/cancel changes,
rollback/deletion, source-neutral backfill and same-prebuilt-query own writes.
The complete existing cross-dialect queue/policy journey, all node/filter/recheck/
loop work, populated 800/160 layouts with indexes installed before and after seed,
source/outbox byte preservation, forced-immediate behavior and actual migration
preflight remain pending. Whole-source governance must be regenerated again after
merging the counsel and queue candidates.

## Closed migration dependency and database entry points

Migration0006 reads the LF-pinned `task_queue_page_schema_v1.py` through one
regular descriptor, with bounded bytes and final leaf/namespace reconciliation,
checks its exact source SHA256, and compiles that retained buffer before database
binding or DDL. It imports neither mutable current ORM tables nor a cached helper
module. The helper has no import side effects; current model schema hooks are
registered separately. Once published, this v1 helper is immutable: any change
requires a new version and forward migration. Historical migration acceptance
must include these exact helper bytes and their Git LF contract. Simulated
Windows metadata controls are distinct from actual Windows execution.

All six PostgreSQL helper/trigger functions are SECURITY INVOKER, fixed to the
canonical public schema and a pg_catalog/public search path, with PUBLIC EXECUTE
revoked explicitly. Catalog acceptance checks the actual isolated canonical
migrator/runtime owner, exact signatures, ACL, volatility and namespace; it does
not promise arbitrary externally granted database-role compatibility.

The measured 24-plan TEMP fixture had two groups and160 eligible rows. Date
filters, late cursors, many current Matter groups and arbitrary large histories
have no universal400-work proof. Preserve all actual nodes and adverse/default
plans in a separately bounded follow-up study; the required original production
plan and concurrency inventory runs first with unchanged400/5s assertions.
