# CaseOps agent instructions

- A row lock does not refresh an ORM identity already cached by the session.
  Refresh the locked authoritative event/generation before status, replay or
  readiness decisions; regress a committed competing application/readiness
  transition, immutable counts/timestamps, manifest invalidation and old-writer
  rejection through separate PostgreSQL sessions.

- Auth/session minting must serialize current User and Membership changes
  without conflicting with historical FK key-share provenance. Prove both
  lock orders and deactivation/cutoff rejection on PostgreSQL; provenance
  compatibility must not weaken live mutation authorization.
- Synchronous database, scanner and password work must not run on the HTTP
  event loop. Prove an unrelated real socket request stays responsive while
  the actual handler's service is blocked, and preserve its error/commit contract.
- A green CodeQL job is not a zero-alert security inventory. Reconcile fresh
  main alert states and original taint/dependency paths; suppressions and
  moving imports inside functions do not establish a permanent fix.

- Keyset performance must cover a validated cursor beyond the pre-import ID
  histogram. A first page and a generic plan can be bounded while a custom
  cursor plan scans/sorts thousands of keys. Train and assert the stale
  histogram before importing deterministic higher IDs; retain first/cursor,
  custom/generic and complete authorized pagination under the original bounds.
- Windows native JSON discovery must be written by the reporter to an owned
  fresh file and read explicitly as UTF-8, not round-tripped through console
  strings. Preserve inherited reporter settings and prior evidence; prove
  non-ASCII identities as well as nonempty ordered selection and completion.
- A Docker browser process exit cannot certify execution by itself. Retain
  unique JSON/JUnit reports and a reconciled nonempty completion for every
  serialized shard, then compare their identities and classified outcomes
  with discovery. Missing or interrupted reports remain incomplete. Isolate
  discovery from inherited reporter output variables and restore them even
  after rejection so an inventory cannot overwrite prior execution evidence.
- Upload admission must release database transactions before scanning/object
  storage, then recheck current tenant, actor, token cutoff, capability, quota,
  parent lifecycle and references before publishing. Keep the object transient
  until admission and compensate rejected storage only after rollback. Company
  quota serialization must allow unrelated audit FK KEY SHARE while excluding
  concurrent quota writers; prove the real employee/upload overlap and exact
  one-winner quota admission on PostgreSQL, not only generated lock SQL.
  Compare the captured lifecycle version after I/O, not only current status:
  a dispose/reopen cycle must reject the old request while a fresh upload into
  the explicitly reopened engagement remains allowed.
- A permission predicate can evaluate to SQL NULL when an optional assignee
  is absent. Hidden-child checks must require explicit TRUE for visibility,
  not negate a nullable predicate. Regress restricted unassigned records on
  list/detail/download/update/upload alongside authorized owner controls.
- Upload cleanup must distinguish rejected pre-commit admission from an
  uncertain commit response. After commit is attempted, retain object bytes
  unless authoritative evidence proves no durable record references them;
  never delete a committed document or automatically retry its mutation.
- A service releasing its request transaction for upload I/O must not discard
  caller-owned writes. ORM new/dirty/deleted checks miss already-flushed and
  Core SQL writes. Verify read-only ownership without assigning a transaction
  ID, reject before transport and preserve the caller's transaction. Regress
  both direct read-only HTTP admission and pending/flushed/Core-write rejection.
- Shared storage quota must count every retained IP document version once,
  including superseded and terminal history. Links do not allocate extra
  bytes; lifecycle or visibility filters must not erase physical storage.
  Prove exact historical accounting and concurrent one-winner admission.
- A destructive migration regression must use the independently fresh
  migration fixture, not require its file to run first on a shared database.
  Prove both orders beside real preceding fixtures, retain the exact expected
  preservation guard and downgrade/recovery assertions, and leave the source
  database untouched. Reordering a green run is not test isolation.
- A Git change gate comparing base...HEAD must run after the candidate is
  committed. A pre-commit green result does not cover dirty or untracked
  changes. Re-run governance and migration diff gates on the exact candidate
  before publication; preserve a superseded interrupted acceptance as incomplete.

- Projection currentness must hash exactly the same canonical text as the
  writer. Regress repeated spaces, CRLF, tabs and Unicode whitespace across
  all metadata source types through two rebuilds and retrieval. A valid
  generation manifest alone does not prove canonical-source equivalence;
  preserve exact source-version, access and tombstone fences for saved output.
- A Company-first source fix is not a complete lock-order proof when a later
  event FK or actor check can wait on Membership. Force same-actor overlap
  between background and interactive writers in both acquisition orders;
  retain non-null provenance, authorization locks and post-I/O lifecycle checks.

- An immediate post-upload source save must survive background extraction.
  ORM autoflush before a SELECT can lock the source before tenant authority.
  Acquire the shared tenant fence with autoflush suppressed after extraction
  and before source/job writes; audit document link/state writers as well.
  Prove forced worker/correction overlap on PostgreSQL and retain the browser's
  immediate save, response, source hash, reload and download assertions. Never
  hide the failed mutation with a retry or a wait for indexing completion.

- OAuth acceptance must exercise authorization scopes, token exchange, account
  identity, durable claim cleanup and the browser's return to the work area.
  An existing-connection refresh test cannot close a new-connection callback
  defect. Persist attempt identity, reject stale/expired finalizers and replay,
  release transactions over provider I/O, and recheck current authorization and
  connector configuration before publishing credentials. Failure cleanup may
  alter only its own claim, never a newer attempt or a disconnect. Prove the
  round trip with an isolated provider emulator and keep live Google consent
  explicitly unverified until an authorized account completes it.
  Retain session issuance metadata when refreshing context, recheck current
  tenant activity and session revocation, and reject unused consent issued
  before disconnect. Prove cross-provider authority-lock ordering on PostgreSQL,
  including compatibility with ordinary tenant foreign-key inserts.
  A completed callback replay must retain the healthy connection but return
  its consumed-attempt rejection, not bypass the durable consumption ledger
  with a fresh success. Assert the service result and browser notice together.
  A concurrency test must hold the observed post-rollback boundary until its
  lock probe completes. An event that merely records an earlier backoff does
  not prove the next attempt has not reacquired the row. Use entered/resume
  handshakes, preserve NOWAIT probes and require both real writers to finish.

- A repeated report must be tied to the exact serving API and web revision,
  not the newest dirty source tree. Inspect loaded selector options and the
  reported persisted records before choosing between missing deployment,
  missing source data, policy exclusion and a code defect. Preserve every
  genuinely unverified legal record's fail-closed behavior.
- A multi-file test filter is not proof that every requested file ran. Reconcile
  selected files and collected identities against the intended inventory; a
  misspelled file can disappear from an otherwise green run. Re-run the missing
  selection and preserve the earlier incomplete coverage claim as incomplete.

- A legacy-data backfill regression must explicitly establish its pre-feature
  state. Scope automatic linking off only while creating that legacy fixture,
  assert zero preexisting bookmarks, restore the prior runtime policy and
  exercise enabled and disabled ambient settings. Do not alter normal
  auto-linking or weaken assertions to accommodate setup-created children.
- Case-tracking network calls must not retain database transactions. Durable
  pre-call claims require bounded expiry and crash recovery; a bare commit can
  strand a running operation forever. Recheck the claim, current access,
  bookmarks, source identity and locked lifecycle after transport, and prove
  both manual and scheduled boundaries with deterministic PostgreSQL races.

- A long-running pytest gate must retain structured setup/call/teardown results
  as they occur, not only its final JUnit file. Do not classify buffered progress
  characters as diagnoses. An interrupted run without a completion event is
  incomplete, and prior failures remain open until their full details and the
  complete replacement inventory are reconciled. Never overwrite failed evidence.
  API coverage shards are not exempt: archive each shard's unique selected-file
  inventory, incremental journal and JUnit report alongside its coverage data.

- Isolated PostgreSQL HTTP fixtures may clone only a separately migrated,
  connection-disabled test template, never the shared application database or
  retained tenant rows. Prove identical schema/index/constraint/trigger/catalog
  state, independent tenant bootstraps and interruption cleanup. Dedicated
  migration upgrade and downgrade rehearsals must still start independently
  fresh; test-speed work cannot replace migration evidence with a clone.

- Whole-catalogue acceptance must reconcile the final provision's continuation
  pages, not only arrangement identities and hashes of extracted text. BNS
  section 358(4) was omitted on a separate page even though every section number
  was present. Inventory schedules, Orders, forms and successor enactments
  separately; a publisher-hosted PDF may itself be incomplete. Preserve failed
  acquisitions, source editions and historical references, and require positive
  attachment/reload/source-opening proof before catalogue closure.
- A cold-start optimization must preserve byte-identical route contracts and
  fail-closed malware readiness. Measure full HTTP startup beside the real
  scanner on an isolated Docker network; prove clean and EICAR scans plus
  post-start scanner outage rejection. Import-only timings cannot close a
  production latency defect or authorize weakening the scanner fence.

- Windows release-test wrappers must preserve drive-letter arguments through
  native PowerShell forwarding. Pass an explicit argument array, inspect the
  received arguments and reconcile the nonempty collected test inventory.
  A zero-test XML report is incomplete evidence, even with zero failures.
- TLS-terminated router redirects must retain the caller's scheme and origin.
  Emit a relative Location for the exact same-origin slash correction, preserve
  method/body/authentication and encoded queries, and leave publisher/signed
  source redirects unchanged. Do not solve this by trusting arbitrary forwarded
  headers, following an HTTPS-to-HTTP mutation, or retrying a failed mutation.
- A green app-config suite does not cover production-only dated contracts.
  Inventory historical assertions affected by new fields, navigation and source
  verification, replay those complete changed journeys against local Docker,
  then rerun the exact-release production suite. Keep a genuinely unverified
  negative statute alongside the positive official-source record; do not freeze
  a newly verified provision in an obsolete unverified test expectation.

- A nonselectable statute count includes retired and quarantined rows as well
  as verification-pending rows. Discover the exact state before testing its UI.
  Source-opening acceptance must exercise the authenticated, audited redirect
  and its exact official destination, not demand a bypassing external href.
