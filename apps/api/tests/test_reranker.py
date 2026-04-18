"""Reranker provider tests (§4.2)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from caseops_api.services.llm import LLMCompletion, LLMProvider
from caseops_api.services.reranker import (
    LLMReranker,
    MockReranker,
    RerankerCandidate,
    _parse_order,
    build_reranker,
    candidates_from_iterable,
)


def _cand(i: int, title: str, text: str) -> RerankerCandidate:
    return RerankerCandidate(identifier=f"id-{i}", title=title, text=text)


class TestMockReranker:
    def test_preserves_order_and_clamps(self) -> None:
        mock = MockReranker()
        out = mock.rerank(
            "bail triple test",
            [_cand(0, "A", "alpha"), _cand(1, "B", "beta"), _cand(2, "C", "gamma")],
            top_k=2,
        )
        assert [c.identifier for c in out] == ["id-0", "id-1"]

    def test_empty_input_returns_empty(self) -> None:
        assert MockReranker().rerank("q", [], top_k=5) == []


@dataclass
class _StubLLM:
    """Returns a fixed completion text so the reranker can parse it."""

    text: str
    name: str = "stub"
    model: str = "stub-1"

    def generate(
        self,
        messages,
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> LLMCompletion:
        return LLMCompletion(
            text=self.text,
            provider=self.name,
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=1,
        )


class TestLLMReranker:
    def test_reorders_by_llm_judgement(self) -> None:
        # LLM asks to return index 2 first, then 0, then 1.
        llm: LLMProvider = _StubLLM(text='{"order":[2,0,1]}')
        reranker = LLMReranker(llm)
        out = reranker.rerank(
            "bail triple test",
            [
                _cand(0, "Tax appeal", "income tax"),
                _cand(1, "Writ petition", "land revenue"),
                _cand(2, "Bail application", "triple test satisfied"),
            ],
            top_k=2,
        )
        assert [c.identifier for c in out] == ["id-2", "id-0"]

    def test_duplicates_in_order_are_ignored(self) -> None:
        llm: LLMProvider = _StubLLM(text='{"order":[1,1,0]}')
        reranker = LLMReranker(llm)
        out = reranker.rerank(
            "q",
            [_cand(0, "A", "a"), _cand(1, "B", "b")],
            top_k=2,
        )
        assert [c.identifier for c in out] == ["id-1", "id-0"]

    def test_undersupplied_order_is_backfilled_from_input(self) -> None:
        # Model only returned one id; reranker backfills the rest from
        # the original order so top_k is still honored.
        llm: LLMProvider = _StubLLM(text='{"order":[2]}')
        reranker = LLMReranker(llm)
        out = reranker.rerank(
            "q",
            [_cand(0, "A", "a"), _cand(1, "B", "b"), _cand(2, "C", "c")],
            top_k=3,
        )
        assert [c.identifier for c in out] == ["id-2", "id-0", "id-1"]

    def test_single_candidate_short_circuits(self) -> None:
        llm: LLMProvider = _StubLLM(text='unused')
        reranker = LLMReranker(llm)
        # Nothing to rank against — the LLM should not be called.
        out = reranker.rerank("q", [_cand(0, "A", "a")], top_k=5)
        assert [c.identifier for c in out] == ["id-0"]

    def test_malformed_llm_output_falls_back_to_input_order(self) -> None:
        llm: LLMProvider = _StubLLM(text="definitely not json")
        reranker = LLMReranker(llm)
        out = reranker.rerank(
            "q",
            [_cand(0, "A", "a"), _cand(1, "B", "b"), _cand(2, "C", "c")],
            top_k=2,
        )
        assert [c.identifier for c in out] == ["id-0", "id-1"]

    def test_bare_list_response_is_also_accepted(self) -> None:
        llm: LLMProvider = _StubLLM(text="[1, 0]")
        reranker = LLMReranker(llm)
        out = reranker.rerank(
            "q",
            [_cand(0, "A", "a"), _cand(1, "B", "b")],
            top_k=2,
        )
        assert [c.identifier for c in out] == ["id-1", "id-0"]

    def test_parse_order_handles_code_fence(self) -> None:
        parsed = _parse_order('```json\n{"order":[3,1,2]}\n```', expected=3)
        assert parsed == [3, 1, 2]


class TestBuildReranker:
    def test_default_is_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CASEOPS_RERANK_ENABLED", raising=False)
        assert isinstance(build_reranker(), MockReranker)

    def test_enabled_with_llm_backend_uses_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CASEOPS_RERANK_ENABLED", "true")
        monkeypatch.setenv("CASEOPS_RERANK_BACKEND", "llm")
        stub: LLMProvider = _StubLLM(text='{"order":[]}')
        reranker = build_reranker(provider=stub)
        assert isinstance(reranker, LLMReranker)

    def test_unknown_backend_falls_back_to_mock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CASEOPS_RERANK_ENABLED", "true")
        monkeypatch.setenv("CASEOPS_RERANK_BACKEND", "does-not-exist")
        assert isinstance(build_reranker(), MockReranker)


@pytest.mark.skipif(
    not __import__("os").environ.get("CASEOPS_RERANK_RUN_NATIVE"),
    reason="Set CASEOPS_RERANK_RUN_NATIVE=1 to exercise the 130MB fastembed model",
)
class TestFastembedRerankerIntegration:
    def test_reorders_bail_cases_above_tax_cases(self) -> None:
        from caseops_api.services.reranker import FastembedReranker

        reranker = FastembedReranker()
        cands = [
            _cand(0, "Income tax appeal", "assessment year 2018 transfer pricing"),
            _cand(1, "Bail application", "applicant seeks regular bail triple test"),
            _cand(2, "Writ for land acquisition", "collector notification 2017"),
            _cand(3, "Bail in economic offence", "parity with co-accused granted"),
        ]
        out = reranker.rerank(
            "bail triple test parity co-accused", cands, top_k=2
        )
        # The two bail cases should outrank the tax + land matters.
        assert {c.identifier for c in out} == {"id-1", "id-3"}


class TestCandidatesAdapter:
    def test_pulls_id_title_and_summary(self) -> None:
        @dataclass
        class Row:
            id: str
            title: str
            summary: str

        rows = [
            Row(id="x1", title="Bail order", summary="triple test met"),
            Row(id="x2", title="Tax appeal", summary="assessment year 2022"),
        ]
        cands = candidates_from_iterable(rows)
        assert [c.identifier for c in cands] == ["x1", "x2"]
        assert cands[0].title == "Bail order"
