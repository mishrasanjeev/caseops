"""Sprint R4 — per-step Haiku preview for the drafting stepper.

The stepper collects facts field-by-field; after each step group
(``facts``, ``grounds``, ``relief``, etc) the web POSTs what's been
filled so far to ``/api/drafting/preview`` and receives a partial
draft for immediate feedback.

Design notes:

- Uses Haiku (`purpose="metadata_extract"` provider) — fast + cheap.
  A full-generation step still goes through the drafting service
  with Sonnet / Opus; this is a preview, not the final draft.
- Accepts partial ``facts`` — the Pydantic facts model's fields are
  declared as required, but the preview should not gate on that.
  We wrap the input in a ``dict`` + JSON-serialise so the LLM gets
  the current state regardless of completeness.
- Returns plain text, not structured JSON — the preview is rendered
  verbatim; no parsing needed.
- Budget: ~400 tokens out → ~$0.002/request. Cheap enough that the
  stepper can call on every completed step.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import HTTPException, status

from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.drafting_prompts import get_prompt_parts
from caseops_api.services.llm import (
    LLMMessage,
    LLMProvider,
    build_provider,
)

_PREVIEW_MAX_TOKENS = 900
_PREVIEW_TEMPERATURE = 0.15


@dataclass(frozen=True)
class DraftPreview:
    template_type: str
    preview_text: str
    step_group: str | None
    model: str
    prompt_tokens: int
    completion_tokens: int


def generate_step_preview(
    *,
    template_type: DraftTemplateType,
    facts: dict,
    step_group: str | None = None,
    provider: LLMProvider | None = None,
) -> DraftPreview:
    """Emit a short (~400 word) partial draft reflecting ``facts`` so far.

    Callers should treat the response as illustrative — it's driven
    by whatever fields the user has filled. A still-empty required
    field appears as "[not yet specified]" rather than a guess.
    """
    parts = get_prompt_parts(template_type)

    llm = provider or _default_preview_provider()

    preview_instruction = (
        "Produce a short partial draft (300-500 words) reflecting the "
        "facts provided below. For any field the user has not filled, "
        "write the literal placeholder '[not yet specified]' rather "
        "than inventing a plausible value.\n\n"
        "If the user indicates a step group, focus the preview on that "
        "section of the pleading. Do NOT produce a complete draft — the "
        "stepper issues the full draft separately.\n"
    )
    if step_group:
        preview_instruction += f"\nCurrent step group: {step_group}\n"

    user_msg = (
        preview_instruction
        + "\nFacts so far (JSON):\n"
        + json.dumps(facts, ensure_ascii=False, indent=2, default=str)
    )

    messages = [
        LLMMessage(role="system", content=parts.system),
        LLMMessage(role="user", content=user_msg),
    ]

    try:
        completion = llm.generate(
            messages=messages,
            temperature=_PREVIEW_TEMPERATURE,
            max_tokens=_PREVIEW_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Drafting preview failed: {exc}",
        ) from exc

    return DraftPreview(
        template_type=template_type.value,
        preview_text=completion.text.strip(),
        step_group=step_group,
        model=completion.model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
    )


def _default_preview_provider() -> LLMProvider:
    """Pick Haiku by default. Callers can override by passing a
    ``provider`` to ``generate_step_preview`` — useful in tests."""
    try:
        return build_provider(purpose="metadata_extract")
    except Exception:  # noqa: BLE001
        # Fall back to the default purpose if the metadata_extract
        # slot isn't configured.
        return build_provider(purpose="drafting")


__all__ = [
    "DraftPreview",
    "generate_step_preview",
]
