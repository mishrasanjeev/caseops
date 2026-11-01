"""Account-level monthly cap on managed Gemini spend (the OpenAI fallback).

Owner decision, 1 November 2026: CaseOps may spend up to INR 10,000
(1,000,000 paise) of fresh Gemini spend per IST month. The month row is
created on first use with zero opening liability. This ledger is independent
of the shared AI money guard (``ai_money_budget``), which is off by default; it
does not read that guard's settings, prices or tables.

Every managed Gemini transport first commits a worst-case charge here, in its
own transaction. Input is bounded by UTF-8 bytes (never fewer than tokens) and
output by the effective ``max_output_tokens``, which includes thinking tokens.
Nothing is refunded: a timeout, refusal or invalid answer keeps its charge.
Admissions are content-free: month, model, amount and time only.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.db.ai_spend_models import AiGeminiSpendAdmission, AiGeminiSpendMonth
from caseops_api.db.session import get_session_factory
from caseops_api.services.ai_money_budget import AiMoneyBudgetError

_IST = timezone(timedelta(hours=5, minutes=30))

GEMINI_FALLBACK_MODEL = "gemini-3.8-flash"
# Owner-authorized fresh Gemini spend per IST month, in paise (INR 10,000).
MONTHLY_CAP_MINOR = 1_000_000

# Standard (non-promotional) Standard-PayGo prices for gemini-3.8-flash on the
# global endpoint, USD per 1M tokens, checked on 2026-11-01 at PRICING_SOURCE_URL
# ("Gemini 3.8 Flash Starting January 1, 2027"). The page also lists
# introductory $0.75/$3.75 through 2026-12-31; it is deliberately not used.
# Output includes reasoning ("Text output (response and reasoning)"). Non-global
# regions ($1.65/$8.25) and the Priority tier are never requested by CaseOps.
PRICING_SOURCE_URL = (
    "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
)
PRICING_CHECKED_ON = "2026-11-01"
_USD_PER_MILLION = {
    GEMINI_FALLBACK_MODEL: (Decimal("1.50"), Decimal("7.50")),
}
# Reviewed all-in INR per USD multiplier: an assumed market-rate ceiling of
# about INR 88 per USD x 1.18 (18% GST on Google Cloud services) = ~INR 104,
# plus about 6% for card/bank FX fees and rate movement = INR 110. Revisit it if
# the market rate exceeds about INR 88. Change it only with a reviewed commit.
INR_PER_USD_ALL_IN = Decimal("110.0")

_UNBOUNDED = "Gemini request cost cannot be bounded. No external request was sent."
CAP_REFUSAL = "The monthly Gemini fallback allowance is used up. No external request was sent."


class GeminiAllowanceError(AiMoneyBudgetError):
    """The Gemini fallback cap refused a transport; nothing was sent."""


def ist_month(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("ist_month requires an aware datetime.")
    return moment.astimezone(_IST).strftime("%Y-%m")


def worst_case_minor(*, model: str, input_bytes: int, output_tokens: int) -> int:
    """Conservative paise for one transport, rounded up and never zero."""
    try:
        input_rate, output_rate = _USD_PER_MILLION[model]
    except KeyError:
        raise AiMoneyBudgetError(
            "Gemini pricing for this model is not reviewed. No external request was sent."
        ) from None
    if (
        isinstance(input_bytes, bool)
        or not isinstance(input_bytes, int)
        or not 0 <= input_bytes <= 10_000_000
        or isinstance(output_tokens, bool)
        or not isinstance(output_tokens, int)
        or not 0 <= output_tokens <= 128_000
    ):
        raise AiMoneyBudgetError(_UNBOUNDED)
    amount = (
        (Decimal(input_bytes) * input_rate + Decimal(output_tokens) * output_rate)
        * INR_PER_USD_ALL_IN
        * 100
        / 1_000_000
    ).to_integral_value(rounding=ROUND_CEILING)
    return max(1, int(amount))


def reserve_gemini_spend(
    *, model: str, input_bytes: int, output_tokens: int, now: datetime | None = None
) -> str:
    """Commit a worst-case charge against this IST month's cap before transport.

    Uses its own session so a caller's rollback can never undo a charge, and a
    compare-and-set update so concurrent writers cannot both spend the last
    paise. Returns the content-free admission id.
    """
    if paid_providers_blocked_for_request():
        raise AiMoneyBudgetError("Automated verification cannot call paid AI providers.")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", model or ""):
        raise AiMoneyBudgetError(_UNBOUNDED)
    amount = worst_case_minor(model=model, input_bytes=input_bytes, output_tokens=output_tokens)
    moment = now or datetime.now(UTC)
    month = ist_month(moment)
    receipt = str(uuid4())
    try:
        with get_session_factory()() as session:
            dialect = session.get_bind().dialect.name
            values = {
                "month": month,
                "limit_minor": MONTHLY_CAP_MINOR,
                "admitted_minor": 0,
                "created_at": moment,
            }
            if dialect == "postgresql":
                opening = postgresql_insert(AiGeminiSpendMonth).values(**values)
            elif dialect == "sqlite":
                opening = sqlite_insert(AiGeminiSpendMonth).values(**values)
            else:
                raise AiMoneyBudgetError(
                    "Gemini spending controls are unavailable. No external request was sent."
                )
            # A new month opens at zero; an existing month (and its spend) is kept.
            session.execute(opening.on_conflict_do_nothing(index_elements=["month"]))
            period = session.scalar(
                select(AiGeminiSpendMonth)
                .where(AiGeminiSpendMonth.month == month)
                .with_for_update()
            )
            if (
                period is None
                or not 0 < period.limit_minor <= MONTHLY_CAP_MINOR
                or not 0 <= period.admitted_minor <= period.limit_minor
            ):
                raise AiMoneyBudgetError(
                    "Gemini spending controls are inconsistent. No external request was sent."
                )
            if period.admitted_minor + amount > period.limit_minor:
                raise GeminiAllowanceError(CAP_REFUSAL)
            admitted = session.execute(
                update(AiGeminiSpendMonth)
                .where(
                    AiGeminiSpendMonth.month == month,
                    AiGeminiSpendMonth.admitted_minor == period.admitted_minor,
                    AiGeminiSpendMonth.admitted_minor <= AiGeminiSpendMonth.limit_minor - amount,
                )
                .values(admitted_minor=AiGeminiSpendMonth.admitted_minor + amount)
                .execution_options(synchronize_session=False)
            )
            if admitted.rowcount != 1:
                raise GeminiAllowanceError(
                    "The Gemini fallback allowance changed concurrently. "
                    "No external request was sent."
                )
            session.execute(
                insert(AiGeminiSpendAdmission).values(
                    id=receipt,
                    month=month,
                    model=model,
                    upper_bound_minor=amount,
                    created_at=moment,
                )
            )
            session.commit()
    except SQLAlchemyError as exc:
        raise AiMoneyBudgetError(
            "Gemini spending controls are temporarily unavailable. No external request was sent."
        ) from exc
    return receipt


__all__ = [
    "CAP_REFUSAL",
    "GEMINI_FALLBACK_MODEL",
    "INR_PER_USD_ALL_IN",
    "MONTHLY_CAP_MINOR",
    "PRICING_CHECKED_ON",
    "PRICING_SOURCE_URL",
    "GeminiAllowanceError",
    "ist_month",
    "reserve_gemini_spend",
    "worst_case_minor",
]
