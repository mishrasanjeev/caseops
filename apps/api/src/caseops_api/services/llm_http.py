from __future__ import annotations

from fastapi import HTTPException, status

from caseops_api.services.llm import LLMProviderError, LLMQuotaExhaustedError


def provider_failure_http_exception(
    *,
    noun: str,
    exc: LLMProviderError,
) -> HTTPException:
    if isinstance(exc, LLMQuotaExhaustedError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Could not generate the {noun}: the configured AI provider "
                "quota is exhausted. Restore or top up provider credits, then "
                "retry. No output was saved."
            ),
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=(
            f"Could not generate the {noun}: {type(exc).__name__}: {exc}. "
            "Please retry in a minute."
        ),
    )


__all__ = ["provider_failure_http_exception"]
