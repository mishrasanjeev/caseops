"""Bounded availability routing, never a financial or legal-safety bypass.

Recommendations keep their own plan (source revalidation before the fallback
and the 100-second service budget) on top of the general OpenAI availability
fallback settings in ``llm.build_gemini_fallback``. A healthy primary behaves
exactly as with the fallback switched off: it runs on its normal provider and
timeout, with no plan deadline, revalidation or lineage requirement.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.core.settings import get_settings
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import (
    MIN_FALLBACK_SECONDS,
    build_gemini_fallback,
    fallback_deadline,
    log_fallback_failure,
    provider_deadline,
    provider_time_remaining,
    with_fallback_refusal,
)
from caseops_api.services.llm_types import (
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMQuotaExhaustedError,
    LLMResponseFormatError,
    LLMTransientProviderError,
)

logger = logging.getLogger(__name__)

_PURPOSE = "recommendations"


def recommendation_fallback_enabled() -> bool:
    settings = get_settings()
    return (
        settings.llm_fallback_enabled
        and settings.llm_provider.lower() == "openai"
        and not paid_providers_blocked_for_request()
    )


def build_recommendation_fallback(*, timeout_seconds: float) -> LLMProvider:
    if not recommendation_fallback_enabled():
        raise AiMoneyBudgetError("Recommendation fallback is not enabled for this request.")
    return build_gemini_fallback(timeout_seconds=timeout_seconds)


class RecommendationFallbackPlan:
    """One Gemini attempt after a primary quota/availability failure.

    ``primary_factory(None)`` returns the normal primary provider, used as-is.
    The fallback may only use time left inside the 100-second service budget
    (from ``started_at``) and the HTTP request deadline, and only when at least
    ``min_fallback_seconds`` remain, the sources are revalidatable
    (``eligible``) and the tenant policy allows the fallback model
    (``fallback_permitted``). ``revalidate`` reloads current access and source
    state and releases its read transaction before any credentials are fetched.
    """

    def __init__(
        self,
        *,
        started_at: float,
        primary_factory: Callable[[float | None], LLMProvider],
        revalidate: Callable[[], None],
        fallback_factory: Callable[[float], LLMProvider] | None = None,
        eligible: Callable[[], bool] = lambda: True,
        fallback_permitted: Callable[[str], bool] = lambda model: True,
        min_fallback_seconds: float = MIN_FALLBACK_SECONDS,
    ) -> None:
        self.deadline = started_at + 100.0
        self._primary_factory = primary_factory
        self._primary: LLMProvider | None = None
        self._fallback_factory = fallback_factory or (
            lambda timeout: build_recommendation_fallback(timeout_seconds=timeout)
        )
        self._revalidate = revalidate
        self._eligible = eligible
        self._fallback_permitted = fallback_permitted
        self._min_fallback_seconds = min_fallback_seconds
        self.attempts = 0
        self.fallback_used = False

    def run[T](
        self,
        messages: list[LLMMessage],
        invoke: Callable[[LLMProvider, list[LLMMessage]], tuple[T, LLMCompletion]],
    ) -> tuple[T, LLMCompletion]:
        if self.fallback_used:
            # The fallback already used this request's remaining time and spend.
            raise LLMProviderError("The recommendation provider attempt budget is exhausted.")
        if self._primary is None:
            self._primary = self._primary_factory(None)
        self.attempts += 1
        try:
            return invoke(self._primary, messages)
        except (LLMQuotaExhaustedError, LLMTransientProviderError) as primary_error:
            # Financial/policy/schema/refusal/safety failures never enter here.
            return self._fallback(messages, invoke, primary_error)

    def _skip(self, reason: str, primary_error: LLMProviderError) -> LLMProviderError:
        logger.warning(
            "llm availability fallback skipped purpose=%s reason=%s", _PURPOSE, reason
        )
        return primary_error

    def _fallback[T](
        self,
        messages: list[LLMMessage],
        invoke: Callable[[LLMProvider, list[LLMMessage]], tuple[T, LLMCompletion]],
        primary_error: LLMProviderError,
    ) -> tuple[T, LLMCompletion]:
        if paid_providers_blocked_for_request():
            raise AiMoneyBudgetError(
                "Automated verification cannot call paid AI providers."
            ) from None
        if not self._eligible():
            raise self._skip("source_lineage_missing", primary_error)
        deadline = fallback_deadline(self.deadline, 0.0)
        if deadline - time.perf_counter() < self._min_fallback_seconds:
            raise self._skip("deadline", primary_error)
        model = get_settings().llm_fallback_model
        if not self._fallback_permitted(model):
            raise self._skip("tenant_policy", primary_error)
        self.fallback_used = True
        self._revalidate()
        remaining = deadline - time.perf_counter()
        if remaining < 1.0:
            raise self._skip("deadline", primary_error)
        logger.warning(
            "llm availability fallback purpose=%s reason=%s",
            _PURPOSE,
            type(primary_error).__name__,
        )
        try:
            with provider_deadline(deadline):
                active = self._fallback_factory(remaining)
                provider_time_remaining()
                self.attempts += 1
                result = invoke(active, messages)
                provider_time_remaining()
                return result
        except AiMoneyBudgetError as refusal:
            if paid_providers_blocked_for_request():
                raise
            # A spending control refused before transport: keep the primary's
            # safe failure so the user sees why OpenAI did not answer.
            log_fallback_failure(_PURPOSE, model, refusal)
            raise with_fallback_refusal(primary_error, refusal) from None
        except LLMResponseFormatError:
            raise
        except LLMProviderError as gemini_error:
            # Gemini unavailable, misconfigured or out of time: report the
            # primary failure, as the general fallback does.
            log_fallback_failure(_PURPOSE, model, gemini_error)
            raise primary_error from None

    def audit_metadata(self) -> dict[str, Any]:
        return {
            "availability_fallback_used": self.fallback_used,
            "provider_attempt_count": self.attempts,
        }