- Production patent regression must reuse the dedicated QA tenants without
  bootstrapping accounts or rewriting entitlements. Keep fixture identities
  unique across retained runs, authenticate cross-tenant probes separately,
  assert exact API/web release identity and serialize mutation phases.

- Recursive graph acceptance must bound retained edge/history rows and query
  count, not only distinct nodes returned by a recursive CTE. Charge raw
  versions before filtering current edges, and prove dense/deep-history/depth
  boundaries plus successful below-bound HTTP saves and idempotent replay on
  PostgreSQL. History fixtures must reuse the canonical relationship identity.
- Inspect every failing test's structured result before classifying a run.
  A truncated first failure cannot establish the cause of sibling failures;
  fixture constraint errors are not successful reproductions of product bugs.

- Recurring production verification must survive its own destructive canary.
  Keep Intelligent Review on its persistent projected QA target. A first
  release run proves private answer creation and disposal; later runs must
  prove retained answers, exports, citations, actions, search, autocomplete,
  counts and scope discovery remain revoked, without reopening the fixture.
  Missing retained evidence is a failure, never a skip or empty success.

## User-approved spreadsheet fallback

For standalone spreadsheet creation or editing in this repository, prefer the
configured `@oai/artifact-tool` runtime whenever it is available. If that
runtime or `load_workspace_dependencies` is unavailable, the user explicitly
approved `openpyxl` as the fallback on 17 July 2026. Continue to apply the
spreadsheet skill's formatting, formula, inspection, and visual-verification
requirements when using the fallback.

## Permanent regression learnings

- Parallel pytest collection occurs on xdist workers, not its controller.
  Retain each worker's complete ordered inventory and its agreement with the
  canonical collection before reconciling setup/call/teardown results. A green
  parallel result without collection evidence cannot certify full coverage.

- Scheduled provider eligibility is distinct from configured credentials and
  live-human access. Expose the actual unattended tenant policy without making
  the response depend on the current browser's no-paid marker. A successful
  scheduler process or an excluded QA tenant cannot certify a hearing refresh.
- Next-hearing acceptance must identify the reported Matter and assert its
  actual date value in the visible list, after reload and at responsive widths.
  A column heading, a bookmark count, or a successful provider HTTP response
  cannot substitute for that outcome. Cover both CNR and case-number/court.

- A published legal PDF's arrangement, body, footnotes and judicial treatment
  may disagree. Reconcile the entire numbered inventory against pinned source
  bytes, retain explicit discrepancies and commencement context, and keep
  omitted/conflicted provisions unselectable. A verified edition is not a
  certification of current law or a substitute for missing schedules/Orders.
- Release statute seeding must preserve reviewed labels and provenance, pending
  candidates, stable IDs and immutable version history. Idempotent replay must
  not fabricate a fresh source retrieval/link check or overwrite a separately
  reviewed record merely because the body hash happens to match.

- Fresh Docker acceptance must restore the exact image's release-owned catalog
  seeds after destructive database/migration rehearsals and before Playwright.
  An empty test catalog is a setup defect, not proof that each reported Act
  lacks verified content. Preserve the failed setup report, replay the unchanged
  browser gate after the real seed, and keep content gaps separate and open.

- Fake deployment CLIs must be executable before a test launches its shell.
  A noexec temporary mount can make PATH fall through to real git/gcloud tools
  even after chmod succeeds. Fail before launch, use exec-enabled isolated
  test storage, and keep offline regression containers network-disabled.
- Product-guide search may cache bounded immutable public search metadata,
  never capability decisions or mutable response objects. Normalize the query
  once, recheck current permissions on every search, and retain the original
  performance budget plus content-change and response-mutation regressions.

- A lifecycle command's identity is its locked parent lifecycle version, not
  its calendar date. Regress close, explicit reopen and a second close on the
  same day, reject stale replay, preserve neutralized children and keep the
  prosecution conflict display aligned. Generic root events cannot forge
  lifecycle facts. Backdated close and reopen commands must show the same
  required acknowledgement in preview and commit and retain it in history.

- A terminal patent family's retained disclosure and source versions must stay
  readable to currently authorized users without reopening the record. Keep
  that permission on explicit read paths only; correction, creation replay,
  upload, document lifecycle and publication remain fail-closed. Prove close,
  historical byte-identical download, grant revocation, explicit reopen and a
  second closure through both PostgreSQL and the dated browser journey.
- Fake deployment CLIs must be executable before a test launches its shell.
  A noexec temporary mount can make PATH fall through to real git/gcloud tools
  even after chmod succeeds. Fail before launch, use exec-enabled isolated
  test storage, and keep offline regression containers network-disabled.
- Clean test storage must not hide required runtime binaries. Keep Temporal's
  real test server outside an overlaid /tmp, pin its executable path and hash,
  and run its workflow with networking disabled. A missing cache is a test
  infrastructure failure, not a reason to skip notification workflow coverage
  or enable external provider traffic.
- Product-guide search may cache bounded immutable public search metadata,
  never capability decisions or mutable response objects. Normalize the query
  once, recheck current permissions on every search, and retain the original
  performance budget plus content-change and response-mutation regressions.

- Concurrent-index migrations must recover after the column transaction has
  committed but an index build has failed. Inspect existing column shape,
  rebuild invalid/not-ready indexes, preserve populated identifiers, and prove
  an interrupted build plus a second upgrade on real PostgreSQL.
- Catalog acceptance requires a present option, a positive verified-section
  response, successful selection/attachment and persisted reload. A negative
  enabled-state assertion alone is not proof of a usable native option.
- A saved import's original rows may be retained in the tenant-scoped import
  ledger even when the preview DTO omits them. Recover the authorized job with
  bounded read-only access before asking for another source upload; never
  substitute normalized output for the original court/context fields.
- A bulk-import row may reserve duplicate-detection identities only after it
  passes validation and is admitted for creation. Invalid and skipped rows
  must not suppress later valid rows, including chains where one existing
  identity is combined with a second, previously unused identity. Preserve
  existing rows and prove commit/replay behavior, not preview counts alone.
- Downloaded import templates must round-trip in a fresh tenant. Do not put
  invented owner emails, lawyer emails, or team slugs in the importable sample
  row. Test both CSV and XLSX without silently correcting the template first.
- An explicit catalog ID does not authorize discarding conflicting supplied
  State, District, City, or Consumer Level. Apply the same context predicate
  to ID-based and name/alias-based imports before deriving canonical lineage.
- Additive Matter identifiers must survive the separate workspace DTO as well
  as create, edit, list, bulk, generated OpenAPI and frontend schemas. Verify
  retention when final identifiers arrive, search indexes, stale-write and
  terminal-state rejection, and the same browser journey on mobile and desktop.

- A horizontally scrolling table must contain absolutely positioned accessible
  labels as well as visible cells. Give its scroller a positioning context;
  otherwise an offscreen `sr-only` heading can escape clipping and enlarge the
  page. Assert document width and usable controls before, at, and after layout
  breakpoints while preserving the accessible heading and horizontal scrolling.

- A committed browser spec is not regression coverage until the standard suite
  discovers and runs it. Check the resolved Playwright inventory, propagate
  required fixture configuration into Docker, use the configured browser base
  URL, and keep synthetic global-catalog writes strictly loopback-only.

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
- Do not use Uvicorn `--timeout-keep-alive 0` as a Playwright stability fix. It
  schedules an immediate unannounced socket close and can move `ECONNRESET`
  failures between unrelated requests. Advertise `Connection: close` on the
  loopback test server and close only after the complete response. The Docker
  acceptance proxy must strip upstream hop-by-hop keep-alive response headers,
  close downstream sockets explicitly, and retain bounded upstream pooling;
  never hide a mutation transport failure behind an automatic retry.
- Every provider-normalized identifier exposed by CaseOps must round-trip
  through the corresponding CaseOps input schema. Do not impose guessed
  provider formats (such as a minimum court-code length); preserve bounded
  provider-published values and prove lookup-result-to-follow-up-search flows.
- Paid-provider acceptance must assert a meaningful returned record, not only
  a successful HTTP status. For eCourtsIndia v4, exact case-number lookup uses
  the structured `caseNumbers` filter with a public registration/filing number
  and a search-ready court code; do not substitute packed internal
  `caseNumber` values or general full-text `query`, both of which can produce a
  misleading HTTP 200 with zero results.
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
  source only when the retired projection is not tombstoned, no later event in
  the projection event ledger reaches it, and the active generation has the
  exact same complete source/type/id/version/hash multiset under the current
  ACL; relevant source, access, or tombstone events remain fail-closed in
  every generation.
- A synchronous interactive AI call in an async route must run off the event
  loop, and its total provider budget must fit inside the platform deadline.
  SDK retries must not multiply a per-attempt timeout past Cloud Run's limit;
  after a provider timeout, regression acceptance must also prove an unrelated
  endpoint remains responsive before a single bounded user-level retry.
- Automated suites and persistent QA/test tenants must never call billable
  external APIs. Playwright sends `X-CaseOps-Automated-Test: no-paid-providers`;
  local and Docker tests use deterministic provider emulators; scheduled
  provider polling excludes configured test tenants; and exact-release
  verification consumes stored, hash-verified evidence only. Automated live
  verification may read CaseOps readiness and recorded budget balances, but it
  must not omit the marker or execute search, detail, refresh, retrieval, PDF,
  or other credit-bearing calls. Normal authenticated human use remains
  available for funded live tenants under readiness and budget gates. The one
  owner-approved exception (2026-09-27) is the capped scheduled
  verification-fixture lookup described in the last learning of this file.
- The explicit no-paid-provider request marker is authoritative in every
  runtime, including production and real tenants. Do not make it depend on a
  test-looking tenant slug. Keep funded production tenants out of the static
  test-tenant blocklist, seed provider-wide support from the reviewed provider
  contract, and validate machine readiness without an automated credit-bearing
  probe. Provider-paid operation belongs to authenticated human use and
  provider account evidence.
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
- Any source-backed patent writer that later advances private-projection
  authority must take the tenant authority fence before membership, docket,
  document, or source-version row locks. When an entry point also needs the
  patent-identity advisory lock, acquire that transaction-scoped advisory lock
  first, then the tenant fence; all duplicate/identity writers must use this
  order so a waiter never holds the tenant fence while the current identity
  owner needs it. Document-version replacement takes the tenant lock first;
  taking it only when a later source-link event is emitted can deadlock with a
  patent application holding the membership row while waiting on the version.
  Regress duplicate identity waiters and version-replacement overlap on
  PostgreSQL, proving blocked writers do not retain later-order locks and the
  real projection event can commit.
