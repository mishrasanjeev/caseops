# Patent Pre-Grant Proceeding Journey

Version: PAT-PGO-2026-09-10.1. Parent contract: PAT-2026-09-10.2.
Scope: PAT-03 / IP-SCOPE-01..10 / UJ-39-EXC-03, with PAT-01/04 shared
lifecycle, source, access, audit and document boundaries. Modules M02/M08/M13/M14.
This concrete journey does not close the whole IPLF-079A/B or IPLF-080A/B program.

## Ownership

- EXTEND `IpProceeding`: independent pre-grant opposition identity, represented
  side, office, jurisdiction, stage and optimistic proceeding version.
- NEW typed `IpPatentProceedingDetail`: link that identity to a patent
  application without populating the trademark application FK. The application's
  canonical docket owns access and lifecycle; no second ACL or lifecycle owner.
- LINK `IpIdentifier`: a sourced opposition number, or explicit pending
  allocation followed by one sourced allocation. Retain the original raw value.
  Use the typed `patent_pre_grant_opposition` number kind so a trademark number
  cannot block patent admission or expose a patent in legacy duplicate candidates.
  A later number correction is not implemented by this journey and fails closed.
- LINK `IpPartyAndRole`: the proceeding counterparty identity and represented
  role; the typed detail retains its source-time name snapshot without conferring
  access, inventorship or title rights.
- NEW append-only stage snapshots: application version, lifecycle version,
  exact document version/hash, received/effective dates, actor, reason, outcome,
  optional exact response manifest and acknowledged preview impact.
- LINK canonical document, manifest, audit and idempotency owners. No provider,
  notification queue, deadline calculator, filing integration or Matter is created.

## Journey And Invariants

1. An authorized IP writer opens an IP India / IN patent application, enters
   Proceedings and creates a separate pre-grant opposition from an accessible
   notice source. Supply counterparty, represented side, dates and reason.
   Supply a real source number or explicitly retain allocation pending.
2. Move to response preparation. A later supplied number is allocated once to
   the canonical proceeding identity. Duplicate tenant/office opposition numbers
   are rejected without revealing the other proceeding.
3. Prepare a response using the existing work-product owner; select its exact,
   current application/lifecycle manifest to record response filed. A superseded
   or other-application manifest cannot be admitted or silently substituted.
4. Record hearing and decision, or sourced withdrawal. Decision/withdrawal
   requires an outcome and makes the proceeding read-only. These are lawyer-
   recorded facts, not an assertion of office acceptance or statutory validity.
5. Nonstandard stage order and backdating require explicit source review in both
   preview and commit. Changed data invalidates the preview. History retains the
   acknowledgement, original source and outcome. Application phase and deadlines
   never change as a side effect, and sibling applications remain untouched.
6. All writes reacquire the canonical company/access and source/docket locks,
   then compare application, parent lifecycle, work sequence and proceeding
   version. Current source access is checked on reads and after locking writes.
   Parent closure wins a waiting writer, including idempotent replay.
7. Closure retains readable authorized history and exact source downloads.
   Explicit application reopening does not resurrect an earlier-epoch proceeding.
   A second closure remains independent and leaves every retained snapshot intact.
8. Bound each application to 100 retained proceeding identities and each
   proceeding to 100 immutable stage rows. Lists page at 25, maximum 100, with a
   work-sequence snapshot. History reads validate contiguous revisions and use
   batched source/manifest access. Bounds never truncate claimed complete history.

## Acceptance Inventory

- `tests/test_ip_patent_proceedings.py`: complete notice/response/hearing/decision,
  source-pinned manifest replacement, sibling noninterference, stale commands,
  duplicate number, exceptional/backdated preview, closed/reopened history and ACL.
- `tests/test_ip_patent_proceedings_postgres.py`: all HTTP journeys on PostgreSQL,
  different-actor closure races for create/transition and replay, bounded retained
  history with successful below-bound save and replay.
- `test_patent_work_fresh_migration_roundtrip_and_retained_downgrade`: independently
  fresh migration0004 rehearsal, all five evidence tables, indexes/constraints/
  triggers, and repeated source-preserving refusal when records exist.
- `PatentProceedingsWorkspace.test.tsx`: authoritative discovery, hydrated draft
  preservation, exact command tokens/source, preview acknowledgement, success
  without alerts, rejection without false success, terminal history, strict DTOs.
- `iplf-080b-patent-pregrant-proceeding-2026-09-10.spec.ts`: dated user-visible
  proceeding journey at 393/768/1280px, breakpoint controls, persisted reload,
  exact historical download, independent sibling, closure/reopen/second closure,
  neutralized open child and cross-tenant denial. No paid providers or retries.

## Explicit Remaining Scope

Post-grant opposition, revocation, appeals/Matter linkage, proceeding-number
correction, authoritative service/deadline calculations, fee/cost workflows,
submission and office acceptance remain separate program requirements. Foreign
office workflows are not admitted by this implementation. No source or browser
test can certify production until the parent integrates and validates its release.
