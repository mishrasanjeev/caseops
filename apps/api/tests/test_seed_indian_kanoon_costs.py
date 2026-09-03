from __future__ import annotations

from datetime import UTC, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import ProviderCostProfile
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.seed_indian_kanoon_costs import (
    EVIDENCE_REF,
    PRICE_SCHEDULE_MINOR,
    PRICING_CHECKED_AT,
    PRICING_URL,
    PROVIDER,
    _seed,
)
from tests.test_auth_company import bootstrap_company


def test_seed_creates_complete_machine_verified_price_schedule(client: TestClient) -> None:
    bootstrap_company(client)
    with get_session_factory()() as session:
        inserted, updated = _seed(session)
        rows = list(
            session.scalars(
                select(ProviderCostProfile).where(ProviderCostProfile.provider == PROVIDER)
            )
        )

    assert (inserted, updated) == (5, 0)
    assert {row.category: row.unit_amount_minor for row in rows} == PRICE_SCHEDULE_MINOR
    assert all(row.currency == "INR" for row in rows)
    assert all(row.status == "active" for row in rows)
    assert all(row.source == PRICING_URL for row in rows)
    assert all(row.evidence_ref == EVIDENCE_REF for row in rows)
    assert all(row.cost_basis == "actual" for row in rows)
    assert all(row.confidence_level == "high" for row in rows)
    assert all(row.effective_from.replace(tzinfo=UTC) == PRICING_CHECKED_AT for row in rows)


def test_seed_is_idempotent_and_repairs_seed_owned_rows(client: TestClient) -> None:
    bootstrap_company(client)
    with get_session_factory()() as session:
        _seed(session)
        row = session.scalar(
            select(ProviderCostProfile).where(
                ProviderCostProfile.provider == PROVIDER,
                ProviderCostProfile.evidence_ref == EVIDENCE_REF,
            )
        )
        assert row is not None
        row.unit_amount_minor = 999_999
        row.status = "inactive"
        row.effective_from = PRICING_CHECKED_AT + timedelta(days=1)
        session.commit()

    with get_session_factory()() as session:
        inserted, updated = _seed(session)
        rows = list(
            session.scalars(
                select(ProviderCostProfile).where(ProviderCostProfile.provider == PROVIDER)
            )
        )

    assert (inserted, updated) == (0, 5)
    assert len(rows) == 5
    assert {row.category: row.unit_amount_minor for row in rows} == PRICE_SCHEDULE_MINOR
    assert all(row.status == "active" for row in rows)
    assert all(row.effective_from.replace(tzinfo=UTC) == PRICING_CHECKED_AT for row in rows)
