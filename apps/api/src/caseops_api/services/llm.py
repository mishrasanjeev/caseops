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


class LLMQuotaExhaustedError(LLMProviderError):
    """Raised when the upstream provider rejects the call because the
    account has run out of credits / paid quota (Anthropic 402
    "credit balance is too low", OpenAI 429 "insufficient_quota").

    The drafting / recommendations / hearing-pack / matter-summary
    services treat this as a hard signal to cut over to a different
    provider entirely — retrying on the same provider's cheaper model
    (Haiku) would hit the same wall."""


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
        lowered = joined.lower()
        if "hearing pack" in lowered or "hearing_pack" in lowered:
            text = _mock_hearing_pack_response(joined)
        elif "drafting a legal document" in lowered or "draft title:" in lowered:
            text = _mock_draft_response(joined)
        elif "respond with json" in lowered:
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


def _mock_hearing_pack_response(prompt: str) -> str:
    """Deterministic hearing pack emitter for offline tests.

    Mirrors `_LLMPackResponse` in services/hearing_packs.py — the two must
    stay in sync. Item types are drawn from the allowed enum so the
    normaliser does not drop them.
    """
    title = _extract_between(prompt, "Matter:", "\n") or "Unknown matter"
    hearing_on = _extract_between(prompt, "Upcoming hearing:", "—") or "the next hearing"
    payload: dict[str, Any] = {
        "summary": (
            f"Hearing pack for {title.strip()}. The bench is expected to "
            f"take up the matter on {hearing_on.strip()}. Review below "
            "before court; every item requires partner sign-off."
        ),
        "items": [
            {
                "item_type": "chronology",
                "title": "Matter chronology",
                "body": "Key filings, hearings, and orders in the matter to date.",
                "rank": 1,
            },
            {
                "item_type": "last_order",
                "title": "Last order summary",
                "body": "One-paragraph summary of the most recent order on the matter.",
                "rank": 2,
            },
            {
                "item_type": "pending_compliance",
                "title": "Pending compliance",
                "body": "Outstanding directions from the bench still to be complied with.",
                "rank": 3,
            },
            {
                "item_type": "issue",
                "title": "Live legal issues",
                "body": "Issues the court is likely to frame and hear on this date.",
                "rank": 4,
            },
            {
                "item_type": "opposition_point",
                "title": "Anticipated opposition",
                "body": "The arguments the opposing party is likely to press.",
                "rank": 5,
            },
            {
                "item_type": "authority_card",
                "title": "Supporting authority",
                "body": "The strongest precedent supporting the matter's primary relief.",
                "rank": 6,
                "source_ref": "MOCK-AUTH-1",
            },
            {
                "item_type": "oral_point",
                "title": "Oral submission notes",
                "body": "Two bullet points the lawyer should raise in court.",
                "rank": 7,
            },
        ],
    }
    return json.dumps(payload, separators=(",", ":"))


