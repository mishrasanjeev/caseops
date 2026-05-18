# Corpus duplicate read-only audit - 2026-05-18

## Findings

The approved production-primary audit completed inside a PostgreSQL read-only
transaction. No data was modified.

The current hc-delhi scoped production state is much smaller than the earlier
pre-guard duplicate suspicion:

- Canonical-key duplicate rows: `0`.
- Same `source_reference` duplicate groups: `6`.
- Extra same-`source_reference` rows: `6`.
- Exact-content duplicate groups: `2`.
- Exact-content loser rows: `2`.
- Same-ref/different-content groups requiring manual review: `4`.
- Same-ref/different-content extra rows: `4`.

Only `authority_document_chunks` has FK-backed rows attached to exact-content
loser candidates in this audit. All other FK-backed and semantic dependency
counts were `0` for exact-content loser candidates.

## Audit Environment

- Environment label: `production-primary-readonly-transaction`
- Timestamp: `2026-05-18T15:37:53.041112Z`
- SQL file: `scripts/corpus-duplicate-audit-readonly.sql`
- SQL commit used: `7c0fcea7aa64eaac5009bcd74c12b117dd51ab58`
- SQL SHA-256: `bd7b0ac5f7bc1692781c58dd71f7b4b7315e2d8997db96e526f290355ce979c2`
- Statement count: `8`
- Statement timeout: `180s`
- Transaction read-only confirmation: `transaction_read_only = on`
- Transaction end behavior: explicit rollback/connection close

No database URL, hostname, password, token, credential, full OCR text, full
judgment text, or tenant/matter payload is recorded in this report.

## Duplicate Summary Counts

| Metric | Count |
| --- | ---: |
| hc-delhi scoped authority documents | 119701 |
| distinct canonical keys | 119701 |
| canonical-key extra rows | 0 |
| documents with `source_reference` | 119701 |
| distinct `source_reference` values | 119695 |
| same-`source_reference` extra rows | 6 |
| same-`source_reference` duplicate groups | 6 |

All six same-`source_reference` groups have two rows each and two distinct
canonical keys.

## Exact-Content Dry-Run Summary

| Metric | Count |
| --- | ---: |
| exact-content duplicate groups | 2 |
| exact-content candidate rows | 4 |
| exact-content keeper rows | 2 |
| exact-content loser rows | 2 |
| represented groups in keeper/loser map | 2 |

Bounded keeper/loser sample:

| Source reference | Keeper id | Loser count | Text hash prefix | Bounded title signal |
| --- | --- | ---: | --- | --- |
| `DLHC010128692024_1_2024-12-23.pdf` | `f791ca94-9198-4448-a16c-81ec27ed8fc7` | 1 | `7343caaca1dc` | `CONT.CAS(C) 647/2024` |
| `DLHC010253692023_1_2025-01-13.pdf` | `200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8` | 1 | `c36ce2055829` | `CRL.REV.P. 714/2023`; alternate title `Kapil Bhati v. Jyoti Choudhary & Anr.` |

No cleanup was run. The keeper ids above are dry-run audit outputs only.

## Manual-Review Queue Summary

| Metric | Count |
| --- | ---: |
| same-ref/different-content groups | 4 |
| rows in manual-review queue | 8 |
| extra rows requiring manual review | 4 |

Bounded ambiguous samples:

