# Core IP records and workspace configuration

Last updated: 7 August 2026

Implementation slices: `IPLF-021A`, `IPLF-021B`

Status: repository implementation and local verification complete; serial CI
and exact-release production verification remain pending.

## Purpose and boundary

This contract adds the canonical, tenant-scoped records required to identify an
IP asset, its trademark application, a proceeding, and every legal identifier
without overloading a Matter or storing one identifier in another identifier's
field. `ip_docket_records` remains the access and lifecycle anchor. Matter,
Client, document, audit, deadline, notification, and billing services retain
their existing owners.

The workspace configuration contract records what a tenant administrator has
selected and which safe readiness probes passed for that exact configuration
version. It stores provider keys/references, but never provider credentials.
Secrets continue to belong to the integration/secret owner. Saving this
configuration does not itself enable a feature.

## Canonical record graph

```text
ip_docket_records (access and lifecycle anchor)
  +-- ip_assets
      +-- trademark_applications
          +-- trademark_application_scopes
          +-- trademark_representations
          +-- ip_proceedings
          +-- ip_identifiers (application/registration identifiers)
      +-- ip_proceedings
          +-- ip_identifiers (opposition/rectification/appeal/court identifiers)
      +-- ip_parties_and_roles ----> clients (optional canonical party link)
      +-- ip_relationships --------> another tenant IP asset

companies
  +-- ip_workspace_configurations (one current row per tenant)
      +-- ip_workspace_test_results (append-only results by configuration version)
```

Every legal-state row carries `company_id`. Composite foreign keys ensure a
child cannot refer to a parent owned by another tenant. The API additionally
reuses the docket's authoritative restricted-record and terminal-lifecycle
guard for reads and writes.

## Identifier requirements

The command service implements the IPLF-021 contribution to `IP-ID-01` through
`IP-ID-08`:

| Requirement | Enforced behavior |
| --- | --- |
| `IP-ID-01` | Application, registration, opposition, rectification, appeal, and court identifiers are typed facts. Application/registration identifiers belong to an application; proceeding identifiers belong to a proceeding. |
| `IP-ID-02` | `raw_value` is immutable source display data. `normalized_value` is a separate Unicode-normalized, case-folded, alphanumeric search value. |
| `IP-ID-03` | Kind, office, jurisdiction, source, effective-from date, and primary designation are required; effective-until is validated when present. |
| `IP-ID-04` | A trademark application cannot enter `filed` without a current confirmed application identifier unless `source_pending_identifier_allocation` is explicit. |
| `IP-ID-05` | An opposition number can only belong to an `ip_proceeding`; the application owner shape is rejected. |
| `IP-ID-06` | Exact normalized search accepts common punctuation/case/spacing variants and returns the original source form. |
| `IP-ID-07` | A current normalized collision returns duplicate candidates and marks the new fact `needs_review`; it never merges assets or applications. |
| `IP-ID-08` | A correction creates a successor identifier, closes the old effective range, and requires `supersedes_identifier_id` plus a correction reason. |

These requirements remain program-level `in_progress` until the reciprocal
manual create/reconciliation paths assigned to `IPLF-031B` are implemented and
released. IPLF-021B must not be represented as completing that later slice.

## Command and query API

All routes are under `/api/ip`. Read operations require `ip:read`; core record
mutations require `ip:write`; workspace configuration/test/enable operations
require `ip:taxonomy_admin`. Capability authorization, subscription
entitlement, deployment rollout flags, and tenant configuration are separate,
fail-closed gates.

