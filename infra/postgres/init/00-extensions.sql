-- CaseOps Postgres bootstrap — runs once per fresh data volume.
-- The pgvector extension is required for authority_document_chunks.embedding_vector.
CREATE EXTENSION IF NOT EXISTS vector;
