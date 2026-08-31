# CaseOps agent instructions

## User-approved spreadsheet fallback

For standalone spreadsheet creation or editing in this repository, prefer the
configured `@oai/artifact-tool` runtime whenever it is available. If that
runtime or `load_workspace_dependencies` is unavailable, the user explicitly
approved `openpyxl` as the fallback on 17 July 2026. Continue to apply the
spreadsheet skill's formatting, formula, inspection, and visual-verification
requirements when using the fallback.

## Permanent regression learnings

- A green source-tree test is not a deployed fix. Build the current source,
  verify the exact image/revision serving production, and rerun the same dated
  Playwright spec against production before marking an item fixed. Never use a
  stale `next start` build as evidence.
- Responsive acceptance tests must assert the user-visible surface at a
  narrow viewport, including every action/link in a grouped control. Nested
  flex containers must be explicitly shrinkable (`min-w-0`), full-width on
  mobile, and wrapping; an element merely existing in the DOM is not enough.
- Matter lifecycle state is authoritative and fail-closed: only the dedicated
  lifecycle endpoint may dispose or reopen a Matter. Generic metadata PATCHes,
  imports, workers, and child updates must not reactivate terminal rows.
  Status, `is_active`, lifecycle version, audit events, and operational-child
  neutralization must change atomically under the parent lock with an
  optimistic-concurrency token.
- A lifecycle regression is not complete until it proves dispose, stale-write
  rejection, operational-view suppression, controlled Disposed -> Intake
  reopening, no child resurrection, and final-state persistence after reload.
- `main` is the canonical source and release branch. Before declaring a
  change complete, ensure the validated commit is fast-forwarded or merged
  onto `main`, push `main` when remote publication is in scope, and verify
  that local `main` and `origin/main` resolve to the released commit. Do not
  leave completed fixes only on an agent branch.
- A production release must keep proving that its candidate is the current
  `origin/main` across long-running builds and mutation boundaries. Refresh
  the remote ref before cloud work, after image builds, immediately before
  routing, and before release-owned QA/certification; fail closed when main
  advances and revalidate the new canonical revision.
- Performance acceptance must bound total work, not merely raise timeouts:
  cap candidates and child rows, prevent N+1 loading, batch provider calls,
  give interactive provider calls a deadline, and test production-scale query
  counts. After an abandoned request, verify an unrelated endpoint remains
  responsive so server-side starvation is not missed.
- On a concurrency-one service, a page must not fan out duplicate supporting
  requests when the primary response already contains that data. Interactive
  paths may not scan corpus-scale tables, resolve/download models or tokenizers
  over the network, or initialize model sessions on demand; use catalog
  estimates/materialized counters, baked local assets, process caches, and
  startup warm-up, then assert the end-to-end production latency budget.
- Cloud Run warm capacity must be configured at service level, not pinned to
  each revision. Production deploys must clear obsolete revision tags and
  verify latest-only traffic; otherwise tagged revisions with old pinned secret
  versions can keep restarting and consume capacity after credential rotation.
- When manual and bulk workflows select the same legal hierarchy, they must
  resolve one server-owned active catalog, persist the catalog ID and derived
  lineage, and reject inactive, ambiguous, mismatched, or invented entries.
  A UI-only hierarchy fix is incomplete.
- A controlled `Disposed -> Intake` transition and a later explicit
  `Intake -> Active` transition are not silent reactivation. Reopen audits must
  distinguish those events and prove terminal immutability across generic
  PATCHes, imports, workers, children, operational views, audits, and reloads.
- Responsive control groups must be tested against the width available after
  navigation and sidebars, not only the browser viewport. Assert useful input
  width, sibling non-overlap, and full visibility at widths immediately below,
  at, and above every breakpoint; `scrollWidth == clientWidth` alone can still
  hide a control that flexbox collapsed to zero.
- A legal-operator workflow must not ask the browser to invent server-owned
  identifiers, tenant hashes, catalog keys, or candidate counts. Resolve tenant
  scope from the authenticated context, expose the same reviewed catalog used
  for admission, reject invented entries, and surface the API problem detail.
- A non-executable diagnostic record does not need a manual approval workflow.
  Remove approval routes, capabilities, and UI for that record while keeping
  destructive execution unavailable through a machine-enforced fail-closed
  boundary.
- Bug-workbook summary tabs are not authoritative. Count and classify the
  populated issue rows, reconcile any stale totals or copied summaries, and
  report the discrepancy before implementation.
- Investigate a reopening report from persisted lifecycle state and audit
  events. Do not infer an automatic resurrection from an explicit, audited
  `Disposed -> Intake` transition, and do not weaken lifecycle protections to
  make a UI symptom disappear.
- A cost reference is not permanently valid merely because it was active when
  first linked or approved. Every workflow transition that depends on an
  estimate, fee, actual, invoice, or other cost evidence must re-resolve the
  stored reference under the current tenant and docket, require the active
  lineage row, and fail closed after void or supersession until an explicit
  replacement is selected. Retained historical events must keep their original
  immutable references.
- Dated Playwright journeys must enter the current user-visible work area
  before asserting a nested workflow. When a page adds tabs or durable view
  routing, update the dated specs to select that tab or deep link and rerun the
  complete journey; an old locator timing out on the default tab is test drift,
  not proof that the underlying workflow is absent.
- When a tenant already has an active private generation, creating a Matter or
  IP docket must emit a source-change event. If no prior projection exists to
  tombstone, invalidate the active verification manifest so bounded maintenance
  rebuilds it; otherwise new records remain permanently unavailable to saved
  source-bounded workflows. Production QA targets must be seeded before the
  exact-release private rebuild and their projections must be asserted.
- GitHub evaluates a workflow graph from the triggering branch even after a
  later checkout switches the workspace to the exact serving release. A newly
  introduced optional production gate must verify its release-owned config is
  present after that checkout and must never execute newer test code against an
  older serving release. Canonical deploy dispatch still requires current main.
- Private-projection rebuild bounds must be derived from observed production
  tenant volume, not small fixture assumptions. The 2026-09-01 production
  baseline was 9,820 eligible projections; keep the 20,000-row cap, 50-row
  commit batches, tenant isolation, and explicit bounded error detail under
  regression. Never silently truncate a rebuild or hold parent locks across it.
