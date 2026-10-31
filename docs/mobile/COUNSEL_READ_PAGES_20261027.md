# Isolated counsel read-page candidate, 2026-10-27

This candidate preserves the existing Matter counsel endpoint, DTO serializers,
money arithmetic, independent assignment/spend continuations, current parent
authorization and readable closed history. It does not add a mobile feature,
an identity-directory endpoint, a permission, a provider call or a retention
approval. It is not deployed or accepted on either native platform.

The original ordinary-query adverse work failure remains recorded. The separate
eight-plan physical experiment passed at158default/224adverse work for its two
fixture insertion orders, with complete canonical JSON comparisons. Its first
envelope was incomplete after an external `.codex` directory timestamp change;
the complete replacement retained every ancestor guard and passed. Neither
experiment measures the production query below, which adds the deferred protocol
and explicit own-write branch. The production400bound and five-second statement deadline are
unchanged and require actual default/adverse plans.

## Physical format and valid old writes

PostgreSQL `counsel_read_pages` stores dense25record leaves per
`(company_id,matter_id,record_kind)`, ordered by immutable source ID. JSON metadata
contains explicitly listed existing bounded source columns, current Counsel name
and a same-company Membership's User association. It never serializes arbitrary
future source columns through `to_jsonb(source)`.

Each model has one unbounded source Text field: assignment `internal_notes` or
spend `notes`. The25slots store that field in independent native Text columns.
There is no new1MiB source limit, truncation, substring or JSON/array aggregate of
these notes. A valid large legacy note remains independently TOAST-able. The
bounded metadata's encoded size is checked by tests, not imposed as a new source
write constraint. It must not be confused with the earlier prototype's complete
JSON payload limit.

SQLite does not enforce VARCHAR lengths. Its canonical source-join reader stays
unchanged; `counsel_read_page_members` stores native source keys and dense page/
slot ranks without copying names, notes or a JSON aggregate. Each logical group
of25is explicit. PostgreSQL alone uses physical packed leaves for serving.

PostgreSQL source INSERT/UPDATE/DELETE triggers collect affected old/new scopes
in private `counsel_read_page_dirty` rows keyed by server transaction ID. They
acquire no shared projection lock. An initially deferred constraint trigger
refreshes every collected scope in the same transaction at commit, including old
processes that write only original columns. SQLite retains immediate native-key
membership maintenance.
Backfill and trigger installation are one migration transaction. Source rows,
their timestamps and audit/outbox data are not rewritten by this projection.
Counsel tenant changes recompute eligibility; invalid foreign Counsel references
remain stored where the original schema accepts them but do not enter a read
page. Foreign actor Memberships yield a null label, never another tenant's name.

## Current names and lock boundaries

Current actor names are copied into the authorized parent leaf along with the
same-company Membership User ID. There is no separate global name-directory
serving join. Its earlier proposed bucket/min/max join lacked a first-candidate
barrier and had not measured arbitrary higher-page scans; source checkpoints
9855/bace are retained as unaccepted designs, not as measured plan failures.

Every User change records its exact server User ID in the transaction's private
dirty table. At commit the finalizer first acquires shared DER1 `(1145393713,0)`.
Only then does a fresh VOLATILE command discover existing affected source scopes
via exact current Membership/User identity and company equality. If a new-parent
source committed first, that scope is visible to User expansion; if the User
committed first, the later source finalizer reads its current name. A waited gate
requires a fresh statement snapshot. Both orders and a real directed wait must
be tested on PostgreSQL; this is the source argument, not runtime acceptance.

The first immediate-trigger candidate was separately rejected for a canonical
Membership FOR UPDATE → projection lock versus source projection lock → audit
Membership FK cycle, and for multi-statement old-source/profile lock inversion.
The replacement takes no projection lock during source, profile, activity or
audit/FK writes. Finalizers alone acquire DER1, then deduplicated actual CPG1
hash keys in order, then refresh all logical scopes. All derived tables have no
parent/company/source FK; finalization performs MVCC source reads and derived
writes without Matter, Membership, User or source-row locks. The separate task
projection uses the same commit-only gate to prevent reversed finalizer order.
No security-definer function or broader writer grant is added.

A typed execution-time SQL UNION uses the canonical source join while this
transaction has any dirty marker, including User markers before scope expansion.
The same prebuilt statement therefore sees own source/profile/User writes before
commit; rollback restores earlier values. Committed page plans must show zero
executed source-fallback loops. Every branch and dirty-table node remains visible
to observers and the unchanged400work calculation. Explicit early
`SET CONSTRAINTS ... IMMEDIATE` followed by more writes is an unverified
administrative path, not a claimed canonical API transaction. Standard stronger
isolation may reject serialization; no automatic replay is introduced.

## Query, migration and acceptance boundaries

The typed read admits two physical source leaves, expands only static slots0..24,
checks exact company/Matter/source IDs and orders before the existing limit+1.
A materialized bounded result extracts the current actor name from that parent leaf. Every
introduced relation, CTE, Values/filter/sort/join node, removed row and loop must
remain in the original400work calculation. No source-table or directory hydration
is hidden in a SQL function, opaque text wrapper or unobserved helper. No planner,
statistics, ANALYZE, VACUUM or timeout waiver is used.

Migration0005follows0004without changing historical migrations. New tables and
SQL functions are source reviewed; function execution is revoked from PUBLIC.
DDL/parent-scope acquisition uses the existing bounded migration controls. A
failed upgrade rolls back. Downgrade refuses before DDL, including an empty
projection; real catalog/raw-row/revision preservation tests are required.
Canonical map, compiled projection and actual changed-migration preflight remain
mandatory. A populated privacy downgrade test is separately pinned to its actual
historical0004boundary so it cannot accidentally accept this newer refusal.

New tests cover old-column CRUD, dense order, large notes, full DTO/reload and
money, source+projection+audit/outbox rollback, foreign labels and parent moves.
PostgreSQL sources add both actual key-fence directions, User-name/new-parent
overlap, a preheld Matter inversion control and a waited same-parent statement
seeing a committed peer. Existing plan tests retain400/5s and inspect the actual
new indexes before/after seeding in both source cohort orders.

The first complete SQLite/common31 run reached all93phases with28passes and
3catalog-comparison failures. Two read-only observations of the same retained
SQLite database proved22byte-identical partial-index predicate TextClause
objects compared by identity; the narrow test fix preserves their exact SQL text
and every other catalog field. Its envelope also recorded only external `.codex`
directory timestamp drift, with all3819file bytes/metadata unchanged. These
failures are retained. The complete independent cache-clone replacement32 then reached all96phases:
30passes and two structural guard failures, with all4136source/installed files
and every ancestor metadata observation stable. Those two actual statements were
typed read-only but used three unlisted standard functions; the narrow shared
guard correction now admits only its two remaining actual constructors/observers
(`jsonb_build_object`, `txid_current_if_assigned`). Unused `md5`, assigning XID
variants, arbitrary functions/packages, opaque SQL and nested DML remain denied.
These results and the original reporter's stale71progress label (actual76
collection was checked) are retained. The whole affected inventory must run
after the current parent-label source closes. Production PostgreSQL plans, migration backfill and
concurrency behavior remain UNRUN. The merged fpdf2 security baseline is admitted
separately; it does not certify this candidate. Global Mine/Team/Unassigned
queue performance remains a separate unresolved architecture task.