- Diagnose a private-projection maintenance alert against persisted event epochs
  and the active workload. Continuous production E2E writes in a shared QA
  tenant can correctly fence every shadow; preserve the 300-second blocker,
  stop the overlapping mutation, and require one quiescent rebuild plus a
  second clean cadence. Do not label a safe stale-writer rejection as
  corruption, suppress QA blockers, or weaken the access/tombstone fence.
- Catalog completeness is not fixed by proving one positive fixture. Expose
  catalogued and verified totals separately, keep incomplete entries visible
  but disabled, and enforce one source-verification predicate on every UI and
  API write path. Never describe a partially verified seed as a complete
  selectable legal catalog.
- A no-paid-provider rejection is successful test isolation, not evidence that
  the configured provider is unavailable. Regular, bulk, Docker, and
  production regression runs must assert the rejection without spending.

- Private-index embedding reuse may reuse vectors only; it must preserve the
  canonical `source_version` emitted by the current source-version function.
  A legacy timestamp version with the same content hash is not interchangeable
  with a content-hash version. Regress Matter and IP-docket rebuilds from
  legacy versions and assert exact current-version projections before accepting
  a generation or running release-owned retrieval QA.
- An async review history and its selected detail must converge on the same
  terminal record. If the list returns full updated DTOs, a cached running
  detail cannot remain visible after the list turns terminal and disables its
  polling. Regress the running-to-abstained transition through the actual UI,
  including the visible reason, without adding redundant supporting requests.
- Production browser assertions for an application alert must scope to its
  workflow panel. Next.js also mounts an empty route-announcer alert; an
  unscoped role query can fail strict mode after the real error has rendered.
  Keep the exact-release production journey running through its later visible
  result, not merely the first API checks.
- A tamper regression must actually change the signed input for every random
  token. Replacing a hex signature's final character with a fixed value is a
  1-in-16 no-op when it already has that value; choose a different character
  and assert rejection, including that formerly colliding case.
- Production verification must fit the repository's effective 40-minute
  GitHub-hosted job ceiling. Serialize mutation-capable QA shards as separate
  jobs, pin and recheck the same exact serving SHA at every shard boundary,
  retain sibling results after a shard failure, and write release evidence only
  after every required shard succeeds. A suite canceled after earlier green
  subsets is incomplete, never a product pass.
- Scheduled production monitoring must stay read-only. Run destructive QA
  journeys only for an exact-release dispatch while private-projection
  maintenance is paused and drained; after the mutations stop, require one
  converged maintenance execution and a second clean no-rebuild execution
  before resuming cadence. Do not suppress the QA tenant, relax the 300-second
  SLO, or treat a stale-writer fence as corruption.
- A recurring-job drain must size its complete unfiltered execution scan from
  observed retained production history, not a small fixture. The five-minute
  private-projection job retained 1,768 executions on 2026-09-23; preserve a
  bounded sentinel above that volume and fail closed when the sentinel is hit,
  because a newest-only sample can hide an older running execution.
- Release control-plane reads that establish immutable image identity may retry
  transient transport and 5xx failures with a small finite bound. Revalidate
  the digest format after every attempt and fail before migration or routing if
  the bound is exhausted; never turn the retry into an unbounded release wait.
- A Cloud Run Job's `executionCount` is lifetime creation count, not retained
  history size. Drain retained executions through bounded v2 API pages with a
  hard inventory sentinel, validate every execution identity and terminal
  field, and require two clean samples after pausing. Do not put gcloud's full
  client-side history materialization behind a shorter sub-deadline; the 1,899
  retained projection executions took 44 seconds through gcloud on 2026-09-23.
  Provider-paid operation is established through authenticated human use and
  provider account evidence, never by an automated credit-bearing canary.
- An automatic next-hearing sync is an identity-and-evidence workflow, not a
  blind field copy. Prefer normalized CNR; otherwise require one exact
  case-number-plus-court match. Zero, multiple, or mismatched results must write
  no matter data and must retain a distinct machine-readable response class.
- Scheduled hearing sync must cover bounded batches of both newly linked and
  pre-existing eligible matters without N+1 provider calls. Resolve the nearest
  evidenced non-past date, distinguish confirmed absence from unavailable or
  malformed provider data, retain the last valid date on failure, respect an
  explicit manual lock, and never mutate matter lifecycle state.
- A daily job's product time, Cloud Scheduler cron, timezone, runtime window,
  support-matrix SLA, and checked-in inventory are one contract. Test the exact
  18:00 Asia/Kolkata boundary and pause every superseded scheduler name; a job
  deployed with a window that excludes its own cron is not complete.
- Provider-authoritative, uniquely verified hearing updates do not require a
  human approval queue. Machine-enforce identity, non-past evidence, tenant
  scope, manual locks, disposed-matter suppression, idempotency, and one running
  refresh per tracked case, then apply the update and retain audit history.
- A provider refresh can promote a case-number identity to a CNR that already
  has a canonical tracked row. Never blind-update the unique identity key or
  let one tenant poison the whole scheduled poll transaction. Converge active
  bookmarks and dependent references onto the canonical row under a lock,
  retain the retired row as hashed lineage, and isolate each case mutation in a
  savepoint so a database constraint failure becomes a typed per-case outcome.
- An API login token is not browser-session evidence. A production Playwright
  test that opens authenticated UI after an API login must establish the
  client session context or complete the visible sign-in flow. Exact-release
  checks use the API-owned `/api/build` route and the web-owned
  `/api/release-identity` route; never assume the services expose symmetric
  identity paths.
- Every credit-bearing provider path must reserve against its effective
  monthly budget scope and publish the settled spend through the existing
  billing owner. When the product promise is a per-account limit, aggregate
  every provider in that shared scope; do not multiply the allowance by
  treating each provider as an independent default budget. Human entitlement
  must not be inferred from a test-looking slug; the explicit automation
  marker is authoritative, and
  unlimited access must come from an active policy row rather than a company
  name check in request code.
- Provider entitlement and readiness reads must remain read-only before an
  independent spend reservation. A helper that silently creates a subscription
  or flushes unrelated state can deadlock SQLite tests and hold production
  locks across provider I/O. Scheduled workflows that already own a writer
  transaction may reserve in that transaction, commit, and only then call the
  provider.
- Shared court-complex labels are not unique legal identities. Resolve one
  active canonical court or reviewed alias using state, district, level, and
  category context; preserve the original input and reject zero or multiple
  candidates. Never let a short consumer-forum name shadow district-court
  aliases or encode location guesses in a spreadsheet parser.
- A legal alias master is not complete when aliases exist only as migration
  seeds. Provide governed platform configuration for canonical target, alias
  type, source evidence, review state, activity, actor attribution, optimistic
  version, and audit reason. Pending and rejected rows must never resolve;
  ambiguous bulk rows must return bounded canonical candidates with lineage.
- Governed catalog mutations must reject explicit null or no-op updates at the
  request boundary and lock the canonical parent before the alias row in one
  stable order. Do not use eager outer joins in a PostgreSQL `FOR UPDATE`
  query; prove create and update behavior on real PostgreSQL as well as SQLite.
- Public product copy, operator guidance, API status, and billing projections
  must describe the same provider budget scope enforced by reservations. After
  changing per-provider to shared-account semantics, search every user-visible
  and governance surface for stale wording and regress provider contribution
  separately from total budget use.
- Read serializers must not mutate lifecycle fields to make legacy state look
  consistent. Project the response from an immutable payload, then diagnose any
  reported reopening from persisted status, lifecycle version, and audit events.
  Only the dedicated lifecycle command may persist a controlled reopen.
- A private projection event may ORM-mutate only the active generation captured
  on that event. Building and ready shadows are unreadable and must be fenced by
  epoch advancement, not loaded into a lifecycle transaction where failed-shadow
  cleanup can delete them and cause `StaleDataError`. Tenant-wide disposition is
  the exception: neutralize every generation with a set-based update that tolerates
  concurrent shadow deletion, then prove zero retained live content. Regress the
  exact cleanup overlap on PostgreSQL and assert the lifecycle commit persists.
- Never automatically retry a mutation after an ambiguous transport failure. Read
  authoritative state and reconcile one exact versioned event, operation key, or
  immutable result reference; continue only when that evidence proves the original
  request committed exactly once. Otherwise fail visibly and require operator
  reconciliation.
- GitHub-hosted Playwright jobs must not run `playwright install-deps` or an apt
  transaction. Install the pinned browser independently, then launch it against a
  local smoke page to prove the actual shared-library/runtime contract before the
  suite. This keeps optional font-mirror stalls from consuming the browser-test
  budget while still failing closed when Chromium genuinely cannot start.
  production regression runs must assert the rejection without spending; only
  a separate opt-in budget-capped canary may establish live paid operation.
- Private-projection batch writes must acquire their exact, bounded Client,
  Matter, and IP-docket scope parents in deterministic `FOR KEY SHARE` order
  before locking a shadow generation. Otherwise a lifecycle writer that owns a
  parent and advances the generation epoch can deadlock the rebuild. Treat only
  PostgreSQL `40P01` and `55P03` as bounded concurrency conflicts: retry once,
  then defer only after a fresh-session integrity inspection proves an active
  generation, no pending/failed events, exclusively repairable blockers, and
  repair age inside the 300-second SLO. Unknown SQLSTATEs, unsafe blockers, and
  SLO breaches remain release-blocking; require a later clean no-rebuild cadence
  after overlapping writers stop.
- A dependency-audit transport failure is neither a clean scan nor a reported
  vulnerability. Retry recognized network failures inside a bounded budget,
  fail immediately on every non-network audit error, and require an independent
  digest-pinned scanner to return a clean result for the exact lockfile before
  accepting a fallback. Never waive or manually approve a broken security gate.

- A successful mutation must not be erased by an older in-flight list read.
  Wait for initial authoritative discovery before choosing create versus update,
  cancel stale exact queries, apply the server-returned record, and refetch.
  Regress delayed initial loads, failed loads, background reads, sibling rate
  mutations, persisted reload, and prevention of accidental duplicate defaults.
