from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingSubscription,
    Company,
    CompanyMembership,
    Matter,
    PrivateIndexProjection,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.embeddings import EmbeddingResult
from caseops_api.services.private_retrieval import (
    enqueue_private_projection_event,
    hydrate_private_projection_results,
    private_retrieval_activation,
    retrieve_private_content,
)
from caseops_api.services.private_retrieval_jobs import (
    MAX_PRIVATE_PROVIDER_BATCH,
    inspect_private_index_integrity,
    process_pending_private_projection_events,
    rebuild_private_index,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_workspace_assistant_qa import _enable_assistant, _matter


class _SpyEmbeddingProvider:
    name = "external-spy"
    model = "private-spy-v1"
    dimensions = 3

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def embed(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> EmbeddingResult:
        self.calls.append((input_type, tuple(texts)))
        return EmbeddingResult(
            vectors=[[1.0, 0.0, 0.0] for _text in texts],
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
        )


def _context(company_id: str, membership_id: str) -> SessionContext:
    with get_session_factory()() as session:
        company = session.get(Company, company_id)
        membership = session.get(CompanyMembership, membership_id)
        assert company is not None and membership is not None
        user = session.get(User, membership.user_id)
        assert user is not None
        session.expunge(company)
        session.expunge(membership)
        session.expunge(user)
        return SessionContext(company=company, membership=membership, user=user)


def _set_ip_workspace_entitlement(company_id: str, *, enabled: bool = True) -> None:
    with get_session_factory()() as session:
        subscription = session.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.company_id == company_id)
            .order_by(BillingSubscription.created_at.desc())
        )
        if subscription is None:
            subscription = BillingSubscription(
                company_id=company_id,
                status="manual_active",
                segment="law_firm",
                source="iplf-066b-test",
                externally_billable=False,
                entitlement_overrides_json={"ip_workspace": enabled},
            )
            session.add(subscription)
        else:
            overrides = dict(subscription.entitlement_overrides_json or {})
            overrides["ip_workspace"] = enabled
            subscription.entitlement_overrides_json = overrides
        session.commit()


