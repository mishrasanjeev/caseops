# IP foreign-associate instruction workflow

**Slices:** IPLF-059A and IPLF-059B

**Journey boundary:** IPLF-059A supplies the canonical persistence and API
contract used by UJ-37. IPLF-059B extends that owner with the operator page and
shared-notification reminder projection, and proves the complete browser
journey. Neither slice replaces a linked platform owner.

## Ownership contract

`ip_foreign_associate_instructions` is the only coordination aggregate added by
this slice. It records a versioned instruction, its reviewed dispatch scope,
acknowledgement, foreign filing report, independent filing verification and
reconciliation links. It does not own the linked concerns:

- `IpClientInstruction` owns canonical client authority and supersession.
- `OutsideCounsel` and `MatterOutsideCounselAssignment` own the panel firm and
  approved Matter assignment.
- `Communication` and existing connectors own dispatch and delivery evidence.
- `IpDocument` owns selected, privileged, filing-report and verification
  documents; selected privileged material requires explicit inclusion and
  `ip:approve`.
- `IpCostItem`, `OutsideCounselSpendRecord` and Matter billing own estimates,
  actual legal costs, invoices, payment and accounting reconciliation.
- `IpDeadline` owns legal deadlines; the aggregate stores only its associate
  response target for the later shared reminder projection.
- `IpDocketEvent`, access controls and audit remain the canonical event,
  authorization and audit owners.

No associate directory, mailer, document store, invoice ledger, cost ledger,
deadline engine, notification dispatcher, access system or event log is added.

## State and evidence

The instruction progresses through `draft`, `approved`, `dispatched`,
`acknowledged`, `in_progress`, `filing_reported`, `evidence_verified`,
`invoiced` and `completed`. `refused`, `superseded` and `cancelled` preserve
terminal history. Every command requires both the aggregate row version and the
docket lifecycle version.

Delivery is not acknowledgement. Filing-report evidence is not independent
Registry evidence. Completion is rejected until a paid outside-counsel spend
record and a matched actual IP cost item are linked. Fee or FX changes require
an approver and replace the estimate link without deleting the prior event
evidence. Conflict or refusal re-assignment creates a successor instruction and
preserves the original correspondence, scope and selected-document history.

An approved Matter assignment must carry a budget ceiling before the initial
estimate can be admitted. A canonical Communication counts as dispatch only in
manual-log, sent, delivered or opened state; queued, failed and bounced records
cannot start the response clock. A terminal docket transition atomically marks
every unfinished instruction `cancelled` with the lifecycle event, lifecycle
version and timestamp. Those records remain audit history but are excluded from
instruction reads, so controlled reopen cannot resurrect actionable work.

## API contract

- `GET/POST /api/ip/foreign-associate-instructions`
- `GET /api/ip/foreign-associate-instructions/create-options?docket_id=&target_jurisdiction=`
- `GET /api/ip/foreign-associate-instructions/{instruction_id}`
- `GET /api/ip/foreign-associate-instructions/{instruction_id}/workspace`
- `POST /api/ip/foreign-associate-instructions/{instruction_id}/transactions`
- `POST /api/ip/foreign-associate-instructions/{instruction_id}/reminders`

The list supports explicit outstanding-response and missing-filing-evidence
filters. All reads and commands resolve the authenticated company and existing
docket access policy; cross-company identifiers fail as not found.

`create-options` (IP write or approve) serves the New instruction form from the
create validator's own predicates: panel associates approved for the target
jurisdiction, budgeted Matter assignments with the active estimates that fit
them, active estimates, accepted proceed client instructions and linked
documents, plus typed blockers that name the missing prerequisite and where it
is created. Filing jurisdictions use one canonical vocabulary (ISO 3166-1
alpha-2 plus EM, WO and EP; aliases such as UK and United Kingdom resolve to
GB). Counsel profile text is normalized on read and match, never migrated;
create refuses a target outside the vocabulary, while instructions stored
before normalization keep the exact comparison (create-options returns such a
stored target unchanged and offers the counsel that comparison accepts, for
reassignment). On a counsel profile a bare code that is also an Indian state,
union territory or court abbreviation (AR, AS, BR, CG, CH, GA, HR, LA, MH, ML,
MN, MP, MZ, NL, PY, SC, SK, TG, TN, TR) names no country; the country must be
written out ("Switzerland", not "CH"). A filing target, always picked from the
vocabulary, is unaffected.

Blockers carry a link only when the caller's role can act on it:
`can_manage_counsel` (outside_counsel:manage: owner, admin, partner) gates the
Add counsel and Matter assignment links, `can_record_estimate`
(ip:fees_manage) the quote path, and otherwise the message names who can act.
The documents blocker deep-links to the record's Documents tab
(`/app/ip?docket=<id>&area=documents`) and says when uploads first need an
active document classification (an IP taxonomy admin's setup). For an estimate
whose amount is withheld from the caller (confidential rate, no fee
permission), assignment compatibility compares the currency only; create
checks the budget ceiling. Matter assignments take a currency chosen in Assign
counsel, so a foreign quote pairs with a budget in the same currency.

## Migration and rollback

Migration `20260825_0006` adds an empty coordination table and an optional,
tenant-correlated event link with a five-second PostgreSQL lock timeout. Empty
rollback is supported. Once instruction or linked event data exists, downgrade
fails closed and the release must restore forward.

## Operator and reminder surface

`/app/ip/foreign-associates` exposes intake/search entry, explicit document and
privilege selection, authority, approved associate/assignment/budget, estimate
and tax terms, approvals, dispatch, acknowledgement, queries, lawyer-reviewed
responses, fee changes, filing report and independent verification, invoice and
payment reconciliation, completion, refusal and reassignment. Separate queues
identify outstanding acknowledgements and filing reports missing independent
evidence. Selected documents and URL evidence open their canonical sources.

Reminder requests project into `NotificationDeliveryIntent`; they do not add a
second notification scheduler. Policies are version-checked, bounded to ten
unique offsets from 0 to 720 hours and the existing in-app/email channels, and
idempotent on replay. A critical overdue escalation is addressed to the named
or configured responsible membership. Acknowledgement, refusal, cancellation
or reassignment cancels still-actionable intents while preserving delivered or
provider-blocked history for audit.

The guide and law-firm page describe the implemented reviewed workflow without
claiming automated foreign filing or provider delivery. Local and exact-release
production Playwright tests own the dated UJ-37 acceptance boundary.