| Method and path | Contract |
| --- | --- |
| `GET /identifiers/search?q=` | Tenant-scoped normalized exact search; inaccessible, restricted, missing, or terminal docket rows are omitted. |
| `GET /dockets/{id}/core-records` | Returns assets, applications, proceedings, and identifier history after the docket access/lifecycle guard. |
| `POST /dockets/{id}/assets` | Creates the docket's canonical IP asset. |
| `POST /dockets/{id}/applications` | Creates a typed trademark application and can atomically create its first identifier. |
| `PATCH /applications/{id}/filing-phase` | Uses an optimistic `expected_version`, parent-before-child locks, and the filed-phase invariant. |
| `POST /dockets/{id}/proceedings` | Creates a proceeding owned by the same docket/asset/application graph. |
| `POST /dockets/{id}/identifiers` | Creates a typed identifier and returns any reconciliation candidates. |
| `POST /dockets/{id}/identifiers/{identifier_id}/corrections` | Creates immutable correction history and returns duplicate candidates. |
| `GET /workspace/configuration` | Returns current tenant configuration, tests, manual readiness, and blockers. |
| `PUT /workspace/configuration` | Creates or version-updates configuration with optimistic concurrency; an update disables the workspace and invalidates old-version test evidence. |
| `POST /workspace/tests` | Persists one safe dry-run result for the exact configuration version and actor. |
| `POST /workspace/enable` | Enables manual workspace use or selected automations only when their current-version prerequisites pass. |
| `GET /readiness` | Overlays tenant configuration and test state on capability, entitlement, and deployment rollout decisions. |

## UJ-01 workspace setup

The responsive `/app/ip` setup surface records enabled asset types,
jurisdictions, offices, timezone, holiday calendar, working weekdays, document
taxonomy, event catalog, deadline-rule versions, notification channels,
critical-event policy, escalation owner, provider references, and provider
terms acceptance. It links administrators to the existing role, team, and
integration owners instead of creating duplicate administration stores.

Four tests are deliberately side-effect free:

- Connection and source-open tests validate configured provider references and
  accepted terms with `external_call=false`.
- Notification validation records `sent=false`; it never sends a message.
- Deadline calculation uses a deterministic sample and records
  `legal_deadline=false`; it never creates an operational deadline.

Missing or failed provider tests do not block manual docketing. They block only
the affected automation. A configuration version change disables the tenant
workspace and makes older test results ineligible. The environment and
entitlement gates still win even after tenant enablement.

No seven-day or other arbitrary elapsed-time requirement is part of this
contract. Readiness is established by deterministic current-version evidence,
exact-revision release checks, and required human/provider approvals.

## Transactions, concurrency, and audit

Core mutations lock the docket parent before child rows, validate tenant
ownership and lifecycle state, write the legal record and audit event in one
transaction, and commit only after all invariants pass. Filing-phase and
workspace changes use client-supplied optimistic versions so stale writes fail
with `409` and require reload.

Workspace saves, readiness tests, enablement, assets, applications,
proceedings, identifiers, corrections, and phase changes emit tenant audit
events. Identifier raw values are not copied into audit metadata. Test evidence
records the actor, configuration version, result, failure code, and safe-result
details.

## Migration, rollout, and rollback

`20260807_0001` creates the eight core legal-record tables. `20260807_0002`
adds `ip_workspace_configurations` and `ip_workspace_test_results`. Both are
additive, tenant-scoped migrations. They neither infer existing legal records
nor activate rollout flags.

Before rollout, CI must prove PostgreSQL migration order and the exact candidate
must pass Security, CodeQL, API, web, and OpenAPI generated-client gates. The
serial release must then migrate production, deploy the exact API/web image
digests, verify the serving Cloud Run revisions, and rerun the dated production
acceptance journey against that revision.

Before writes, the tested downgrade removes the new tables. After writes,
rollback is flag-off plus forward-fix/export preservation; destructive
downgrade is not an acceptable way to discard legal history. No production
automation flag is enabled by merging this slice.

## Verification map

- `test_ip_record_workflow.py`: filed invariant, typed ownership, raw/normalized
  search, duplicate reconciliation, correction history, tenant and restricted
  access, audit events.
- `test_ip_workspace_configuration.py`: UJ-01 normal and three exception paths,
  tenant/admin scope, terms, actor/version evidence, manual fallback, and
  fail-closed readiness overlay.
- `test_20260807_ip_core_migration.py` and
  `test_20260807_ip_workspace_migration.py`: upgrade, downgrade, removal, and
  re-upgrade.
- `page.test.tsx`: visible narrow-viewport setup controls and every grouped
  action/link, plus manual and automation states.
- `openapi-types.ts`: generated from the API schema; CI rejects drift.

Local evidence is recorded in
`docs/ip-implementation/evidence/m2/IPLF-021B/release-2026-08-07.md`.

