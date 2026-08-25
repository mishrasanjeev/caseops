# IP foreign-associate instruction foundation

**Slice:** IPLF-059A

**Journey boundary:** This slice supplies the canonical persistence and API
contract used by UJ-37. IPLF-059B owns the operator page, reminders,
notifications, guide and public claims, and the complete browser journey.

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
- `GET /api/ip/foreign-associate-instructions/{instruction_id}`
- `GET /api/ip/foreign-associate-instructions/{instruction_id}/workspace`
- `POST /api/ip/foreign-associate-instructions/{instruction_id}/transactions`

The list supports explicit outstanding-response and missing-filing-evidence
filters. All reads and commands resolve the authenticated company and existing
docket access policy; cross-company identifiers fail as not found.

## Migration and rollback

Migration `20260825_0006` adds an empty coordination table and an optional,
tenant-correlated event link with a five-second PostgreSQL lock timeout. Empty
rollback is supported. Once instruction or linked event data exists, downgrade
fails closed and the release must restore forward.

## Deferred completion surface

IPLF-059B must expose the aggregate through the complete UJ-37 operator journey,
including intake/search entry, document selection, approvals, dispatch,
acknowledgement and query handling, lawyer-reviewed substantive responses,
filing evidence, invoice/payment reconciliation, outstanding-response and
missing-evidence queues, reminders/escalations, source opening, responsive UI,
guide and truthful law-firm landing-page coverage. IPLF-059A does not claim
those journey paths complete.