- Saved-import confirmation and interrupted-import recovery must revalidate the
  original retained source cells, not previously normalized catalog identifiers.
  Withdrawn aliases fail closed; a changed canonical court requires a new preview
  instead of silently moving the Matter. Preserve source evidence and already
  created rows, and test both boundaries with forced catalogue changes.

- An edit form must hydrate the saved server record before becoming editable.
  Refetches must preserve unsaved edits, and PATCH must contain only dirty
  editable fields, never hardcoded tenant identity or hidden billing defaults.
  Prove that changing an address preserves tax applicability, billing mode,
  payment terms, invoice sequence, and the other saved profile fields.
- Filtering an import to currently valid candidates must not bypass the
  no-work guard. A fresh confirmation with all-invalid or all-duplicate rows
  must reject with zero created Matters, while interrupted recovery must retain
  its already-created outcomes. Test empty admission as well as mixed rows,
  both through the browser action state and a direct confirmation request.
- Cross-format import evidence must preserve logical record identity. Embedded
  newlines make CSV physical line numbers differ from Excel row numbers; never
  join findings on those numbers alone. Reconcile record count and every source
  identity before reporting row-level outcomes, and label both row conventions.
- A loopback test proxy must release its upstream when the browser closes a
  response, not only when a request upload is aborted. Distinguish intentional
  cancellation from real upstream failures, keep complete mutation responses
  intact, and regress both cancellation phases without increasing timeouts.

- A cross-tenant browser test must isolate the second tenant's cookie jar.
  Bootstrap and login issue session cookies, and cookie-first authentication
  intentionally takes precedence over a supplied bearer token. Verify the
  original user remains authenticated before continuing that user's mutation;
  do not weaken authentication to compensate for a shared test session.
- Append-only legal history requires database mutation guards as well as a
  correction service. Prove direct UPDATE/DELETE rejection, a legitimate new
  version, historical reload and retained guards after repeated refused
  downgrades on PostgreSQL; service-only tests cannot establish immutability.
- A patent disclosure source pin must also retain the canonical restricted
  document link. Create it atomically with document-management authorization,
  audit and private-index invalidation; correction must not remove historical
  disclosure scope. Verify reuse of a previously trademark-only document, not
  just a document already uploaded inside the restricted family.
- Destructive migration probes must own disposable databases. PostgreSQL
  TRUNCATE CASCADE follows table-level foreign-key dependencies even when the
  surviving global rows have null administrative references; truncating users
  can therefore erase reviewed aliases. Assert exact main-schema/catalogue
  retention around probes and run browser acceptance on the untouched database.
  Fixed-tenant API fixtures and bounded global-worker queues need the same
  isolation on repeat runs. Do not clear shared data or increase a queue limit
  merely to make a test's newly inserted record appear in the first page.
- Foreign-key index acceptance must inspect complete constraint prefixes in the
  actual migrated schema, using the same rule as release index health. Do not
  add redundant single-column indexes to satisfy a component-only heuristic;
  prove that dropping a required composite index is detected by the gate.
- A Docker test snapshot must include repository-level fixtures, not only the
  application directory. Explicit node selections must strip CRLF delimiters,
  remain nonempty and reconcile one-to-one with collected identities. PostgreSQL
  shards must migrate their independent base database before fixtures snapshot
  catalogs. Preserve failed attempts and verify every shard's source hash.
- A success-path test must verify the successful user outcome and the absence
  of error feedback. Missing notification mocks can turn a successful mutation
  into a caught error while a weak call-count assertion still passes. Pair
  publication success with rejection, retained inputs and unchanged evidence.
- A nested navigation destination must have one active visible owner. Match
  the most-specific authorized catalog path, respecting segment boundaries,
  and regress every catalog destination plus desktop and mobile navigation.
- Responsive list actions must not squeeze the record title into a narrow
  column. Reserve a useful title basis, wrap actions to the next row when needed,
  and assert title width and sibling non-overlap after the sidebar consumes its
  space. Inspect screenshots as well as DOM bounds at breakpoint edges.
- A supporting-request count must start at the intended workflow boundary.
  Finish asynchronous sign-in/landing discovery before measuring the workspace,
  and inspect trace timestamps before attributing a late setup request to that
  workspace. Keep the zero-duplicate assertion and rerun the broader sequence;
  do not hide the request with a retry or a relaxed count.
- A shared-corpus browser fixture needs a unique searchable test scope and
  proof that its record entered the bounded candidate set. Retained fixtures
  from another journey must not displace the intended quality-filter probe.
  Assert raw candidates, omissions and visible output together, rerun against
  retained corpus noise, and never delete another journey's source records.
- A product domain is not identical to a storage discriminator. Inventory every
  canonical creator and schema before adding a domain allowlist; Madrid
  international registrations and designations are existing trademark records.
  Preserve their list, event, document, portal and PostgreSQL journeys while
  keeping unknown or unimplemented domains fail-closed.
- A document linked to an undisclosed domain cannot gain AI, portal, export or
  notification eligibility through an ordinary second link. Check every current
  link before pagination, reuse that policy for saved-publication reads and
  delivery-time authorization, and prove both old-projection denial and the
  original query-count budget. Internal authorized download remains separate.
- A complete PostgreSQL gate selects all tests carrying the postgres marker,
  not a single historical test file. Reconcile skipped nodes by module and
  reason, and keep local Docker and CI selectors identical. Dialect-only tests
  must use the PostgreSQL fixture and marker, not a SQLite client with a
  permanent skip. Global aggregate refreshes must own disposable databases;
  passing the marked suite does not prove incorrectly unmarked nodes executed.
  still bound to SQLite remain unverified even when the marked suite passes.
- Public requests use the shared HTTP deadline boundary without credentials.
  A JSON deadline must include body consumption, preserve caller cancellation,
  clear timers/listeners and never retry silently. Prove stalled headers and
  stalled bodies separately; receiving headers is not request completion.
- An evidence-refusing downgrade must leave the entire schema and every index
  unchanged, not merely retain the protected table or an ancestor revision.
  Concurrent index builds belong to upgrades; downgrade removals must stay in
  the enclosing transaction so a later refusal rolls them back. Regress two
  consecutive refusals, exact head/column/index equality and evidence retention,
  and rerun index health after migration rehearsals before resuming workers.
- A final SQL LIMIT and a green index inventory do not bound a multi-table
  listing's intermediate work. Admit an ACL-filtered parent page first, then
  load only its exact current-version keys. Regress a freshly populated 10,000
  record PostgreSQL dataset without relying on manual ANALYZE, enforce a short
  statement budget, and retain the slow-run evidence rather than raising timeouts.
  Regress adverse join plans as well: use the tenant cursor index and bounded
  correlated ACL lookups where the join can otherwise defeat early pagination.
  A later fast EXPLAIN does not establish which plan caused a prior timeout.
- Restricted invention disclosure is a server-owned invariant. Generic access
  management must not make patent anchors unrestricted and thereby expose their
  linked documents. Keep explicit grants and ethical walls available; test the
  shared mutation boundary, not only the patent form's confidentiality label.
- A Docker frontend snapshot must include repository-level golden fixtures as
  well as the web source. A missing fixture is a harness failure, not product
  evidence. Regress each new route page and measure native checkbox/radio labels
  as click targets while still asserting that the input itself remains visible.
- Regenerate schema/index governance fingerprints and their runtime projection
  before building the acceptance images. A passing source-tree generator does
  not update a previously built image; retain exact-source hashes and separate
  later test-only changes from the runtime revision actually exercised.
- A shared document panel displays the canonical controlled filename, which
  may differ from its title. Assert the server-returned filename, fully visible
  download control and original byte hash; do not rename a source or weaken
  controlled naming to satisfy a title-based browser locator.
- Clean test storage must not hide required runtime binaries. Keep Temporal's
  real test server outside an overlaid /tmp, pin its executable path and hash,
  and run its workflow with networking disabled. A missing cache is a test
  infrastructure failure, not a reason to skip notification workflow coverage
  or enable external provider traffic.
- PostgreSQL test migrations must pin both Alembic's URL and the Settings
  database URL to the explicit test DSN, clearing cached Settings before and
  after migration. A config-only override can silently target the application
  database because env.py resolves Settings. Prove isolation with a different
  application DSN and never treat setup failures as executed test coverage.
- Multi-tenant API regressions must isolate session cookies as well as bearer
  headers. Bootstrap replaces the client's cookie; use separate clients or
  clear that cookie before switching explicit bearer identities. Check both
  tenants' positive results in addition to foreign-ID denial.
- Independent patent records may share immutable source evidence. Closing a
  sibling or family must not prevent corrections to an active application.
  Distinguish read-only source parents from mutation targets under the same
  deterministic locks; retain source ACL/hash checks and terminal-write guards.
  Regress closed siblings, closed families and revoked source access together.
- Docker acceptance must recheck the candidate source after image builds,
  before browser tests and before certification. Reject source or commit drift
  instead of attributing green tests to an image built from different code.
  Exercise the actual PowerShell guard, not only a string-presence assertion.
- Authority serialization on Company must permit implicit foreign-key KEY SHARE
  locks held by waiting idempotent writers. Use the canonical NO KEY UPDATE
  private-authority fence for bootstrap and event/generation transitions; it
  still excludes authority writers and deletion. Regress different actors,
  real uncommitted claims, both patent parent kinds, closure persistence and
  zero generated child rows. Same-actor tests can hide this inversion behind
  the membership lock; never mask it with retries or a rolled-back closure.
- A client-side link click is not proof that navigation has committed. Assert
  the destination URL and record heading before using shared tab labels or
  saving page.url(); otherwise a test can operate on the previous record and
  later misdiagnose a terminal-history failure. Replay the complete journey.
- Async DOM polling must not starve the render it awaits. When a cold role
  query is expensive, poll a precise user-visible text/element and then retain
  the accessible-role and visibility assertion under the original deadline.
  Measure test-resource contention and rerun the full suite; never hide a
  product failure with longer timeouts, mutation retries or disabled checks.