## IPLF-040A opposition extension

`20260823_0001` extends the existing proceeding owner; it does not introduce a
parallel opposition record. Every opposition starts in `draft`, records its
intake origin and applicant/opponent stage-template version, and may explicitly
remain pending Registry number allocation. A supplied number is written in the
same transaction to `ip_identifiers.proceeding_id` and can never become the
linked application's application number.

The proceeding cannot leave `draft` until it has both a linked application and
a confirmed current opposition number. Accepted changes use the canonical PRD
Section 12.2 stages, expected proceeding version, evidence, reason, and the
existing `ip_docket_events` timeline. Exceptional changes require authority;
closure additionally requires outcome, effective date, source, evidence, and
authorized confirmation. The dedicated transition route requires `ip:approve`,
and the generic event route applies the same guard so it is not a bypass.

Only marked opposition-stage events receive the new database append-only
trigger. Existing docket lifecycle events retain their established in-transaction
finalization before commit. Full applicant/opponent workspaces, pleadings,
service, evidence packages, deadlines, hearings, orders, appeals, reporting,
and UJ-12/UJ-13 browser proof remain owned by `IPLF-040B` and later M4 slices.

## IPLF-040B opposition workspace extension

`20260823_0002` keeps the same owners and adds one nullable
`ip_parties_and_roles.proceeding_id` link so two oppositions on one trademark
application cannot collapse their parties. Docket-level legacy parties remain
valid. Current proceeding parties are effective-dated; corrections retire the
prior row and append the new fact.

The baseline applicant/opponent profile is a typed, append-only
`ip_docket_events.event_kind = opposition_profile` revision. Its payload records
the applicable rule version, forum, source notice, client-instruction and
limitation facts, structured lawyer-authored grounds, challenged class segments,
relied-on rights, and service facts. The latest event ID is the profile's
optimistic-concurrency fence. PostgreSQL and SQLite reject updates or deletes to
both marked stage events and profile revisions.

The aggregate workspace reads the existing proceeding, application and
opposition identifiers, proceeding-scoped parties, Matter link, and stage-event
history. Leaving `draft` fails closed until both identifiers and the role-specific
profile facts are confirmed. Profile confirmation requires `ip:approve`; an
AI-assisted category remains visibly attributed and only becomes operative when
saved by that reviewer. Stage progression continues through the existing typed
opposition state machine. Documents, deadlines, hearings, tasks, billing,
communications, audit, and Matter lifecycle remain with their existing owners.

Specialized TM-O pleadings, Rules 45-47 evidence elections, legal deadline
calculation, hearing/order/appeal handling, downstream application-disposition
review, translations, adjournments, security for costs, Madrid designations, and
complete UJ-12/UJ-13 acceptance remain assigned to the later M4 slices; this
workspace does not claim or duplicate them.

## IPLF-041 applicant opposition workflow

IPLF-041 extends the IPLF-040 proceeding aggregate without adding a second
opposition, deadline, document, notification, or Matter owner. Applicant work
product is appended to `ip_docket_events` as typed
`opposition_applicant_action` facts. Counterstatement and applicant-evidence
dates are proposed and confirmed through the existing governed `ip_deadlines`
service and its Matter deadline, responsibility, reminder, calendar, and audit
projections.

The applicant workflow keeps pending opposition-number allocation explicit and
selects only an active rule whose immutable rule-set scope is exactly
`opposition` / `applicant` / `counterstatement_due` or
`applicant_evidence_due`. Critical confirmation requires the existing
operational Matter boundary and distinct primary/backup responsibility. A
counterstatement filing records its filing reference/date, final signed
document, filing evidence, and verification facts: signatory, authority,
place/date, verified paragraph ranges, knowledge basis, and signed-document
reference. Service is a separate fact. Rule 46 requires an explicit
`file_evidence` or `rely_on_pleaded_facts` election; absence is not an election.

Normal entry into `counterstatement_filed` and `applicant_evidence_filed` is
blocked until the corresponding work product exists. Exceptional opposition
transitions require source, evidence, authority, and authorized confirmation.
Withdrawal changes only the proceeding stage and preserves the linked Matter.
Applicant-action writes compose their response before commit so a failed
response cannot leave a committed legal event.

