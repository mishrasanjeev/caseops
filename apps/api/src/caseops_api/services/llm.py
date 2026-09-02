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
from typing import Any, NoReturn

from pydantic import BaseModel, ValidationError

from caseops_api.core.settings import get_settings
from caseops_api.services.llm_types import (
    LLMCallContext,
    LLMCompletion,
    LLMDailyCapReachedError,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMQuotaExhaustedError,
    LLMResponseFormatError,
    ModelRunWriter,
)

logger = logging.getLogger(__name__)


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
        if "untrusted_authority_sources:" in lowered and "issue_summary" in lowered:
            text = _mock_intelligent_review_response(joined)
        elif "workspace_assistant_qa" in lowered:
            text = _mock_workspace_assistant_response(joined)
        elif "matter_file_qa" in lowered:
            text = _mock_matter_file_qa_response(joined)
        elif "hearing pack" in lowered or "hearing_pack" in lowered:
            text = _mock_hearing_pack_response(joined)
        elif "drafting a legal document" in lowered or "draft title:" in lowered:
            text = _mock_draft_response(joined)
        elif "produce a litigation strategy" in lowered and "forum_sequence" in lowered:
            text = _mock_litigation_strategy_response(joined)
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


def _estimate_call_tokens(messages: list[LLMMessage], max_tokens: int) -> int:
    prompt_estimate = sum(_rough_token_estimate(message.content) for message in messages)
    return max(1, prompt_estimate + max(max_tokens, 0))


def _mock_plain_response(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    return f"mock-ack::{digest}"


def _mock_intelligent_review_response(prompt: str) -> str:
    context_raw = _extract_between(
        prompt,
        "CONTEXT_MANIFEST:\n",
        "\n\nUNTRUSTED_AUTHORITY_SOURCES:",
    )
    sources_raw = _extract_between(
        prompt,
        "UNTRUSTED_AUTHORITY_SOURCES:\n",
        "\n\nReturn this schema:",
    )
    try:
        context = json.loads(context_raw or "{}")
        sources = json.loads(sources_raw or "[]")
    except json.JSONDecodeError:
        context, sources = {}, []
    if not isinstance(context, dict):
        context = {}
    if not isinstance(sources, list):
        sources = []

    authorities: list[dict[str, Any]] = []
    source_ids: list[str] = []
    for index, source in enumerate(sources[:25]):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("authority_document_id") or "").strip()
        excerpt = " ".join(str(source.get("untrusted_source_excerpt") or "").split())
        if not source_id or not excerpt:
            continue
        source_ids.append(source_id)
        authorities.append(
            {
                "authority_document_id": source_id,
                "disposition": "supporting" if index == 0 else "contrary",
                "passage": excerpt[:600],
                "relevance": (
                    "Supports the issue on the supplied frozen record."
                    if index == 0
                    else "Provides contrary material that the lawyer should distinguish."
                ),
                "treatment": "Review against the current facts and procedural posture.",
            }
        )

    facts = context.get("facts", [])
    relevant_facts = [
        f"{item.get('label')}: {item.get('value')}"
        for item in facts
        if isinstance(item, dict) and item.get("label") and item.get("value")
    ][:50]
    primary_ids = source_ids[:1]
    all_ids = source_ids[:10]
    payload = {
        "issue_summary": str(context.get("issue") or "Review the stated legal issue."),
        "relevant_facts": relevant_facts,
        "applicable_provisions": (
            [
                {
                    "text": "Apply the governing provisions reflected in the selected authority.",
                    "authority_document_ids": primary_ids,
                }
            ]
            if primary_ids
            else []
        ),
        "authorities": authorities,
        "factual_analogies": (
            [
                {
                    "text": (
                        "Compare the supplied facts with the records described in "
                        "the selected authorities."
                    ),
                    "authority_document_ids": all_ids,
                }
            ]
            if all_ids
            else []
        ),
        "gaps": ["Confirm current law, registry status, and the complete evidentiary record."],
        "lawyer_checks": ["Open each source and verify the passage before reliance."],
        "unresolved_contradictions": [],
    }
    return json.dumps(payload, separators=(",", ":"))