- Route-reference heuristics are not behavioral coverage. When a URL helper
  hides a tested route from the inventory, make the path explicit in an actual
  executed HTTP assertion with status and payload checks. Do not satisfy the
  gate with comments, unused strings, exemptions or a weaker detector.
- A committed-diff release gate does not inspect an uncommitted candidate.
  Enumerate tracked and untracked changes with the workstation's Git, then
  apply the existing migration and data-governance analyzers to those exact
  files. Do not accept "no migration changed" or an advisory-only validate
  result as dirty-source acceptance. Risk annotations need reviewed operational
  rationale and real PostgreSQL proof; comment-only changes must retain exact
  executable equivalence with the tested image.
- A test-tools image may define its own entrypoint and may not include Bash.
  Inspect the image contract, select the intended entrypoint and available
  shell explicitly, and require a nonempty selected-test count, actual exit
  status and uniquely named report. A zero-test or failed-launch run is never
  acceptance; keep its diagnostics separate from the corrected execution.
- Reusable test-tools images must reject implicit execution instead of inheriting
  a historical runner from their base image. Require an explicit current-source
  runner and unique report paths, and execute the default-entrypoint refusal in
  regression coverage. A green run from the wrong source owner is not evidence;
  retain it separately and never reuse its generic output files as certification.
- An authorization-aware serializer may omit a record whose source access was
  revoked. Bulk consumers must reconcile requested identities with returned
  authorized identities and return a typed denial, not index a missing record.
  Regress a readable child with an unreadable parent source, including history
  and idempotent replay, without granting access or turning denial into a 500.
- A Docker test snapshot must include repository-level fixtures, not only the
  application directory. Explicit node selections must strip CRLF delimiters,
  remain nonempty and reconcile one-to-one with collected identities. PostgreSQL
  shards must migrate their independent base database before fixtures snapshot
  catalogs. Preserve failed attempts and verify every shard's source hash.
- A success-path test must verify the successful user outcome and the absence
  of error feedback. Missing notification mocks can turn a successful mutation
  into a caught error while a weak call-count assertion still passes. Pair
  publication success with rejection, retained inputs and unchanged evidence.
- A nested navigation destination must have one active visible owner. Match
  the most-specific authorized catalog path, respecting segment boundaries,
  and regress every catalog destination plus desktop and mobile navigation.
- Responsive list actions must not squeeze the record title into a narrow
  column. Reserve a useful title basis, wrap actions to the next row when needed,
  and assert title width and sibling non-overlap after the sidebar consumes its
  space. Inspect screenshots as well as DOM bounds at breakpoint edges.
- Independent patent records may share immutable source evidence. Closing a
  sibling or family must not prevent corrections to an active application.
  Distinguish read-only source parents from mutation targets under the same
  deterministic locks; retain source ACL/hash checks and terminal-write guards.
  Regress closed siblings, closed families and revoked source access together.
- Docker acceptance must recheck the candidate source after image builds,
  before browser tests and before certification. Reject source or commit drift
  instead of attributing green tests to an image built from different code.
  Exercise the actual PowerShell guard, not only a string-presence assertion.
- Browser specs and Playwright configurations must be type-checked before
  expensive Docker builds and in CI. Query options from Testing Library are
  not interchangeable with Playwright options; unsupported options can be
  silently ignored at runtime. Use the installed contract and retain the
  original failure plus the complete corrected user journey.
- A provider-deadline regression must measure the provider boundary separately
  from database setup and cleanup, prove an unrelated endpoint remains within
  its latency budget while the provider is still blocked, then prove no late
  projection is persisted. Keep total-work performance tests separate; never
  inflate a timeout or count a test-only replay as a clean full release run.
- A retained local web process also retains its anti-abuse buckets. Before a
  complete Docker browser replay, restart only the owned exact-image web
  container when the previous run consumed its demo quota. Preserve both
  structured failures and network traces; do not raise limits, spoof client
  identity, or automatically retry a mutation to obtain a green result.
- A parallel read-only source audit must authenticate once per worker, not
  once per batch. Keep release identity and no-paid-provider assertions, dispose
  worker contexts, and prove every source record with the existing login limit.
- Existing-tenant document journeys need unique synthetic evidence bytes, not
  only unique titles. HTTP 200 can validly return a duplicate offer without a
  created document. Assert the outcome and retained byte hash; preserve prior
  fixtures and duplicate detection when replaying production-shaped tests.
- An outcome heading can repeat text already present in a coverage banner.
  Use its precise accessible role, verify the committed HTTP query and response,
  and retain the original visibility deadline. Never swallow strict-locator
  errors inside a Promise race and mistake them for a missing result surface.
- Research quality-filter outcomes and index-health notices are independent.
  Assert the actual outcome heading, exact candidate/omission counts and the
  returned coverage notice together; a stale index can legitimately replace
  supporting prose without exposing an unreadable result.
- A retained shared catalog can satisfy a broad success locator with an older
  record. Match the exact new alias, assert its mutation response and current
  displayed identity version before a dependent merge. Inspect the HTTP
  conflict and refresh timeline; never replay a stale mutation automatically
  or weaken its optimistic-concurrency token to make the journey pass.
- Replay the actual committed-diff CLI after publication as well as the local
  dirty-source evaluator. A text-only governance reader must not decode unrelated
  binary evidence, but unreadable governed source must still fail closed with a
  bounded diagnostic. Regress binary evidence beside real provider and migration
  changes so a parsing repair cannot bypass the map or migration-marker checks.
- A successful idempotency record does not authorize a terminal patent write.
  Creation replays must revalidate and lock their original operational targets
  and source access before returning retained evidence. A correction's unchanged
  historical parent can remain read-only, but its child cannot be terminal.
  Capture and replay actual browser commands after closure, preserve historical
  reads, and prove a different actor's concurrent closure wins on PostgreSQL.
- A shared PostgreSQL fixture must explicitly depend on base migrations before
  reading its catalog snapshot; importing it from another module cannot rely on
  that module's autouse order. Partition the complete marked collection across
  isolated databases when it outgrows one runner, then reconcile every selected
  identity with successful JUnit evidence. Missing artifacts and skipped nodes
  remain failures; do not extend timeouts to conceal setup errors.
- A retained-record immutability journey must compare authoritative persisted
  reads before and after the operation. A creation response can serialize an
  in-memory UTC timestamp differently from SQLite's reloaded value. Preserve
  full field equality, including timestamps, between the two database reads;
  do not omit timestamps or normalize away real retained-record changes.
- A pytest plugin loaded with `-p` is imported before normal root-path setup.
  Keep CI and Docker on the same `python -m pytest` entry point. Exercise the
  workflow's actual launcher and options in a clean subprocess with no inherited
  PYTHONPATH, then reconcile all four real reports; an in-process partition test
  cannot prove that the CI executable can import the plugin.
- A bounded recurring scan must advance past rejected, incomplete, linked and
  terminal rows. Persist its tenant/provider checkpoint atomically with admission,
  wrap for later corrections, and count raw rows before filtering. Prove a
  supported record beyond a rejected full page, two concurrent scans, tenant
  isolation, rollback and disposal winning after discovery on PostgreSQL and
  the dated browser journey; raising the batch limit does not repair starvation.
- Reusing another worktree's Python runtime can import its editable package.
  Pin PYTHONPATH to the candidate source before schema/code generation and
  validation, inspect the resolved module path, and require the new table or
  contract in the generated result. A zero-diff regeneration is not proof.
- A long offline suite needs measured free executable scratch storage for its
  source archive, migrated templates, retained SQLite databases and journal files.
  A 1 GiB tmpfs exhausted during the September 08 full API run. Preflight capacity
  and actual executable launch, use isolated disk-backed storage, keep Temporal
  pinned outside it, and replay every affected node without erasing the failed
  run. Composed replay coverage is not a clean single full-suite result.
- A scanner-service exception is not an HTTP upload verdict. Cold-start
  acceptance must separately prove authenticated upload, byte-identical download,
  EICAR rejection with no attachment persisted, scanner outage and recovery.
  Retain cold-budget failures even when later functional diagnostics pass; a
  diagnostic continuation must preserve the failed gate and nonzero exit code.
- A provider scrape acknowledgement is not fresh case data. eCourts refresh is
  asynchronous: inspect its free status before another purchase, retain pending
  work for scheduled recovery, and fetch details only after confirmed completion.
  Prove submit, pending, completion, malformed receipts and mixed outcomes; do
  not call an immediate cached detail read a successful hearing refresh.
- Provider recovery needs a durable fenced claim and reserved budget before
  transport, not just a transaction commit. A lost response remains an uncertain
  budget hold; only evidenced free outcomes release it. Distinguish refresh,
  search, detail and download prices. Cover the entire response-body deadline,
  recheck current identity/access/lifecycle after I/O, and prove interruption,
  concurrent claims and revocation on PostgreSQL without another paid request.
- Repinning a Cloud Run job does not stop its previous executions. Pause the
  canonical paid scheduler before changing its recovery protocol, inspect a
  bounded complete execution history rather than only the newest execution,
  and require current terminal state before continuing. Unknown/truncated state
  or a drain deadline fails closed with the scheduler paused. Resume only the
  exact verified release runtime; do not cancel uncertain paid work or use a
  paid execution as a deployment test.
- An added audit or outbox event must use the existing ownership ledger's exact
  owner ID. Validate the complete catalogue immediately and regress the named
  owner; a plausible subsystem label is not a registered owner.
- Official-PDF compilation runs in its pinned isolated build environment, not
  the application OCR environment. Keep those dependency graphs separate and
  select compiler tests there. A missing compiler dependency is incomplete
  collection, not product evidence or permission to upgrade runtime pdfminer.
- A hearing refresh for an authorized bookmark must neither consume another
  actor's private Matter as matching input nor update that private Matter.
  After provider transport, lock the authorized parent and then reread/lock
  the bookmark before publication. Prove archive and retarget writes both
  between scope discovery and publication and while publication owns its fence,
  through manual and scheduled PostgreSQL paths.
- New offline provider fixtures must use disjoint identities and preserve the
  older fixture's records, dates and order-download handler. Run their combined
  journeys against the same installed worker and emulator; independently green
  fixtures cannot establish that the integrated browser stack is compatible.