This slice proves the applicant counterstatement and Rule 46 path, pending
number handling, sourced extension control, and linked-Matter preservation.
Rules 47, further-evidence leave, hearing, order, appeal, settlement detail,
translations, security for costs, and downstream application disposition remain
with IPLF-043 and later allocated slices.

## IPLF-042 opponent opposition workflow

IPLF-042 composes the same IPLF-040 proceeding aggregate, append-only
`ip_docket_events`, governed `ip_deadlines`, shared Matter task writer, and
identifier owner. It adds no parallel opposition, deadline, task, document,
notification, or audit table. Opponent work product is recorded as typed
`opposition_opponent_action` facts with immutable source, evidence, document,
responsible-lawyer, time, and reason data.

The opponent workflow selects only active rules whose immutable rule-set scope
is exactly `opposition` / `opponent` and one of `notice_filing_due`,
`opponent_evidence_due`, or `reply_evidence_due`. Critical deadlines retain the
existing Matter projection, reminder policy, and distinct primary/backup
responsibility. Pending Registry opposition-number allocation remains explicit
and separate from the application number.

An accepted TM-O notice records the filing reference/date, final signed
document, filing evidence, and verification facts. Registry rejection does not
mark the notice filed: it appends the rejection fact and atomically opens an
urgent corrective shared task. Notice service remains a separate sourced fact.
Rule 45 requires an explicit `file_evidence` or `rely_on_pleaded_facts`
election, and Rule 47 requires `file_reply_evidence` or `no_reply_evidence`;
filed-evidence elections require both document and filing evidence references.
A watch hit can be closed without creating a filed opposition, while missing
client instruction stays in intake and opens an urgent limitation-aware shared
task.

Normal stage entry into `notice_filed`, `opponent_evidence_filed`, and
`reply_evidence_filed` is blocked until the corresponding opponent action
exists. Shared further-evidence leave, extensions, hearing, order, appeal,
settlement, translations, security for costs, and downstream application
disposition remain allocated to IPLF-043 and later slices.

## IPLF-043 shared opposition resolution workflow

IPLF-043 extends the same opposition aggregate without a migration or a second
evidence, hearing, deadline, order, appeal, Matter, document, or audit owner.
Typed `opposition_shared_action` facts live in append-only `ip_docket_events`.
Each fact has a stable legal-action identity, source, effective time,
responsible lawyer, confirmation, evidence, documents, and correction lineage.

Rules 45, 46, and 47 evidence packages record affidavit, exhibit, index,
verification, relied-on-document, filing, and service facts. Side and stage are
checked against the represented opposition. Further evidence additionally
requires a previously recorded matching leave or order. Same package versions
cannot be silently duplicated; corrections supersede a same-kind prior event.

An authorized extension delegates to the governed `ip_deadlines` override
writer in the same transaction. The prior deadline becomes superseded, the
replacement retains calculation lineage, and fresh primary/backup ownership
and reminders are applied. If the legal event append fails, the deadline change
rolls back too.

Hearing work points to the canonical shared `MatterHearing` record for the IP
docket. Preparation captures the issue checklist, evidence, authorities,
written submissions, attendance, and cause-list source. Post-hearing notes
require that hearing to be completed. Normal progression to
`reserved_for_order` is blocked until preparation exists.

An order can be recorded only at `reserved_for_order`, after hearing
preparation, and must identify the affected application and opposition. It
captures the operative result, costs, compliance directions, appeal review,
and final order document. Normal progression to `decided` requires that order.
An appeal link then preserves the order event while linking either a separate
appeal proceeding with a current appeal identifier or an access-visible Matter;
normal progression to `appealed` requires that link.

Withdrawal, waiver, abandonment, settlement closure, and other exceptional
stage decisions continue through the existing opposition transition writer,
which requires source, evidence, authority, and authorized confirmation and
does not close the linked Matter. Multi-class partial outcomes, translation,
adjournment detail, nonappearance, security for costs, and downstream
application disposition remain assigned to later slices.

## IPLF-044 Matter linkage and independent lifecycle display