def _mock_draft_response(prompt: str) -> str:
    """Deterministic legal-draft emitter for offline tests.

    Emits a short but structurally-complete document body plus the
    citations it was given. When no authorities were retrieved the
    draft flags it in the summary rather than inventing sources.
    """
    title = _extract_between(prompt, "Draft title:", "\n") or "Draft"
    matter = _extract_between(prompt, "Matter:", "\n") or "the matter"
    authorities = _extract_citations(prompt)
    cite_list = authorities[:5]
    cite_sentences = "\n".join(
        f"The Hon'ble Court's ruling in [{c}] applies to the facts here."
        for c in cite_list
    )
    body_lines = [
        f"Brief in {title.strip()}",
        "",
        f"1. This brief concerns {matter.strip()}.",
        "2. The facts, authorities, and reliefs are set out below.",
        "",
        "FACTS",
        (
            "The parties and the operative dates are as recorded on the "
            "matter record. Prior directions of the bench have been complied "
            "with save to the extent noted below."
        ),
        "",
        "SUBMISSIONS",
        cite_sentences
        or (
            "The submissions rest on first principles; no binding authority "
            "has been cited because none was retrieved for this draft."
        ),
        "",
        "PRAYER",
        "It is respectfully prayed that the relief sought be granted.",
    ]
    payload: dict[str, Any] = {
        "body": "\n".join(body_lines),
        "citations": cite_list,
        "summary": (
            f"Draft generated for {title.strip()}; "
            f"{len(cite_list)} authorities cited."
            if cite_list
            else (
                f"Draft generated for {title.strip()}; NO authorities cited — "
                "partner review should supply grounding before approval."
            )
        ),
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
    """Thin adapter around the Anthropic SDK.

    Supports Anthropic's ephemeral prompt caching (``cache_control``)
    on the system block when ``prompt_cache`` is True. Large CaseOps
    system prompts (drafting ABSOLUTE RULES + statute guidance) are
    ~2-3 KB of static text; reusing the same system prompt within the
    5-minute TTL drops input-token billing on that block to ~10 %.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        prompt_cache: bool = True,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMProviderError(
                "The 'anthropic' package is not installed. Run "
                "'uv add anthropic' and set CASEOPS_LLM_PROVIDER=anthropic.",
            ) from exc
        self._client = anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self.model = model
        self._prompt_cache = prompt_cache

    # Model families that have deprecated the `temperature` parameter.
    # Currently Opus 4.7 and its reasoning-model siblings. Add newer
    # prefixes here as they ship; keeping the list explicit beats
    # guessing from error strings at runtime.
    _NO_TEMPERATURE_PREFIXES: tuple[str, ...] = (
        "claude-opus-4-7",
    )

    def _model_rejects_temperature(self) -> bool:
        name = (self.model or "").lower()
        return any(name.startswith(p) for p in self._NO_TEMPERATURE_PREFIXES)

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        system_prompt, chat = _split_system_and_chat(messages)
        started = time.perf_counter()
        kwargs: dict = {
            "model": self.model,
            "messages": chat,
            "max_tokens": max_tokens,
        }
        # Anthropic's reasoning models (Opus 4.7+) deprecated the
        # `temperature` parameter. Including it surfaces a 400 at the
        # wire, and the error message does not propagate cleanly into
        # the structured-output path. Skip it for known-new models;
        # keep it for Sonnet / Haiku where it still tunes output.
        if not self._model_rejects_temperature():
            kwargs["temperature"] = temperature
        if system_prompt:
            # Anthropic treats a list of system blocks with
            # cache_control="ephemeral" as a 5-minute cache hint.
            # We only cache when the prompt is large enough to matter —
            # under ~500 tokens the minimum billable unit outweighs the
            # savings.
            if self._prompt_cache and len(system_prompt) >= 2000:
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                kwargs["system"] = system_prompt
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:
            if _is_quota_exhausted(exc):
                raise LLMQuotaExhaustedError(
                    f"Anthropic quota exhausted: {exc}",
                ) from exc
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


class OpenAIProvider:
    """Thin adapter around the OpenAI Python SDK.

    Used as a hard cross-provider fallback when Anthropic returns 402
    (credit balance too low). Defaults to ``gpt-5.1``.

    Two model-family quirks worth knowing:

    - ``gpt-5.x`` reasoning models reject any temperature other than
      the default. We omit the parameter entirely for ``gpt-5*`` so the
      wire request never carries it, mirroring how
      :class:`AnthropicProvider` treats Opus 4.7.
    - The Chat Completions API now prefers ``max_completion_tokens``
      over the legacy ``max_tokens``. We send the new field; the SDK
      maps it correctly for older models too.
    """

    name = "openai"

    _NO_TEMPERATURE_PREFIXES: tuple[str, ...] = (
        "gpt-5",
        "o1",
        "o3",
    )

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        try:
            import openai  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMProviderError(
                "The 'openai' package is not installed. Run "
                "'uv add openai' and set CASEOPS_LLM_PROVIDER=openai "
                "(or configure OpenAI as a fallback).",
            ) from exc
        self._client = openai.OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self.model = model

    def _model_rejects_temperature(self) -> bool:
        name = (self.model or "").lower()
        return any(name.startswith(p) for p in self._NO_TEMPERATURE_PREFIXES)

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        oai_messages = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_completion_tokens": max_tokens,
        }
        if not self._model_rejects_temperature():
            kwargs["temperature"] = temperature
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if _is_quota_exhausted(exc):
                raise LLMQuotaExhaustedError(
                    f"OpenAI quota exhausted: {exc}",
                ) from exc
            raise LLMProviderError(f"OpenAI call failed: {exc}") from exc
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        choice = response.choices[0] if getattr(response, "choices", None) else None
        text = ""
        if choice is not None and getattr(choice, "message", None) is not None:
            text = getattr(choice.message, "content", "") or ""
        usage = getattr(response, "usage", None)
        return LLMCompletion(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
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


# Purpose tags the drafting / recommendation / hearing-pack / eval
# pipelines pass to build_provider so each workflow gets the model
# best suited to it. Legal drafting wants Opus-class reasoning;
# structured-output recommendations are fine on Sonnet; metadata
# extraction at corpus scale stays on Haiku. A circular eval
# (same-model judge and drafter) is worse than no eval, so the eval
# purpose deliberately resolves to the strongest available model.
Purpose = str
PURPOSE_DRAFTING = "drafting"
PURPOSE_RECOMMENDATIONS = "recommendations"
PURPOSE_HEARING_PACK = "hearing_pack"
PURPOSE_METADATA_EXTRACT = "metadata_extract"
PURPOSE_EVAL = "eval"


def _resolve_model_for_purpose(settings: object, purpose: str | None) -> str:
    """Pick the configured model for ``purpose``; fall back to the
    global ``llm_model`` when no per-purpose override is set.

    Treats None and empty string the same so operators can clear a
    per-purpose override with ``CASEOPS_LLM_MODEL_DRAFTING=""`` rather
    than having to unset the env var entirely.
    """
    mapping = {
        PURPOSE_DRAFTING: getattr(settings, "llm_model_drafting", None),
        PURPOSE_RECOMMENDATIONS: getattr(settings, "llm_model_recommendations", None),
        PURPOSE_HEARING_PACK: getattr(settings, "llm_model_hearing_pack", None),
        PURPOSE_METADATA_EXTRACT: getattr(
            settings, "llm_model_metadata_extract", None
        ),
        PURPOSE_EVAL: getattr(settings, "llm_model_eval", None),
    }
    override = mapping.get(purpose) if purpose else None
    if override and str(override).strip():
        return str(override).strip()
    return getattr(settings, "llm_model", "") or "caseops-mock-1"


def build_provider(purpose: str | None = None) -> LLMProvider:
    settings = get_settings()
    inner = _build_inner_provider(settings, purpose)
    # Cassette wrapping is opt-in (off by default). Sprint 11 offline
    # eval: capture once with credentials in `record` mode, replay
    # forever in CI in `replay` mode.
    from caseops_api.services.llm_cassette import maybe_wrap_with_cassette
    return maybe_wrap_with_cassette(
        inner,
        mode=getattr(settings, "llm_cassette_mode", None),
        path=getattr(settings, "llm_cassette_path", None),
    )


def _build_inner_provider(settings: object, purpose: str | None) -> LLMProvider:
    provider_name = settings.llm_provider.lower()
    model = _resolve_model_for_purpose(settings, purpose)
    if provider_name in {"mock", "noop", "off"}:
        return MockProvider(model=model)
    if not settings.llm_api_key:
        raise LLMProviderError(
            f"CASEOPS_LLM_API_KEY must be set when CASEOPS_LLM_PROVIDER={provider_name!r}.",
        )
    # BUG-015 (Ram 2026-04-26 Critical reopen): the recommendations
    # endpoint hung for the full Cloud Run 300-second timeout (504),
    # surfacing in the browser as "Could not reach the workspace API".
    # Cloud Run access logs confirmed: every recommendation POST
    # returned 504 at 300.0006s. Worst-case Anthropic call with the
    # default timeout=60s + max_retries=2 = up to 180s per provider;
    # times Sonnet primary + Haiku fallback + OpenAI fallback = ~9 min.
    # Cap the per-purpose worst case so the handler fits inside Cloud
    # Run's 300s budget with headroom for citation-verification + DB.
    per_purpose_timeout: dict[str, float] = {
        PURPOSE_RECOMMENDATIONS: 30.0,
        PURPOSE_HEARING_PACK: 30.0,
        PURPOSE_METADATA_EXTRACT: 30.0,
        # Drafting can legitimately need longer responses (full appeal
        # memorandum, 8K output tokens) — keep its budget generous.
        PURPOSE_DRAFTING: 90.0,
        PURPOSE_EVAL: 60.0,
    }
    per_purpose_retries: dict[str, int] = {
        PURPOSE_RECOMMENDATIONS: 1,
        PURPOSE_HEARING_PACK: 1,
        PURPOSE_METADATA_EXTRACT: 1,
        PURPOSE_DRAFTING: 2,
        PURPOSE_EVAL: 2,
    }
    timeout_for_purpose = per_purpose_timeout.get(purpose or "", 60.0)
    retries_for_purpose = per_purpose_retries.get(purpose or "", 2)
    if provider_name == "anthropic":
        return AnthropicProvider(
            # 2026-04-26 cost-discipline default: Haiku, not Opus.
            # In prod every purpose sets a per-purpose model via env
            # (CASEOPS_LLM_MODEL_DRAFTING=claude-opus-4-7, etc.), so
            # this safety-net only fires when neither the per-purpose
            # override nor the global CASEOPS_LLM_MODEL is set. Per
            # `feedback_corpus_spend_audit`: prefer the cheap default;
            # callers that genuinely need Opus already set it
            # explicitly.
            model=model or "claude-haiku-4-5-20251001",
            api_key=settings.llm_api_key,
            prompt_cache=bool(getattr(settings, "llm_prompt_cache_enabled", True)),
            timeout_seconds=timeout_for_purpose,
            max_retries=retries_for_purpose,
        )
    if provider_name == "gemini":
        return GeminiProvider(
            model=model or "gemini-2.5-pro",
            api_key=settings.llm_api_key,
        )
    if provider_name == "openai":
        return OpenAIProvider(
            model=model or "gpt-5.1",
            api_key=settings.llm_api_key,
        )
    raise LLMProviderError(
        f"Unknown CASEOPS_LLM_PROVIDER value: {provider_name!r}. "
        "Use 'mock', 'anthropic', 'openai', or 'gemini'.",
    )


_QUOTA_EXHAUSTED_MARKERS = (
    "credit balance is too low",
    "insufficient_quota",
    "exceeded your current quota",
    "billing_hard_limit_reached",
)


def _is_quota_exhausted(exc: BaseException) -> bool:
    """Best-effort sniff for "you ran out of paid credits" errors.

    Sniffs both HTTP status (402 / 429-with-insufficient_quota) and
    the rendered error message. Provider SDKs surface this differently:

    - Anthropic SDK: ``BadRequestError`` (400 wrapper) carrying the
      message ``"Your credit balance is too low to access the
      Anthropic API."``
    - OpenAI SDK: ``RateLimitError`` (429) with body
      ``{"error":{"code":"insufficient_quota", ...}}``

    We fall back to a substring scan of ``str(exc)`` because the SDK
    classes are imported lazily and we don't want to add hard imports
    just to do isinstance checks.
    """
    status_code = getattr(exc, "status_code", None)
    if status_code == 402:
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _QUOTA_EXHAUSTED_MARKERS)


def max_tokens_for_purpose(purpose: str | None) -> int:
    """Per-purpose output ceiling. Drafting needs headroom; structured
    recommendations + metadata extraction do not."""
    settings = get_settings()
    if purpose == PURPOSE_DRAFTING:
        return getattr(settings, "llm_max_output_tokens_drafting", 8192)
    if purpose == PURPOSE_HEARING_PACK:
        return getattr(settings, "llm_max_output_tokens_hearing_pack", 4096)
    return settings.llm_max_output_tokens


def generate_structured[T: BaseModel](
    provider: LLMProvider,
    *,
    schema: type[T],
    messages: list[LLMMessage],
    context: LLMCallContext,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    on_model_run: ModelRunWriter | None = None,
    session: Any | None = None,
) -> tuple[T, LLMCompletion]:
    """Run the provider and validate its output as ``schema``.

    The caller is expected to instruct the model to output JSON that matches
    ``schema`` — we only parse and validate. A ``LLMResponseFormatError`` is
    raised if validation fails; the caller is responsible for fallback
    behaviour (retry, refuse, ask for clarification).

    When a ``session`` is passed and ``context.tenant_id`` is set, the call is
    gated by ``TenantAIPolicy``: if the model is not on the tenant's
    allow-list for the purpose, the call is blocked *before* any tokens are
    spent. Callers that omit ``session`` (tests, CLI) are not gated — the
    DEFAULT_POLICY allows everything anyway, so the effect is identical when
    no restriction has been configured.
    """
    if session is not None and context.tenant_id:
        from caseops_api.services.tenant_ai_policy import (
            is_model_allowed,
            resolve_tenant_policy,
        )

        policy = resolve_tenant_policy(session, company_id=context.tenant_id)
        if not is_model_allowed(
            policy, purpose=context.purpose, model=provider.model
        ):
            from fastapi import HTTPException
            from fastapi import status as _status

            raise HTTPException(
                status_code=_status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Model {provider.model!r} is blocked by the tenant AI "
                    f"policy for purpose {context.purpose!r}. Contact your "
                    "workspace admin to adjust the policy."
                ),
            )
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
        payload = _tolerant_json_loads(_strip_code_fence(completion.text))
    except json.JSONDecodeError as exc:
        # Include a prefix of the raw model output so prod 502s are
        # debuggable without a redeploy-to-log cycle. ``completion.text``
        # is bounded by ``max_tokens`` so a 1000-char prefix is always
        # safe to surface.
        preview = (completion.text or "").strip()[:1000]
        logger.warning(
            "generate_structured JSON decode failed (%s:%s). raw preview: %s",
            completion.provider,
            completion.model,
            preview,
        )
        raise LLMResponseFormatError(
            f"{completion.provider}:{completion.model} did not return valid "
            f"JSON. raw[:500]={preview[:500]!r}",
        ) from exc
    try:
        validated = schema.model_validate(payload)
    except ValidationError as exc:
        # Same treatment for schema-validation failures — we still parsed
        # SOMETHING, so surface what the keys looked like so the fix is
        # targeted.
        preview_keys: Any = payload
        if isinstance(payload, dict):
            preview_keys = list(payload.keys())
        logger.warning(
            "generate_structured schema mismatch (%s:%s). payload keys: %s",
            completion.provider,
            completion.model,
            preview_keys,
        )
        raise LLMResponseFormatError(
            f"{completion.provider}:{completion.model} returned JSON that did "
            f"not match the expected schema. keys={preview_keys!r}",
        ) from exc
    return validated, completion


_TRAILING_COMMA_RE = __import__("re").compile(r",(\s*[}\]])")


def _tolerant_json_loads(text: str) -> Any:
    """Load JSON emitted by an LLM, tolerating the three common
    failure modes:

    1. **Trailing commas** inside objects / arrays — Sonnet emits them
       on long structured outputs ~4 % of the time.
    2. **Preamble / postamble text** — the model writes "Here is the
       JSON you asked for:" before the block, or commentary after.
       BUG-005: prod recommendations endpoint 502'd because both
       Sonnet AND Haiku were sometimes wrapping the payload in
       narration. Extract the first balanced ``{...}`` (or
       ``[...]``) block and retry.
    3. **Escaped single quotes / smart quotes** — not handled here;
       would need a proper tokenizer. Callers that still fail after
       this pass should bump to a bigger model or simplify the
       schema.

    Order: raw → trailing-comma → balanced-block → balanced-block
    + trailing-comma. Re-raise the *first* JSONDecodeError so the
    caller sees the real error, not the post-rewrite one."""
    original_error: json.JSONDecodeError | None = None

    attempts = [
        lambda s: s,
        lambda s: _TRAILING_COMMA_RE.sub(r"\1", s),
    ]
    for transform in attempts:
        try:
            return json.loads(transform(text))
        except json.JSONDecodeError as exc:
            if original_error is None:
                original_error = exc

    # Preamble / postamble extraction — find the first balanced JSON
    # block and try again. Handles "Here is the JSON: {...}" and
    # "{...}\n\nNote: I've included X" equally.
    extracted = _extract_first_json_block(text)
    if extracted is not None and extracted != text:
        for transform in attempts:
            try:
                return json.loads(transform(extracted))
            except json.JSONDecodeError:
                continue

    assert original_error is not None
    raise original_error


def _extract_first_json_block(text: str) -> str | None:
    """Return the first balanced ``{...}`` or ``[...]`` block in
    ``text``, or None if no obvious JSON structure is present.

    Walks the text respecting quoted strings (so a ``}`` inside
    ``"foo}bar"`` does not close the outer brace).
    """
    # Find the earlier of '{' or '['.
    start_obj = text.find("{")
    start_arr = text.find("[")
    candidates = [s for s in (start_obj, start_arr) if s >= 0]
    if not candidates:
        return None
    start = min(candidates)
    opener = text[start]
    closer = "}" if opener == "{" else "]"

    depth = 0
    in_str = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


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
    "LLMQuotaExhaustedError",
    "LLMResponseFormatError",
    "MockProvider",
    "ModelRunWriter",
    "OpenAIProvider",
    "PURPOSE_DRAFTING",
    "PURPOSE_EVAL",
    "PURPOSE_HEARING_PACK",
    "PURPOSE_METADATA_EXTRACT",
    "PURPOSE_RECOMMENDATIONS",
    "Purpose",
    "build_provider",
    "generate_structured",
    "max_tokens_for_purpose",
]
