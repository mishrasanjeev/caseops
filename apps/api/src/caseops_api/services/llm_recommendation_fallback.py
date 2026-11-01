"""Bounded availability routing, never a financial or legal-safety bypass.

Recommendations keep their own plan (source revalidation before every attempt
and a shared two-attempt deadline) on top of the general OpenAI availability
fallback settings in ``llm.build_gemini_fallback``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.core.settings import get_settings
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import (
    build_gemini_fallback,
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
    LLMTransientProviderError,
)


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
    """Share two attempts and a deadline across fallback and output repair.

    The supplied invoke function performs policy/quota/billing preflight for
    the actual provider and releases its read transaction before transport.
    Revalidation must likewise release its transaction before SDK construction.
    """

    def __init__(
        self,
        *,
        started_at: float,
        primary_factory: Callable[[float], LLMProvider],
        revalidate: Callable[[], None],
        fallback_factory: Callable[[float], LLMProvider] | None = None,
    ) -> None:
        self.deadline = started_at + 100.0
        self._primary_factory = primary_factory
        self._fallback_factory = fallback_factory or (
            lambda timeout: build_recommendation_fallback(timeout_seconds=timeout)
        )
        self._revalidate = revalidate
        self.attempts = 0
        self.fallback_used = False

    def _dispatch[T](
        self,
        messages: list[LLMMessage],
        invoke: Callable[[LLMProvider, list[LLMMessage]], tuple[T, LLMCompletion]],
    ) -> tuple[T, LLMCompletion]:
        if paid_providers_blocked_for_request():
            raise AiMoneyBudgetError("Automated verification cannot call paid AI providers.")
        if self.attempts >= 2 or time.perf_counter() >= self.deadline - 1.0:
            raise LLMProviderError("The recommendation provider attempt budget is exhausted.")
        self._revalidate()
        remaining = self.deadline - time.perf_counter()
        if remaining < 1.0:
            raise LLMProviderError("The recommendation provider deadline has elapsed.")
        timeout = min(40.0 if self.fallback_used else 45.0, remaining)
        factory = self._fallback_factory if self.fallback_used else self._primary_factory
        with provider_deadline(self.deadline):
            active = factory(timeout)
            provider_time_remaining()
            self.attempts += 1
            result = invoke(active, messages)
            provider_time_remaining()
            return result

    def run[T](
        self,
        messages: list[LLMMessage],
        invoke: Callable[[LLMProvider, list[LLMMessage]], tuple[T, LLMCompletion]],
    ) -> tuple[T, LLMCompletion]:
        try:
            return self._dispatch(messages, invoke)
        except (LLMQuotaExhaustedError, LLMTransientProviderError) as primary_error:
            # Only the first primary quota/availability failure may switch provider.
            # Financial/policy/schema/refusal/safety failures never enter here.
            if self.fallback_used or self.attempts != 1:
                raise
            self.fallback_used = True
            try:
                return self._dispatch(messages, invoke)
            except AiMoneyBudgetError as refusal:
                if paid_providers_blocked_for_request():
                    raise
                # A spending control refused before transport: keep the primary's
                # safe failure so the user sees why OpenAI did not answer.
                raise with_fallback_refusal(primary_error, refusal) from None

    def audit_metadata(self) -> dict[str, Any]:
        return {
            "availability_fallback_used": self.fallback_used,
            "provider_attempt_count": self.attempts,
        }
