"""Sprint R4 — per-step Haiku preview for the drafting stepper.

The stepper collects facts field-by-field; after each step group
(``facts``, ``grounds``, ``relief``, etc) the web POSTs what's been
filled so far to ``/api/drafting/preview`` and receives a partial
draft for immediate feedback.

Design notes:

- Uses Haiku (``purpose="metadata_extract"`` provider) — fast + cheap.
  A full-generation step still goes through the drafting service
  with Sonnet / Opus; this is a preview, not the final draft.
- Accepts partial ``facts`` — the Pydantic facts model's fields are
  declared as required, but the preview should not gate on that.
- Returns plain text, not structured JSON — the preview is rendered
  verbatim; no parsing needed.

EG-006 (2026-04-23) hardening:

- The call now flows through the same tenant-AI-policy gate the
  recommendations / drafting / hearing-pack services apply via
  ``generate_structured``. A tenant whose admin has restricted Haiku
  no longer leaks via the preview path.
- Every successful call writes a ``ModelRun`` row so preview spend is
  auditable next to the rest of AI usage. Failed calls also persist a
  ``ModelRun`` with ``status="error"``.
- Anthropic 402 ("credit balance is too low") triggers a hard cutover
  to OpenAI ``gpt-5.1`` — same pattern as the other AI services.
- The 502 response no longer interpolates the raw exception text into
  ``detail`` (Codex 2026-04-19 finding #6 — "no internal exception
  strings in user-visible errors"). The full traceback is logged; the
  user sees an actionable, redacted message.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from caseops_api.db.models import ModelRun
from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.drafting_prompts import get_prompt_parts
from caseops_api.services.identity import SessionContext
from caseops_api.services.llm import (
    AnthropicProvider,
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMQuotaExhaustedError,
    OpenAIProvider,
    build_provider,
)

logger = logging.getLogger(__name__)

PURPOSE = "drafting_preview"
_PREVIEW_MAX_TOKENS = 900
_PREVIEW_TEMPERATURE = 0.15
_HAIKU_FALLBACK_MODEL = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class DraftPreview:
    template_type: str
    preview_text: str
    step_group: str | None
    model: str
    prompt_tokens: int
    completion_tokens: int


def _haiku_fallback_provider() -> LLMProvider | None:
    from caseops_api.core.settings import get_settings

    settings = get_settings()
    if (settings.llm_provider or "").lower() != "anthropic":
        return None
    return AnthropicProvider(
        model=_HAIKU_FALLBACK_MODEL,
        api_key=settings.llm_api_key,
        prompt_cache=bool(getattr(settings, "llm_prompt_cache_enabled", True)),
    )


def _openai_fallback_provider() -> LLMProvider | None:
    from caseops_api.core.settings import get_settings

    settings = get_settings()
    if not getattr(settings, "openai_api_key", None):
        return None
    return OpenAIProvider(
        model=getattr(settings, "openai_fallback_model", "gpt-5.1"),
        api_key=settings.openai_api_key,
    )


def generate_step_preview(
    *,
    template_type: DraftTemplateType,
    facts: dict,
    step_group: str | None = None,
    provider: LLMProvider | None = None,
    session: Session | None = None,
    context: SessionContext | None = None,
) -> DraftPreview:
    """Emit a short (~400 word) partial draft reflecting ``facts`` so far.

    When ``session`` + ``context`` are supplied (the production path
    from ``/api/drafting/preview``), the call is gated by the tenant
    AI policy and a ``ModelRun`` row is persisted for audit. Tests
    that omit those parameters skip the policy gate and the audit
    write — the original pure-function behaviour is preserved for
    fixtures.
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
    prompt_hash = _prompt_hash(messages)

    # EG-006: gate every preview call by the tenant AI policy. The
    # production routes always pass session + context.company_id so
    # this branch is the live path; tests that omit them skip the
    # check (DEFAULT_POLICY allows everything anyway).
    if session is not None and context is not None and context.company.id:
        from caseops_api.services.tenant_ai_policy import (
            is_model_allowed,
            resolve_tenant_policy,
        )

        policy = resolve_tenant_policy(session, company_id=context.company.id)
        if not is_model_allowed(policy, purpose=PURPOSE, model=llm.model):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Drafting preview model {llm.model!r} is blocked "
                    f"by your workspace AI policy. Ask your workspace "
                    "admin to allow this model for drafting previews."
                ),
            )

    try:
        completion = _invoke_with_cutover(llm, messages)
    except HTTPException:
        # _invoke_with_cutover already raised an actionable, redacted
        # 4xx/5xx — record the failure for audit, then re-raise.
        if session is not None and context is not None:
            _write_model_run(
                session,
                context=context,
                completion=None,
                prompt_hash=prompt_hash,
                model_hint=llm.model,
                provider_hint=getattr(llm, "name", "unknown"),
                status_label="error",
                error="preview_provider_failed",
            )
            session.commit()
        raise

    if session is not None and context is not None:
        _write_model_run(
            session,
            context=context,
            completion=completion,
            prompt_hash=prompt_hash,
            model_hint=completion.model,
            provider_hint=completion.provider,
            status_label="ok",
            error=None,
        )
        session.commit()

    return DraftPreview(
        template_type=template_type.value,
        preview_text=completion.text.strip(),
        step_group=step_group,
        model=completion.model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
    )


