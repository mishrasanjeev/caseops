# Corpus duplicate metadata extract - 2026-05-18

## Findings

The approved metadata extract completed inside a PostgreSQL read-only
transaction. `transaction_read_only` was confirmed as `on`, the session used a
`180s` statement timeout, and the transaction ended with rollback. No data was
modified.

The extract re-identified only the six duplicate groups from the prior
read-only audit:

- exact-content groups: `2`
- exact-content rows: `4`
- current keeper candidates: `2`
- current loser candidates: `2`
- quarantined same-ref/different-content groups: `4`
- quarantined rows: `8`

The current exact-content loser candidates still have `140`
`authority_document_chunks` rows. Every other checked FK-backed and semantic /
non-FK dependency count is `0`.

Cleanup remains unapproved. No deletion, dependency repointing, index creation,
migration, ingest, backfill, or embedding job was run.

## Extract Environment

- Environment label: `production-primary-readonly-transaction`
- Extract timestamp: `2026-05-18T16:47:49.328883Z`
- Transaction read-only confirmation: `transaction_read_only = on`
- Statement timeout: `180s`
- Transaction end behavior: rollback/connection close
- Source corpus scope: `ecourts-hc`
- Target source references: `6`
- Rows extracted: `12`

No database URL, hostname, password, token, credential, full OCR text, full
judgment text, full `document_text`, source payload, or tenant/matter payload is
recorded in this report.

## Source References

- Read-only audit report:
  `docs/runbooks/corpus-duplicate-readonly-audit-2026-05-18.md`
- Manual-review packet:
  `docs/runbooks/corpus-duplicate-manual-review-packet-2026-05-18.md`
- Exact-content approval packet:
  `docs/runbooks/corpus-duplicate-exact-content-cleanup-approval-packet-2026-05-18.md`
- Read-only query inventory:
  `scripts/corpus-duplicate-audit-readonly.sql`

## Group Summary

| Group type | Source reference | Rows | Distinct text hashes | Text length range | Authority document ids |
| --- | --- | ---: | ---: | --- | --- |
| exact-content | `DLHC010128692024_1_2024-12-23.pdf` | 2 | 1 | `301860-301860` | `8c8eafd3-b75e-4b24-993a-e68a483485bc`; `f791ca94-9198-4448-a16c-81ec27ed8fc7` |
| exact-content | `DLHC010253692023_1_2025-01-13.pdf` | 2 | 1 | `2272-2272` | `200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8`; `5b79de0a-5a2e-4354-8347-f5ecd94af211` |
| quarantined same-ref/different-content | `DLHC010026412024_1_2025-01-13.pdf` | 2 | 2 | `6037-7153` | `2ef2d85e-306c-48e0-9582-ce269127e2c5`; `ad5e99fd-d7e0-4663-abac-2ec02199fadd` |
| quarantined same-ref/different-content | `DLHC010087382023_1_2025-01-13.pdf` | 2 | 2 | `4212-4221` | `18687e36-79f0-4134-9f62-4828a30f0eb1`; `763bf1be-6622-4b0f-892a-26ab9c458f5e` |
| quarantined same-ref/different-content | `DLHC010146102023_1_2023-05-30.pdf` | 2 | 2 | `23865-23865` | `6497a7ce-50e0-4484-8157-59108708cca8`; `82f1ed37-f120-41cc-acb0-8f628b063e19` |
| quarantined same-ref/different-content | `DLHC010146112023_1_2023-05-30.pdf` | 2 | 2 | `23865-23865` | `463fc76b-5583-424a-a13b-64978d362553`; `c22e0558-8fb2-42d7-9d4f-8f8a1e158463` |

## Exact-Content Metadata

Rows below are current dry-run review roles only. They do not authorize cleanup.

