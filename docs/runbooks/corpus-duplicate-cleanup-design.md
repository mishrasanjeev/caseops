# Corpus duplicate cleanup design

Read-only design for the next corpus reliability milestone after the ingest
watchdog and source-reference dedupe guard. This document converts the
2026-05-18 hc-delhi duplicate audit into an audited cleanup plan. It does not
authorize or implement production writes.

## Findings

- Canonical-key duplicates: `0`. The existing
  `uq_authority_document_canonical_key` constraint worked for the canonical
  identity that includes the size-sensitive key.
- Same `source_reference` duplicate groups: `846`.
- Exact-content duplicate groups among same-reference groups: `700`.
- Same-reference but different-content groups: `146`.
- Cross-court same-reference collisions: `0`.
- Title/date/court collision counts are not reliable duplicate signals. The
  largest collisions were polluted extracted titles such as court headers,
  signature lines, and OCR markers; those belong to title hygiene, not document
  deletion.

Interpretation: this is a narrow corpus identity problem, not a broad corpus
collapse. The safe cleanup unit is `(source, source_reference)` after exact
content classification, not title similarity.

## Boundaries

This milestone is read-only and design-only.

- Do not delete production data.
- Do not run duplicate cleanup.
- Do not add unique indexes, constraints, or migrations.
- Do not run corpus ingest, backfill, or embedding jobs.
- Do not repoint dependent rows.
- Do not expose database URLs, API keys, or other secrets in artifacts.

The SQL companion file is
[`scripts/corpus-duplicate-audit-readonly.sql`](../../scripts/corpus-duplicate-audit-readonly.sql).
It is intended for off-peak or read-replica execution and contains only
read-only result sets.

## Cleanup Phases

### Phase 0: Reconfirm scope

Run the read-only summary queries against the current production snapshot or a
fresh replica. Reconfirm the counts above and capture the timestamp, database
revision, and query result artifacts outside the repo.

Approval gate: operations owner confirms the duplicate population has not
materially changed since the 2026-05-18 audit.

### Phase 1: Build the dry-run candidate map

Generate a loser-to-keeper report for exact-content same-reference groups only.
The report must include:

- duplicate key: `source`, `source_reference`
- candidate ids
- text hash and text length
- title, court, decision date, case reference, neutral citation
- structured extraction version
- chunk, embedded chunk, and metadata chunk counts
- dependent-row counts by table and column
- deterministic keeper rank and reason fields

Approval gate: reviewer samples at least 25 exact-content groups plus every
group with non-zero dependent rows outside `authority_document_chunks`.

### Phase 2: Quarantine ambiguous groups

Same-reference/different-content groups are not auto-clean candidates. They can
mean upstream republished a corrected PDF, OCR output changed, or the same
filename was reused for genuinely different material. Produce a separate manual
review queue for the `146` groups with side-by-side metadata and text stats.

Approval gate: legal/content reviewer chooses a policy per ambiguous group:
keep both with disambiguated source identity, keep richer record and archive the
other in a future audited cleanup, or mark as unresolved.

### Phase 3: Future write plan, not this milestone

Only after Phases 0-2 are approved should a separate cleanup PR propose a
write-capable tool. That future tool should:

- run inside a single transaction per bounded batch;
- acquire an advisory lock so two cleanup runs cannot overlap;
- write a durable audit log of every loser-to-keeper decision;
- repoint FK-backed dependent rows before removing non-keeper documents;
- merge uniqueness-constrained rows where repointing could collide;
- stop if live counts differ from the approved dry-run artifact.

### Phase 4: Future prevention hardening, not this milestone

After cleanup, a separate schema PR can consider a partial uniqueness guarantee
for `source_reference`. Do not add it before ambiguous same-reference groups are
resolved. If filename reuse across prefixes is possible, the safer schema change
is to persist the full upstream object key first, then constrain that richer
source identity.

## Keeper-Selection Policy

The keeper policy is deterministic, but only for same-reference groups where
all documents in the group share the same non-null text hash.

Rank candidates in this order:

1. Highest `structured_version`, with non-null preferred.
2. Has metadata chunks.
3. Highest embedded chunk count.
4. Highest total chunk count.
5. Highest `extracted_char_count` or text length.
6. Best title hygiene score: non-header, non-signature, non-OCR-marker titles
   with useful length.
7. Latest `updated_at`, then latest `ingested_at`.
8. Lexicographically smallest `id` as the final tie-breaker.

Do not apply this policy to same-reference/different-content groups. Those
require manual classification first.

## Dependency/Repointing Checklist

Before any future cleanup can remove non-keeper documents, the dry-run must
count and plan each dependent surface.

FK-backed dependencies from the current model:

| Table | Column | Current FK behavior | Future cleanup handling |
| --- | --- | --- | --- |
| `authority_document_chunks` | `authority_document_id` | cascade | Usually let non-keeper chunks go after keeper validation; do not repoint chunks into a keeper with existing chunk indexes. |
| `authority_citations` | `source_authority_document_id` | cascade | Repoint outgoing citations to keeper, then merge on `(source_authority_document_id, normalized_reference)` if needed. |
| `authority_citations` | `cited_authority_document_id` | set null | Repoint incoming citations to keeper before removal. |
| `judge_decision_index` | `authority_document_id` | cascade | Repoint or merge on `(judge_id, authority_document_id)`. |
| `judge_authority_affinity` | `cited_authority_document_id` | cascade | Repoint or merge on `(judge_id, cited_authority_document_id)`. |
| `judge_authority_affinity` | `sample_judgment_id` | set null | Repoint sample to keeper when the sample points at a non-keeper. |
| `judge_statute_focus` | `sample_judgment_id` | set null | Repoint sample to keeper when the sample points at a non-keeper. |
| `authority_statute_references` | `authority_id` | cascade | Repoint or merge on `(authority_id, section_id)`. |
| `authority_annotations` | `authority_document_id` | cascade | Repoint per-tenant annotations; merge only when `(company_id, authority_document_id, kind, title)` collides. |
| `contract_legal_references` | `authority_id` | set null | Repoint contract references to keeper before removal. |

Semantic dependencies without hard FKs:

- `predictive_outcome_classifications.source_id` when
  `source_type = 'authority_document'`.
- `predictive_signal_evidence.source_id` when
  `source_type = 'authority_document'`.
- `predictive_outcome_aggregate_snapshots.evidence_source_ids_json` if it stores
  authority document ids in JSON.

The future cleanup tool must either repoint these semantic references or prove
the current production data does not use the authority-document source type.

## Read-Only Audit Queries

Use the companion SQL file for executable queries. It contains result sets for:

- hc-delhi duplicate summary;
- same-reference group classification;
- exact-content loser-to-keeper dry-run map;
- same-reference/different-content review queue;
- FK-backed dependency inventory from `pg_constraint`;
- known dependency counts for exact-content loser candidates;
- semantic dependency counts.

The SQL intentionally does not include production write statements.

## Required Approvals Before Future Cleanup

- Operations approval for the exact production snapshot and dry-run artifact.
- Legal/content approval for ambiguous same-reference/different-content groups.
- Engineering approval for dependency repointing behavior and collision merges.
- Database approval for transaction size, lock strategy, and rollback plan.
- Product approval for any visible changes to recommendations, bench analytics,
  predictive surfaces, annotations, or contract references.
