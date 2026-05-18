# Corpus duplicate exact-content cleanup approval packet - 2026-05-18

## Findings

The read-only production audit identified two hc-delhi same-`source_reference`
groups where all rows in each group had the same text hash. The audit produced a
dry-run keeper signal for each group and found two loser rows in total.

This packet is an approval-planning artifact only. It performs no cleanup,
authorizes no cleanup, and does not include any production write path.

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

## Cleanup-Candidate Summary

| Metric | Count |
| --- | ---: |
| exact-content duplicate groups | 2 |
| exact-content candidate rows | 4 |
| dry-run keeper rows | 2 |
| dry-run loser rows | 2 |
| exact-content loser FK dependency rows in `authority_document_chunks` | 140 |
| all other checked FK-backed dependency rows | 0 |
| checked semantic/non-FK dependency rows | 0 |

## Exact-Content Group Register

| Source reference | Source | Dry-run keeper id | Loser rows | Text hash prefix | Bounded title signal | Dependency signal |
| --- | --- | --- | ---: | --- | --- | --- |
| `DLHC010128692024_1_2024-12-23.pdf` | `ecourts-hc` | `f791ca94-9198-4448-a16c-81ec27ed8fc7` | 1 | `7343caaca1dc` | `CONT.CAS(C) 647/2024` | Included in aggregate 140 loser chunk rows |
| `DLHC010253692023_1_2025-01-13.pdf` | `ecourts-hc` | `200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8` | 1 | `c36ce2055829` | `CRL.REV.P. 714/2023`; alternate title `Kapil Bhati v. Jyoti Choudhary & Anr.` | Included in aggregate 140 loser chunk rows |

The source audit report records keeper ids and loser counts, but it does not
persist the loser row ids or per-group dependency split. Those values must be
refreshed by a future approved read-only dry-run before any write-capable
cleanup PR is proposed.

## Keeper-Selection Policy From Audit Query

The dry-run keeper map applies only to exact-content duplicate groups. Candidate
rows are ranked within each `(source, source_reference)` group by:

- highest `structured_version`;
- highest metadata chunk count;
- highest embedded chunk count;
- highest chunk count;
- highest `GREATEST(extracted_char_count, text_length)`;
- highest title quality score;
- latest `updated_at`;
- latest `ingested_at`;
- lowest row id as the final deterministic tiebreaker.

This policy is not sufficient by itself to authorize deletion. It must be
revalidated against a fresh snapshot and reviewed with dependency, rollback, and
product-impact checks.

## Allowed Review Metadata Fields

Future approval packets may include only bounded metadata:

- `authority_document.id`;
- `source` and `source_reference`;
- content hash or text hash;
- character counts;
- chunk counts, metadata chunk counts, and embedded chunk counts;
- structured metadata presence/version;
- title hygiene flags and bounded titles;
- `ingested_at` and `updated_at` timestamps;
- FK-backed and semantic/non-FK dependency counts.

Full `document_text`, OCR text, source payloads, database URLs, credentials,
tenant/matter data, and large source excerpts are excluded.

## Required Future Dry-Run Checks Before Any Write

Before any write-capable cleanup PR, rerun a read-only dry-run against the exact
approved production snapshot or replica and confirm:

- the two exact-content groups still have identical text hashes within each
  group;
- the dry-run keeper ids are unchanged or any change is explained and approved;
- loser row ids are explicitly listed in the secure dry-run artifact;
- loser chunk counts, metadata chunk counts, and embedded chunk counts are
  recorded per loser;
- `authority_document_chunks.authority_document_id` dependency count is current;
- all other FK-backed dependencies remain zero or have an approved remapping
  plan;
- semantic/non-FK dependencies remain zero or have an approved remapping plan;
- manual-review groups remain excluded from exact-content cleanup;
- no uniqueness/index hardening is bundled into the cleanup PR.

## Approval Gate

Cleanup planning for exact-content groups requires approvals from:

- legal/content, confirming exact-content candidates are safe to treat as
  duplicates without exposing full text in repository artifacts;
- database, approving transaction sizing, locks, rollback mechanics, and audit
  capture;
- engineering, approving keeper/loser mapping and dependency behavior;
- product, approving any possible user-visible corpus or analytics effect;
- operations, approving the production window and execution operator.

This packet is not an approval record. It is the checklist input for future
approval.
