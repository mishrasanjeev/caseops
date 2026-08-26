# IPLF-060 Judge Mapping Foundation and Workflow

Status: repository implementation and exact-production release verified at
`527adb8d48043b7a6087a4bce7c0026aa95e5cc6` for IPLF-060A. IPLF-060B,
JUDGE-01 through JUDGE-10, and UJ-20 are implemented and locally verified on
26 August 2026; their exact-production release remains pending.

## Scope boundary

IPLF-060A is the backend and ownership foundation for canonical judge and bench
mapping. It does not claim the IPLF-060B judge-profile, mapped-judgment browsing,
source-action, curator UI, pilot-court, or UJ-20 release journeys.

The implementation extends these existing owners:

- `Court`, `Bench`, `Judge`, `JudgeAlias`, and `JudgeAppointment` remain the
  canonical identity catalog. No parallel judge, court, tenure, or roster master
  was added.
- `AuthorityDocument.judges_json` remains immutable raw extraction evidence.
- `JudgeDecisionIndex` remains the canonical judge-to-authority projection.
- Existing judge profiles, court pages, court sync, authority source fields,
  predictive-intelligence policy, and audit storage remain authoritative.
- The existing `court_sync:run` staff capability protects global catalog
  curation. Frontend visibility is not authorization.

The new `BenchAlias` and `JudgeMappingReview` records have distinct purposes:
bench name resolution and fail-closed review of unresolved authority evidence.
They do not duplicate an existing writer.

## Data contract

Migration `20260826_0002` is additive and follows expand/backfill/verify/switch:

- Judges and benches gain source provenance and optimistic record versions.
- Judges gain an identity version and a self-referential merge target.
- Existing judge aliases gain source evidence, activation state, and a version.
- Bench aliases are source-attributed and unique per canonical bench.
- Mapping reviews preserve authority ID, source ordinal, raw and normalized
  names, candidates, resolver version, resolution actor/note/time, and version.
- Judge-decision mappings preserve raw name, source ordinal, match confidence,
  mapping status, resolver version, structured evidence, analytics eligibility,
  and update time.

Legacy mappings are backfilled as analytics-eligible only for `exact`,
`initial_surname`, or `curator_confirmed` confidence. New unreviewed rows default
to ineligible. No free-text coincidence becomes an analytics fact by default.

The migration caps PostgreSQL lock acquisition at five seconds. SQLite replay
uses nullable-add, backfill, then non-null alteration for populated tables.
Downgrade is allowed only while every new table and provenance/evidence field is
unused. Once legal-source lineage exists, rollback is restore-forward.

## Resolution behavior

Resolver `judge-alias-v2` performs these steps:

1. Resolve the authority court against the active canonical court catalog.
2. Read raw judge names from `AuthorityDocument.judges_json` without rewriting it.
3. Match only active aliases belonging to active judges in that court.
4. Accept one deterministic candidate; create or refresh a review for zero or
   multiple candidates.
5. Preserve curator-confirmed mappings during automatic reprocessing.
6. Reconcile automatic rows in place, remove stale automatic rows, and retain
   stable source evidence and resolver provenance.

Curator resolution locks the review and selected judge, requires an optimistic
version, rejects inactive/merged or wrong-court judges, removes competing
automatic rows for the same evidence slot, and refuses to replace a competing
curator-confirmed decision.

Alias upsert rejects an alias already owned by another active judge in the same
court and reprocesses only affected open evidence. Duplicate merge locks both
identities, checks both versions, transfers aliases, appointments, mappings, and
review references atomically, invalidates derived affinities, and refuses a
third-judge alias collision in the destination court. Audit and mutation commit
in one transaction through the route layer.

## Analytics boundary

`JudgeDecisionIndex.is_analytics_eligible` is the shared admission fact.
Automatic exact/initial-surname and curator-confirmed mappings set it true;
unreviewed and low-confidence rows remain false while retaining raw evidence.

The fence is enforced by:

- judge authority-affinity and statute-focus refreshes;
- bench-strategy decision counts;
- predictive bench-document loading;
- authority outcome classification judge IDs;
- judge-filtered predictive backfill selection; and
- judge-scoped aggregate selection, including previously classified records.

Revoking eligibility removes a mapping from every predictive consumer without
deleting the authority, raw name, mapping evidence, or review history.

## API and operations

The additive `/api/judge-mapping` contract provides bounded staff-only routes to:

- list open or historical reviews with a maximum page size of 200;
- resolve one review with optimistic concurrency;
- add sourced judge and bench aliases;
- merge duplicate judge identities with source/destination versions; and
- reprocess one authority document.

Every mutation is audited. The nightly `caseops-judge-mapping-refresh` Cloud Run
job uses keyset pagination and bounded batches, replacing the prior offset scan
and first-candidate behavior. Its production scheduler is deployed and
digest-pinned but remains paused until IPLF-060B and independent source,
pilot-court, legal, provider, and UAT acceptance pass.

## IPLF-060B workflow extension

IPLF-060B extends, without duplicating, the foundation above:

- Judge profiles now read only canonical `JudgeDecisionIndex` mappings, embed the
  first bounded page, and provide opaque-cursor pagination with citation, date,
  court/bench, source, mapping confidence, raw evidence, and analytics status.
- Court judge listings expose grouped mapped and analytics-eligible counts
  without per-judge query fan-out.
- Coverage states distinguish no mapped court corpus, no judgments for the
  selected judge, and no filter matches.
- The staff curator UI resolves review evidence, creates sourced judge and bench
  aliases from server-owned catalogs, merges duplicate identities with record
  versions, and reprocesses affected authorities.
- Low-confidence mappings remain visible and labelled but are excluded from
  analytics. Descriptive copy is coverage-qualified and prohibits personality,
  bias, emotion, outcome probability, favoritism, and judge-shopping claims.
- Local UJ-20 normal and three exception journeys pass at a 360px viewport, and
  deterministic source-action smoke tests cover Delhi, Bombay, and Madras High
  Courts.

IPLF-060B adds no schema or writer. Exact-main CI, immutable deployment, real
production pilot-court data/source acceptance, legal/provider acceptance, and
law-firm UAT remain release gates. The refresh scheduler stays paused.

## Verification and rollback

Local evidence is recorded in
`evidence/m6/IPLF-060A/local-2026-08-26.md` and
`evidence/m6/IPLF-060B/local-2026-08-26.md`; IPLF-060A exact-release evidence is
recorded in `evidence/m6/IPLF-060A/release-2026-08-26.md`. CI proved a single Alembic
head, PostgreSQL upgrade/backfill behavior, generated OpenAPI parity,
data-governance parity, API/web tests, and scheduler inventory. Production
proved exact API/web SHA identity, immutable image digests, idempotent migration,
paused exact-digest scheduler reconciliation, latest-only traffic, health, and
unchanged production acceptance.

Before any new lineage is written, rollback may return services and migration to
the predecessor. After lineage is written, keep the additive schema, disable or
pause activation, restore the prior service image if compatible, correct data or
code forward, and retain the evidence and audit trail.