- Test node identities are case-sensitive, including parametrized source text.
  Use ordinal sets and dictionaries when reconciling journals in PowerShell;
  its default hashtables and unique sorting collapse valid case variants.
  Regress distinct-case IDs, true duplicates and mismatched phase identities.
- Dashboard and hearing portfolio counts must come from server-side aggregate
  read models, never from the first page of `/api/matters/` or a raised
  client-side limit. Prove active/intake/hearing counts beyond the visible
  page, show truncation deliberately, and keep exact-date hearing filters
  tied to `next_hearing_on`/hearing dates rather than created/updated dates.
- An automated next-hearing update is incomplete until the calendar-facing
  `MatterHearing` read model is materialized with provider provenance. A
  green matter detail after eCourts sync can still leave Calendar blank.
  Regress provider updates through `/api/calendar/events` and keep manual
  hearing rows deduplicated by their source reference.
- A reported "case reopened" symptom must be diagnosed from persisted
  lifecycle state plus audit events before changing lifecycle code. Dashboard
  miscounts, explicit audited `Disposed -> Intake` transitions, and mutable
  historical access policy are not the same as accidental resurrection. Do
  not weaken terminal-state guards to hide a count or display defect.
- Matter document upload/view support must keep the browser accept list,
  backend signature allowlist and viewer branches aligned. Do not advertise
  formats the API rejects, do not force images or Word files through the PDF
  annotation component, and do not send private tenant documents to third-party
  viewers merely to make DOC/DOCX previews convenient.
- Local browser acceptance must keep the web origin and API cookie host on the
  same loopback hostname. A build that calls `localhost:8000` while Playwright
  serves `127.0.0.1:3100` can pass login transport but lose SameSite cookies,
  redirect back to sign-in and produce false product failures. Align the app
  harness host, API base URL and CSP loopback aliases before trusting UI proof.
- A bulk-update workbook is a mutation plan, not an import variant. Require the
  exact reviewed header inventory, resolve every row by the tenant-scoped Matter
  Code, bind apply to the previewed file hash and `updated_at` tokens, treat
  blank cells as no-op, and route each change through the canonical locked
  matter update service. Never create a missing matter or let a bulk status
  field bypass the dedicated lifecycle endpoint.
- A document viewer regression is closed only when the authenticated browser
  surface visibly renders the actual DOCX text/table content. A successful
  download, a nonempty iframe, or indexed extraction is not enough; preview
  parsing must be bounded and must reuse the same matter visibility gate.
- Reporter-supplied workbook IDs are local to that file and commonly collide
  with older CaseOps ledgers. Namespace newly triaged records by source and
  report date; reconcile populated issue rows and attachments independently of
  copied totals. Keep bug, enhancement, expected configuration, duplicate, and
  inconclusive evidence distinct, and never copy credentials into a ledger or
  generated workbook.
- Connector configuration, a stored OAuth connection, provider activity, and
  a successful provider outcome are separate facts. A local readiness refresh
  is not a provider attempt; only persisted provider success/failure evidence
  may populate provider-attempt timestamps. Do not call paid providers merely
  to make a health dashboard appear green.
- Bulk update status is not an editable spreadsheet field: lifecycle changes
  remain on the dedicated, audited, version-checked transition path. Route
  next-hearing changes through the canonical hearing scheduler, report
  skipped/invalid rows separately from apply-time failures, and tie results to
  tenant-scoped operation history. Review exact old/new values before apply.
- A Matter court link may lead to a supported internal search when exact
  identifiers are available, but an external eCourts destination must come
  from a validated provider result or reviewed source reference. Never invent
  a deep-link URL, infer a case from party names alone, or bypass a CAPTCHA or
  provider budget to satisfy a clickable-link request.
- Adding or changing an ORM table changes the runtime data-class schema
  fingerprint. Regenerate and validate
  `generated_data_class_projection.py` with
  `scripts/ip_data_class_projection.py render` and `validate`, then run the
  PostgreSQL legal-hold regressions. The intentional fail-closed 503 is not a
  reason to weaken the projection check.
- Protected attachment previews must use the authenticated blob client; a raw
  browser `<img src>` cannot attach the CaseOps bearer token. Revoke generated
  object URLs on replacement/unmount, and assert decoded pixels in Playwright,
  not merely that an image element exists.
- Persistent E2E tenants need a fresh Matter/source identity per run, with
  cleanup or explicit retention policy. Fixed codes can silently turn a
  creation/update regression into a stale replay and can mutate a real QA
  record during repeated verification.
- A bulk preview must conceal an inaccessible Matter Code exactly as it
  conceals a missing code: no Matter ID, version, or field values. Its diff
  must include canonical derived court lineage changes, and team-role checks
  must run before the user approves the plan. A post-preview access or
  validation failure must roll back all staged updates, preserve the denial
  audit without an inner commit, and require a fresh preview. Bound XLSX
  columns and iterations as well as upload bytes and rows. A bulk apply
  regression that injects a later-row failure must distinguish canonical
  dry-run updates inside rolled-back savepoints from actual batch writes;
  otherwise a hook can stale the preview token before any row is applied.
- A browser acceptance that spans many independent domain records at multiple
  widths must keep each named test within its measured worst-case budget. Split
  the inventory into bounded, independently reported groups instead of merely
  raising a timeout; retain all source, lifecycle, screenshot, and responsive
  assertions, and reconcile the groups against the complete domain list.
- A dated hearing browser test must respect the current filter contract: an
  exact-date filter shows only matching hearings and intentionally hides
  overdue/missing-date follow-up queues. Assert the filtered records and count,
  clear the filter, then assert both follow-up queues and their matters. Do not
  change product behavior to satisfy a stale simultaneous-state expectation.
  Scope post-filter assertions to the named follow-up region: its urgency
  headings can legitimately also appear in the main hearing buckets.
- A new ORM table, migration index, API route, or response schema must update
  every checked-in generated contract before CI: the data-governance map and
  rendered view, and the OpenAPI TypeScript client. Local Docker acceptance
  does not replace these clean-checkout checks. Run the validators and generated
  diff gates before promoting the candidate.
- A legal calendar date must retain its YYYY-MM-DD value across timezones, but
  its display order follows the runner's locale unless explicitly pinned.
  Browser and unit assertions should verify the value and use the same date
  formatter as the UI, not freeze one regional spelling such as `05 Oct`.
- Scheduled production verification must remain structurally read-only. Pin
  and review the complete scheduled step inventory, not a deny-list of known
  mutating step names; an unnoticed new QA writer can repeatedly fence private
  projection shadows and cause a real 300-second repair SLO breach. Keep
  mutation-capable acceptance on exact-release dispatch under scheduler hold,
  then require a convergent rebuild and a second clean cadence before resume.
- A case-tracking-sourced next-hearing field is not a scheduled hearing. Audit
  the same active Matter's `next_hearing_on`, provenance history and canonical
  `MatterHearing` rows; a `Not set -> date` event can coexist with zero hearings
  after manual clearing and tracked-case recovery. Backfill only current
  non-null eligible dates with idempotent, lifecycle-aware scheduling, then
  prove the exact persisted records across Matter, Hearings, Calendar, Today
  and Cause List after reload.
- Preserve binary regression fixtures byte-for-byte when integrating isolated
  worktrees. A PowerShell text pipeline can corrupt a binary Git patch while
  leaving the expected filename in place; restore the Git blob directly or
  regenerate it, verify its signature/container, and rerun the unchanged
  browser journey before diagnosing a product upload failure.
- A legacy-hearing repair is not release-ready merely because the bounded
  function exists. Execute a provider-free, exact-image backfill before routing
  traffic and production QA, fail on non-convergence, and test cancelled-row
  replacement as well as past/current/future dates and idempotent replay.
- A provider-link test fixture must preserve the identity and transport boundary
  that each regression claims to exercise. A CNR-linked case uses detail/refresh,
  while a case-number-only case uses search; switching one shared fixture can
  bypass an entire race even when a link succeeds. Give those paths distinct
  fixtures, prove the actual provider call and tracked-case identity, and update
  PostgreSQL wrappers when a reused test helper gains a required fixture.
- A dated browser test that exercises standalone search/bookmark behavior must
  not invent a Matter ID merely to enter the screen. A Matter-scoped search now
  offers only server-verified Link actions; keep standalone bookmark/update
  coverage separate from the real Matter link journey, and replay both against
  a production-style build after a UI contract change. A local Next dev 404 or
  partially written generated type file is setup evidence, not a product verdict.
- A legacy-data browser regression must establish the pre-feature state, not
  ask the current public API to create data that its new guard correctly rejects.
  Restrict direct fixture seeding to isolated E2E Docker, assert tenant scope and
  zero existing children, then exercise the normal scheduler/API and verify the
  original record ID survives recovery. Never relax the public guard for a test.
- A sandboxed document preview renders in its iframe, not the parent document.
  Dated Playwright assertions must enter that frame and verify actual rendered
  text, while separate checks retain the sandbox and download authorization.
- A signed test token must be minted with the serving runtime's secret. In
  Docker acceptance, sign inside the exact API container and verify the normal
  server admission path; a host-generated token can fail solely because test
  and container secrets differ. Never weaken signature validation to pass E2E.
- A local green gate does not subsume clean-checkout static analysis. Values
  assigned only inside an optional Matter branch must be converted to an
  explicitly initialized flag before later query construction; do not rely on
  short-circuiting through an unbound local. Treat CodeQL annotations on changed
  production paths as release blockers, fix them, and rerun the exact candidate.
- Dated Playwright assertions must target an exact heading when a valid empty
  state includes the same words. A Windows Docker pass does not certify the
  Linux app CI harness: derive virtualenv executables by platform, report
  spawn errors explicitly, and rerun the selected CI journeys plus the full
  clean-checkout suite before release.
- A release backfill bound must be sized from a read-only production backlog,
  not a small fixture. Preflight every tenant before writing, retain finite
  per-tenant and release-wide caps with observed headroom, and test above the
  prior cap on PostgreSQL. A failed bounded run can commit earlier pages;
  prove idempotent replay, require a zero-remaining postflight even after a
  short SKIP LOCKED page, and keep traffic on the
  old revision until the exact-image job and dated browser journey pass.
