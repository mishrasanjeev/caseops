# IP18 Production Tracker Scale Repair

Status: production acceptance failed on merge
`ee351e0c30d2687a3adfe8f081fcbf79eb9e8bc0`; no fix or production closure claimed.
Write50 naturally completed47P/3F, zero skips/retries, not a timeout. The two
tracker cases failed at their first50-row assertion; the Calendar case is separate.
Private maintenance remains paused; no scheduler resume or workbook upgrade.

## October 18 CodeQL Gate Repair

Candidate1954cd14/PR543 is NOT accepted. Hosted API8879passes, PostgreSQL3129
passes/9387phases and browser588passes/17reasoned skips completed, but the separate
CodeQL result check117572089685 failed on alert584 at ip_portfolio.py:1291.
Its analysis-upload workflow was green; that was not a complete security verdict.
The conditional import precedes the only assignment making category_context
non-null, so a runtime uninitialized-variable failure was not demonstrated.
Initialization is now explicit without weakening policy or day fences;
fresh hosted analysis, not a suppression or a fabricated runtime RED, must clear it.

Two additional behavior controls passed on the unchanged service before this
structural clarification: unfiltered pages require no renewal policy/clock, and
an in-request local-day change rejects the page without emitting a cursor while
the next fresh read succeeds. After the clarification, all32 selected default
family/cursor/route cases passed, with19 native variants deselected rather than
claimed as executed. These are behavior-preservation proofs, not a runtime RED
or a clean CodeQL result. The next candidate still needs fresh complete gates.

Alert584 was created03:12UTC and its data acquired03:13; actionable parent
notification was delayed until04:25 while unrelated CI continued. That was an
operator failure. Early check-run/ref-alert monitoring and immediate failed-verdict
handoff are now required before the next costly Docker gate.

Docker07 on this unreleasable candidate was explicitly operator-cancelled.
Four complete native groups passed1565cases; groups05/06 are interrupted,
07/08 and every browser phase unstarted. These are incomplete, not product
failures or accepted replacement coverage. Child06 was canonically retained,
all owned processes reaped and exact-project resources removed. C source held;
the sealed proof is docker07-reconciliation-01/operator-cancelled-final.
No merge, replacement deployment, scheduler resume or workbook upgrade occurred.

## Earlier Source And Performance Evidence

The retained read-only diagnosis proves the exact tracker API returns the right
50+1 fixture identities and source states in6.2-9.7seconds. Initial unfiltered UI
loading took40.3seconds over a retained portfolio of1345 records. Five rapid filter
scopes can overlap; old query signals are not forwarded to transport. This supports
latency/work amplification, not stale saved-view data as an established cause.

Static PostgreSQL compilation of M produced1,180,096-byte filtered count SQL with
920 textual audit/import provenance bodies and a393,370-byte page statement.
The source repeats date validation/provenance and stop predicates. These are
compiled shapes, not measured PostgreSQL execution/JIT attribution.

First regression imports1345 synthetic records through actual upload/commit/
resume in an isolated PostgreSQL HTTP fixture, including the exact53-row target.
The width uses the observed portfolio baseline; no private audit-row count is
invented. It retains actual requests, SQL, settings and EXPLAIN ANALYZE plans
before checking exact50+1 identities/source states, existing10-second visible
budget, and bounded SQL source-fact expansion. Product files were M for RED.

Measured native RED is retained at `tracker-retained-native-red-05`: one exact
case, three phases P/F/P, natural exit1, source hold unchanged and owned resource
cleanup/reaping complete. Exact50+1 rows, global counts and source provenance
passed. Sequential query/from/to/missing/continuation took19.89/21.33/48.65/41.08/
22.69seconds. The missing-count EXPLAIN generated17,372 JIT functions, with28.18s
JIT inside29.11s execution. Emitted count SQL was1,394,068bytes with920 audit/import
proof bodies. This establishes JIT-dominated expression expansion in the owned
retained-width reproduction, not a direct production SQL-plan measurement.
Earlier attempts01-04 are preserved as setup/admission failures, never test REDs.

