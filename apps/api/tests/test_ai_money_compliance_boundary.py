"""An optional AI stop must not erase deterministic compliance work."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, MatterComplianceExtractionRun, MatterComplianceItem
from caseops_api.db.session import get_session_factory
from caseops_api.services import compliance_extraction as mod
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import LLMProviderError
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_matter_court_orders_create import _create_matter


@pytest.mark.parametrize(
    "client_fixture",
    ["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)],
)
@pytest.mark.parametrize("financial_stop", [True, False])
def test_compliance_retains_deterministic_items_and_distinct_ai_phase(
    request, monkeypatch, client_fixture, financial_stop
):
    client = request.getfixturevalue(client_fixture)
    monkeypatch.setenv("CASEOPS_COMPLIANCE_AI_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_COMPLIANCE_AI_EXTRACTION_AUTO_RUN_ENABLED", "true")
    get_settings.cache_clear()
    calls = []

    class DeniedProvider:
        name = "openai"
        model = "gpt-5-mini"

        def generate(self, *_args, **_kwargs):
            calls.append("offline-denial")
            if financial_stop:
                raise AiMoneyBudgetError("AI monthly spending is awaiting reconciliation.")
            raise LLMProviderError("Offline provider unavailable.")

    monkeypatch.setattr(mod, "build_provider", lambda **_: DeniedProvider())
    monkeypatch.setattr(mod, "is_model_allowed", lambda *_args, **_kwargs: True)
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "AI-MONEY-COMPLIANCE")
    response = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json={
            "order_date": "2026-10-11",
            "title": "Synthetic source-backed compliance direction",
            "summary": "The parties shall comply within two weeks from today.",
            "source": "manual_upload",
            "order_text": "The parties shall comply within two weeks from today.",
        },
    )
    assert response.status_code == 200, response.text
    assert calls == ["offline-denial"]
    with get_session_factory()() as session:
        run = session.scalar(
            select(MatterComplianceExtractionRun).where(
                MatterComplianceExtractionRun.matter_id == matter["id"]
            )
        )
        assert run is not None
        items = list(
            session.scalars(
                select(MatterComplianceItem).where(MatterComplianceItem.matter_id == matter["id"])
            )
        )
        assert items
        assert run.status == "completed"
        assert run.metadata_json["created_item_count"] == len(items)
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == run.id,
                AuditEvent.action == "matter_compliance.extraction.completed",
            )
        )
        assert event is not None
        if financial_stop:
            assert run.metadata_json["ai_deferred"] == "shared_ai_budget"
            assert not run.metadata_json.get("ai_failed", False)
            assert run.error_message_redacted.startswith("AI extraction deferred:")
            assert json.loads(event.metadata_json)["ai_phase"] == "deferred_shared_budget"
        else:
            assert run.metadata_json["ai_failed"] is True
            assert "ai_deferred" not in run.metadata_json
            assert "Offline provider unavailable" in run.error_message_redacted
    get_settings.cache_clear()