def _mock_workspace_assistant_response(prompt: str) -> str:
    sources: list[tuple[str, str, str]] = []
    source_id: str | None = None
    label = "Workspace record"
    text_lines: list[str] = []
    collecting = False
    for line in prompt.splitlines():
        if line.startswith("SOURCE_ID:"):
            source_id = line.split(":", 1)[1].strip()
        elif line.startswith("LABEL:"):
            label = line.split(":", 1)[1].strip() or label
        elif line == "TEXT:":
            collecting = True
            text_lines = []
        elif line == "END_SOURCE":
            if source_id:
                sources.append((source_id, label, " ".join(" ".join(text_lines).split())))
            source_id = None
            label = "Workspace record"
            collecting = False
            text_lines = []
        elif collecting:
            text_lines.append(line)
    if not sources:
        return json.dumps(
            {
                "status": "abstained",
                "answer": "I do not have enough permitted workspace evidence to answer that.",
                "confidence": "insufficient",
                "used_source_ids": [],
                "suggested_searches": ["Search the workspace by matter, mark, or identifier"],
            },
            separators=(",", ":"),
        )
    first_id, first_label, first_text = sources[0]
    # The deterministic provider must exercise the same untrusted-source
    # boundary as a real provider; echoing source instructions makes local E2E
    # safety evidence meaningless and can teach fixtures the wrong contract.
    safe_text = _mock_remove_document_instructions(first_text)
    preview = " ".join((safe_text or first_text).split()[:55])
    return json.dumps(
        {
            "status": "answered",
            "answer": f"Based on {first_label}: {preview}",
            "confidence": "medium",
            "used_source_ids": [source[0] for source in sources[:3]],
            "suggested_searches": [],
        },
        separators=(",", ":"),
    )


def _mock_matter_file_qa_response(prompt: str) -> str:
    source_ids: list[str] = []
    source_texts: list[str] = []
    current_source_id: str | None = None
    collecting_text = False
    text_lines: list[str] = []
    analysis_language = "en"
    for line in prompt.splitlines():
        if line.startswith("ANALYSIS_LANGUAGE:"):
            analysis_language = line.split(":", 1)[1].strip().split(" ", 1)[0] or "en"
            continue
        if line.startswith("SOURCE_ID:"):
            current_source_id = line.split(":", 1)[1].strip()
            continue
        if line == "TEXT:":
            collecting_text = True
            text_lines = []
            continue
        if line == "END_SOURCE":
            collecting_text = False
            if current_source_id:
                source_ids.append(current_source_id)
                source_texts.append(" ".join(" ".join(text_lines).split()))
            current_source_id = None
            text_lines = []
            continue
        if collecting_text:
            text_lines.append(line)
    if not source_ids:
        return json.dumps(
            {
                "status": "insufficient_evidence",
                "answer": "",
                "confidence": "insufficient",
                "source_ids": [],
                "limitations": ["No uploaded matter document chunks were provided."],
            },
            separators=(",", ":"),
        )
    safe_texts = [_mock_remove_document_instructions(text) for text in source_texts]
    preview = " ".join((safe_texts[0] or source_texts[0]).split()[:45])
    payload = {
        "status": "answered",
        "answer": f"The uploaded matter file states: {preview}",
        "confidence": "medium",
        "source_ids": source_ids[:2],
        "limitations": ["Only uploaded matter document chunks were used."],
    }
    if analysis_language != "en":
        payload["local_language_analysis"] = f"Local-language aid ({analysis_language}): {preview}"
    return json.dumps(payload, separators=(",", ":"))