Tracker native GREEN01 completed naturally0 with three passed phases, identical
admitted source/runtime hashes and owned PG/network cleanup/reaping. Its six
HTTP reads took0.63-1.67seconds with the same exact50+1 IDs and all six counts.
The filtered count emitted29,030bytes and one audit/import proof body; EXPLAIN
execution was12.027ms with no JIT. Initial proof rows examined were1345 audit
plus1345 import rows; filtered reads examined53 of each. PostgreSQL JIT settings
and the original10-second visible budget were unchanged. This is an uncommitted
tracker-only scoped proof, not whole-tree acceptance or deployed closure.

Frontend cancellation RED02 retained24P/2F; the two new failures proved absent
React Query signal propagation and absent fetch cancellation. GREEN02 retained
all43 intended identities passed, with six frontend source hashes held. It also
proves a late broader response cannot replace the final filter scope. Existing
deadline/retry behavior and saved-view/export filter assertions remain intact.
The first expanded GREEN01 retained42P/1F from a stale one-argument saved-view
mock expectation; GREEN02 explicitly includes the new signal argument. The first
frontend RED01 did not launch because the local shim path was wrong; it is not
a test reproduction.

The first small source-facts unit passed at its original revision. Expanded
unit02 retained1P/1F: its ACL fixture incorrectly expected direct restriction to
grant the creator continued access. That is not a product regression. The new
fixture establishes the two-row baseline before restriction and will assert
the actual member identity, omission and fresh revocation independently.
Unit03 then passed both current cases (six phases), naturally0, with its five
admitted source hashes unchanged. This includes party-only portfolio search,
restricted omission and revocation between preview/queue plus fresh tracker
counts. Native coverage remains pending; this is not a substitute for it.

Adjacent portfolio/saved-view/family/export remains OPEN. It still uses M's
original expanded predicates until the retained-width adjacent RED completes.
Adjacent native RED01 did NOT reach those measurements: the unchanged import
fixture's final500-row background job resume returned after107.60seconds and
failed its original90-second assertion. All three phases completed P/F/P,
source hashes held and owned resources/processes were removed/reaped. It is
not portfolio RED and is not classified as a product regression or a proved
environmental cause. No per-request SQL/GC evidence was captured for that
boundary. Preserve it as unresolved; do not hide it by extending a deadline.
The extended regression retains actual source SQL/plans, SELECT count, candidate
row work and exact51 identities for saved-view reload, paginated listing,
families and the dated50000-row-limit export preview. Broader party/class/client/
lawyer/team search semantics must remain unchanged. Native correlated-term
states (later active, tied ambiguous, later completed), competing retained
versions and restricted-ACL cases are pending; the small unit is not that proof.

Pending: adjacent measured RED/repair/GREEN and final native source-fence
inventory; combined review and complete replacement release/production gates.
No timeout increase, JIT disabling, ACL cache or policy weakening is authorized.

Adjacent RED02 also remains incomplete: the test demanded51 family rows from M's
HTTP route, which omitted all five date/category fields and returned53. This was
the old implemented behavior, not the intended contract. Parent's independent
family-filter contract RED subsequently proved all7 cases failed, confirming an
API wiring defect; parent corrected it and retained7/7 GREEN. All dated list
identities/counts passed in RED02. Its optional
passive GC recorder overflowed4096 phases, preserving an explicit incomplete
summary, not an environmental diagnosis. Captured list/count statements emitted
282189-282985bytes and180 provenance bodies while returning in2.00-2.26seconds.
The next attempt corrects the family oracle to exact53 target identities,
preserves the dated saved-view/list/export51 expectation. RED03 did not execute
the fixture: the observer's existing hard constructor cap correctly rejected
the proposed65536 buffer. Preserve it as a harness failure. Following parent
direction, the next attempt uses the original4096 cap only during measured
read requests, not the entire import fixture. Request-level numeric SQL timing
still covers setup, but no complete setup GC attribution is claimed. No
production GC policy, request budget or assertion changed. All earlier attempts,
their full exceptions and source holds remain retained.

