# IP document foundation and ownership contract

**Slices:** `IPLF-024A` foundation and `IPLF-024B` controlled workflow

**Program status:** `PROGRAM INCOMPLETE`

**IPLF-024A release status:** `deployment_verified` at canonical release
`65f7c5cd2a669a0751b99280f136a4d18bbc9df2`; detailed evidence is retained in
`docs/ip-implementation/evidence/m2/IPLF-024A/release-2026-08-09.md`.
**IPLF-024B release status:** `deployment_verified` at canonical release
`64f6360b7bd9f4943be56c3d2c28662ce361bf5f`; detailed evidence is retained in
`docs/ip-implementation/evidence/m2/IPLF-024B/release-2026-08-10.md`.

## Purpose and bounded scope

IPLF-024A supplies the additive data and API foundation for governed IP
documents. It creates tenant-owned document identity, immutable binary-version
metadata, typed links to legal records, a configurable seeded taxonomy with
aliases, and a deterministic naming preview. IPLF-024B consumes those owners to
provide the upload, shared processing, duplicate reuse, classification, link,
version, approval/filing-state, policy, download, bulk-preview, and alias-import
workflow for `IP-DOC-01..12` and UJ-14.

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
| Malware/OCR/extraction queue | `LINK` | existing `document_processing_jobs` and shared document-processing adapters | `ip_document_version` is the active target type; IPLF-024B wires upload and worker execution to this existing queue. No second queue is allowed. |
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
| `POST /api/ip/document-taxonomy/import-aliases` | `ip:taxonomy_admin` | Dry-runs or imports a law-firm supplied alias list; normalized collisions fail closed. |
| `GET /api/ip/documents` and `GET /api/ip/documents/{id}` | `ip:read` plus target access | Lists or opens only documents whose linked IP records are visible to the actor. |
| `POST /api/ip/documents/upload` and `POST /api/ip/documents/{id}/new-version` | `ip:write` and `documents:upload` | Runs file policy, quota, malware scan, shared persistence/hash, deterministic name, and the canonical processing job. |
| `POST /api/ip/documents/{id}/links` | `ip:write` and `documents:manage` | Adds tenant-validated typed links without copying bytes and rejects stale document versions. |
| `POST /api/ip/documents/{id}/versions/{version}/transition` | `ip:write` and `documents:manage`; `ip:approve` for Approved/Filed | Locks and checks the current version/state, derives actor from the session, records time, and writes immutable audit evidence. |
| `POST /api/ip/documents/bulk-preview` then `/bulk-apply` | `ip:write` and `documents:manage` | Requires an exact current preview token, preserves extensions and links, and applies taxonomy/name changes atomically. |
| `GET /api/ip/documents/{id}/versions/{version}/download` | `ip:read` plus target access | Streams the immutable original name and bytes through the shared document store; missing objects return 404. |
| `GET /api/ip/documents/{id}/policy` and `POST .../authorize-action` | `ip:read` plus target access | Fails closed for privileged/confidential, incomplete-processing, and low-quality OCR use. |

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

## IPLF-024B controlled workflow

1. The user selects an accessible IP docket, original file, classification,
   naming particulars, date, confidentiality, and privilege label.
2. The UI requires a current controlled-name preview before enabling upload;
   changing any input invalidates that preview.
3. The API validates the upload, scans the temporary file before persistence,
   records SHA-256/size/type, detects duplicates from hash plus classification
   metadata, and either offers reuse or commits one document/version/link.
4. New bytes enqueue the existing `document_processing_jobs` owner using the
   `ip_document_version` target. Extraction status, text count, error, time, and
   a conservative OCR/extraction-quality score are written back to the version.
5. Low or incomplete extraction disables AI/search eligibility. Privileged or
   non-internal documents are denied for AI retrieval, portal sharing, export,
   and notification content by the policy boundary.
6. A duplicate offer can link the existing document to another accessible
   docket without a second stored object. Same filename with different bytes
   is not a duplicate; same bytes under different classification metadata is
   not silently collapsed.
7. Bulk classification/rename requires preview and revalidation under row
   locks. Conflicts receive deterministic suffixes and no binary or link is
   overwritten.
8. Review, approval, filing, service, acceptance, rejection, supersession, and
   replacement-version actions retain actor/state/version/audit evidence.
   Approved and Filed require `ip:approve`; every state command carries the
   expected current version and expected state.
9. A taxonomy administrator previews the supplied law-firm alias list before
   import. Tenant collisions are shown and block mutation.

No provider call, portal publication, notification delivery, filing, service,
fee, payment, or other external legal act is performed by this workflow.

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
- Upload/version actions require both `ip:write` and `documents:upload`;
  classification, linking, and state actions require both `ip:write` and
  `documents:manage`.
- Every document read validates every typed target through the existing IP
  access owner. Restricted-target denial is opaque and filtered from counts.
- Current-version and expected-state tokens reject stale writes; older versions
  cannot be advanced after supersession.
- Missing stored objects return a typed 404 rather than a server error.
- Privilege and confidentiality are first-class document identity fields for
  fail-closed enforcement across AI, portal, export, and notification paths.
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
proves unauthenticated access fails with `401`, the authenticated QA tenant
receives the exact ownership/naming contract, and its tenant-scoped taxonomy
envelope is valid. Capability-denial and cross-tenant behavior remain covered
by the API integration suite rather than by making a false assumption about
the dedicated QA tenant's capabilities.

IPLF-024B adds `apps/api/tests/test_ip_document_workflow.py`,
`apps/web/components/ip/IpDocumentWorkspace.test.tsx`, responsive IP page
coverage, and
`tests/e2e/iplf-024b-document-workflow-2026-08-09.spec.ts`; the stable,
idempotent deployed canary is in `tests/e2e/ram-2026-08-09-prod.spec.ts`. They cover the
normal UJ-14 workflow and all four named exceptions, including actual download
bytes, missing-object failure, current-preview invalidation, capability
composition, stale-version rejection, duplicate reuse, taxonomy-sensitive
hash matching, low OCR, privilege, tenant isolation, alias dry-run/import, and
mobile-visible action groups.

An arbitrary observation duration such as seven consecutive natural days is
not an IPLF-024A passing condition. Exact-commit CI, exact image/revision,
migration completion, current scheduler mapping/health, and dated deployed
acceptance remain mandatory release gates.

IPLF-024A's foundation gates passed on 9 August 2026. IPLF-024B's controlled
workflow gates passed on 10 August 2026 at canonical release `64f6360b...`:
API revision `caseops-api-00265-7zt` and web revision
`caseops-web-00245-6mg` serve 100% traffic; migration execution
`caseops-migrate-job-ftnfg` completed; all six scheduler bindings matched the
immutable API digest; and exact-release production workflow `31329680798`
passed the 59-case RAM batch plus the two-case Notice module. The IPLF-024B
locked/fail-closed document journey passed in 11.5 seconds. Genuine human
legal/UAT acceptance and later program slices remain open, so the program
status stays `PROGRAM INCOMPLETE`.
