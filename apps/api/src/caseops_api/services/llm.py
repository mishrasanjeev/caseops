"""LLM provider abstraction for CaseOps.

Design decisions:

- One ``LLMProvider`` Protocol. Callers never import a specific SDK.
- ``MockProvider`` is the default so local dev, CI, and tests never need a live
  API key. Output is deterministic and structured so assertions are cheap.
- ``AnthropicProvider`` and ``GeminiProvider`` are thin adapters guarded by
  runtime imports: the SDK is pulled in only when the provider is selected,
  keeping the base install light.
- ``generate_structured`` coerces the model's response into a validated
  ``pydantic.BaseModel``. That is the shape CaseOps uses for recommendations,
  drafts, and briefs — arbitrary free text is not acceptable for the product.
- Every call records a ``ModelRun`` so tenant usage is auditable. The writer
  hook is injected so the service layer stays ignorant of the DB session.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from caseops_api.core.settings import get_settings

logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """Raised when a provider call cannot be completed."""


class LLMResponseFormatError(LLMProviderError):
    """Raised when the provider returned text but it did not validate."""


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMCompletion:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    raw: Any = None


@dataclass
class LLMCallContext:
    """Metadata captured alongside every call for auditing."""

    tenant_id: str | None = None
    matter_id: str | None = None
    purpose: str = "unspecified"
    metadata: dict[str, Any] = field(default_factory=dict)


ModelRunWriter = Callable[[LLMCompletion, LLMCallContext, list[LLMMessage]], None]


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion: ...


class MockProvider:
    """Deterministic offline provider.

    Returns a compact JSON string when the caller's last message asks for
    structured output (by including the substring ``"respond with json"``).
    Otherwise returns a short plain-text acknowledgement. The output is a
    stable function of the input, so tests assert against it directly.
    """

    name = "mock"

    def __init__(self, model: str = "caseops-mock-1") -> None:
        self.model = model

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        started = time.perf_counter()
        joined = "\n".join(m.content for m in messages)
        is_structured = "respond with json" in joined.lower()
        if is_structured:
            text = _mock_structured_response(joined)
        else:
            text = _mock_plain_response(joined)
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        return LLMCompletion(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=_rough_token_estimate(joined),
            completion_tokens=_rough_token_estimate(text),
            latency_ms=elapsed_ms,
        )


def _rough_token_estimate(text: str) -> int:
    # ~4 characters per token is a reasonable rough bound for English-heavy
    # legal text; the mock never needs to be precise.
    return max(1, len(text) // 4)


def _mock_plain_response(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    return f"mock-ack::{digest}"


def _mock_structured_response(prompt: str) -> str:
    """Produce a stable JSON object referencing the inputs.

    The heuristic: look for the matter title, forum, and supporting citations
    the caller embedded, then emit a schema the recommendation service
    expects. Services should ALWAYS go through ``generate_structured`` which
    re-validates this with pydantic.
    """
    forum = _extract_between(prompt, "FORUM:", "\n") or "high_court"
    title = _extract_between(prompt, "MATTER_TITLE:", "\n") or "Unknown matter"
    authorities = _extract_citations(prompt)
    excerpts = _extract_excerpts(prompt)
    primary = authorities[0] if authorities else None
    primary_excerpt = excerpts[0] if excerpts else ""
    primary_fragment = " ".join(primary_excerpt.split()[:30])
    payload: dict[str, Any] = {
        "title": f"Recommendation for {title.strip()}",
        "options": [
            {
                "label": (
                    f"Proceed under the available precedent{' ('+primary+')' if primary else ''}"
                ),
                "rationale": (
                    "The retrieved authority supports this route: "
                    f"{primary_fragment}"
                    if primary_fragment
                    else "No retrieved authority strongly supports this route."
                ),
                "confidence": "medium" if primary else "low",
                "supporting_citations": authorities[:3],
                "risk_notes": "Confirm procedural history before filing.",
            },
            {
                "label": "Seek settlement before escalating",
                "rationale": "Reduces fee exposure and preserves optionality.",
                "confidence": "low",
                "supporting_citations": [],
                "risk_notes": "Adverse party may not engage.",
            },
        ],
        "primary_recommendation_label": (
            f"Proceed under the available precedent{' ('+primary+')' if primary else ''}"
        ),
        "rationale": (
            "The retrieved authorities align with the matter's forum and stage. "
            "The primary option is grounded; the settlement option is defensive."
        ),
        "assumptions": [
            f"Matter is before a {forum.strip()} bench",
            "Client has authorized filing within limitation",
        ],
        "missing_facts": [
            "Exact limitation clock for any appeal",
            "Opposing counsel posture",
        ],
        "confidence": "medium" if primary else "low",
        "next_action": "Partner review before any external share.",
    }
    return json.dumps(payload, separators=(",", ":"))


def _extract_between(text: str, start: str, end: str) -> str | None:
    idx = text.find(start)
    if idx == -1:
        return None
    tail = text[idx + len(start) :]
    end_idx = tail.find(end)
    if end_idx == -1:
        return tail.strip() or None
    return tail[:end_idx].strip() or None


def _extract_citations(text: str) -> list[str]:
    """Pick identifiers that look like case references we embedded."""
    citations: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- CITATION:"):
            value = stripped[len("- CITATION:") :].strip()
            if value:
                citations.append(value)
    return citations


def _extract_excerpts(text: str) -> list[str]:
    excerpts: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("EXCERPT:"):
            value = stripped[len("EXCERPT:") :].strip()
            if value:
                excerpts.append(value)
    return excerpts


class AnthropicProvider:
    """Thin adapter around the Anthropic SDK."""

    name = "anthropic"

    def __init__(self, *, model: str, api_key: str) -> None:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMProviderError(
                "The 'anthropic' package is not installed. Run "
                "'uv add anthropic' and set CASEOPS_LLM_PROVIDER=anthropic.",
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        system_prompt, chat = _split_system_and_chat(messages)
        started = time.perf_counter()
        try:
            response = self._client.messages.create(
                model=self.model,
                system=system_prompt or None,
                messages=chat,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise LLMProviderError(f"Anthropic call failed: {exc}") from exc
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        text = "".join(
            block.text
            for block in getattr(response, "content", [])
            if getattr(block, "type", "") == "text"
        )
        usage = getattr(response, "usage", None)
        return LLMCompletion(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            latency_ms=elapsed_ms,
            raw=response,
        )


class GeminiProvider:
    """Thin adapter around google-genai. The hosted path for Gemma 4 family."""

    name = "gemini"

    def __init__(self, *, model: str, api_key: str) -> None:
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMProviderError(
                "The 'google-genai' package is not installed. Run "
                "'uv add google-genai' and set CASEOPS_LLM_PROVIDER=gemini.",
            ) from exc
        self._client = genai.Client(api_key=api_key)
        self.model = model

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        contents = _messages_to_gemini(messages)
        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
        except Exception as exc:
            raise LLMProviderError(f"Gemini call failed: {exc}") from exc
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        text = getattr(response, "text", "") or ""
        usage = getattr(response, "usage_metadata", None)
        return LLMCompletion(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            latency_ms=elapsed_ms,
            raw=response,
        )


def _split_system_and_chat(
    messages: list[LLMMessage],
) -> tuple[str, list[dict[str, str]]]:
    system_parts = [m.content for m in messages if m.role == "system"]
    chat = [
        {"role": m.role, "content": m.content}
        for m in messages
        if m.role in {"user", "assistant"}
    ]
    return "\n\n".join(system_parts), chat


def _messages_to_gemini(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = "user" if message.role in {"user", "system"} else "model"
        contents.append({"role": role, "parts": [{"text": message.content}]})
    return contents


def build_provider() -> LLMProvider:
    settings = get_settings()
    provider_name = settings.llm_provider.lower()
    if provider_name in {"mock", "noop", "off"}:
        return MockProvider(model=settings.llm_model or "caseops-mock-1")
    if not settings.llm_api_key:
        raise LLMProviderError(
            f"CASEOPS_LLM_API_KEY must be set when CASEOPS_LLM_PROVIDER={provider_name!r}.",
        )
    if provider_name == "anthropic":
        return AnthropicProvider(
            model=settings.llm_model or "claude-opus-4-7",
            api_key=settings.llm_api_key,
        )
    if provider_name == "gemini":
        return GeminiProvider(
            model=settings.llm_model or "gemini-2.5-pro",
            api_key=settings.llm_api_key,
        )
    raise LLMProviderError(
        f"Unknown CASEOPS_LLM_PROVIDER value: {provider_name!r}. "
        "Use 'mock', 'anthropic', or 'gemini'.",
    )


def generate_structured[T: BaseModel](
    provider: LLMProvider,
    *,
    schema: type[T],
    messages: list[LLMMessage],
    context: LLMCallContext,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    on_model_run: ModelRunWriter | None = None,
) -> tuple[T, LLMCompletion]:
    """Run the provider and validate its output as ``schema``.

    The caller is expected to instruct the model to output JSON that matches
    ``schema`` — we only parse and validate. A ``LLMResponseFormatError`` is
    raised if validation fails; the caller is responsible for fallback
    behaviour (retry, refuse, ask for clarification).
    """
    completion = provider.generate(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if on_model_run is not None:
        try:
            on_model_run(completion, context, messages)
        except Exception:
            logger.exception("Could not persist ModelRun for %s", context.purpose)
    try:
        payload = json.loads(_strip_code_fence(completion.text))
    except json.JSONDecodeError as exc:
        raise LLMResponseFormatError(
            f"{completion.provider}:{completion.model} did not return valid JSON.",
        ) from exc
    try:
        validated = schema.model_validate(payload)
    except ValidationError as exc:
        raise LLMResponseFormatError(
            f"{completion.provider}:{completion.model} returned JSON that did "
            "not match the expected schema.",
        ) from exc
    return validated, completion


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("\n", 1)[0]
        cleaned = cleaned.strip("`").strip()
    return cleaned


__all__ = [
    "AnthropicProvider",
    "GeminiProvider",
    "LLMCallContext",
    "LLMCompletion",
    "LLMMessage",
    "LLMProvider",
    "LLMProviderError",
    "LLMResponseFormatError",
    "MockProvider",
    "ModelRunWriter",
    "build_provider",
    "generate_structured",
]
