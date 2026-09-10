# Plant Varieties Child PRD

Version: OTHER-IP-2026-09-09.1. Owner: other-ip-domains.
Parent: docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md, sections 13 and 16;
IPLF-091A/091B; PVP-01; UJ-44; IP-SCOPE-01 through IP-SCOPE-10.

## Bounded Contract

This independent contract implements restricted intake and a source-backed evidence
journal. It is not a complete legal lifecycle, an activated jurisdiction, or a
claim that the domain's full parent journey is implemented. Stage remains
unavailable until the parent-owned capability catalogue registers this exact
contract. Registration permits intake only. Beta/GA and authoritative automation
still require the existing source-pack, legal-fixture and exact-release gates.

User story: an authorized specialist records denomination, supplied category, crop/species, applicant, breeder, farmer claim, material custodian and material-access instructions without borrowing trademark
fields or legal states, corrects a transcription with a reason and concurrency
tokens, preserves every earlier version, uploads restricted evidence, and records
an observation tied to an exact document version, SHA-256 and page/locator.

## Normal And Exception Journeys

Normal: select this domain, select an active client, enter the typed facts, create
idempotently, reload, upload evidence into the record's restricted document area,
select its exact retained version, record a domain-specific observation and reload.
Corrections append history. An observation correction explicitly supersedes the
same prior observation and cannot overwrite or branch its retained history.

Material custody is recorded from evidence and does not grant biological-material access. DUS evidence, applicant/breeder/farmer roles and benefit-sharing claims remain distinct.

Missing, changed, inaccessible, rejected or superseded evidence cannot support a
new observation. Source failure is explicit and no provider is called. A stale
version, withdrawn membership, missing capability or revoked docket grant rejects
writes. Close/reopen uses only the existing IP lifecycle command with expected
lifecycle version and reason. Closed history remains readable to currently
authorized users; corrections, uploads and creation replay remain denied. Reopen
returns to ready and never changes previously recorded legal evidence.

## Ownership And Boundaries

Canonical owners: IpDocketRecord for lifecycle/access/current fact version;
IpAsset for independent domain identity; IpSpecialistRecord and immutable versions
for these typed facts; IpSpecialistObservation for source evidence; existing
IpDocument/IpDocumentVersion for bytes; existing grants, audit and private-source
invalidation for ACL/tombstones. No duplicate patent, trademark, Matter, task,
notification, billing or registry owner is introduced.

All ten specialist types remain absent from general IP disclosure. A document
with even one specialist link is denied general AI/portal/export/notification
eligibility even if it also has an ordinary trademark link. Saved projections and
delivery-time reads must reapply that policy. This contract does not enable those
channels. Tenant-only list pages use bounded keyset pagination and omit hidden
records and counts. Private facts never enter public capability metadata.

## Source Inputs And Remaining Work

Required source pack: Official PPV&FR legislation and Rules; exact crop-specific DUS guidelines, denomination/category, seed-material, fee, benefit-sharing and licence procedure packs.
Each legal automation pack needs immutable official bytes, source version, issuing
body, publisher, retrieval/link-check timestamps, section-level provenance, lawful
use evidence, two-reviewer fixtures and exact-release results. Intake records no
current-law conclusion and computes no legal deadline or fee.

Not implemented by this intake: legal-rule activation, automatic filing, paid
registry access, legal status derivation, notices/delivery, obligation/task/billing
projection, complete contested/transfer/maintenance workflows or general disclosure.
These remain explicit parent-journey gaps, not generic completion statuses.

## Acceptance

Stable local tests: OIP-plant_variety-intake, OIP-plant_variety-observation,
OIP-history, OIP-stale, OIP-source-failure, OIP-revocation, OIP-terminal,
OIP-disclosure, OIP-schema, OIP-pg-race and OIP-pg-migration.
HTTP and PostgreSQL must prove normal, invalid, stale, revoked, cross-tenant,
source-version, idempotency and lifecycle boundaries. Frontend must prove hydration,
retained inputs on rejection and canonical nested payloads. Dated Playwright must
prove visible values and reload at 393/768/1280px. Full integration, migration
rehearsal, all normal/exception parent journeys and exact-production proof remain
parent-owned release requirements; local tests cannot close them.