- Hearing materialization must not turn a completed, cancelled or adjourned
  hearing back into a scheduled one. Completed and cancelled are closed;
  adjourned is still open and must remain the authoritative row for an explicit
  hearing edit or reconciliation. A same-date hearing of any status makes a
  legacy date ineligible for automatic backfill; unchanged provider repair
  must preserve it, while a genuinely new date gets a new scheduled row.
  A same-date explicit replacement must update the Matter's source reference;
  reopening a non-neutralized closed hearing by status alone must restore its
  next date and reminders without creating a second calendar row.
  Count active companies rather than active memberships for release repair,
  cap actual writes as well as preflight backlog, and recheck every tenant at
  the end. A point-in-time final recount is not a promise against future writes.
- Local Docker acceptance runs for the same release may overlap across agents.
  Give every invocation a unique Compose project and preferred port block;
  isolate its volumes and retain separate result journals. A SHA-only name
  lets startup or cleanup destroy another run's PostgreSQL mid-test. The
  resulting connection loss and cascading fixture errors are incomplete
  infrastructure evidence, never a product-pass or product-failure verdict.
- Retained production operation histories can contain identical filenames from
  prior acceptance runs. Give each browser-created import/update a unique
  source filename, wait for its exact new history row, and scope result and
  download assertions to that row. A `.first()` locator may select a stale
  operation while an asynchronous history refresh inserts the current one;
  preserve the failed run and fix the test identity rather than misclassifying
  the applied mutation as a product failure.
- A private-projection scheduler resume is a release certification step, not a
  cleanup command. Require the latest successful exact-SHA mutation-capable
  prod-verify dispatch, the currently serving API revision's immutable digest,
  and two later serial clean maintenance executions on that digest, with zero
  rebuilds in the second. A preliminary repair or historical SLO breach remains
  incident evidence. Keep the cadence paused on missing or changed evidence;
  audit direct Cloud Scheduler ResumeJob access because it bypasses the CLI
  guard.
- A Vitest timeout does not stop the test's async user flow. Global `screen`
  queries let the abandoned flow drive the next test's freshly rendered page
  and record a stray mock call there. Scope mutation-test queries to the
  render container, enter bulk text with one paste per field rather than
  per-keystroke typing, await the settled mutation, and assert exact call
  counts and complete payloads. Prove isolation with a forced short-timeout
  copy and measure the full suite under CPU load; never raise the timeout.
- Container scoping does not isolate a timed-out Vitest flow from Radix
  portals: React detaches portal content without emptying it, and
  `user.paste`/`user.keyboard` act on whichever element has focus, which can
  be the next test's input. Require focus on the field before each paste,
  check that page and portal are still mounted before portal queries, and
  prove isolation with a forced short timeout on dialog tests too. A worker's
  first accessible-role query is cold (170-370 ms measured) and is charged to
  the 1 s `findByRole` deadline; poll the precise visible text, then keep the
  role and visibility assertion. Never raise the deadline.
- A source link with `target="_blank"` may emit a browser download on its
  opener or on a transient popup. Subscribe to downloads on every page in the
  same browser context before clicking, then assert the exact source URL and
  downloaded bytes. An API 200 alone does not prove the browser journey.
- A failed Docker acceptance may deliberately retain one-off worker runners.
  Select the canonical service by project, service, and `oneoff=False` labels
  on replay; do not mistake those evidence containers for extra replicas.
  Manual replay must reproduce the standard wrapper's mock-only provider
  environment, and a fixture safety-guard failure is incomplete test setup.
- A form inside a card must stay usable at every page layout, not one viewport.
  Size card-internal forms with container queries: a viewport breakpoint cannot
  know that xl puts two cards in one row, and `minmax(0,1fr)` beside fixed tracks
  lets a title field collapse to zero. Verify with the navigation-driven form
  layout sweep at desktop split-layout widths and mobile; never close a layout
  report on a single width where the defect cannot occur.
- One Matter/provider identity decision, one function. Search, resolve, link,
  refresh, polling and next-hearing sync all call `identity_matches`: a
  normalized CNR decides and free-text court or party wording never overrides
  it; without a CNR, the exact case number with its provider case type plus the
  court is required. Prove parity with a table where search issues a link token
  exactly when refresh accepts, using real-world wording variation. Identical
  fixture strings on both sides cannot test an identity comparison.
- A generated document is verified by reading it. PDF tests must assert glyph
  positions against column borders and printable width, each long value's full
  text inside its own column, and non-Latin input; `%PDF` plus a checksum only
  proves a file exists. Build PDFs through `services/pdf_layout.py`: fpdf2 cells
  neither clip nor wrap, and `multi_cell` leaves the cursor at the right margin
  unless `new_x` is given.
- A reopened report means the previous proof measured a proxy. Before fixing
  again, diff the earlier change and its test against the new report and record
  why that test could not fail. Reproduce on the unfixed commit inside a checkout
  of that commit: pytest's `pythonpath = ["src"]` otherwise imports the
  candidate's source and a "reproduction" silently tests the fix.
- A production-only spec branch must execute before release, not first in
  production. Prove its exact request and response shape in pytest against the
  real provider host with the automation marker (the gate raises before any
  transport), assert blocked-provider bodies only through the shared
  `expectPaidProviderBlocked` helper (RFC 7807 puts `code` at the top level,
  never under `detail`), and read every failure's error-context before deciding
  whether the product or the test changed.
- Test fixtures must be registry-shaped. A random hex slice in a numeric case
  number parsed only when it ended in a digit, so a dated production journey
  passed 62.5% of runs and was mistaken for a regression when it finally drew a
  letter. Generate identifiers in the format the product validates, and treat
  any fixture that can pass by chance as a defect in the test.
- Disposing a fixture does not free its identity: duplicate rules count
  disposed rows, and production tenants keep every earlier run. A journey that
  runs in production creates identifiers no run has used (clock plus serial),
  never a fixed or small-range random value. Prove it by running the journey
  twice against one retained local tenant, and reproduce the old version's
  collision there before trusting the fix.
- A 30-second API response in production verification can be a Cloud Run cold
  start on the concurrency-one service rather than the endpoint. Correlate the
  instance startup logs (sidecar readiness, application startup) with the
  request before blaming the endpoint or the test, and record capacity defects
  instead of retrying them away.
- "Insufficient identifiers" is not an explanation. When a legal record cannot
  be matched, return the one machine-readable gap (`identity_gap`: invalid CNR,
  missing identifiers, unreadable case number, case type required) with the
  recorded value, on the same policy for manual search, resolve and link,
  automatic linking and backfill, and the refresh and polling of automatic
  links, and render that reason. A compound entry naming two records is
  unreadable; never guess which number is the case.
- A unified identity policy has no path-specific exceptions. Requiring a typed
  case number for manual linking while automatic linking and refresh kept the
  weaker check let a provider's only `CRL.A. 6209/2019` result, and its hearing
  date, attach to a `WP(C) 6209/2019` Matter. Inventory every caller of the old
  predicate before narrowing it, and regress each path with a provider that
  publishes exactly one case of another type: zero searches, zero writes.
- A list query-count test must use production-shaped rows. Reviews without a
  private source manifest let each row's reauthorization return before any
  query, so a three-statement test hid about seven statements per production
  review. Reauthorize a page in one batched decision whose one-manifest form is
  the same function, prove each row's decision including revoked and malformed
  manifests, reproduce the old count on the unfixed commit, and bound the page
  on PostgreSQL at retained-generation volume.
- On the concurrency-one API a page's first load must fit warm capacity. Cloud
  Run kept the fifth concurrent read of a four-instance service on a new
  instance for its whole 30.8-second start, although warm instances were free
  within 0.5 s. Start only the primary reads, load pickers on demand, and never
  add a duplicate read to hide a slow primary: bound the primary. The API's own
  startup, not the ClamAV sidecar, was the critical path in 332 of 343 starts.
- An `OR` of equality lookups is index-driven only when every branch has an
  equality index. `neutral_citation` had only a trigram GIN expression index,
  so `id IN ... OR neutral_citation IN ... OR case_reference IN ...` read the
  whole 800K-document authority corpus on every pleading validate: 4.6 s on
  the 1-vCPU production database. Prove such a fix with `EXPLAIN (ANALYZE,
  BUFFERS)` of the exact captured statement on a table large enough that a
  scan costs thousands of blocks, with no manual `ANALYZE`, and bound the
  blocks read rather than the time.
- Alembic's `autocommit_block` restores the isolation level it reads back, and
  psycopg reports READ COMMITTED for an AUTOCOMMIT connection. A migration
  probe that keeps using that connection holds locks in an implicit
  transaction, so a later `DROP INDEX` waits on the test itself, and its
  cleanup is rolled back on close. Re-enable AUTOCOMMIT after the block, bound
  lock waits, and commit the cleanup.
- A list must never return a record that its single-record read refuses. The
  Draft lists read a source manifest that was not a JSON list as "no private
  source" and returned the draft's body, while the read answered 409. Give
  lists and reads one parse and one batched decision, decide each version on
  its own (a merged manifest spans generations and repeats projections), and
  prove list, read and HTTP agreement for malformed shapes beside the statement
  bound, as `test_20260927_draft_lists_bounded.py` does.
- A projection event tombstones rows only in the generation active when it
  applies, so a retired generation's untombstoned row does not prove that no
  event followed. Reauthorize a saved private source only when the event
  ledger holds no event after the saved row was built for the tenant, the
  source or a saved parent scope. Checking the tombstone alone let a document
  proof saved one generation before a Matter grant, or before a dispose and
  reopen, return at the next rebuild, while the same proof saved one
  generation later stayed locked. Regress both saved generations with bare
  and real events, before and after a later rebuild.
- A Workspace Assistant answer is a saved output too: every projection event,
  access included, locks its saved sources for good, and a read never writes.
  Reach the event's target and the records under it from the canonical tables
  (a Matter's documents; an IP docket's asset, application and proceeding
  records and the documents linked to it or its children) in one set-based
  update, not only through the projections the event's generation holds. When
  reads committed their decision, a temporary access loss locked an answer only
  if its author happened to export during it.
- Migration-job safety includes execution topology. Declare and verify one
  task and parallelism one before Alembic execution; inherited job defaults or
  a correct image, command and environment cannot certify serial migration.