| Source reference | Review role | Authority document id | Text hash | Characters | Chunks / embedded / metadata | Structured metadata | Decision date | Updated at | Bounded title |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| `DLHC010128692024_1_2024-12-23.pdf` | keeper candidate | `f791ca94-9198-4448-a16c-81ec27ed8fc7` | `7343caaca1dca196a527c67174b89520` | 301860 | `138 / 138 / 0` | absent; version null; fields `0` | `2022-06-08` | `2026-05-02 06:57:26.724955+00` | `CONT.CAS(C) 647/2024` |
| `DLHC010128692024_1_2024-12-23.pdf` | loser candidate | `8c8eafd3-b75e-4b24-993a-e68a483485bc` | `7343caaca1dca196a527c67174b89520` | 301860 | `138 / 138 / 0` | absent; version null; fields `0` | `2022-06-08` | `2026-04-29 10:53:22.184788+00` | `CONT.CAS(C) 647/2024` |
| `DLHC010253692023_1_2025-01-13.pdf` | keeper candidate | `200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8` | `c36ce20558296cc83b64171f0a55ec28` | 2272 | `2 / 2 / 1` | present; version `1`; fields `6` | `2025-01-24` | `2026-05-04 06:31:55.709235+00` | `CRL.REV.P. 714/2023` |
| `DLHC010253692023_1_2025-01-13.pdf` | loser candidate | `5b79de0a-5a2e-4354-8347-f5ecd94af211` | `c36ce20558296cc83b64171f0a55ec28` | 2272 | `2 / 2 / 1` | present; version `1`; fields `6` | `2025-01-24` | `2026-05-04 06:30:21.083026+00` | `Kapil Bhati v. Jyoti Choudhary & Anr.` |

The current keeper candidates match the prior audit's keeper ids:

- `DLHC010128692024_1_2024-12-23.pdf`:
  `f791ca94-9198-4448-a16c-81ec27ed8fc7`
- `DLHC010253692023_1_2025-01-13.pdf`:
  `200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8`

## Quarantined Group Metadata

These rows remain quarantined for legal/content review. None is an automatic
cleanup candidate.

| Source reference | Authority document id | Text hash | Characters | Chunks / embedded / metadata | Structured metadata | Decision date | Updated at | Bounded title |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| `DLHC010026412024_1_2025-01-13.pdf` | `ad5e99fd-d7e0-4663-abac-2ec02199fadd` | `59110fa2e9412b9711563e19e34acceb` | 7153 | `4 / 4 / 2` | present; version `1`; fields `6` | `2025-01-24` | `2026-05-04 06:30:57.557836+00` | `Mr. Ishwar Sahai v. Shri A K Singh IAS & Ors.; Ishwar Sahai v. Govt of NCT of Delhi & Ors.` |
| `DLHC010026412024_1_2025-01-13.pdf` | `2ef2d85e-306c-48e0-9582-ce269127e2c5` | `9cb8a9c8f103a80909042f6470d30ddc` | 6037 | `3 / 3 / 0` | present; version `1`; fields `2` | `2025-07-01` | `2026-04-23 06:17:15.156334+00` | `This is a digitally signed order.` |
| `DLHC010087382023_1_2025-01-13.pdf` | `18687e36-79f0-4134-9f62-4828a30f0eb1` | `14edfe29e1c46c3ffb5a4a1ba4b46b8a` | 4221 | `2 / 2 / 1` | present; version `1`; fields `6` | `2023-03-15` | `2026-05-04 07:01:54.769105+00` | `Yassh Deep Builders LLP v. Sushil Kumar Singh` |
| `DLHC010087382023_1_2025-01-13.pdf` | `763bf1be-6622-4b0f-892a-26ab9c458f5e` | `992c2f67166c2423f7048c922ea2f6f3` | 4212 | `2 / 2 / 1` | present; version `1`; fields `6` | `2023-03-15` | `2026-05-04 07:01:58.942987+00` | `Yassh Deep Builders LLP v. Sushil Kumar Singh` |
| `DLHC010146102023_1_2023-05-30.pdf` | `6497a7ce-50e0-4484-8157-59108708cca8` | `29d4f7df49c3faed1cee9749bd6f1367` | 23865 | `11 / 11 / 1` | present; version `1`; fields `6` | null | `2026-05-09 18:03:18.550407+00` | `Equestrian Federation of India v. Rajasthan Equestrian Association & Ors.` |
| `DLHC010146102023_1_2023-05-30.pdf` | `82f1ed37-f120-41cc-acb0-8f628b063e19` | `8e9c3861fa557e355e59fa250313eeb0` | 23865 | `11 / 11 / 1` | present; version `1`; fields `6` | null | `2026-05-09 17:36:46.886943+00` | `LPA 369/2023 & LPA 370/2023: EQUESTRIAN FEDERATION OF INDIA v. RAJASTHAN EQUESTRIAN ASSOCIATION & ORS.` |
| `DLHC010146112023_1_2023-05-30.pdf` | `463fc76b-5583-424a-a13b-64978d362553` | `8e9c3861fa557e355e59fa250313eeb0` | 23865 | `11 / 11 / 1` | present; version `1`; fields `6` | null | `2026-05-09 18:02:15.111766+00` | `Equestrian Federation of India v. Rajasthan Equestrian Association & Ors.` |
| `DLHC010146112023_1_2023-05-30.pdf` | `c22e0558-8fb2-42d7-9d4f-8f8a1e158463` | `29d4f7df49c3faed1cee9749bd6f1367` | 23865 | `11 / 11 / 1` | present; version `1`; fields `6` | null | `2026-05-09 17:36:28.685446+00` | `EQUESTRIAN FEDERATION OF INDIA v. RAJASTHAN EQUESTRIAN ASSOCIATION & ORS.` |

