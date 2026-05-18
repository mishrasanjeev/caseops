-- Read-only corpus duplicate audit for hc-delhi.
--
-- This file is intentionally report-only. It contains no data-changing
-- statements, no index/constraint creation, and no cleanup execution.
-- Prefer a read replica or an off-peak production window.

\echo '1. hc-delhi duplicate summary'
WITH params AS (
    SELECT
        'ecourts-hc'::text AS target_source,
        '%delhi%'::text AS target_court_pattern
),
scoped_docs AS (
    SELECT
        ad.id,
        ad.source,
        ad.source_reference,
        ad.canonical_key
    FROM authority_documents ad
    CROSS JOIN params p
    WHERE ad.source = p.target_source
      AND ad.court_name ILIKE p.target_court_pattern
)
SELECT
    COUNT(*) AS document_count,
    COUNT(DISTINCT canonical_key) AS distinct_canonical_keys,
    COUNT(*) - COUNT(DISTINCT canonical_key) AS canonical_key_extra_rows,
    COUNT(*) FILTER (WHERE source_reference IS NOT NULL) AS with_source_reference,
    COUNT(DISTINCT source_reference) FILTER (
        WHERE source_reference IS NOT NULL
    ) AS distinct_source_references,
    COUNT(*) FILTER (WHERE source_reference IS NOT NULL)
      - COUNT(DISTINCT source_reference) FILTER (
            WHERE source_reference IS NOT NULL
        ) AS source_reference_extra_rows
FROM scoped_docs;

\echo '2. same-source_reference duplicate groups'
WITH params AS (
    SELECT
        'ecourts-hc'::text AS target_source,
        '%delhi%'::text AS target_court_pattern
),
same_ref_groups AS (
    SELECT
        ad.source,
        ad.source_reference,
        COUNT(*) AS document_count,
        COUNT(DISTINCT ad.canonical_key) AS canonical_key_count,
        MIN(ad.ingested_at) AS first_ingested_at,
        MAX(ad.ingested_at) AS last_ingested_at
    FROM authority_documents ad
    CROSS JOIN params p
    WHERE ad.source = p.target_source
      AND ad.court_name ILIKE p.target_court_pattern
      AND ad.source_reference IS NOT NULL
    GROUP BY ad.source, ad.source_reference
    HAVING COUNT(*) > 1
)
SELECT *
FROM same_ref_groups
ORDER BY document_count DESC, source_reference
LIMIT 200;

\echo '3. classify duplicate groups by exact text hash vs differing text'
WITH params AS (
    SELECT
        'ecourts-hc'::text AS target_source,
        '%delhi%'::text AS target_court_pattern
),
same_ref_groups AS (
    SELECT ad.source, ad.source_reference
    FROM authority_documents ad
    CROSS JOIN params p
    WHERE ad.source = p.target_source
      AND ad.court_name ILIKE p.target_court_pattern
      AND ad.source_reference IS NOT NULL
    GROUP BY ad.source, ad.source_reference
    HAVING COUNT(*) > 1
),
dup_docs AS (
    SELECT
        ad.source,
        ad.source_reference,
        ad.id,
        CASE
            WHEN ad.document_text IS NULL THEN NULL
            ELSE md5(ad.document_text)
        END AS text_hash
    FROM authority_documents ad
    JOIN same_ref_groups g
      ON g.source = ad.source
     AND g.source_reference = ad.source_reference
),
classified AS (
    SELECT
        source,
        source_reference,
        COUNT(*) AS document_count,
        COUNT(text_hash) AS docs_with_text,
        COUNT(DISTINCT text_hash) AS distinct_text_hashes
    FROM dup_docs
    GROUP BY source, source_reference
)
SELECT
    COUNT(*) AS duplicate_groups,
    SUM(document_count - 1) AS extra_documents,
    COUNT(*) FILTER (
        WHERE docs_with_text = document_count
          AND distinct_text_hashes = 1
    ) AS exact_content_groups,
    SUM(document_count - 1) FILTER (
        WHERE docs_with_text = document_count
          AND distinct_text_hashes = 1
    ) AS exact_content_extra_documents,
    COUNT(*) FILTER (
        WHERE docs_with_text <> document_count
           OR distinct_text_hashes <> 1
    ) AS requires_manual_review_groups,
    SUM(document_count - 1) FILTER (
        WHERE docs_with_text <> document_count
           OR distinct_text_hashes <> 1
    ) AS requires_manual_review_extra_documents
FROM classified;