Adjacent RED04 hit the existing600-second outer wrapper while importing the
retained fixture. Only setup completed; call/teardown and adjacent measurements
are absent. Its original4096 GC cap captured measured reads only (none reached),
and per-request numeric SQL counts/timings remain retained. No setup GC attribution
or pure performance RED is claimed. Owned controller/runtime processes exited,
container/network were removed and port49129 was closed. No deadline was raised.

The focused adjacent source regression then completed RED1P/1F naturally: all
broader party-search, ACL/revocation, count and export assertions passed before
the final emitted-SQL bound failed (229410-229754bytes,200 proof bodies on SQLite).
This independently agrees with RED02's actual native282KB/180-body queries while
not upgrading its incomplete whole-case result. The portfolio adapter now stages
distinct candidate dockets after its complete existing scope, retains every outer
application predicate, preserves its broader search ORs and uses scalar staged
dates/stops. Candidate projection explicitly retains original FROMs. The focused
default GREEN passed2/2 naturally with no timeouts/JIT/ACL-policy changes.
Fresh native28-case source/ACL/term/current-version/worker matrix and retained-
width dated list/export/family measurements remain pending. The parent owns
family HTTP filter wiring, its contract tests, generated types and browser spec.
The final benchmark requires the exact51 missing-date family/list/export IDs,
retains a query-only53-family control and adds a separate all-five-filter due-date
profile requiring the exact one positive docket. Nonempty renewal-date bounds
cannot truthfully select the51 records whose renewal date is missing.

Native source/ACL/term matrix GREEN01 completed2026-10-18 02:44UTC: all28 exact
collected identities across the four selected files passed all84 setup/call/
teardown phases; JUnit28 and the session's natural exit0 agree. Counts by file
were20 tracker filter/current-source cases,2 source-fact/provenance/ACL cases,
3 competing-term cases and3 native worker/history cases. This includes later-
active, tied-ambiguous and later-completed terms; all six counts; sibling source
isolation; correction's exact `tracker_row`; retained versions; restricted actor
and export revocation; and the existing32000-row historical work bound. Admitted
source/runtime and harness hashes held. All owned processes were reaped, zero
HTTP databases remained before shutdown, owned PG/network were removed and
port49129 closed. Evidence: `tracker-final-fences-native-green-01`.

This matrix predates the separately reviewed family-cursor repairs. Independent
review found pre-existing SQL-lower/casefold ordering mismatch and missing
filter/grouping/actor cursor binding. Fermat owns only the family-cursor helpers,
select/consumption and its dedicated regression; `_scoped_query` is reserved
unchanged. No final retained-width source admission will start before that
coordinated freeze. This is scoped local proof, not final-source, full-gate,
production repair acceptance or permission to resume private maintenance.

Family cursor source is now frozen after complete default-suite GREEN30/30,
90passed phases and zero skips across the new cursor, existing family and shared
route-contract modules. The cursor retains the exact emitted SQL lower-sort key,
uses a bounded versioned HMAC payload, binds company/member/grouping/all filters/
limit, and binds current policy/local day when categories apply. Continuation
still rechecks current ACL. Earlier RED01's two invalid-email fixture failures
are separate from its12 actual cursor reproductions; corrected RED02 preserves
the remaining observed failures. Collection and source hashes are retained in
`family-cursor-reconciliation-01`. No native cursor pass is claimed yet.

Standard discovery includes3129 unique PostgreSQL cases in eight exact-once
groups, including17 native cursor parameters and the retained-width benchmark
once. Its dated list/family/export measurements are unconditional and the normal
Docker driver retains all raw SQL, plans and measurement summaries recursively.
Do not repeat a separate long native wrapper: the fresh committed-source full
Docker gate is the next authoritative source/adjacent/native cursor acceptance.
Green hosted CI, canonical merge, guarded deployment, complete production replay,
clean maintenance and guarded cadence resume remain separate required steps.