## Dependency Summary

Only `authority_document_chunks.authority_document_id` has non-zero counts for
the extracted rows:

| Review role | Chunk dependency rows |
| --- | ---: |
| exact-content keeper candidates | 140 |
| exact-content loser candidates | 140 |
| quarantined manual-review rows | 55 |

Non-zero chunk dependency counts by row:

| Source reference | Authority document id | Review role | Chunk dependency rows |
| --- | --- | --- | ---: |
| `DLHC010128692024_1_2024-12-23.pdf` | `f791ca94-9198-4448-a16c-81ec27ed8fc7` | keeper candidate | 138 |
| `DLHC010128692024_1_2024-12-23.pdf` | `8c8eafd3-b75e-4b24-993a-e68a483485bc` | loser candidate | 138 |
| `DLHC010253692023_1_2025-01-13.pdf` | `200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8` | keeper candidate | 2 |
| `DLHC010253692023_1_2025-01-13.pdf` | `5b79de0a-5a2e-4354-8347-f5ecd94af211` | loser candidate | 2 |
| `DLHC010026412024_1_2025-01-13.pdf` | `ad5e99fd-d7e0-4663-abac-2ec02199fadd` | manual review | 4 |
| `DLHC010026412024_1_2025-01-13.pdf` | `2ef2d85e-306c-48e0-9582-ce269127e2c5` | manual review | 3 |
| `DLHC010087382023_1_2025-01-13.pdf` | `18687e36-79f0-4134-9f62-4828a30f0eb1` | manual review | 2 |
| `DLHC010087382023_1_2025-01-13.pdf` | `763bf1be-6622-4b0f-892a-26ab9c458f5e` | manual review | 2 |
| `DLHC010146102023_1_2023-05-30.pdf` | `6497a7ce-50e0-4484-8157-59108708cca8` | manual review | 11 |
| `DLHC010146102023_1_2023-05-30.pdf` | `82f1ed37-f120-41cc-acb0-8f628b063e19` | manual review | 11 |
| `DLHC010146112023_1_2023-05-30.pdf` | `463fc76b-5583-424a-a13b-64978d362553` | manual review | 11 |
| `DLHC010146112023_1_2023-05-30.pdf` | `c22e0558-8fb2-42d7-9d4f-8f8a1e158463` | manual review | 11 |

All other checked dependencies were `0`:

- `authority_annotations.authority_document_id`
- `authority_citations.cited_authority_document_id`
- `authority_citations.source_authority_document_id`
- `authority_statute_references.authority_id`
- `contract_legal_references.authority_id`
- `judge_authority_affinity.cited_authority_document_id`
- `judge_authority_affinity.sample_judgment_id`
- `judge_decision_index.authority_document_id`
- `judge_statute_focus.sample_judgment_id`
- `predictive_outcome_aggregate_snapshots.evidence_source_ids_json`
- `predictive_outcome_classifications.source_id`
- `predictive_signal_evidence.source_id`

## Safety Boundary

This report includes only bounded metadata: ids, source references, text hashes,
character counts, chunk counts, structured metadata presence/version, title
hygiene flags, bounded titles, timestamps, and dependency counts.

This report excludes full `document_text`, OCR text, source payloads, database
URLs, credentials, tenant/matter data, and large source excerpts.

## Remaining Approvals Required

Cleanup remains unapproved until all of the following approvals are recorded
for a separate future cleanup PR:

- legal/content approval for all four quarantined same-ref/different-content
  groups;
- database approval for transaction sizing, locks, timeout settings, rollback,
  and audit capture;
- engineering approval for the final keeper/loser map and dependency behavior;
- product approval for any user-visible corpus, recommendation, analytics,
  prediction, citation, annotation, or contract-reference impact;
- operations approval for the environment, execution window, operator, and
  rollback owner.

No future cleanup should proceed unless a fresh dry-run immediately before the
write-capable PR confirms the same target rows, hashes, keeper roles,
dependencies, rollback path, and audit plan.