\echo '4. exact-content loser-to-keeper dry-run map'
WITH params AS (
    SELECT
        'ecourts-hc'::text AS target_source,
        '%delhi%'::text AS target_court_pattern
),
same_ref_groups AS (
    SELECT ad.source, ad.source_reference
    FROM authority_documents ad
    CROSS JOIN params p
    WHERE ad.source = p.target_source
      AND ad.court_name ILIKE p.target_court_pattern
      AND ad.source_reference IS NOT NULL
    GROUP BY ad.source, ad.source_reference
    HAVING COUNT(*) > 1
),
chunk_counts AS (
    SELECT
        authority_document_id,
        COUNT(*) AS chunk_count,
        COUNT(*) FILTER (WHERE embedding_model IS NOT NULL) AS embedded_chunk_count,
        COUNT(*) FILTER (WHERE chunk_role = 'metadata') AS metadata_chunk_count
    FROM authority_document_chunks
    GROUP BY authority_document_id
),
dup_docs_base AS (
    SELECT
        ad.id,
        ad.source,
        ad.source_reference,
        ad.canonical_key,
        ad.court_name,
        ad.title,
        ad.case_reference,
        ad.neutral_citation,
        ad.decision_date,
        ad.structured_version,
        ad.extracted_char_count,
        length(COALESCE(ad.document_text, '')) AS text_length,
        CASE
            WHEN ad.document_text IS NULL THEN NULL
            ELSE md5(ad.document_text)
        END AS text_hash,
        ad.ingested_at,
        ad.updated_at,
        COALESCE(cc.chunk_count, 0) AS chunk_count,
        COALESCE(cc.embedded_chunk_count, 0) AS embedded_chunk_count,
        COALESCE(cc.metadata_chunk_count, 0) AS metadata_chunk_count,
        CASE
            WHEN ad.title ILIKE '%high court of delhi%' THEN 0
            WHEN ad.title ILIKE '%signature not verified%' THEN 0
            WHEN ad.title ILIKE '%reserved on%' THEN 0
            WHEN ad.title ILIKE '%(cid:%' THEN 0
            WHEN length(ad.title) < 12 THEN 0
            ELSE 1
        END AS title_quality_score
    FROM authority_documents ad
    JOIN same_ref_groups g
      ON g.source = ad.source
     AND g.source_reference = ad.source_reference
    LEFT JOIN chunk_counts cc
      ON cc.authority_document_id = ad.id
),
exact_ref_groups AS (
    SELECT source, source_reference
    FROM dup_docs_base
    GROUP BY source, source_reference
    HAVING COUNT(text_hash) = COUNT(*)
       AND COUNT(DISTINCT text_hash) = 1
),
ranked AS (
    SELECT
        d.*,
        FIRST_VALUE(d.id) OVER (
            PARTITION BY d.source, d.source_reference
            ORDER BY
                d.structured_version DESC NULLS LAST,
                d.metadata_chunk_count DESC,
                d.embedded_chunk_count DESC,
                d.chunk_count DESC,
                GREATEST(d.extracted_char_count, d.text_length) DESC,
                d.title_quality_score DESC,
                d.updated_at DESC,
                d.ingested_at DESC,
                d.id ASC
        ) AS keeper_id,
        ROW_NUMBER() OVER (
            PARTITION BY d.source, d.source_reference
            ORDER BY
                d.structured_version DESC NULLS LAST,
                d.metadata_chunk_count DESC,
                d.embedded_chunk_count DESC,
                d.chunk_count DESC,
                GREATEST(d.extracted_char_count, d.text_length) DESC,
                d.title_quality_score DESC,
                d.updated_at DESC,
                d.ingested_at DESC,
                d.id ASC
        ) AS keeper_rank
    FROM dup_docs_base d
    JOIN exact_ref_groups g
      ON g.source = d.source
     AND g.source_reference = d.source_reference
)
SELECT
    source,
    source_reference,
    text_hash,
    id AS candidate_id,
    keeper_id,
    keeper_rank,
    title,
    decision_date,
    case_reference,
    neutral_citation,
    structured_version,
    extracted_char_count,
    text_length,
    chunk_count,
    embedded_chunk_count,
    metadata_chunk_count,
    title_quality_score,
    ingested_at,
    updated_at
FROM ranked
ORDER BY source_reference, text_hash, keeper_rank
LIMIT 500;

