"""Matter-attachment embedding wiring (§4.2).

Covers two shapes:

- The ORM column is present on ``matter_attachment_chunks`` after the
  20260418_0004 migration (required for the retrieval union).
- ``embed_matter_attachment_chunks`` populates the columns when the
  configured embedding provider is the mock — the deterministic path
  we use in tests — so the post-ingest job produces ready-to-query
  rows without talking to any network.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import inspect, select

from caseops_api.db.models import (
    MatterAttachment,
    MatterAttachmentChunk,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.document_processing import (
    embed_matter_attachment_chunks,
)


def _column_names(session, table: str) -> set[str]:
    insp = inspect(session.bind)
    return {col["name"] for col in insp.get_columns(table)}


@pytest.mark.usefixtures("client")
def test_migration_adds_embedding_columns_to_matter_attachment_chunks() -> None:
    Session = get_session_factory()
    with Session() as session:
        cols = _column_names(session, "matter_attachment_chunks")
    # The four JSON-shaped columns the embedding pipeline writes.
    required = {
        "embedding_model",
        "embedding_dimensions",
        "embedding_json",
        "embedded_at",
    }
    missing = required - cols
    assert not missing, f"Missing embedding columns: {missing}"


@pytest.mark.usefixtures("client")
def test_embed_matter_attachment_chunks_populates_json_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the deterministic mock embedding provider regardless of .env.
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "mock")

    Session = get_session_factory()
    with Session() as session:
        # Build a minimal matter attachment manually so we can exercise
        # the embedding path without going through the HTTP upload +
        # worker queue dance.
        from caseops_api.db.models import (
            Company,
            CompanyMembership,
            Matter,
            User,
        )
        company = Company(
            name="EmbedCo",
            slug="embedco",
            tenant_key="embedco",
            company_type="law_firm",
        )
        session.add(company)
        session.flush()
        user = User(email="ec@example.com", full_name="EC", password_hash="x")
        session.add(user)
        session.flush()
        membership = CompanyMembership(
            company_id=company.id, user_id=user.id, role="owner", is_active=True
        )
        session.add(membership)
        session.flush()
        matter = Matter(
            company_id=company.id,
            matter_code="EMB-001",
            title="Embedding smoke test",
            practice_area="civil",
            forum_level="high_court",
            status="open",
        )
        session.add(matter)
        session.flush()
        attachment = MatterAttachment(
            matter_id=matter.id,
            uploaded_by_membership_id=membership.id,
            original_filename="pleading.txt",
            storage_key="not-used-for-this-test",
            content_type="text/plain",
            size_bytes=100,
            sha256_hex="0" * 64,
        )
        session.add(attachment)
        session.flush()
        session.add_all(
            [
                MatterAttachmentChunk(
                    attachment_id=attachment.id,
                    chunk_index=0,
                    content="The petitioner seeks bail under BNSS s.483.",
                    token_count=8,
                ),
                MatterAttachmentChunk(
                    attachment_id=attachment.id,
                    chunk_index=1,
                    content="The Court considered the triple test factors.",
                    token_count=7,
                ),
            ]
        )
        session.flush()

        # Reload with relationship populated.
        attachment = session.scalar(
            select(MatterAttachment).where(MatterAttachment.id == attachment.id)
        )
        count = embed_matter_attachment_chunks(session, attachment)
        session.commit()

    assert count == 2
    with Session() as session:
        rows = list(
            session.scalars(
                select(MatterAttachmentChunk).where(
                    MatterAttachmentChunk.attachment_id == attachment.id
                )
            )
        )
        assert len(rows) == 2
        for row in rows:
            assert row.embedding_model is not None
            assert row.embedding_dimensions == 1024
            assert row.embedded_at is not None
            vec = json.loads(row.embedding_json or "[]")
            assert len(vec) == 1024
            # Mock provider emits normalised vectors, so the L2 norm is 1.
            norm = sum(v * v for v in vec) ** 0.5
            assert 0.95 < norm < 1.05
