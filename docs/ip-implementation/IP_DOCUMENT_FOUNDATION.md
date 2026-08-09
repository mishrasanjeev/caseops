# IP document foundation and ownership contract

**Slice:** `IPLF-024A`

**Program status:** `PROGRAM INCOMPLETE`

## Purpose and bounded scope

IPLF-024A supplies the additive data and API foundation for governed IP
documents. It creates tenant-owned document identity, immutable binary-version
metadata, typed links to legal records, a configurable seeded taxonomy with
aliases, and a deterministic naming preview. The slice deliberately does not
claim the IPLF-024B upload/review/approval user journey or completion of
`IP-DOC-01..12` and UJ-14; those remain allocated to the dependent completion
slice.

This boundary is functional rather than deferred design. IPLF-024B can consume
the exact records and contracts documented here without adding another binary
store, malware queue, OCR queue, or synthetic Matter requirement.

## One-writer ownership decisions

| Concern | Decision | Canonical owner | Compatibility rule |
|---|---|---|---|
| IP document identity | `NEW` | `ip_documents` | One stable identity may have many immutable versions and many legal-record links. |
| IP binary/version evidence | `NEW` identity over `LINK` infrastructure | `ip_document_versions` owns original/display name, storage key, content hash, processing evidence, state, and approval lock | Binary bytes remain in shared document storage; no byte copy is permitted. |
| IP legal-record links | `NEW` | `ip_document_links` | A link has exactly one typed target and never duplicates a binary. |
| Tenant document taxonomy | `NEW` | `ip_document_taxonomy_entries` and `ip_document_taxonomy_aliases` | Seeded entries are tenant-owned, configurable, versioned, and optimistic-concurrency protected. |
| Malware/OCR/extraction queue | `LINK` | existing `document_processing_jobs` and shared document-processing adapters | `ip_document_version` is the reserved target type; IPLF-024B wires upload and worker execution to this existing queue. No second queue is allowed. |
| Matter attachments | `KEEP` | existing `matter_attachments` | Matter-bound legacy uploads remain canonical for Matter workflows. No portfolio document is forced into a synthetic Matter. |

The schema enforces company-matched composite foreign keys for every taxonomy,
document, version, actor, and legal target. A version-specific link must point
to a version belonging to that same document; a same-tenant version from a
different document cannot be substituted.

## Additive schema

Migration `20260809_0001_ip_document_foundation.py` advances the single Alembic
head from `20260807_0005` and adds five tables:

1. `ip_document_taxonomy_entries` — tenant key, label, description, ordering,
   active/seeded flags, optimistic version, and updater.
2. `ip_document_taxonomy_aliases` — original alias and normalized alias, unique
   per tenant and bound to one taxonomy entry.
3. `ip_documents` — stable identity, taxonomy, title, confidentiality,
   privilege, current-version pointer, and creator.
4. `ip_document_versions` — immutable original filename, controlled display
   name, unique storage key, SHA-256, size/type, shared-processing status,
   extraction/OCR evidence, legal-document state, uploader, and approval lock.
5. `ip_document_links` — document and optional version plus exactly one of
   docket, application, proceeding, event, or deadline.

Database checks reject non-positive versions, invalid confidentiality or state,
negative sizes/extracted counts, non-64-character hashes, OCR scores outside
0..1, an approved/filed version without actor and timestamp, zero or multiple
link targets, a target-type/ID mismatch, and a version from another document.

The migration is expand-only and contains no backfill because there is no
pre-existing canonical IP document table. Downgrade removes only the five new
empty-schema owners in reverse dependency order; production rollback after
data creation must roll application traffic back while retaining the additive
tables until data retention/export review is complete.

## API contracts

All routes remain behind the independent `ip_workspace` billing entitlement.
Authentication, entitlement, and capability enforcement are server-side.

| Method and route | Capability | Effect |
|---|---|---|
| `GET /api/ip/documents/foundation-contract` | `ip:read` | Returns canonical owner names, shared storage/queue owners, reserved processing target, naming pattern, and supported link targets. |
| `POST /api/ip/documents/naming-preview` | `ip:read` | Pure preview; writes no record and overwrites no file. |
| `GET /api/ip/document-taxonomy` | `ip:read` | Lists only the authenticated tenant's entries and aliases. |
| `POST /api/ip/document-taxonomy/seed` | `ip:taxonomy_admin` | Idempotently creates missing baseline categories and aliases with an audit event. |
| `PUT /api/ip/document-taxonomy/{key}` | `ip:taxonomy_admin` | Creates a custom entry or updates an existing entry with an expected-version check, normalized alias collision detection, and audit event. |

The baseline taxonomy is trademark filing, examination, opposition, evidence,
hearing, order, appeal, renewal, assignment, licence, correspondence, search,
watch, and invoice. Seeding is explicit rather than a mutating read operation.

## Naming preview behavior

The canonical pattern is:

```text
[ClientCode]_[AssetType]_[Mark]_[Jurisdiction]_[ApplicationNo]_[ProceedingType]_[ProceedingNo]_[DocumentType]_[YYYY-MM-DD]_[Version]
```

- unavailable components are omitted;
- Unicode is normalized with NFKC;
- filesystem-reserved characters and control characters are replaced;
- whitespace/separator runs are collapsed;
- Windows reserved device names are prefixed;
- spreadsheet-formula-leading components are prefixed before export;
- extensions accept only letters and numbers;
- names are capped at 240 characters; and
- case-insensitive conflicts receive deterministic `_2`, `_3`, ... suffixes.

The response returns requested and resolved names, every omitted component,
sanitized components, conflict status/suffix, warnings, and an export-safe
value. It is a preview only and therefore cannot silently overwrite storage.

## Security and legal-safety properties

- Tenant filters and composite foreign keys prevent cross-company taxonomy,
  actor, document, version, or target references.
- Taxonomy mutation requires `ip:taxonomy_admin`; ordinary IP readers cannot
  seed or edit it.
- Existing aliases cannot be rebound silently to another category.
- Optimistic concurrency rejects stale taxonomy writes.
- Original filename and content hash are version fields, not mutable document
  display metadata.
- `approved` and `filed` state cannot exist without a locking actor and time.
- Privilege and confidentiality are first-class document identity fields for
  IPLF-024B enforcement across AI, portal, export, and notification paths.
- The slice sends no email/SMS/WhatsApp, files nothing, pays no fee, accepts no
  legal classification, and performs no external provider action.

## Verification contract

Repository tests cover route authentication/authorization, explicit and
idempotent seeding, the 14-entry baseline, tenant isolation, normalized aliases,
alias collision, optimistic concurrency, audit actions, naming sanitization,
formula and reserved-name safety, deterministic conflict suffixing, schema
validation, migration upgrade/downgrade/re-upgrade, and database fail-closed
constraints. The dated Playwright spec
`tests/e2e/iplf-024a-document-foundation-2026-08-09.spec.ts` exercises the
entitled API journey end to end. The dated production RAM spec additionally
proves that the deployed routes exist and remain unavailable to the unentitled
legal tenant.

An arbitrary observation duration such as seven consecutive natural days is
not an IPLF-024A passing condition. Exact-commit CI, exact image/revision,
migration completion, current scheduler mapping/health, and dated deployed
acceptance remain mandatory release gates.