| Source reference | Rows | Distinct hashes | Text length range | Bounded title samples |
| --- | ---: | ---: | --- | --- |
| `DLHC010026412024_1_2025-01-13.pdf` | 2 | 2 | 6037-7153 | `Mr. Ishwar Sahai v. Shri A K Singh IAS & Ors.; Ishwar Sahai v. Govt of NCT of Delhi & Ors.` / `This is a digitally signed order.` |
| `DLHC010087382023_1_2025-01-13.pdf` | 2 | 2 | 4212-4221 | `Yassh Deep Builders LLP v. Sushil Kumar Singh` |
| `DLHC010146102023_1_2023-05-30.pdf` | 2 | 2 | 23865-23865 | `LPA 369/2023 & LPA 370/2023: EQUESTRIAN FEDERATION OF INDIA v. RAJASTHAN EQUESTRIAN ASSOCIATI...` / `Equestrian Federation of India v. Rajasthan Equestrian Association & Ors.` |
| `DLHC010146112023_1_2023-05-30.pdf` | 2 | 2 | 23865-23865 | `Equestrian Federation of India v. Rajasthan Equestrian Association & Ors.` / `EQUESTRIAN FEDERATION OF INDIA v. RAJASTHAN EQUESTRIAN ASSOCIATION & ORS.` |

These four groups remain quarantined for manual legal/content review. They are
not automatic cleanup candidates.

## FK-Backed Dependency Counts

Live FK inventory references `authority_documents` through ten columns:

| Dependency | On delete |
| --- | --- |
| `authority_annotations.authority_document_id` | cascade |
| `authority_citations.cited_authority_document_id` | set null |
| `authority_citations.source_authority_document_id` | cascade |
| `authority_document_chunks.authority_document_id` | cascade |
| `authority_statute_references.authority_id` | cascade |
| `contract_legal_references.authority_id` | set null |
| `judge_authority_affinity.cited_authority_document_id` | cascade |
| `judge_authority_affinity.sample_judgment_id` | set null |
| `judge_decision_index.authority_document_id` | cascade |
| `judge_statute_focus.sample_judgment_id` | set null |

Dependency counts for exact-content loser candidates:

| Dependency | Row count |
| --- | ---: |
| `authority_document_chunks.authority_document_id` | 140 |
| `authority_annotations.authority_document_id` | 0 |
| `authority_citations.cited_authority_document_id` | 0 |
| `authority_citations.source_authority_document_id` | 0 |
| `authority_statute_references.authority_id` | 0 |
| `contract_legal_references.authority_id` | 0 |
| `judge_authority_affinity.cited_authority_document_id` | 0 |
| `judge_authority_affinity.sample_judgment_id` | 0 |
| `judge_decision_index.authority_document_id` | 0 |
| `judge_statute_focus.sample_judgment_id` | 0 |

## Semantic / Non-FK Dependency Counts

| Dependency | Row count |
| --- | ---: |
| `predictive_outcome_aggregate_snapshots.evidence_source_ids_json` | 0 |
| `predictive_outcome_classifications.source_id` | 0 |
| `predictive_signal_evidence.source_id` | 0 |

## Risks

- The audit ran against the writable primary by explicit approval, but the
  transaction was read-only. Re-running should still prefer a replica/snapshot
  when available to reduce primary load.
- Same-ref/different-content groups may represent corrected PDFs, OCR drift, or
  genuine source ambiguity; they require manual review before any future write.
- Exact-content loser candidates still own chunk rows. Future cleanup must
  verify keeper chunk quality before allowing loser chunks to cascade.
- Future repointing must merge uniqueness-constrained rows if dependent data
  exists in later snapshots.
- No DB uniqueness/index hardening should be attempted until ambiguous groups
  are resolved and a cleanup transaction plan is approved.

## Required Approvals Before Cleanup

- Operations approval for the exact production snapshot and dry-run artifact.
- Legal/content approval for all four same-ref/different-content groups.
- Engineering approval for dependency repointing and merge behavior.
- Database approval for transaction sizing, lock strategy, rollback plan, and
  any future index/constraint plan.
- Product approval if any cleanup would alter user-visible recommendations,
  bench analytics, predictive surfaces, annotations, or contract references.

## No-Modification Statement

No production data was modified. The audit used read-only statements only,
confirmed `transaction_read_only = on`, and ended with rollback/connection
close. No cleanup, deletion, dependency repointing, migration, index creation,
ingest, backfill, or embedding job was run.
