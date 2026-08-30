# ADR-001: One-writer ownership for IP extensions

- Status: Accepted as the repository engineering boundary
- Date: 2026-08-06
- Scope: M2 and M3 architecture / IPLF-019
- Enforcement: Repository ownership validation, reciprocal manifest coverage, ADR presence, and exact-release evidence are the complete engineering gate; no separate manual program signature is required.

## Context

The IP PRD adds legal facts that CaseOps does not currently model, but it also
touches mature Matter/platform owners for tasks, hearings, deadlines, access,
notices, notifications, documents, billing, sources, court tracking, provider
operations, imports, and reporting. Creating an IP-prefixed copy of those
owners would introduce conflicting lifecycle, actor, target, evidence, retry,
and audit state.

PRD Section 11.2 therefore binds implementation to one service owner and one
canonical mutable state after cutover. Physical Matter-named tables may remain
during compatibility. Naming cleanliness is not a reason to replace them.

## Decision

`docs/ip-implementation/OWNERSHIP_LEDGER.yaml` is the repository-backed
Definition-of-Ready registry for every M2/M3 epic. Each proposal must declare:

- `NEW`, `EXTEND`, `LINK`, or `REPLACE`;
- the canonical writer and exact state boundary;
- the compatibility adapter;
- reconciliation and one-writer switch evidence;
- the earliest just-in-time milestone and retirement gate; and
- an ADR for every overlapping `REPLACE` proposal.

New IP tables are permitted only for the legal facts named in PRD Section 11.1
or a reviewed decomposition of them. New neutral tables are permitted only for
the shared foundations named in Section 11.3. Existing owner expansions remain
just in time: M2 does not prebuild nullable portal, intake, conflict, drafting,
provider, report, assistant, access-review, emergency-access, or purge surfaces
whose first consumer belongs to a later milestone.

The following rules are invariant:

1. A legal IP fact, Matter operational fact, audit fact, provider operation,
   outbox event, and notification effect remain distinct records and are
   composed by reference; they are never bidirectionally synchronized copies.
2. Target-aware compatibility routes delegate mutations to one command owner.
3. A shared projection is one-way and uniquely correlated to its legal source.
4. Old and new revisions may coexist only during an explicit
   expand/backfill/verify/switch window with optimistic concurrency and worker
   fencing.
5. A compatibility path is not retired until reconciliation, rollback/forward
   repair, exact-image production E2E, and the slice-specific machine evidence
   pass.

## Enforcement

`scripts/ip_ownership_ledger.py validate` parses the binding Section 11.2
capability list, requires an ordered decision for every M2/M3 epic, validates
repository owner references and ADRs, checks every M2/M3 manifest slice against
its ledger decision, and scans application/migration/web/Cloud Run source for
forbidden duplicate identifiers and control-plane patterns. CI runs the check.

The guard is deliberately conservative. A legitimate future exception requires
a version-controlled field-by-field gap analysis, ADR, and validator update in
the same exact candidate before the guard and ledger can change. A passing
application suite alone is not permission to weaken it.

## Consequences

- Later slices may require refactoring Matter-named services rather than adding
  a convenient IP-specific subsystem.
- Migration work must include explicit compatibility and reconciliation gates.
- Current bounded IP tails remain preserved and are listed in the ledger so
  later foundation work migrates or composes them instead of creating a second
  docket/cost/evidence owner.
- Legally, financially, externally, or destructively effectful authorization
  remains localized to the exact product action; it is not an architecture,
  implementation, compatibility-retirement, or release signoff.

## Rollback

This ADR changes governance and CI only. Rollback is removal of the validator
invocation and ledger metadata in one revert; it does not mutate schema or
production data. Application changes made under later slices retain their own
rollback plans and cannot rely on reverting this ADR.