\echo '5. same-reference/different-content manual review queue'
WITH params AS (
    SELECT
        'ecourts-hc'::text AS target_source,
        '%delhi%'::text AS target_court_pattern
),
same_ref_groups AS (
    SELECT ad.source, ad.source_reference
    FROM authority_documents ad
    CROSS JOIN params p
    WHERE ad.source = p.target_source
      AND ad.court_name ILIKE p.target_court_pattern
      AND ad.source_reference IS NOT NULL
    GROUP BY ad.source, ad.source_reference
    HAVING COUNT(*) > 1
),
dup_docs_base AS (
    SELECT
        ad.id,
        ad.source,
        ad.source_reference,
        ad.canonical_key,
        ad.court_name,
        ad.title,
        ad.case_reference,
        ad.neutral_citation,
        ad.decision_date,
        ad.structured_version,
        ad.extracted_char_count,
        length(COALESCE(ad.document_text, '')) AS text_length,
        CASE
            WHEN ad.document_text IS NULL THEN NULL
            ELSE md5(ad.document_text)
        END AS text_hash,
        ad.ingested_at
    FROM authority_documents ad
    JOIN same_ref_groups g
      ON g.source = ad.source
     AND g.source_reference = ad.source_reference
),
classified AS (
    SELECT source, source_reference
    FROM dup_docs_base
    GROUP BY source, source_reference
    HAVING COUNT(text_hash) <> COUNT(*)
        OR COUNT(DISTINCT text_hash) <> 1
)
SELECT d.*
FROM dup_docs_base d
JOIN classified c
  ON c.source = d.source
 AND c.source_reference = d.source_reference
ORDER BY d.source_reference, d.text_length DESC, d.ingested_at DESC
LIMIT 500;

\echo '6. live FK-backed dependency inventory for authority_documents'
SELECT
    con.conname AS constraint_name,
    con.conrelid::regclass::text AS referencing_table,
    att.attname AS referencing_column,
    CASE con.confdeltype
        WHEN 'a' THEN 'no action'
        WHEN 'r' THEN 'restrict'
        WHEN 'c' THEN 'cascade'
        WHEN 'n' THEN 'set null'
        WHEN 'd' THEN 'set default'
        ELSE con.confdeltype::text
    END AS on_delete
FROM pg_constraint con
JOIN pg_attribute att
  ON att.attrelid = con.conrelid
 AND att.attnum = ANY (con.conkey)
WHERE con.contype = 'f'
  AND con.confrelid = 'authority_documents'::regclass
ORDER BY referencing_table, referencing_column;

\echo '7. dependency counts for exact-content loser candidates'
WITH params AS (
    SELECT
        'ecourts-hc'::text AS target_source,
        '%delhi%'::text AS target_court_pattern
),
same_ref_groups AS (
    SELECT ad.source, ad.source_reference
    FROM authority_documents ad
    CROSS JOIN params p
    WHERE ad.source = p.target_source
      AND ad.court_name ILIKE p.target_court_pattern
      AND ad.source_reference IS NOT NULL
    GROUP BY ad.source, ad.source_reference
    HAVING COUNT(*) > 1
),
dup_docs_base AS (
    SELECT
        ad.id,
        ad.source,
        ad.source_reference,
        CASE
            WHEN ad.document_text IS NULL THEN NULL
            ELSE md5(ad.document_text)
        END AS text_hash,
        ad.structured_version,
        ad.extracted_char_count,
        length(COALESCE(ad.document_text, '')) AS text_length,
        ad.updated_at,
        ad.ingested_at
    FROM authority_documents ad
    JOIN same_ref_groups g
      ON g.source = ad.source
     AND g.source_reference = ad.source_reference
),
exact_ref_groups AS (
    SELECT source, source_reference
    FROM dup_docs_base
    GROUP BY source, source_reference
    HAVING COUNT(text_hash) = COUNT(*)
       AND COUNT(DISTINCT text_hash) = 1
),
ranked AS (
    SELECT
        d.*,
        FIRST_VALUE(d.id) OVER (
            PARTITION BY d.source, d.source_reference
            ORDER BY
                d.structured_version DESC NULLS LAST,
                GREATEST(d.extracted_char_count, d.text_length) DESC,
                d.updated_at DESC,
                d.ingested_at DESC,
                d.id ASC
        ) AS keeper_id,
        ROW_NUMBER() OVER (
            PARTITION BY d.source, d.source_reference
            ORDER BY
                d.structured_version DESC NULLS LAST,
                GREATEST(d.extracted_char_count, d.text_length) DESC,
                d.updated_at DESC,
                d.ingested_at DESC,
                d.id ASC
        ) AS keeper_rank
    FROM dup_docs_base d
    JOIN exact_ref_groups g
      ON g.source = d.source
     AND g.source_reference = d.source_reference
),
losers AS (
    SELECT id, keeper_id
    FROM ranked
    WHERE keeper_rank > 1
)
SELECT 'authority_document_chunks.authority_document_id' AS dependency, COUNT(*) AS row_count
FROM authority_document_chunks c JOIN losers l ON l.id = c.authority_document_id
UNION ALL
SELECT 'authority_citations.source_authority_document_id', COUNT(*)
FROM authority_citations c JOIN losers l ON l.id = c.source_authority_document_id
UNION ALL
SELECT 'authority_citations.cited_authority_document_id', COUNT(*)
FROM authority_citations c JOIN losers l ON l.id = c.cited_authority_document_id
UNION ALL
SELECT 'judge_decision_index.authority_document_id', COUNT(*)
FROM judge_decision_index j JOIN losers l ON l.id = j.authority_document_id
UNION ALL
SELECT 'judge_authority_affinity.cited_authority_document_id', COUNT(*)
FROM judge_authority_affinity j JOIN losers l ON l.id = j.cited_authority_document_id
UNION ALL
SELECT 'judge_authority_affinity.sample_judgment_id', COUNT(*)
FROM judge_authority_affinity j JOIN losers l ON l.id = j.sample_judgment_id
UNION ALL
SELECT 'judge_statute_focus.sample_judgment_id', COUNT(*)
FROM judge_statute_focus j JOIN losers l ON l.id = j.sample_judgment_id
UNION ALL
SELECT 'authority_statute_references.authority_id', COUNT(*)
FROM authority_statute_references s JOIN losers l ON l.id = s.authority_id
UNION ALL
SELECT 'authority_annotations.authority_document_id', COUNT(*)
FROM authority_annotations a JOIN losers l ON l.id = a.authority_document_id
UNION ALL
SELECT 'contract_legal_references.authority_id', COUNT(*)
FROM contract_legal_references c JOIN losers l ON l.id = c.authority_id
ORDER BY dependency;

