"""Initialize an immutable monthly AI budget from reconciled billing evidence.

Run with the release's database configuration; this never contacts providers,
enables a provider or changes the October exception/runtime switch.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from caseops_api.db.ai_spend_models import AiProviderSpendMonth
from caseops_api.db.session import get_session_factory, serialize_sqlite_writer
from caseops_api.services.ai_money_budget import TokenPrice


class ReconciledBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    limit_minor: int = Field(default=1_000_000, gt=0, le=1_000_000, strict=True)
    opening_spend_minor: int = Field(ge=0, le=2_000_000_000, strict=True)
    inr_per_usd_all_in: Decimal = Field(gt=0, le=10000, decimal_places=6)
    opening_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pricing: dict[str, TokenPrice] = Field(min_length=1, max_length=32)


def initialize_budget(policy: ReconciledBudget) -> bool:
    prices = {key: value.model_dump(mode="json") for key, value in policy.pricing.items()}
    for key, value in policy.pricing.items():
        provider, separator, model = key.partition(":")
        if not separator or not provider or not model or len(key) > 153:
            raise ValueError("Each price must name the exact provider:model.")
        if not value.source_url.startswith("https://"):
            raise ValueError("Pricing must have dated official HTTPS evidence.")
    with get_session_factory()() as session:
        serialize_sqlite_writer(session)
        existing = session.scalar(
            select(AiProviderSpendMonth)
            .where(AiProviderSpendMonth.month == policy.month)
            .with_for_update()
        )
        if existing is not None:
            # A replay cannot reset previously admitted spend or replace its
            # pricing. A changed reconciliation requires a separately reviewed
            # migration, not an automatic refund of unknown provider liability.
            if (
                existing.limit_minor == policy.limit_minor
                and existing.opening_spend_minor == policy.opening_spend_minor
                and existing.inr_per_usd_all_in == policy.inr_per_usd_all_in
                and existing.opening_evidence_sha256 == policy.opening_evidence_sha256
                and existing.pricing_json == prices
                and existing.admitted_minor >= policy.opening_spend_minor
            ):
                return False
            raise ValueError("This month is already initialized; refusing to reset its liability.")
        session.add(
            AiProviderSpendMonth(
                month=policy.month,
                limit_minor=policy.limit_minor,
                opening_spend_minor=policy.opening_spend_minor,
                admitted_minor=policy.opening_spend_minor,
                inr_per_usd_all_in=policy.inr_per_usd_all_in,
                pricing_json=prices,
                opening_evidence_sha256=policy.opening_evidence_sha256,
                reconciled_at=datetime.now(UTC),
            )
        )
        session.commit()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-file", required=True, type=Path)
    args = parser.parse_args()
    if args.policy_file.stat().st_size > 128_000:
        parser.error("Budget policy file exceeds the 128 KB bound.")
    policy = ReconciledBudget.model_validate(
        json.loads(args.policy_file.read_text(encoding="utf-8"))
    )
    created = initialize_budget(policy)
    print(
        json.dumps({"month": policy.month, "created": created, "limit_minor": policy.limit_minor})
    )


if __name__ == "__main__":
    main()