def _mock_remove_document_instructions(text: str) -> str:
    blocked = (
        "ignore previous instructions",
        "do not cite sources",
        "reveal all documents",
        "guaranteed to win",
        "will win",
    )
    parts = []
    for sentence in __import__("re").split(r"(?<=[.!?])\s+", text):
        lowered = sentence.lower()
        if any(marker in lowered for marker in blocked):
            continue
        parts.append(sentence)
    return " ".join(parts).strip()


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
                "label": "Proceed under the available precedent"
                + (f" ({primary})" if primary else ""),
                "rationale": (
                    f"The retrieved authority supports this route: {primary_fragment}"
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
            f"Proceed under the available precedent{' (' + primary + ')' if primary else ''}"
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


def _mock_litigation_strategy_response(prompt: str) -> str:
    """Mirror the strict litigation-strategy contract for offline acceptance.

    The general recommendation fixture predates the nested strategy payload.
    Keeping this purpose-specific emitter aligned with the production schema
    ensures Docker and CI exercise validation rather than failing on fixture
    drift before the workflow itself is reached.
    """
    forum = (_extract_between(prompt, "FORUM:", "\n") or "unknown").strip()
    title = (_extract_between(prompt, "MATTER_TITLE:", "\n") or "Unknown matter").strip()
    authorities = _extract_citations(prompt)
    tagged_authorities = [f"[{index}] {citation}" for index, citation in enumerate(authorities, 1)]
    primary = tagged_authorities[:1]
    confidence = "medium" if primary else "low"
    forum_level = (
        "supreme_court"
        if "supreme" in forum
        else "lower_court"
        if forum in {"district_court", "lower_court"}
        else "tribunal"
        if "tribunal" in forum
        else "high_court_single_bench"
        if "high_court" in forum
        else "other"
    )
    payload: dict[str, Any] = {
        "title": f"Litigation strategy for {title}",
        "current_posture": (
            f"The matter is recorded at the {forum or 'unknown'} stage. "
            "The available record must be checked before any filing."
        ),
        "recommended_route": {
            "label": "Review the present record and prepare the next procedural filing",
            "rationale": (
                "The available authority supports a record-led procedural review."
                if primary
                else "No retrieved authority supports a more specific route."
            ),
            "confidence": confidence,
            "availability": "available" if primary else "uncertain",
            "supporting_citations": primary,
            "risk_notes": "Confirm limitation, maintainability, and the latest order first.",
        },
        "alternative_routes": [],
        "forum_sequence": [
            {
                "forum_level": forum_level,
                "stage_label": "Current procedural stage",
                "forum_name": None,
                "rationale": "Use the recorded forum and verify jurisdiction from the case file.",
                "statutory_basis": [],
                "expected_filings": ["procedural filing after lawyer review"],
                "supporting_citations": primary,
            }
        ],
        "limitation_flags": [],
        "required_documents": ["Latest order", "Complete pleadings", "Limitation chronology"],
        "missing_facts": ["Latest operative order", "Confirmed limitation start date"],
        "risks": [
            {
                "label": "Incomplete procedural record",
                "description": (
                    "The next filing cannot be settled until the latest order is checked."
                ),
                "severity": "medium",
                "mitigation": "Obtain and review the certified record.",
                "supporting_citations": [],
            }
        ],
        "next_best_actions": [
            {
                "action": "Review the latest order and calculate limitation.",
                "supporting_citations": primary,
            }
        ],
        "rationale": "This route keeps the recommendation within the available record.",
        "confidence": confidence,
        "next_action": "Lawyer review before any external filing.",
        "assumptions": ["The recorded forum and matter stage are current."],
        "disclaimer": (
            "Strategy outputs are citation-grounded but require lawyer review before any filing. "
            "CaseOps does not promise outcomes."
        ),
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
        f"The Hon'ble Court's ruling in [{c}] applies to the facts here." for c in cite_list
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
            f"Draft generated for {title.strip()}; {len(cite_list)} authorities cited."
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
    """Pick identifiers that look like case references we embedded.

    Supports two prompt formats:
      Legacy:  ``- CITATION: <text>``
      v2 (BUG-024 fix 2026-04-27): ``[N] CITATION: <text>``
    Both formats end with the citation text after the ``CITATION:`` token.
    """
    citations: list[str] = []
    import re as _re

    for line in text.splitlines():
        stripped = line.strip()
        # Match either "- CITATION:" or "[N] CITATION:" prefix.
        m = _re.match(r"^(?:-|\[\d+\])\s*CITATION:\s*(.+)$", stripped)
        if m:
            value = m.group(1).strip()
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
    _NO_TEMPERATURE_PREFIXES: tuple[str, ...] = ("claude-opus-4-7",)

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

    # Reasoning-class OpenAI models bill hidden reasoning tokens against
    # ``max_completion_tokens``. Even with ``reasoning_effort=low`` the
    # legal-strategy prompts emit ~2-4K reasoning tokens before any visible
    # content. If the operator-configured ``max_tokens`` is below this
    # floor, the model burns the whole budget on reasoning and returns an
    # EMPTY content string with status=ok — the parser then raises
    # LLMResponseFormatError on raw=''. PR #7 / 2026-05-03 prod incident:
    # default 4096 was too low for the strategy planner; bumped to 16384
    # via env override. Codify the floor so a future cutover to a reasoning
    # model on ANY purpose can't repro this trap.
    _REASONING_PREFIXES: tuple[str, ...] = ("gpt-5", "o1", "o3")
    _REASONING_MIN_COMPLETION_TOKENS: int = 8192

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
        self._openai = openai
        self.model = model

    def _model_rejects_temperature(self) -> bool:
        name = (self.model or "").lower()
        return any(name.startswith(p) for p in self._NO_TEMPERATURE_PREFIXES)

    def _is_reasoning_model(self) -> bool:
        name = (self.model or "").lower()
        return any(name.startswith(p) for p in self._REASONING_PREFIXES)

    def _effective_max_completion_tokens(self, requested: int) -> int:
        """Floor for reasoning-class models. See ``_REASONING_MIN_COMPLETION_TOKENS``
        for the rationale (PR #7 / 2026-05-03 prod incident)."""
        if self._is_reasoning_model() and requested < self._REASONING_MIN_COMPLETION_TOKENS:
            logger.warning(
                "openai: bumping max_completion_tokens %d -> %d for reasoning "
                "model %s; the requested cap would have starved visible content "
                "after reasoning_effort tokens. Set "
                "CASEOPS_LLM_MAX_OUTPUT_TOKENS_<PURPOSE> >= %d in your env to "
                "silence this warning.",
                requested,
                self._REASONING_MIN_COMPLETION_TOKENS,
                self.model,
                self._REASONING_MIN_COMPLETION_TOKENS,
            )
            return self._REASONING_MIN_COMPLETION_TOKENS
        return requested

    def _request_kwargs(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "max_completion_tokens": self._effective_max_completion_tokens(max_tokens),
        }
        if not self._model_rejects_temperature():
            kwargs["temperature"] = temperature
        if self._is_reasoning_model():
            kwargs["reasoning_effort"] = "low"
        return kwargs

    def _completion_from_response(
        self,
        response: Any,
        *,
        started: float,
        text_override: str | None = None,
    ) -> LLMCompletion:
        choice = response.choices[0] if getattr(response, "choices", None) else None
        text = ""
        if choice is not None and getattr(choice, "message", None) is not None:
            text = getattr(choice.message, "content", "") or ""
        if text_override is not None:
            text = text_override
        usage = getattr(response, "usage", None)
        return LLMCompletion(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
            raw=response,
        )

    def _raise_call_error(self, exc: Exception) -> NoReturn:
        if _is_quota_exhausted(exc):
            raise LLMQuotaExhaustedError(
                f"OpenAI quota exhausted: {exc}",
            ) from exc
        raise LLMProviderError(f"OpenAI call failed: {exc}") from exc

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        kwargs = self._request_kwargs(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # gpt-5.x reasoning models add significant latency at the default
        # ``reasoning_effort`` ("medium" → 30-90s of thinking even for
        # short structured-output tasks). CaseOps recommendations / drafts
        # / hearing-packs are prompt-following structured-output, not
        # multi-step reasoning, so cap the thinking at "low" — keeps
        # quality on legal Q&A while bringing latency back under the
        # per-purpose Cloud Run budget. 2026-04-30: surfaced when the
        # stress-matter probe (BUG-024 grounding) hit a 110s client
        # timeout post-deploy.
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            self._raise_call_error(exc)
        return self._completion_from_response(response, started=started)

    def generate_structured[T: BaseModel](
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMCompletion:
        """Use OpenAI's strict Pydantic response contract.

        A successful HTTP response is not sufficient evidence that the model
        produced usable JSON.  ``chat.completions.parse`` asks the provider to
        enforce the supplied schema and returns a parsed Pydantic value.  We
        serialize that validated value for the provider-neutral validation and
        audit path below, so prose or truncated JSON can never masquerade as a
        provider outage.
        """

        kwargs = self._request_kwargs(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.parse(
                **kwargs,
                response_format=schema,
            )
        except (
            self._openai.LengthFinishReasonError,
            self._openai.ContentFilterFinishReasonError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise LLMResponseFormatError(
                f"OpenAI:{self.model} did not complete the required structured response."
            ) from exc
        except Exception as exc:
            self._raise_call_error(exc)

        choice = response.choices[0] if getattr(response, "choices", None) else None
        message = getattr(choice, "message", None)
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            refusal = bool(getattr(message, "refusal", None))
            detail = "refused" if refusal else "contained no parsed value"
            raise LLMResponseFormatError(f"OpenAI:{self.model} structured response {detail}.")
        try:
            validated = schema.model_validate(parsed)
        except ValidationError as exc:
            raise LLMResponseFormatError(
                f"OpenAI:{self.model} returned a parsed value outside the required schema."
            ) from exc
        return self._completion_from_response(
            response,
            started=started,
            text_override=validated.model_dump_json(),
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
        {"role": m.role, "content": m.content} for m in messages if m.role in {"user", "assistant"}
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
PURPOSE_ASSISTANT = "assistant"
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
        PURPOSE_ASSISTANT: getattr(settings, "llm_model_assistant", None),
        PURPOSE_RECOMMENDATIONS: getattr(settings, "llm_model_recommendations", None),
        PURPOSE_HEARING_PACK: getattr(settings, "llm_model_hearing_pack", None),
        PURPOSE_METADATA_EXTRACT: getattr(settings, "llm_model_metadata_extract", None),
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
    # BUG-015 / Ram 2026-09-02 BUG-004: an SDK timeout is per attempt,
    # not an end-to-end request budget. Production recommendations run
    # behind a 120-second Cloud Run deadline. A 90-second OpenAI attempt
    # plus one automatic SDK retry therefore reached the platform 504
    # before CaseOps could return a controlled provider error. Keep the
    # interactive recommendation call to one attempt of at most 100 seconds,
    # leaving 20 seconds for bounded retrieval, verification, persistence,
    # and response serialization. Other purposes retain their independently
    # measured budgets.
    per_purpose_timeout: dict[str, float] = {
        PURPOSE_ASSISTANT: 60.0,
        PURPOSE_RECOMMENDATIONS: 100.0,
        PURPOSE_HEARING_PACK: 90.0,
        PURPOSE_METADATA_EXTRACT: 60.0,
        # Drafting can legitimately need longer responses (full appeal
        # memorandum, 8K output tokens) — keep its budget generous.
        PURPOSE_DRAFTING: 120.0,
        PURPOSE_EVAL: 60.0,
    }
    per_purpose_retries: dict[str, int] = {
        PURPOSE_ASSISTANT: 1,
        PURPOSE_RECOMMENDATIONS: 0,
        PURPOSE_HEARING_PACK: 1,
        PURPOSE_METADATA_EXTRACT: 1,
        PURPOSE_DRAFTING: 1,
        PURPOSE_EVAL: 2,
    }
    timeout_for_purpose = per_purpose_timeout.get(purpose or "", 60.0)
    retries_for_purpose = per_purpose_retries.get(purpose or "", 2)
    # The corpus metadata job can fan out hundreds of thousands of calls.
    # Retrying a paid-quota rejection inside every OpenAI SDK call delays the
    # worker's process-wide stop signal and multiplies useless requests.  Let
    # the job observe the first response immediately; ordinary transient
    # errors remain per-document failures and can be retried by a later run.
    if provider_name == "openai" and purpose == PURPOSE_METADATA_EXTRACT:
        retries_for_purpose = 0
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
            timeout_seconds=timeout_for_purpose,
            max_retries=retries_for_purpose,
        )
    raise LLMProviderError(
        f"Unknown CASEOPS_LLM_PROVIDER value: {provider_name!r}. "
        "Use 'mock', 'anthropic', 'openai', or 'gemini'.",
    )


_QUOTA_EXHAUSTED_MARKERS = (
    "credit balance is too low",
    "credit_balance_exhausted",
    "insufficient_quota",
    "no credits remaining",
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
    if purpose == PURPOSE_ASSISTANT:
        return getattr(settings, "llm_max_output_tokens_assistant", 2048)
    if purpose == PURPOSE_RECOMMENDATIONS:
        return getattr(settings, "llm_max_output_tokens_recommendations", 4096)
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
    release_session_before_provider: bool = False,
) -> tuple[T, LLMCompletion]:
    """Run the provider and validate its output as ``schema``.

    Providers with a native structured-response contract receive ``schema``
    directly; other providers are expected to follow the caller's JSON prompt.
    Both paths are validated here. A ``LLMResponseFormatError`` is raised if
    validation fails; the caller owns bounded fallback behaviour.

    When a ``session`` is passed and ``context.tenant_id`` is set, the call is
    gated by ``TenantAIPolicy``: if the model is not on the tenant's
    allow-list for the purpose, the call is blocked *before* any tokens are
    spent. Callers that omit ``session`` (tests, CLI) are not gated — the
    DEFAULT_POLICY allows everything anyway, so the effect is identical when
    no restriction has been configured. Callers may opt into
    ``release_session_before_provider`` after completing all of their own
    read-only retrieval. That closes the transaction before network latency;
    the session is reusable and billing starts a fresh transaction only after
    a schema-valid response. The caller must revalidate mutable source state
    before persisting the result.
    """
    estimated_billing_credits = 0
    if session is not None and context.tenant_id:
        from caseops_api.services.tenant_ai_policy import (
            is_model_allowed,
            resolve_tenant_policy,
        )

        policy = resolve_tenant_policy(session, company_id=context.tenant_id)
        if not is_model_allowed(policy, purpose=context.purpose, model=provider.model):
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
        from caseops_api.services.ai_token_governance import (
            assert_ai_token_quota_allows_call,
        )

        assert_ai_token_quota_allows_call(
            session,
            company_id=context.tenant_id,
            actor_membership_id=context.actor_membership_id,
            matter_id=context.matter_id,
            purpose=context.purpose,
            provider=provider.name,
            model=provider.model,
            estimated_tokens=_estimate_call_tokens(messages, max_tokens),
        )
        from caseops_api.services.saas_billing import (
            assert_ai_credits_available,
            estimate_ai_credits_for_call,
        )

        estimated_billing_credits = estimate_ai_credits_for_call(
            purpose=context.purpose,
            prompt_tokens=sum(_rough_token_estimate(message.content) for message in messages),
            completion_tokens=max_tokens,
        )
        assert_ai_credits_available(
            session,
            company_id=context.tenant_id,
            estimated_credits=estimated_billing_credits,
        )
    if release_session_before_provider and session is not None:
        # This boundary is allowed to discard only a read transaction.  A
        # caller that staged ORM writes must choose and document its own commit
        # boundary; silently rolling those writes back here would corrupt the
        # surrounding workflow.  The check also makes the opt-in useful for
        # system/background calls whose context intentionally has no tenant ID.
        if session.new or session.dirty or session.deleted:
            raise RuntimeError(
                "Cannot release the database session before an LLM provider "
                "call while ORM writes are pending."
            )
        # Preflight is intentionally read-only on the success path. Do not
        # leave its transaction open across a provider deadline: SQLite can
        # otherwise retain a reader that delays a writer, while PostgreSQL can
        # terminate an idle transaction and retains every acquired row lock.
        session.rollback()
    native_generate = getattr(provider, "generate_structured", None)
    if callable(native_generate):
        completion = native_generate(
            messages=messages,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
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
        # DATA-GOV-15: the previous form logged a 1000-char prefix of the raw
        # model output, justified on the grounds that ``max_tokens`` bounds its
        # LENGTH. Length is not the concern - this model writes draft legal text
        # about client matters, so a bounded prefix is a bounded privilege leak.
        # What actually diagnoses a decode failure is the SHAPE of the response,
        # which is reported here instead: enough to tell "model returned prose",
        # "output truncated" and "fence not stripped" apart without shipping a
        # word of the content.
        shape = _response_shape(completion.text)
        logger.warning(
            "generate_structured JSON decode failed (%s:%s). %s decode_error=%s",
            completion.provider,
            completion.model,
            shape,
            f"line {exc.lineno} col {exc.colno}",
        )
        raise LLMResponseFormatError(
            f"{completion.provider}:{completion.model} did not return valid "
            f"JSON. {shape} decode_error=line {exc.lineno} col {exc.colno}",
        ) from exc
    try:
        validated = schema.model_validate(payload)
    except ValidationError as exc:
        # Surface the exact pydantic field violations — listing top-level
        # keys alone (as the prior error did) was misleading because the
        # most common failure mode is a nested constraint (e.g.
        # options[i].rationale exceeding max_length, or options being
        # empty). Show first 5 errors with field path + message so prod
        # 502s point at the actual fix.
        violations = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(p) for p in err.get("loc", ()))
            violations.append(f"{loc}: {err.get('msg', err.get('type', '?'))}")
        preview_keys: Any = payload
        if isinstance(payload, dict):
            preview_keys = list(payload.keys())
        # Field violations and payload keys are the diagnosis; the raw body is
        # not, and it is the part that carries client content.
        logger.warning(
            "generate_structured schema mismatch (%s:%s). violations=%s payload_keys=%s %s",
            completion.provider,
            completion.model,
            violations,
            preview_keys,
            _response_shape(completion.text),
        )
        raise LLMResponseFormatError(
            f"{completion.provider}:{completion.model} returned JSON that did "
            f"not match the expected schema. violations={violations} "
            f"keys={preview_keys!r}",
        ) from exc
    if session is not None and context.tenant_id and estimated_billing_credits > 0:
        from caseops_api.services.saas_billing import (
            debit_ai_credits,
            estimate_ai_credits_for_call,
        )

        debit_ai_credits(
            session,
            company_id=context.tenant_id,
            actor_membership_id=context.actor_membership_id,
            matter_id=context.matter_id,
            purpose=context.purpose,
            credits=estimate_ai_credits_for_call(
                purpose=context.purpose,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
            ),
            source_object_type="llm_completion",
            source_object_id=hashlib.sha256(completion.text.encode("utf-8")).hexdigest()[:32],
        )
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


def _response_shape(text: str | None) -> str:
    """Describe a model response structurally, without emitting its content.

    Distinguishes the failure modes that matter operationally - prose instead of
    JSON, truncation mid-object, an unstripped code fence - using only the length,
    the delimiters and the character classes present.
    """
    raw = (text or "").strip()
    if not raw:
        return "shape=empty len=0"
    fenced = raw.startswith("```")
    body = raw
    opener = body[:1]
    closer = body[-1:]
    balanced = body.count("{") == body.count("}") and body.count("[") == body.count("]")
    return (
        f"shape=len:{len(raw)} opens:{opener!r} closes:{closer!r} "
        f"fenced:{fenced} balanced:{balanced}"
    )


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
    "LLMDailyCapReachedError",
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
