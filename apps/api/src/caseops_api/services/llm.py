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
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
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
    provider_name = settings.llm_provider.lower()
    model = _resolve_model_for_purpose(settings, purpose)
    if provider_name in {"mock", "noop", "off"}:
        return MockProvider(model=model)
    if not settings.llm_api_key:
        raise LLMProviderError(
            f"CASEOPS_LLM_API_KEY must be set when CASEOPS_LLM_PROVIDER={provider_name!r}.",
        )
    if provider_name == "anthropic":
        return AnthropicProvider(
            model=model or "claude-opus-4-7",
            api_key=settings.llm_api_key,
            prompt_cache=bool(getattr(settings, "llm_prompt_cache_enabled", True)),
        )
    if provider_name == "gemini":
        return GeminiProvider(
            model=model or "gemini-2.5-pro",
            api_key=settings.llm_api_key,
        )
    raise LLMProviderError(
        f"Unknown CASEOPS_LLM_PROVIDER value: {provider_name!r}. "
        "Use 'mock', 'anthropic', or 'gemini'.",
    )


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
