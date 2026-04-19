"""Sprint 11 — LLM cassette record/replay layer."""
from __future__ import annotations

from pathlib import Path

import pytest

from caseops_api.services.llm import LLMCompletion, LLMMessage, MockProvider
from caseops_api.services.llm_cassette import (
    CASSETTE_MODE_OFF,
    CASSETTE_MODE_RECORD,
    CASSETTE_MODE_REPLAY,
    CassetteMissError,
    CassetteProvider,
    cassette_key,
    load_cassette_index,
    maybe_wrap_with_cassette,
)


def _msgs(text: str = "respond with json") -> list[LLMMessage]:
    return [LLMMessage(role="user", content=text)]


def test_cassette_key_is_stable_for_identical_inputs() -> None:
    a = cassette_key(model="m1", temperature=0.0, max_tokens=128, messages=_msgs("hello"))
    b = cassette_key(model="m1", temperature=0.0, max_tokens=128, messages=_msgs("hello"))
    assert a == b


def test_cassette_key_changes_with_any_field() -> None:
    base = cassette_key(model="m1", temperature=0.0, max_tokens=128, messages=_msgs("a"))
    diff_model = cassette_key(model="m2", temperature=0.0, max_tokens=128, messages=_msgs("a"))
    diff_temp = cassette_key(model="m1", temperature=0.5, max_tokens=128, messages=_msgs("a"))
    diff_tokens = cassette_key(model="m1", temperature=0.0, max_tokens=256, messages=_msgs("a"))
    diff_msg = cassette_key(model="m1", temperature=0.0, max_tokens=128, messages=_msgs("b"))
    diff_role = cassette_key(
        model="m1", temperature=0.0, max_tokens=128,
        messages=[LLMMessage(role="system", content="a")],
    )
    assert len({base, diff_model, diff_temp, diff_tokens, diff_msg, diff_role}) == 6


def test_record_mode_writes_jsonl_and_returns_inner_completion(tmp_path: Path) -> None:
    inner = MockProvider(model="caseops-mock-1")
    cas_path = tmp_path / "cas.jsonl"
    provider = CassetteProvider(inner, path=cas_path, mode=CASSETTE_MODE_RECORD)

    out = provider.generate(_msgs("respond with json"), temperature=0.0, max_tokens=64)

    assert isinstance(out, LLMCompletion)
    assert cas_path.exists()
    body = cas_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(body) == 1
    # Re-load and confirm round-trip parity.
    index = load_cassette_index(cas_path)
    assert len(index) == 1
    cached = next(iter(index.values()))
    assert cached.text == out.text
    assert cached.provider == "mock"
    assert cached.raw is None  # raw stripped on serialise


def test_record_mode_dedupes_repeated_calls(tmp_path: Path) -> None:
    inner = MockProvider(model="caseops-mock-1")
    cas_path = tmp_path / "cas.jsonl"
    provider = CassetteProvider(inner, path=cas_path, mode=CASSETTE_MODE_RECORD)

    provider.generate(_msgs("respond with json"), temperature=0.0, max_tokens=64)
    provider.generate(_msgs("respond with json"), temperature=0.0, max_tokens=64)
    provider.generate(_msgs("respond with json"), temperature=0.0, max_tokens=64)

    body = cas_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(body) == 1, "duplicate keys must not append"


def test_replay_mode_serves_from_cassette_without_calling_inner(tmp_path: Path) -> None:
    cas_path = tmp_path / "cas.jsonl"
    # First record one call.
    recorder = CassetteProvider(
        MockProvider(model="caseops-mock-1"), path=cas_path, mode=CASSETTE_MODE_RECORD,
    )
    recorded = recorder.generate(_msgs("respond with json"), temperature=0.0, max_tokens=64)

    class _Boom:  # any call to inner.generate is a test failure
        name = "boom"
        model = "caseops-mock-1"

        def generate(self, messages, *, temperature=0.0, max_tokens=64):  # pragma: no cover
            raise AssertionError("replay must not call the inner provider")

    replayer = CassetteProvider(_Boom(), path=cas_path, mode=CASSETTE_MODE_REPLAY)
    served = replayer.generate(_msgs("respond with json"), temperature=0.0, max_tokens=64)
    assert served.text == recorded.text
    assert served.provider == "mock"


def test_replay_miss_raises_clean_error(tmp_path: Path) -> None:
    cas_path = tmp_path / "empty.jsonl"
    cas_path.write_text("", encoding="utf-8")
    inner = MockProvider(model="caseops-mock-1")
    replayer = CassetteProvider(inner, path=cas_path, mode=CASSETTE_MODE_REPLAY)

    with pytest.raises(CassetteMissError) as exc:
        replayer.generate(_msgs("a question never recorded"), temperature=0.0, max_tokens=64)
    assert "no recording for key" in str(exc.value)


def test_off_mode_or_no_path_returns_inner_unchanged() -> None:
    inner = MockProvider(model="caseops-mock-1")
    assert maybe_wrap_with_cassette(inner, mode=CASSETTE_MODE_OFF, path="x.jsonl") is inner
    assert maybe_wrap_with_cassette(inner, mode=None, path=None) is inner
    assert maybe_wrap_with_cassette(inner, mode=CASSETTE_MODE_RECORD, path=None) is inner


def test_invalid_mode_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cassette mode"):
        CassetteProvider(
            MockProvider(model="m"), path=tmp_path / "c.jsonl", mode="rerecord",
        )