`20260823_0003` adds `ip_matter_links` as an effective-dated relationship
history between the existing IP docket and Matter owners. It does not replace
either aggregate. Existing `ip_docket_records.matter_id` values are backfilled
as deterministic active `operational` relationships and remain a compatibility
pointer for the one operational Matter. Additional `litigation`, `advisory`,
`appeal`, `enforcement`, `billing`, and `other` roles are reference-only.

Relationship writes require access to both records, the `ip:write` capability,
the current docket timestamp, a reason, tenant-matched foreign keys, and
Matter-before-docket lock order. Active duplicates are rejected. Retirement is
an append-preserving state change with its own actor, time, reason, and link
version fence; only retirement of the active operational relationship clears
the compatibility pointer. A downgrade refuses once governed manual or retired
history exists.

Each authorized read returns the two lifecycle states side by side and flags a
different effective access policy. Readers without access to either side receive
no relationship row, count, or hidden identifier. Matter timelines compose
accessible `ip_docket_events` through each relationship's effective interval and
link back to the source IP docket; they do not copy an event into
`matter_activities`.

Matter disposal and reopen no longer archive, cancel, close, or resurrect the
linked IP docket, coverage, obligations, or events. IP lifecycle operations do
not change the linked Matter. Shared task, deadline, hearing, document,
notification, billing, opposition, and audit owners remain unchanged.

## IPLF-048 specialized opposition paths

IPLF-048 extends the existing `opposition_shared_action` event stream and reads
current class/goods rows from `trademark_application_scopes`. It adds no second
opposition or scope table. Every scope review records an explicit decision per
selected class segment and preserves all unlisted scopes. Partial or missing
Registry scope requires a source-confirmation reference. A later amendment or
division must identify both the related same-tenant application and the source
relationship reference.

Foreign-language evidence identifies the source and translated document by
reference and SHA-256, names the source language, translator, credential,
attestation, and service fact. A Rules 45/46/47 or further-evidence package that
declares foreign-language documents is rejected until each has a matching
attested translation event.

Hearing notice, adjournment, written arguments, and attendance records point to
the canonical `MatterHearing`. They preserve minimum-notice and rule-version
candidates, adjournment form/reason/fee/count/outcome, argument service, and
confirmed nonappearance consequences. Hearing status is checked at write time.
Security for costs remains its own classification and records direction,
enhancement, due date, payment evidence, and a confirmed consequence candidate.

Closure or an order does not infer an application result. A separate
disposition-review event identifies its trigger, affected current scope IDs,
recommendation, review status, and `no_automatic_application_update=true`.
Madrid oppositions additionally link the current application to its WIPO and
Indian designation identifiers and lifecycle source without replacing the
application owner.

## IPLF-049 post-registration proceedings

IPLF-049 extends `ip_proceedings`, `ip_identifiers`, and the append-only
`ip_docket_events` stream. It creates no parallel rectification, cancellation,
non-use, party, fee, service, document, hearing, deadline, order, or audit
owner. `rectification`, `cancellation`, and `non_use_removal` remain distinct
proceeding and identifier kinds. Opposition numbers and opposition stage
templates are rejected for these proceedings.

Each post-registration profile records the target right, applicant and
respondent, challenged class scope, grounds, forum, form, fee and service
status, source documents, and a lawyer-confirmed rule map. The canonical
template key is `post-registration/{proceeding_kind}`. A rule applied mutatis
mutandis must name its source rule, mapped provisions, excluded provisions,
and lawyer confirmation; copying an opposition template is not accepted.

Procedural actions append typed `post_registration_action` events. Stage,
evidence, hearing, order, compliance, and appeal states use the proceeding's
own template. A parallel court or Registry proceeding is linked by ID but
remains a separate `ip_proceedings` row. Interim-stay and stay-lift events are
projected in sequence, and an active stay blocks both creation and approval of
a registration-disposition candidate.

Settlement, withdrawal, and closure require the closure type, explicit legal
effect, effective date, source evidence, and authorized confirmation. A
disposition remains a candidate followed by an explicit approve/reject review.
Both events carry `registration_disposition_applied=false`; this workflow never
changes the linked trademark application's phase, active state, or registration
scope automatically.