def _invoke_with_cutover(
    primary: LLMProvider,
    messages: list[LLMMessage],
) -> LLMCompletion:
    """Run the preview through the configured provider and apply the
    cross-provider cutover ladder used by the rest of the AI services.

    Returns the successful ``LLMCompletion`` or raises ``HTTPException``
    with a redacted, actionable detail. The raw exception is always
    logged at WARN with full repr so we can still debug from prod logs.
    """

    def _run(p: LLMProvider) -> LLMCompletion:
        return p.generate(
            messages=messages,
            temperature=_PREVIEW_TEMPERATURE,
            max_tokens=_PREVIEW_MAX_TOKENS,
        )

    try:
        return _run(primary)
    except LLMQuotaExhaustedError as quota_exc:
        logger.warning(
            "Preview primary %s quota exhausted; cutting over to OpenAI",
            getattr(primary, "model", "<unknown>"),
        )
        return _preview_via_openai(_run, quota_exc)
    except LLMProviderError as exc:
        logger.warning(
            "Preview primary %s failed (%s); trying Haiku fallback",
            getattr(primary, "model", "<unknown>"),
            type(exc).__name__,
        )
        haiku = _haiku_fallback_provider()
        if haiku is None:
            return _preview_via_openai(_run, exc)
        try:
            return _run(haiku)
        except LLMQuotaExhaustedError as quota_exc:
            return _preview_via_openai(_run, quota_exc)
        except LLMProviderError as retry_exc:
            return _preview_via_openai(_run, retry_exc)


def _preview_via_openai(
    run, root_exc: Exception
) -> LLMCompletion:
    """Cross-provider hard cutover. Returns the OpenAI completion or
    raises a redacted 502."""
    openai = _openai_fallback_provider()
    if openai is None:
        # Don't echo the raw exception into ``detail`` — log it and
        # show the user something actionable.
        logger.warning(
            "Preview unavailable, no OpenAI fallback configured. "
            "Underlying error: %r",
            root_exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Drafting preview is temporarily unavailable. Please "
                "retry in a minute, or contact support if this persists."
            ),
        ) from root_exc
    try:
        return run(openai)
    except LLMProviderError as oa_exc:
        logger.warning(
            "Preview OpenAI fallback also failed. Underlying errors: "
            "primary=%r openai=%r",
            root_exc,
            oa_exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Drafting preview is temporarily unavailable. Please "
                "retry in a minute, or contact support if this persists."
            ),
        ) from oa_exc


def _write_model_run(
    session: Session,
    *,
    context: SessionContext,
    completion: LLMCompletion | None,
    prompt_hash: str,
    model_hint: str,
    provider_hint: str,
    status_label: str,
    error: str | None,
) -> ModelRun:
    """Persist a ``ModelRun`` audit row for the preview call. Mirrors
    ``services.drafting._write_model_run`` so the existing audit /
    export pipeline picks the row up automatically."""
    run = ModelRun(
        company_id=context.company.id,
        matter_id=None,  # preview is pre-draft; no matter scope yet
        actor_membership_id=context.membership.id,
        purpose=PURPOSE,
        provider=completion.provider if completion else provider_hint,
        model=completion.model if completion else model_hint,
        prompt_hash=prompt_hash,
        prompt_tokens=completion.prompt_tokens if completion else 0,
        completion_tokens=completion.completion_tokens if completion else 0,
        latency_ms=completion.latency_ms if completion else 0,
        status=status_label,
        error=error,
    )
    session.add(run)
    session.flush()
    return run


def _prompt_hash(messages: list[LLMMessage]) -> str:
    h = hashlib.sha256()
    for m in messages:
        h.update(m.role.encode("utf-8"))
        h.update(b"\x00")
        h.update(m.content.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


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
    "PURPOSE",
    "generate_step_preview",
]
