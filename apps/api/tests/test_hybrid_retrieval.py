from __future__ import annotations

from caseops_api.services.embeddings import MockProvider
from caseops_api.services.retrieval import RetrievalCandidate, rank_candidates


def _embed(text: str) -> list[float]:
    return MockProvider(dimensions=256).embed([text]).vectors[0]


def test_hybrid_ranks_vector_positive_above_vector_negative() -> None:
    """Two candidates with the same keyword-overlap: the one whose
    embedding is closer to the query should rank higher."""
    query = "patent illegality Section 34 arbitration award public policy"

    # Both candidates mention the query terms ("Section 34" and "arbitration")
    # so lexical score is similar. Their embeddings diverge.
    positive_text = (
        "Section 34 arbitration award. This judgment on patent illegality "
        "under Section 34 holds that awards opposed to Indian public policy "
        "may be set aside. The court reviewed precedent."
    )
    negative_text = (
        "Section 34 arbitration. Tax treatment of non-resident shipping "
        "companies. The ruling addresses commercial shipping matters and "
        "customs duty levied under the Tax Act."
    )

    positive = RetrievalCandidate(
        attachment_id="pos",
        attachment_name="positive",
        content=positive_text,
        embedding=_embed(positive_text),
    )
    negative = RetrievalCandidate(
        attachment_id="neg",
        attachment_name="negative",
        content=negative_text,
        embedding=_embed(negative_text),
    )
    query_vector = _embed(query)

    ranked = rank_candidates(
        query=query,
        candidates=[positive, negative],
        limit=5,
        query_vector=query_vector,
    )
    assert len(ranked) == 2
    assert ranked[0].attachment_id == "pos"
    assert ranked[0].score >= ranked[1].score


def test_hybrid_falls_back_to_lexical_without_vectors() -> None:
    candidates = [
        RetrievalCandidate(
            attachment_id="only-text",
            attachment_name="only",
            content="Section 34 arbitration patent illegality public policy.",
        ),
    ]
    ranked = rank_candidates(query="Section 34 arbitration", candidates=candidates, limit=5)
    assert ranked
    assert ranked[0].attachment_id == "only-text"


def test_hybrid_handles_missing_embedding_on_some_candidates() -> None:
    """When some candidates have embeddings and some don't, all should
    still appear, scored with whichever signals are available."""
    query = "patent illegality"
    query_vector = _embed(query)
    ranked = rank_candidates(
        query=query,
        candidates=[
            RetrievalCandidate(
                attachment_id="with-vec",
                attachment_name="with-vec",
                content="Patent illegality is a ground under Section 34.",
                embedding=_embed("Patent illegality ground Section 34"),
            ),
            RetrievalCandidate(
                attachment_id="no-vec",
                attachment_name="no-vec",
                content="Patent illegality text only, without any embedding attached.",
                embedding=None,
            ),
        ],
        limit=5,
        query_vector=query_vector,
    )
    ids = {r.attachment_id for r in ranked}
    assert ids == {"with-vec", "no-vec"}
