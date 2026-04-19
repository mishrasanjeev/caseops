"""LLM cassette — record real provider responses, replay them later.

Powers Sprint 11's offline eval mode. Two distinct shapes:

- ``record``: every call delegates to the wrapped provider AND
  appends ``(key, completion)`` to a JSONL cassette file. First-time
  capture during a real run with credentials.
- ``replay``: every call is served from the cassette by key. A miss
  raises ``CassetteMissError`` so a CI run that drifted off the
  fixture surfaces immediately, instead of silently calling the
  network (we don't *have* credentials in CI).

Off mode (the default) returns the inner provider untouched, so
nothing in the production hot-path pays for cassette plumbing.

Key design: the cassette key is a stable hash of ``(model,
temperature, max_tokens, [(role, content) for each message])``. Two
calls with identical inputs deduplicate to the same fixture; two
calls that differ in even one character will miss in replay (which
is what we want — we shouldn't replay an answer to a question we
didn't ask).

Cassette format: JSONL — one ``{"key": "...", "completion": {...}}``
record per line. Append-only. ``load_cassette_index`` reads the
file once into a dict for O(1) lookups during replay.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path

from caseops_api.services.llm import LLMCompletion, LLMMessage, LLMProvider, LLMProviderError

logger = logging.getLogger(__name__)


CASSETTE_MODE_OFF = "off"
CASSETTE_MODE_RECORD = "record"
CASSETTE_MODE_REPLAY = "replay"
_VALID_MODES = frozenset({CASSETTE_MODE_OFF, CASSETTE_MODE_RECORD, CASSETTE_MODE_REPLAY})


class CassetteError(LLMProviderError):
    """Base for cassette failures (miss / corrupt / mode misuse)."""


class CassetteMissError(CassetteError):
    """The cassette didn't contain a recording for this call. In
    replay mode, this means the test/run drifted off the fixture and
    needs a fresh capture under credentials."""


def cassette_key(
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    messages: list[LLMMessage],
) -> str:
    """Stable SHA-256 of the call shape. Sensitive to message
    role + content + model + sampling knobs; insensitive to the
    in-memory object identity."""
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\x1f")
    h.update(f"{temperature:.4f}".encode())
    h.update(b"\x1f")
    h.update(str(int(max_tokens)).encode("utf-8"))
    h.update(b"\x1e")
    for m in messages:
        h.update(m.role.encode("utf-8"))
        h.update(b"\x1f")
        h.update((m.content or "").encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def _completion_to_dict(c: LLMCompletion) -> dict:
    # asdict drags the raw provider response (often huge SDK objects)
    # along — we strip it before serialising.
    payload = asdict(c)
    payload.pop("raw", None)
    return payload


def _completion_from_dict(payload: dict) -> LLMCompletion:
    return LLMCompletion(
        text=payload["text"],
        provider=payload["provider"],
        model=payload["model"],
        prompt_tokens=int(payload.get("prompt_tokens", 0) or 0),
        completion_tokens=int(payload.get("completion_tokens", 0) or 0),
        latency_ms=int(payload.get("latency_ms", 0) or 0),
        raw=None,
    )


def load_cassette_index(path: Path) -> dict[str, LLMCompletion]:
    """Load a JSONL cassette into a key -> LLMCompletion map.

    A missing file produces an empty index (record mode starts from
    scratch; replay mode would then miss on every call, which is the
    correct loud failure)."""
    if not path.exists():
        return {}
    index: dict[str, LLMCompletion] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CassetteError(
                    f"cassette {path}:{line_no} is not valid JSON: {exc}"
                ) from exc
            key = row.get("key")
            completion = row.get("completion")
            if not key or not isinstance(completion, dict):
                raise CassetteError(
                    f"cassette {path}:{line_no} missing 'key' or 'completion'"
                )
            index[key] = _completion_from_dict(completion)
    return index


class CassetteProvider:
    """Wrap any ``LLMProvider`` with record/replay over a JSONL file.

    Record mode is write-through: the wrapped provider is called
    every time, and successful completions are appended. Duplicate
    keys (same call repeated) skip the append so the cassette stays
    deduplicated.

    Replay mode never calls the wrapped provider — it serves entirely
    from the loaded index. This is what makes offline CI runs viable.
    """

    name = "cassette"

    def __init__(
        self,
        inner: LLMProvider,
        *,
        path: Path,
        mode: str,
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"cassette mode must be one of {sorted(_VALID_MODES)}; got {mode!r}"
            )
        self._inner = inner
        self._path = path
        self._mode = mode
        self.model = inner.model
        # Replay loads the index up-front; record loads it (best-effort)
        # so we can dedupe seen keys against an existing capture.
        self._index: dict[str, LLMCompletion] = load_cassette_index(path)
        self._write_lock = threading.Lock()

    @property
    def mode(self) -> str:
        return self._mode

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        key = cassette_key(
            model=self._inner.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
        )
        if self._mode == CASSETTE_MODE_REPLAY:
            cached = self._index.get(key)
            if cached is None:
                raise CassetteMissError(
                    f"cassette {self._path} has no recording for key {key[:12]}… "
                    f"(model={self._inner.model}, {len(messages)} messages). "
                    "Re-run in CASEOPS_LLM_CASSETTE_MODE=record under credentials "
                    "to capture this call."
                )
            return cached
        # record + off both delegate.
        completion = self._inner.generate(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        if self._mode == CASSETTE_MODE_RECORD and key not in self._index:
            self._append(key, completion)
            self._index[key] = completion
        return completion

    def _append(self, key: str, completion: LLMCompletion) -> None:
        record = json.dumps(
            {"key": key, "completion": _completion_to_dict(completion)},
            separators=(",", ":"),
            ensure_ascii=False,
        )
        with self._write_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(record + "\n")


def maybe_wrap_with_cassette(
    inner: LLMProvider, *, mode: str | None, path: str | None
) -> LLMProvider:
    """Apply cassette wrapping iff ``mode`` is record/replay AND a
    path is configured. Off mode (or missing path) returns ``inner``
    unchanged. Production callers don't need to know cassettes exist.
    """
    if not mode or mode == CASSETTE_MODE_OFF:
        return inner
    if not path:
        logger.warning(
            "cassette mode=%s requested but no path set; running passthrough", mode
        )
        return inner
    return CassetteProvider(inner, path=Path(path), mode=mode)


__all__ = [
    "CASSETTE_MODE_OFF",
    "CASSETTE_MODE_RECORD",
    "CASSETTE_MODE_REPLAY",
    "CassetteError",
    "CassetteMissError",
    "CassetteProvider",
    "cassette_key",
    "load_cassette_index",
    "maybe_wrap_with_cassette",
]
