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
- Every provider-normalized identifier exposed by CaseOps must round-trip
  through the corresponding CaseOps input schema. Do not impose guessed
  provider formats (such as a minimum court-code length); preserve bounded
  provider-published values and prove lookup-result-to-follow-up-search flows.
- When a client bulk file puts a configured leaf court in a hierarchy column,
  resolve the active court name or approved catalog alias before category
  validation. Alias data belongs in the server-owned catalog, never in parser
  branches. Populate lineage only for one active match; reject conflicts and
  collisions at the source row. Keep template, preview, commit revalidation,
  audit preservation, and manual-entry behavior aligned, and regress unique
  names, aliases, inactive configuration, ambiguity, 500-row bounded work, and
  original input persistence.
- A licensed-provider activation must use machine-verifiable runtime terms
  metadata, dated official pricing evidence, positive budgets, retention, and a
  server-side secret. Do not introduce a human approval key or route. When the
  provider mandates attribution assets, render its supplied responsive asset
  unaltered and assert that exact user-visible surface before activation.
- A tenant AI-policy disablement must fail closed across the entire assistant
  surface, including scope discovery that returns private record labels. Gate
  discovery, session creation, retrieval, generation, and actions with the
  same server-owned policy and typed recovery error; a disabled toggle with a
  still-working picker is not a complete fix.
- A private-projection stale-writer rejection during a rebuild is a working
  security fence, not proof of corruption. Remove the partial shadow, keep the
  active generation fail-closed, and defer only repairable blockers while their
  persisted repair age remains inside the bounded SLO. Repeated concurrency
  must be regression-tested across consecutive maintenance runs; unsafe
  blockers and SLO breaches remain release-blocking.
- Provider rate limits, timeouts, and generic outages are transient availability
  states, not corrupt records. Bound retries and apply a machine-scheduled
  cooldown, but never permanently quarantine a tracked case or require human
  replay solely for a transient response. Auto-release legacy transient
  quarantines and prove successful recovery in regression tests.
- Every object node in a provider-facing strict structured-output schema must
  reject additional properties. Do not use bare dictionaries in an LLM response
  contract; recursively assert `additionalProperties: false` in the generated
  JSON Schema.
- Frontend validators must mirror the complete nested API contract, including
  optional source-action target identity. A page test must exercise canonical
  payloads rather than accepting a locally simplified fixture.
- Legal-reference pickers must only offer Acts that have verified selectable
  sections and must distinguish an honest empty catalog from catalog- and
  section-load failures. A visible Act with zero sections is not a usable option.
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
  commit batches, tenant isolation, and sanitized bounded error detail under
  regression. Each batch must lock/check the shadow epoch once and bulk-write
  projections/scopes; a 10,000-row PostgreSQL regression must bound total SQL
  statements and prove a concurrent epoch writer remains responsive. Never
  silently truncate a rebuild or hold parent locks across it.
- A destructive production canary must be rerunnable without resurrecting its
  terminal fixture. Bootstrap a new release-scoped iteration, preserve every
  disposed predecessor, discover the one active iteration through public
  server-owned identifiers, and prove both idempotence and terminal immutability.
- Private-index rebuilds must not retain source-row foreign-key locks across an
  unbounded tenant transaction. Commit unreadable shadow projections in bounded
  batches, fence every batch with the captured security epochs, remove partial
  rows when a shadow fails, and prove on PostgreSQL that ordinary IP writers
  remain below the lock-timeout budget while projection scopes are inserted.
- An HTTP 200 from an LLM provider is not evidence of valid structured output.
  Use the provider's native strict schema path when available, preserve the
  existing validation boundary for every provider, and test malformed/refusal
  behavior so legal reviews cannot fail later on truncated free-form JSON.
- Authentication, MFA, and capability reads must not dirty shared platform
  administration rows. Select scalar policy/capability data on ordinary tenant
  paths, keep founder seeding idempotent, and never swallow a database exception
  while leaving the request session rollback-only. A PostgreSQL regression must
  hold the shared row lock while an unrelated tenant mutation still completes.
