# Sources navigation-instance ownership — 2026-11-14

J20/M22; US-MOB-03/05/08; SOURCE-02/03/04 and the independent83-case
platform inventories. **Partially implemented / Partially fixed / NO-GO**.
This follow-up preserves the earlier cursor-only and evidence-stream repairs.

The preceding2a053086 candidate passed all21source gates and its actual Android
build/independent APK postflight. Before full native execution, the adjacent
route audit found that one company/type-keyed cursor host could be reused for
a nested Sources entry or another tab. A pop/push batched before a commit could
also replace a navigation slot without replacing that host. These builds and
gates remain valid for their source, but do not establish release acceptance.
No native case credit transfers to this follow-up.

The expanded source harness extracts, transpiles and executes the actual
`MobileApplication` Sources JSX fragment with the real list and resource hooks.
Its original three new journeys failed against the preceding fragment:
nested Sources showed Page2 instead of a new Page1; another tab inherited Page2;
a same-index batched replacement retained the former row. Preserve
`/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/source-list-ownership-red-01.tap`.
This is source-level reproduction, not a native run.

Each new Sources route now receives a synchronously allocated navigation
instance before dispatch. The safe-integer counter refuses overflow. Enumerate
all retained source-list entries across all tab stacks and key their cursor
hosts by company, originating tab, selected source type and instance. Activate
only the exact current route object in its originating tab. Position/index is
not its identity: popping and recreating the same slot in one commit produces
a new instance. Existing inactive hosts return null, unmount readers, abort
requests and retire controls. Retain only each route's cursor/history; Back
performs a fresh authorized read. Removing an entry unmounts its cursor, while
older entries and other tabs preserve their independent cursors. Type changes
and company/session ownership continue to reset the appropriate hosts.

Regression coverage executes the actual app mapping for nested lists, separate
tab cursors, batched replacement, inactive requests/controls and late aborted
reader results. It also executes the actual creator callback twice before a
commit and proves distinct IDs plus overflow refusal. Descriptor guards reject
invalid/repeated instances and independently bind company/type/tab. Existing
fresh-authorization, revocation, page bounds, inactive callback and reset checks
remain intact. These source tests do not replace fresh Android/iOS builds and
all83 native cases per platform; those gates remain required.

The adjacent trace audit also restores one canonical ID-bound `find` event and
its existing wrapped budget charge before row positioning (and the original
scoped-segment find event). Polling does not duplicate that event; budget or
recorder refusal precedes native lookup. Single gesture/click evidence remains
explicit. This does not increase a native workflow or action budget.
