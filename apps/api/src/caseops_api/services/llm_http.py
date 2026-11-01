from __future__ import annotations

from fastapi import HTTPException, status

from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import LLMProviderError, LLMQuotaExhaustedError


def fallback_refusal_suffix(exc: BaseException) -> str:
    """Why the Gemini fallback did not run, placed after any retry advice.

    Retry advice concerns the primary provider only; a used-up monthly
    allowance is not fixed by retrying.
    """
    refusal = getattr(exc, "fallback_refusal", None)
    return f" {refusal}" if isinstance(refusal, str) and refusal else ""


def provider_failure_http_exception(
    *,
    noun: str,
    exc: LLMProviderError,
) -> HTTPException:
    if isinstance(exc, AiMoneyBudgetError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, LLMQuotaExhaustedError):
        # When the Gemini fallback was refused before transport, say so after
        # the primary's own quota message.
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Could not generate the {noun}: the configured AI provider "
                "quota is exhausted. Restore or top up provider credits, then "
                "retry. No output was saved." + fallback_refusal_suffix(exc)
            ),
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=(
            f"Could not generate the {noun}: {type(exc).__name__}: {exc}. "
            "Please retry in a minute." + fallback_refusal_suffix(exc)
        ),
    )


__all__ = ["fallback_refusal_suffix", "provider_failure_http_exception"]