- A schema-valid LLM response can still violate a legal-safety rule. Never
  weaken the fail-closed detector or hide the failure with a browser retry.
  Persist the rejected model-run evidence, revalidate tenant access, target
  lifecycle, private-generation manifests, and frozen source versions, then
  allow at most one server-side regeneration that does not echo the rejected
  text. A second violation remains terminal and must retain its audit linkage.
- An external model call must never wait while the request owns an open
  database transaction or parent-row lock. Complete read-only retrieval and
  policy/quota preflight, release the transaction, invoke the provider, then
  start a fresh transaction for durable usage accounting and reload tenant
  access plus the authoritative lifecycle lock before model-run,
  recommendation, or audit persistence. Regression tests
  must assert the session is out of transaction inside the provider callback
  and that a concurrent disposal wins without leaving generated rows behind.
- Initial provider search and tracked-bookmark recovery are separate failure
  boundaries. A recovery-only regression cannot close a search defect. Validate
  user-supplied provider codes before a credit-bearing request, test the exact
  reported search inputs through the browser, and prove malformed or invented
  identifiers result in zero provider calls.
- Configured credentials do not prove that a paid provider is operational.
  Classify authentication, billing exhaustion, rate limits, timeouts, and data
  errors separately; expose safe actionable copy, keep billing recovery free of
  manual replay gates, and require a real paid-path result before describing the
  integration as end-to-end operational.
- A populated statute seed is not a selectable verified statute catalog.
  Verified release provisions must carry exact official text, a text hash,
  official publisher and issuing body, an exact source version, and a checked
  section-level link. Pin and execute the current seed image before production
  traffic, then assert a positive verified provision through API and Playwright;
  never satisfy acceptance only with a synthetic local statute row.
- A private-output manifest must distinguish a relevant source/access change
  from a benign shadow-generation rebuild. Reauthorize an unchanged saved
  source only when the retired projection is not tombstoned and the active
  generation has the exact same complete source/type/id/version/hash multiset
  under the current ACL; relevant source, access, or tombstone events remain
  fail-closed.
- A synchronous interactive AI call in an async route must run off the event
  loop, and its total provider budget must fit inside the platform deadline.
  SDK retries must not multiply a per-attempt timeout past Cloud Run's limit;
  after a provider timeout, regression acceptance must also prove an unrelated
  endpoint remains responsive before a single bounded user-level retry.
- Automated suites and persistent QA/test tenants must never call paid external
  APIs. Playwright sends `X-CaseOps-Automated-Test: no-paid-providers`; local
  and Docker tests use deterministic provider emulators; scheduled provider
  polling excludes configured test tenants; and exact-release verification
  consumes stored, hash-verified evidence only. A deliberate live-provider
  check is a separately budgeted operational action, never part of bulk or
  regular regression testing.
- The explicit no-paid-provider request marker is authoritative in every
  runtime, including production and real tenants. Do not make it depend on a
  test-looking tenant slug. Keep funded production tenants out of the static
  test-tenant blocklist, seed provider-wide support from the reviewed provider
  contract, and validate activation with one opt-in, budget-capped live probe.
- Tenant document naming must not copy corpus-scale filename history into a
  request DTO. Serialize allocations under the tenant lock, probe a fixed
  number of exact candidates, and retain a regression with more than 500
  historical versions so upload, new-version, and bulk rename paths cannot
  regress into an unbounded scan or schema-limit 500.
- Private projection generation transitions and lifecycle/access/tombstone
  events must acquire locks in one tenant-first order: `Company`, then active
  and shadow `PrivateIndexGeneration` rows. A readiness-plus-activation
  transaction may never lock a generation before the tenant row. Prove the
  overlap on PostgreSQL; converting the deadlock to a generic retry or a 503
  assertion would hide the lifecycle-write failure and can look like a case
  reopened when disposal actually rolled back.
