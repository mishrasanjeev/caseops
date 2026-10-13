"""Shared pre-transport money admission, separate from tenant retail credits.

Only text-token transports are supported. Pricing is a reconciled, bounded
monthly snapshot of conservative USD rates (including any applicable cache,
region, priority and long-context premiums). The FX multiplier includes tax
and fees. Unknown prices and missing opening balances fail closed.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.core.settings import get_settings
from caseops_api.db.ai_spend_models import AiProviderSpendAdmission, AiProviderSpendMonth
from caseops_api.db.session import get_session_factory
from caseops_api.services.llm_types import LLMProviderError

_IST = timezone(timedelta(hours=5, minutes=30))
OWNER_CEILING_MINOR = 1_000_000


class AiMoneyBudgetError(LLMProviderError):
    """No provider transport was admitted; safe to display to an operator."""


class AiMoneyAdmission(str):
    """Ephemeral dispatch ticket for a durable content-free admission."""

    def __new__(cls, receipt: str, month: str) -> AiMoneyAdmission:
        admission = super().__new__(cls, receipt)
        admission.month = month
        return admission

    month: str


class TokenPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_usd_per_million: Decimal = Field(gt=0, le=1000)
    output_usd_per_million: Decimal = Field(ge=0, le=1000)
    source_url: str = Field(min_length=12, max_length=2048)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def current_budget_month() -> str:
    return datetime.now(UTC).astimezone(_IST).strftime("%Y-%m")


def budget_applies() -> bool:
    return _budget_applies_for_month(current_budget_month())


def _budget_applies_for_month(month: str) -> bool:
    settings = get_settings()
    return (
        settings.effective_ai_money_budget_enabled and month >= settings.ai_money_budget_start_month
    )


def assert_paid_ai_dispatch(admission: str | None) -> None:
    """Recheck the marker and period immediately before native SDK dispatch.

    A rollover denial retains the old reservation. It does not silently move
    unknown liability into a new month or resend a partially completed request.
    """
    if paid_providers_blocked_for_request():
        raise AiMoneyBudgetError("Automated verification cannot call paid AI providers.")
    month = current_budget_month()
    if _budget_applies_for_month(month) and (
        not isinstance(admission, AiMoneyAdmission) or admission.month != month
    ):
        raise AiMoneyBudgetError(
            "The AI budget period changed before dispatch. No external request was sent."
        )


def _price(pricing: dict, provider: str, model: str) -> TokenPrice:
    if not isinstance(pricing, dict) or not 1 <= len(pricing) <= 32:
        raise AiMoneyBudgetError("AI pricing is not reconciled. No external request was sent.")
    try:
        result = TokenPrice.model_validate(pricing[f"{provider}:{model}"])
    except (KeyError, ValidationError, TypeError) as exc:
        raise AiMoneyBudgetError(
            "AI pricing for this workflow is not reconciled. No external request was sent."
        ) from exc
    if not result.source_url.startswith("https://"):
        raise AiMoneyBudgetError("AI pricing evidence is invalid. No external request was sent.")
    return result


def reserve_paid_ai_call(
    *, provider: str, model: str, input_bytes: int, output_tokens: int, retry_count: int = 0
) -> str | None:
    """Commit a worst-case charge before transport without borrowing caller state.

    UTF-8 bytes are deliberately used as a token upper bound, not the English
    character/4 estimate. Adapters must include schema/framing bytes and the
    effective output cap (reasoning included), and bound all SDK attempts.
    No refunds occur on timeout, crash, refusal or invalid output.
    """
    if paid_providers_blocked_for_request():
        raise AiMoneyBudgetError("Automated verification cannot call paid AI providers.")
    month = current_budget_month()
    if not _budget_applies_for_month(month):
        return None
    if (
        not isinstance(input_bytes, int)
        or isinstance(input_bytes, bool)
        or not 0 <= input_bytes <= 10_000_000
        or not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
        or not 0 <= output_tokens <= 128_000
        or not isinstance(retry_count, int)
        or isinstance(retry_count, bool)
        or not 0 <= retry_count <= 4
        or not re.fullmatch(r"[a-z0-9_-]{1,32}", provider)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", model)
    ):
        raise AiMoneyBudgetError("AI request cost cannot be bounded. No external request was sent.")
    receipt = str(uuid4())
    try:
        with get_session_factory()() as session:
            period = session.scalar(
                select(AiProviderSpendMonth)
                .where(AiProviderSpendMonth.month == month)
                .with_for_update()
            )
            if (
                period is None
                or not 0 < period.limit_minor <= OWNER_CEILING_MINOR
                or period.opening_spend_minor < 0
                or period.admitted_minor < period.opening_spend_minor
                or not re.fullmatch(r"[a-f0-9]{64}", period.opening_evidence_sha256)
                or period.reconciled_at is None
            ):
                raise AiMoneyBudgetError(
                    "AI monthly spending is awaiting reconciliation. No external request was sent."
                )
            price = _price(period.pricing_json, provider, model)
            fx = Decimal(period.inr_per_usd_all_in)
            if not fx.is_finite() or fx <= 0:
                raise AiMoneyBudgetError(
                    "AI currency costs are not reconciled. No external request was sent."
                )
            if output_tokens and price.output_usd_per_million <= 0:
                raise AiMoneyBudgetError(
                    "AI output pricing is missing. No external request was sent."
                )
            amount = max(
                1,
                int(
                    (
                        (
                            Decimal(input_bytes) * price.input_usd_per_million
                            + Decimal(output_tokens) * price.output_usd_per_million
                        )
                        * (retry_count + 1)
                        * fx
                        * 100
                        / 1_000_000
                    ).to_integral_value(rounding=ROUND_CEILING)
                ),
            )
            if period.admitted_minor + amount > period.limit_minor:
                raise AiMoneyBudgetError(
                    "The shared monthly AI budget is exhausted. Existing work remains available; "
                    "new paid generation is unavailable. No external request was sent."
                )
            # The database compare-and-set also protects separate SQLite
            # processes, without borrowing a caller's Python writer mutex.
            admitted = session.execute(
                update(AiProviderSpendMonth)
                .where(
                    AiProviderSpendMonth.month == month,
                    AiProviderSpendMonth.admitted_minor == period.admitted_minor,
                    AiProviderSpendMonth.admitted_minor <= period.limit_minor - amount,
                )
                .values(admitted_minor=AiProviderSpendMonth.admitted_minor + amount)
                .execution_options(synchronize_session=False)
            )
            if admitted.rowcount != 1:
                raise AiMoneyBudgetError(
                    "The shared AI budget changed concurrently. No external request was sent."
                )
            session.execute(
                insert(AiProviderSpendAdmission).values(
                    id=receipt,
                    month=month,
                    provider=provider,
                    model=model,
                    upper_bound_minor=amount,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
    except SQLAlchemyError as exc:
        raise AiMoneyBudgetError(
            "AI spending controls are temporarily unavailable. No external request was sent."
        ) from exc
    return AiMoneyAdmission(receipt, month)