def _other_company(client: TestClient) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Private Retrieval Other LLP",
            "company_slug": "private-retrieval-other",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "private-retrieval-other@example.in",
            "owner_password": "OtherPrivate123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_rebuild_batches_only_one_tenant_and_search_reauthorizes_current_source(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "IPLF-066B-PRIVATE")
    other = _other_company(client)
    other_token = str(other["access_token"])
    _enable_assistant(client, other_token)
    other_matter = _matter(client, other_token, "IPLF-066B-OTHER")

    with get_session_factory()() as session:
        row = session.get(Matter, str(matter["id"]))
        other_row = session.get(Matter, str(other_matter["id"]))
        assert row is not None and other_row is not None
        row.description = "Zephyr cipher renewal strategy for the permitted tenant."
        other_row.description = "Cross tenant orchid secret must never enter this batch."
        session.commit()

    spy = _SpyEmbeddingProvider()
    with get_session_factory()() as session:
        summary = rebuild_private_index(
            session,
            company_id=company_id,
            provider=spy,
            allow_external_provider=True,
            activate=True,
        )
        session.commit()
        assert summary.projection_count >= 1
        assert summary.provider_text_count == summary.projection_count
        assert summary.provider_batch_count == len(spy.calls)
    assert spy.calls
    provider_text = " ".join(
        text for input_type, batch in spy.calls for text in batch if input_type == "document"
    )
    assert "Zephyr cipher" in provider_text
    assert "orchid secret" not in provider_text
    assert company_id not in provider_text
    assert str(matter["id"]) not in provider_text
    assert all(
        len(batch) <= MAX_PRIVATE_PROVIDER_BATCH
        for _input_type, batch in spy.calls
    )

    _set_ip_workspace_entitlement(company_id)
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "false")
    get_settings.cache_clear()
    unavailable = client.post(
        "/api/private-retrieval/search",
        headers=auth_headers(token),
        json={"query": "Zephyr cipher"},
    )
    assert unavailable.status_code == 503, unavailable.text
    assert unavailable.json()["reason"] == "rollout_disabled"

    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    get_settings.cache_clear()
    found = client.post(
        "/api/private-retrieval/search",
        headers=auth_headers(token),
        json={
            "query": "Zephyr cipher",
            "scope_ids": {"matter": [matter["id"]]},
        },
    )
    assert found.status_code == 200, found.text
    assert [item["source_id"] for item in found.json()["items"]] == [matter["id"]]
    assert "Zephyr cipher" in found.json()["items"][0]["content"]

    # A source edit that did not yet produce a new verified generation is
    # rejected during hydration, even if its old ID remains in the cache.
    with get_session_factory()() as session:
        row = session.get(Matter, str(matter["id"]))
        assert row is not None
        row.description = "Replacement content after the generation was built."
        row.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        session.commit()
    stale = client.post(
        "/api/private-retrieval/search",
        headers=auth_headers(token),
        json={"query": "Zephyr cipher"},
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["items"] == []
    integrity = client.get(
        "/api/private-retrieval/integrity",
        headers=auth_headers(token),
    )
    assert integrity.status_code == 200, integrity.text
    assert integrity.json()["stale_source_count"] >= 1
    assert "stale_or_ineligible_sources" in integrity.json()["blockers"]

    # The other tenant can activate its own empty/different partition and
    # cannot discover the first tenant's label, snippet, count, or candidate.
    _set_ip_workspace_entitlement(str(other["company"]["id"]))
    with get_session_factory()() as session:
        rebuild_private_index(
            session,
            company_id=str(other["company"]["id"]),
            activate=True,
        )
        session.commit()
    cross_tenant = client.post(
        "/api/private-retrieval/search",
        headers=auth_headers(other_token),
        json={"query": "Zephyr cipher"},
    )
    assert cross_tenant.status_code == 200, cross_tenant.text
    assert cross_tenant.json()["items"] == []


def test_pending_event_worker_exposes_lag_then_tombstones_all_saved_candidates(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "IPLF-066B-EVENT")
    _set_ip_workspace_entitlement(company_id)
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    get_settings.cache_clear()

    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        event = enqueue_private_projection_event(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key="iplf-066b-pending-worker",
            event_type="revoked",
            target_type="matter",
            target_id=str(matter["id"]),
            target_version=None,
            reason_code="access_revoked",
        )
        event.created_at = datetime.now(UTC) - timedelta(seconds=90)
        session.commit()

    with get_session_factory()() as session:
        context = _context(company_id, membership_id)
        before = inspect_private_index_integrity(session, company_id=company_id)
        assert before.pending_event_count == 1
        assert before.oldest_pending_lag_seconds is not None
        assert before.oldest_pending_lag_seconds >= 89
        applied = process_pending_private_projection_events(
            session,
            company_id=company_id,
        )
        assert len(applied) == 1
        session.commit()
        assert retrieve_private_content(
            session,
            context=context,
            query="IPLF-066B-EVENT",
        ) == ()
        assert hydrate_private_projection_results(
            session,
            context=context,
            projection_ids=session.scalars(
                select(PrivateIndexProjection.id).where(
                    PrivateIndexProjection.company_id == company_id
                )
            ).all(),
            query="IPLF-066B-EVENT",
        ) == ()
        after = inspect_private_index_integrity(session, company_id=company_id)
        assert after.pending_event_count == 0
        assert after.tombstoned_projection_count >= 1


def test_activation_rechecks_role_entitlement_rollout_and_tenant_policy(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    token = str(bootstrap["access_token"])
    context = _context(company_id, membership_id)

    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    get_settings.cache_clear()
    with get_session_factory()() as session:
        decision = private_retrieval_activation(session, context=context)
        assert decision.available is False
        assert decision.reason in {"missing_entitlement", "tenant_ai_policy_disabled"}

    _set_ip_workspace_entitlement(company_id)
    _enable_assistant(client, token)
    with get_session_factory()() as session:
        decision = private_retrieval_activation(session, context=context)
        assert decision.available is True
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = "viewer"
        session.commit()
        decision = private_retrieval_activation(session, context=context)
        assert decision.available is False
        assert decision.reason == "missing_capability"