\echo '8. semantic dependency counts for exact-content loser candidates'
WITH params AS (
    SELECT
        'ecourts-hc'::text AS target_source,
        '%delhi%'::text AS target_court_pattern
),
same_ref_groups AS (
    SELECT ad.source, ad.source_reference
    FROM authority_documents ad
    CROSS JOIN params p
    WHERE ad.source = p.target_source
      AND ad.court_name ILIKE p.target_court_pattern
      AND ad.source_reference IS NOT NULL
    GROUP BY ad.source, ad.source_reference
    HAVING COUNT(*) > 1
),
dup_docs_base AS (
    SELECT
        ad.id,
        ad.source,
        ad.source_reference,
        CASE
            WHEN ad.document_text IS NULL THEN NULL
            ELSE md5(ad.document_text)
        END AS text_hash,
        ad.structured_version,
        ad.extracted_char_count,
        length(COALESCE(ad.document_text, '')) AS text_length,
        ad.updated_at,
        ad.ingested_at
    FROM authority_documents ad
    JOIN same_ref_groups g
      ON g.source = ad.source
     AND g.source_reference = ad.source_reference
),
exact_ref_groups AS (
    SELECT source, source_reference
    FROM dup_docs_base
    GROUP BY source, source_reference
    HAVING COUNT(text_hash) = COUNT(*)
       AND COUNT(DISTINCT text_hash) = 1
),
ranked AS (
    SELECT
        d.*,
        ROW_NUMBER() OVER (
            PARTITION BY d.source, d.source_reference
            ORDER BY
                d.structured_version DESC NULLS LAST,
                GREATEST(d.extracted_char_count, d.text_length) DESC,
                d.updated_at DESC,
                d.ingested_at DESC,
                d.id ASC
        ) AS keeper_rank
    FROM dup_docs_base d
    JOIN exact_ref_groups g
      ON g.source = d.source
     AND g.source_reference = d.source_reference
),
losers AS (
    SELECT id
    FROM ranked
    WHERE keeper_rank > 1
)
SELECT 'predictive_outcome_classifications.source_id' AS dependency, COUNT(*) AS row_count
FROM predictive_outcome_classifications p
JOIN losers l ON l.id = p.source_id
WHERE p.source_type = 'authority_document'
UNION ALL
SELECT 'predictive_signal_evidence.source_id', COUNT(*)
FROM predictive_signal_evidence p
JOIN losers l ON l.id = p.source_id
WHERE p.source_type = 'authority_document'
UNION ALL
SELECT 'predictive_outcome_aggregate_snapshots.evidence_source_ids_json', COUNT(*)
FROM predictive_outcome_aggregate_snapshots p
JOIN losers l ON p.evidence_source_ids_json LIKE '%' || l.id || '%'
ORDER BY dependency;
