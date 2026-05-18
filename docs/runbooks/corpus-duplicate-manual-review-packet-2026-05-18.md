# Corpus duplicate manual-review packet - 2026-05-18

## Findings

This packet covers the four hc-delhi same-`source_reference` /
different-content duplicate groups identified by the read-only production audit.
These groups are quarantined for manual legal/content review and are not
automatic cleanup candidates.

This artifact performs no cleanup and authorizes no cleanup. It contains only
bounded metadata copied from the merged audit report and review instructions for
a future approved read-only metadata packet.

## Source Audit Reference

- Source audit report:
  `docs/runbooks/corpus-duplicate-readonly-audit-2026-05-18.md`
- Source query inventory:
  `scripts/corpus-duplicate-audit-readonly.sql`
- Audit environment: `production-primary-readonly-transaction`
- Audit timestamp: `2026-05-18T15:37:53.041112Z`
- SQL commit used by the successful audit:
  `7c0fcea7aa64eaac5009bcd74c12b117dd51ab58`
- Transaction safety recorded by the audit: `transaction_read_only = on`,
  rollback/connection close, no data modified

## Review Boundary

This packet may be used to plan manual review only. It does not approve or
execute production writes, dependency remapping, index creation, migrations,
ingest, backfill, embedding work, or source reprocessing.

Full `document_text`, OCR text, source payloads, database URLs, credentials,
tenant/matter data, and large source excerpts are excluded from this artifact.

## Manual-Review Queue Summary

| Metric | Count |
| --- | ---: |
| same-ref/different-content groups | 4 |
| rows in manual-review queue | 8 |
| extra rows requiring manual review | 4 |

## Allowed Review Metadata Fields

The following bounded fields are allowed for future secure review packets:

- `authority_document.id`
- `source`
- `source_reference`
- content hash or text hash
- character counts
- chunk counts
- structured metadata presence
- embedded chunk counts
- title hygiene flags
- timestamps

The merged audit report did not persist all per-row values for these fields.
Missing per-row values must be populated only by a future approved read-only
metadata extract, preferably from a replica or fresh snapshot.

## Ambiguous Group Register

| Source reference | Source | Rows | Distinct hashes | Character-count signal | Bounded title signal | Title hygiene flag | Per-row ids / hash values / chunk fields |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| `DLHC010026412024_1_2025-01-13.pdf` | `ecourts-hc` | 2 | 2 | Text length range `6037-7153` | `Mr. Ishwar Sahai v. Shri A K Singh IAS & Ors.; Ishwar Sahai v. Govt of NCT of Delhi & Ors.` / `This is a digitally signed order.` | Mixed substantive/order-title signal | Not recorded in source report; require approved read-only metadata extract |
| `DLHC010087382023_1_2025-01-13.pdf` | `ecourts-hc` | 2 | 2 | Text length range `4212-4221` | `Yassh Deep Builders LLP v. Sushil Kumar Singh` | Similar title, differing text length/hash | Not recorded in source report; require approved read-only metadata extract |
| `DLHC010146102023_1_2023-05-30.pdf` | `ecourts-hc` | 2 | 2 | Text length range `23865-23865` | `LPA 369/2023 & LPA 370/2023: EQUESTRIAN FEDERATION OF INDIA v. RAJASTHAN EQUESTRIAN ASSOCIATI...` / `Equestrian Federation of India v. Rajasthan Equestrian Association & Ors.` | Truncated/uppercase versus normalized title | Not recorded in source report; require approved read-only metadata extract |
| `DLHC010146112023_1_2023-05-30.pdf` | `ecourts-hc` | 2 | 2 | Text length range `23865-23865` | `Equestrian Federation of India v. Rajasthan Equestrian Association & Ors.` / `EQUESTRIAN FEDERATION OF INDIA v. RAJASTHAN EQUESTRIAN ASSOCIATION & ORS.` | Case/format normalization difference | Not recorded in source report; require approved read-only metadata extract |

## Legal / Content Review Questions

For each ambiguous group, legal/content review must decide whether the two rows
represent:

- the same judgment with harmless extraction or title drift;
- a corrected, superseded, or materially different court source file;
- two related but distinct orders that should both remain indexed;
- a source ambiguity that requires court/source revalidation before any action.

No row should be treated as a cleanup loser until legal/content review records a
group-level decision and the future dry-run validates the exact current row ids,
hashes, dependencies, chunks, and timestamps.

## Required Future Read-Only Metadata Extract

Before any approval packet can move toward a write-capable cleanup PR, produce a
fresh read-only extract for these four groups containing only the allowed fields:

- row ids and source identity fields;
- full text hashes, not full text;
- extracted character counts and text lengths;
- chunk counts, metadata chunk counts, and embedded chunk counts;
- structured metadata presence/version;
- bounded title and title hygiene flags;
- `ingested_at` and `updated_at` timestamps;
- FK-backed dependency counts and semantic/non-FK dependency counts.

The extract must explicitly confirm that full text, OCR text, source payloads,
secrets, and DB connection details were not captured.

## Approval Gate

These groups require legal/content approval before engineering, database,
product, or operations may consider cleanup planning. If legal/content decides
any group should keep both rows, that group must remain excluded from cleanup
and any future uniqueness/index hardening must account for the exception or
resolve the source ambiguity first.
