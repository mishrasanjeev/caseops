# IP prosecution workflow contract

Last updated: 7 August 2026

Implementation slice: `IPLF-022B`

Status: repository implementation and local verification complete at
`08ae3ecd0a8eedd3d5f2bc2e994b48732fddfaf1`; independent CI, canonical-main
release, exact production verification, and human acceptance remain pending.

## Purpose and ownership

This workflow turns the IPLF-022A append-only event store into a usable,
capability-gated prosecution workspace. `IpDocketEvent` remains the immutable
legal-fact history and `TrademarkApplication` remains the independent
application-phase owner. Existing Matter tasks, deadlines, communications,
billing, documents, and audit records are linked by identifiers and summary
counts; this slice does not create competing shared subsystems.

The routes require the existing `ip:read`, `ip:write`, or `ip:approve`
capability as appropriate. Tenant and restricted-Matter access are enforced on
the server. Frontend visibility, rollout state, and billing entitlement never
substitute for authorization.

## Preview-before-commit event flow

`POST /api/ip/dockets/{docket_id}/events/preview` is side-effect free. It
validates the docket lifecycle version, the optional application version,
tenant ownership, target ownership, event semantics, registry-source rules,
and correction/reconciliation links. The response shows:

- current and proposed phase;
- whether the effective date is backdated and recalculation is required;
- possible duplicate event identifiers;
- facts, forms, fees, documents, approvals, and exception checklist rows;
- unresolved exception codes; and
- an explicit statement that operational effects are proposals and filing is
  not claimed.

`POST /api/ip/dockets/{docket_id}/events` repeats the authoritative validation
inside the write transaction. It locks the parent, allocates the next sequence,
appends the legal event, updates the targeted application or proceeding phase
with optimistic concurrency, and appends audit evidence. Preview is a user
safety step, not a reusable authorization token.

Manual events require a reason. Registry events require a source reference and
remain candidates until an explicit `same_fact`, `keep_separate`, or
`reject_candidate` reconciliation. Corrections append a new event linked by
`supersedes_event_id`; the original row is never rewritten.

## Application lifecycle

Alembic revision `20260807_0004` adds `is_active` and `lifecycle_version` to
trademark applications and normalizes existing terminal phases. Filing,
formalities, examination, response, hearing, acceptance, publication,
registration, renewal, refusal, abandonment, and restoration map to explicit
phases.

Refused or abandoned applications are fail-closed. Generic phase PATCHes and
ordinary child events cannot reactivate them. Only a version-checked
`restoration` legal event can return the application to an active phase. Each
application keeps its own identifier, event history, version, and lifecycle
version even when dockets are grouped at client, mark, or family level.

## Checklist and legal-effect boundary

The checklist reports whether supporting facts, forms, fee evidence,
documents, approvals, and exception handling are present. Missing items remain
visible as gaps. Historical events may still need to be recorded with gaps, so
checklist completion is not treated as proof that a filing occurred, was
accepted by a registry, or achieved a final legal disposition.

The stored event payload distinguishes four report dimensions:

1. operational completion;
2. filing evidence;
3. registry acceptance; and
4. final legal disposition.

No external filing, fee payment, notification, registry mutation, or client
communication is performed by these routes.

## Workspace read model

`GET /api/ip/dockets/{docket_id}/prosecution` returns the current phase,
registry freshness (`not_configured`, `candidate_pending`, or `current`), data
quality gaps, unconfirmed deadline references, conflicting event identifiers,
the ordered immutable timeline, and separate counts for the four report
dimensions above. The web card keeps these signals adjacent to the current
phase and exposes preview and commit as separate controls.

The narrow-mobile acceptance test measures every grouped action at 360 pixels.
Containers are explicitly shrinkable, full-width on mobile, and wrapping;
DOM presence alone is not acceptance evidence.

## Docket lifecycle workflow

`POST /api/ip/dockets/{docket_id}/lifecycle/preview` computes downstream
coverage, obligation, deadline, incident, proceeding, recordal, Matter, and
successor impacts without mutation. Open deadline incidents become blocker
codes. Commit requires exact acknowledgement of unresolved exceptions and may
require a different second approver for high-risk outcomes.

`POST /api/ip/dockets/{docket_id}/lifecycle` repeats the preview under the
parent locks, rejects stale versions, applies the active/terminal transition,
neutralizes operational children atomically, appends the final-disposition
event and audit row, and preserves successor/report/Matter handling choices.
Controlled reopen never resurrects neutralized children. Transfer requires an
active same-tenant successor and preserves the redirect in immutable history.

## Verification and rollback

The authoritative executable proofs are:

- `test_ip_prosecution_workflow.py` for UJ-06/UJ-53 normal and exception
  behavior, application terminal state, reconciliation, correction,
  backdating, reporting, transfer, close, stale rejection, and reopen;
- `test_ip_lifecycle_service.py` for the IPLF-022A history/lifecycle
  invariants;
- `test_20260807_application_lifecycle_migration.py` for exact upgrade,
  downgrade, re-upgrade, defaults, normalization, and indexes;
- `apps/web/app/app/ip/page.test.tsx` for preview gating, blocker
  acknowledgement, reporting language, and responsive controls; and
- `tests/e2e/ram-2026-08-01-bugs.spec.ts` for the full synthetic browser flow
  through real API persistence at 360 pixels.

Before legal event writes, the additive migration can be downgraded. After
append-only history exists, rollback is rollout-off plus a forward,
history-preserving correction. Destructive removal of legal events is not an
authorized production rollback.

IPLF-033B still owns the later trademark-specific workflow depth allocated to
the same `IP-PROS-01..12`, UJ-06, and UJ-53 records. Therefore this slice can be
implemented and verified without claiming those reciprocal program records,
M2, M3, or the full program complete.