- GitHub auto-merge is not a CI gate when the branch has no required checks.
  Inspect the exact-head check rollup and repository enforcement before using
  it, keep pending rewritten-head evidence pending, and require completed CI
  on the combined current main before any production deployment.
- A hidden assistant answer must redact every source-derived response field,
  not only content and citations. Suggested searches and proposed actions can
  retain private record labels and links. Enforce redaction on server-owned
  read and export DTOs, reject hidden-answer action preview and execution, and
  preserve immutable stored evidence. Prove both hidden and visible controls,
  access restoration, citation rejection and responsive browser reloads.
- A release regression cannot wait for a scheduler the release deliberately
  holds paused. Keep production seed, QA mutations and maintenance serialized;
  use canonical producer audit evidence for retained production reads and a
  fresh loopback event/rebuild journey for Docker. Never resume overlapping
  cadence, fabricate output evidence or weaken a readiness fence to make a
  new test pass. Preserve the separate two-clean-run resume guard after QA.
- Release-owned browser journeys must receive the same exact source identity
  in every standard API/web harness, not only Docker. Propagate a valid explicit
  image SHA or resolve the candidate checkout, reject malformed identity rather
  than substituting one, and prove the normal suite discovers and runs the
  journey. Preserve a failed harness baseline separately from acceptance.
- A stronger security rejection can legitimately precede an older stale-target
  error. Audit dated browser expectations after changing that ordering; assert
  the exact typed response and user-visible copy plus unchanged persisted
  fields and child identities, never accept several errors or weaken the fence.
- A multi-record browser journey must establish its visible list/detail context
  on every iteration. Preserve failed partially edited fixtures, prove the
  replacement journey on a fresh fixture and rerun its retained terminal state;
  resetting saved evidence is not idempotence or revocation proof.
- Automated production runs that may only assert the no-paid rejection cannot
  observe a provider-search fix. Replay stored evidence instead of spending: a
  checked-in verification fixture is refreshed only by the window-enforcing
  18:00 IST scheduled job, with the exact live CNR lookup, at most once per
  Asia/Kolkata day including failures, budget-reserved and claimed before
  transport, never published to its tracked case and never retried. Replay
  answers only requests carrying both the no-paid marker and
  `X-CaseOps-Provider-Replay: verified-fresh`, for the fixture's CNR in its own
  workspace, from evidence retrieved within 24 hours, hash-verified and not
  superseded by a later not-found or unreadable answer, through the live
  presentation code. Anything else fails closed with a typed `replay.status`
  and no provider call. Never widen the registry, relax the 24-hour bound, fall
  back to older evidence, or add a deploy-time paid warm-up to make a replayed
  check pass.
- An eCourts exact case-number search is not safe with only a human court
  name. Require a provider-published court code or current Matter CNR before
  reserving spend or dispatching transport; exclude unsearchable scheduled
  rows from the bounded batch while counting them as blocked/backlogged.
  Readiness for automatic links must use the current Matter identity, not a
  stale learned CNR, and must disable Refresh with actionable copy. Preserve
  the more specific missing-court, malformed-CNR and case-type errors ahead
  of the court-code hint. Regress both the no-charge blocked path and a
  reviewed-code search/link/hearing reload in Playwright; a no-charge 409
  alone does not satisfy next-hearing acceptance.
- A signed provider result can create a second active Matter bookmark when a
  code-less auto-link already exists under another tracked identity. Reconcile
  only matching system-created placeholders inside the locked Matter-link
  transaction: archive same-member duplicates, move other members without
  losing bookmark IDs or notification settings, retain old tracked rows and
  audit the change. Replayed selections must be idempotent. PostgreSQL tests
  must identify the intended actor explicitly; an invite helper can leave a
  shared TestClient logged in as the invited user despite later bearer headers.
- A new provider pre-spend identity fence must be replayed against every dated
  emulator journey, not only the newest fixture. Use each emulator's actual
  provider-published court code (the older base fixture and a newer hearing
  fixture may differ), keep CNR-only and no-code/no-transport negatives, and
  prove the code-backed positive still yields the expected persisted hearing.
- A pre-spend rejection also owns the existing no-charge user contract. Keep
  actionable identity guidance and the explicit no-external-request assurance
  together across Matter resolution, manual search and refresh. Regress the
  exact dated production Playwright assertions, zero transport and zero spend;
  local API safety alone cannot certify the user-visible production copy.
- A production-verification matrix addition must update the workflow inventory
  test and its secret/project assertions in the same change. Refresh
  `origin/main` before governance change-gate checks; that gate compares
  committed branch history, so uncommitted map edits cannot satisfy it. A
  governance-note edit must render and validate both the Markdown map and
  generated data-class projection before freezing a Docker candidate.
- Race diagnostics must live outside the upload/storage root whose contents a
  test asserts. Exercise the harness with its evidence-directory override unset
  as well as configured; never ignore unexpected files or weaken atomic cleanup
  assertions to accommodate a journal created by the test itself.
- A lock-order regression must identify the actual PostgreSQL lock owner.
  Tenant-first lifecycle admission legitimately holds Company while OAuth backs
  off; prove the callback has rolled back with independent backend/activity and
  lock observations, then prove disposal and callback complete. An observer must
  not borrow the callback's named pooled connection and misattribute its own
  transaction to OAuth.
- Finish static, governance, security and complete affected-file gates before
  freezing a full Docker candidate. Preserve interrupted runs as incomplete.
  A retained-fixture browser branch must repeat every new revocation assertion
  from the fresh branch, and its release-contract inventory must change with it.
- Changing a private upload helper's signature, return value or transaction
  ownership is a caller contract change. Inventory every production caller and
  rerun its complete workflow tests, including Gmail reviewed attachments; a
  passing inbound-email suite cannot certify a caller omitted from that suite.
  Every upload that rolls back before I/O must first reject new, dirty, deleted,
  flushed/Core-written or nested caller transactions without discarding them.
  Prove the caller can still commit its original work after the rejection.
  Maintain a fast complete caller-contract inventory beside workflow tests:
  reviewed Drive imports share this helper too. A known broken adjacent caller
  cannot be deferred as out of scope while releasing that helper change.
- Connector review actions must serialize against the same freshly locked
  candidate as content admission. A completed import cannot be reset by a
  stale ignore, retry or metadata-link writer. Prove both overlap orders and
  keep metadata review available without live provider consent where allowed.
  Provider downloads must enforce the smaller tenant and server byte limits
  while streaming, plus one total deadline across refresh and replay; a later
  storage-size rejection cannot protect an earlier unbounded allocation.
- A page LIMIT does not bound correlated authorization work when the planner
  filters a whole tenant before sorting. Preserve ACL-before-pagination and
  selective matches beyond the first page; prove actual row/loop and buffer work
  under stale statistics and custom/generic plans beside the unchanged deadline.
  A passing elapsed-time sample or bounded SQL statement count is insufficient.
  Bound inner identity lookups too: an ordered outer barrier can still repeat
  a company-only scan thousands of times. Retain the hosted counterexample and
  prove examined rows, not merely outer loops or one favorable local plan.
- Bound the outer ordered parent scan as well as each inner identity lookup.
  A wide family subquery can scan and sort 10,001 tenant rows under generic
  stale statistics even when docket probes are bounded. Keep ordered keys
  narrow, hydrate only the authorized page, and regress mixed-tenant fresh
  imports with actual family/docket work and buffers for custom/generic plans.
  Preserve late selective matches and all ACL predicates; do not cap raw
  candidates, add a duplicate index, or relax a budget to hide the plan.
- A unique authorization result does not bound its executor work. Retained
  grants and stale statistics can choose a global active-grant bitmap or scan
  thousands of one member's grants for each docket. Regress the full shared
  IP policy against retained foreign imports, preserve member/team windows
  and wall precedence, and bound all plan nodes, not only family/docket rows.
  A scoped green replay is superseded by a later retained-data counterexample.
  A unique active-key seek must reject a nonmatching successor before applying
  its window; prove present wrong-subject/target successors for grants and
  walls, both membership and team, beside exact-pair positive controls.
- A clean or fresh SQLAlchemy Session can still be bound to a Connection whose
  transaction belongs to its caller. Reject that boundary before querying or
  rolling back, including savepoint and control-fully join modes. Prove the
  external transaction and Session state remain unchanged and caller work can
  commit; a nonassigning PostgreSQL xid probe alone cannot identify ownership.
- A Cloud Run request timestamp plus its latency can identify a request that
  waited for a new scanner-gated API instance. Correlate the instance startup
  logs before calling a missing browser row a data or permission defect. Keep
  loading, failed metadata, absent attachment and unsupported format as
  distinct viewer states. Give non-performance browser assertions a bounded
  cold-start allowance, while retaining separate warm-path latency gates;
  never hide a slow mutation with an automatic retry.

- Google Gmail and Drive safe-read paths that persist refresh tokens must use
  server-side tenant OAuth configuration to refresh on provider 401, retry that
  read at most once, and persist refreshed tokens encrypted while retaining
  the old refresh token if Google omits a rotated value. Treat invalid/revoked
  consent as an explicit reconnect state using a non-auth 409 response; never
  return provider-consent failure as HTTP 401, which the shared web client
  interprets as an expired CaseOps login. 429s, timeouts, and 5xx responses are
  temporary and must not permanently mark a connection or review candidate
  broken. Convert provider exceptions to typed API responses so browser CORS
  does not turn an upstream failure into a misleading "API unreachable"
  message. Regress sync, browse, reviewed attachment/file reads, transient
  refresh failure, revoked consent, response status, and persisted state with
  deterministic provider emulators; verify the authenticated production UI
  against the exact deployed SHA. Do not blindly replay calendar mutations:
  only retry a write after proving its operation-specific idempotency and
  unknown-outcome contract.
- A production Playwright assertion made after `page.reload()` must not parse a
  response object captured from the navigation: Chromium may discard that
  response body even when the HTTP status was observed successfully. After the
  reload, issue a fresh authenticated, no-paid-provider API read (or assert the
  rendered persisted value) and verify the durable state there. Distinguish
  browser-protocol response-body loss from a product persistence failure, and
  preserve both sync-success and post-reload persistence assertions.
