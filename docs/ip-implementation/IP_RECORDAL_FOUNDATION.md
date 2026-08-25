# Post-registration recordal foundation

Last updated: 25 August 2026

## Scope and ownership

`ip_post_registration_recordals` is the typed legal aggregate for assignment,
transmission, registered-user, licence, name/address, association, division,
limitation, disclaimer, certified-copy, well-known-mark, renewal and restoration
recordals. It does not own opposition, rectification, cancellation or non-use
proceedings; those remain in the IPLF-049 proceeding workspace. Renewal terms
and client instructions remain with IPLF-037.

The aggregate links to existing canonical owners:

| Concern | Canonical owner |
| --- | --- |
| Docket access and lifecycle | `ip_docket_records`, Matter access policy and IP lifecycle service |
| Legal transaction history | Append-only `ip_docket_events` |
| Effective-dated title/licence projection | `ip_title_interests` through `services/ip_operations.py` |
| Instruments and filing evidence | IP document/version/link records |
| Official and professional costs | `ip_cost_items` and Matter billing reconciliation |
| Legal deadlines | `ip_deadlines` and the active rule catalog |
| Registry provenance | Immutable registry links, attempts and snapshots |
| Actor evidence | Shared audit records and capability checks |

## State contract

The supported path is `draft -> ready -> filed -> accepted`. A filed recordal
may receive an acknowledgement, become defective, be corrected to ready and be
filed again. Filed or defective recordals may be rejected or withdrawn. Draft
and ready recordals may be withdrawn at their allowed transitions.

Every mutation requires both the expected recordal version and the current
docket lifecycle version. Review, acceptance and rejection require `ip:approve`;
other commands require `ip:write`. Transactions append an event atomically with
the aggregate update, title projection and audit evidence.

Assignment, transmission, licence and registered-user requests require an
execution date, effective date and their legally relevant parties. Partial
scope requires affected Nice classes. Supporting instruments must be canonical
documents linked to the selected docket, and every party must cite one of those
instruments. Cost, deadline and registry references must belong to the same
tenant and docket.

## Title and registry controls

A reviewed assignment/transmission or licence projects a `pending` title
interest. Filing changes that projection to `filed`; neither state replaces a
registry-recorded proprietor. Registry acceptance changes only the projected
recordal interests to `recorded` and stores the registry-recorded date.

Acceptance requires evidence, a registry source URL/reference and an immutable
snapshot from a confirmed application or registration link whose normalized
identifier is explicitly affected by the recordal. The supplied URL must match
that snapshot. The docket event is the approving operator's manual legal
decision with registry provenance in its payload; raw registry-origin events
continue to enter the shared lifecycle as candidates until separately
reconciled.

The shared duplicate detector keys a recordal transaction by recordal ID,
transaction kind and prior aggregate version. This rejects exact replays while
allowing a corrected recordal to be filed again on the same date.

## Release boundary

IPLF-058A provides persistence, ownership, typed APIs, state transitions,
access filtering, canonical evidence links and title projection. IPLF-058B owns
the complete user interface and UJ-36/UJ-61 normal and exception paths,
including full-scope/partial-scope operator ergonomics, impact review,
responsive acceptance, user-facing documentation and truthful landing-page
claims. This foundation does not claim those journeys complete.
