from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AssistantSessionScope,
    AssistantTurn,
    BillingSubscription,
    Company,
    CompanyMembership,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    PrivateIndexProjection,
    PrivateProjectionEvent,
    PrivateSavedOutputAccess,
    TenantAIPolicy,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import private_retrieval_jobs
from caseops_api.services.embeddings import EmbeddingResult
from caseops_api.services.llm_types import LLMCompletion
from caseops_api.services.private_retrieval import (
    PrivateRetrievalInvariantError,
    enqueue_private_projection_event,
    hydrate_private_projection_results,
    private_retrieval_activation,
    propagate_private_projection_change,
    retrieve_private_content,
)
from caseops_api.services.private_retrieval_jobs import (
    MAX_PRIVATE_PROVIDER_BATCH,
    inspect_private_index_integrity,
    process_pending_private_projection_events,
    rebuild_private_index,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.workspace_assistant import _sources_for_scopes
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


def _indexed_matter_attachment(
    *,
    matter_id: str,
    membership_id: str,
    text: str,
) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with get_session_factory()() as session:
        attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=membership_id,
            original_filename=f"{digest[:12]}.txt",
            storage_key=f"iplf-066b/{digest}",
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            sha256_hex=digest,
            processing_status="indexed",
            extracted_char_count=len(text),
            extracted_text=text,
        )
        session.add(attachment)
        session.flush()
        session.add(
            MatterAttachmentChunk(
                attachment_id=attachment.id,
                chunk_index=0,
                content=text,
                token_count=max(1, len(text.split())),
            )
        )
        session.commit()
        return str(attachment.id)


def _assistant_session(
    client: TestClient,
    token: str,
    *,
    scope_type: str,
    scope_id: str,
) -> dict:
    response = client.post(
        "/api/workspace-assistant/sessions",
        headers=auth_headers(token),
        json={
            "title": "Private retrieval regression",
            "scopes": [{"scope_type": scope_type, "scope_id": scope_id}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ask_assistant(
    client: TestClient,
    token: str,
    *,
    assistant_session: dict,
    question: str,
):
    return client.post(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/ask",
        headers=auth_headers(token),
        json={"expected_version": assistant_session["version"], "question": question},
    )


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
    punctuation_only = client.post(
        "/api/private-retrieval/search",
        headers=auth_headers(token),
        json={"query": "!!"},
    )
    assert punctuation_only.status_code == 200, punctuation_only.text
    assert punctuation_only.json()["items"] == []

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


def test_assistant_document_text_has_no_legacy_fallback_without_private_activation(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    membership_id = str(bootstrap["membership"]["id"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "IPLF-066B-NO-FALLBACK")
    attachment_id = _indexed_matter_attachment(
        matter_id=str(matter["id"]),
        membership_id=membership_id,
        text="NoFallbackUnique private attachment evidence.",
    )
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "false")
    get_settings.cache_clear()
    assistant_session = _assistant_session(
        client,
        token,
        scope_type="matter_document",
        scope_id=attachment_id,
    )

    response = _ask_assistant(
        client,
        token,
        assistant_session=assistant_session,
        question="What does NoFallbackUnique say?",
    )

    assert response.status_code == 200, response.text
    assistant_turn = response.json()["assistant_turn"]
    assert assistant_turn["status"] == "abstained"
    assert assistant_turn["citations"] == []
    assert assistant_turn["model"] is None
    assert "NoFallbackUnique" not in assistant_turn["content"]


def test_all_provider_sources_are_manifested_and_any_revocation_hides_answer(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    _enable_assistant(client, token)
    first = _matter(client, token, "IPLF-066B-MANIFEST-A")
    second = _matter(client, token, "IPLF-066B-MANIFEST-B")
    with get_session_factory()() as session:
        for matter_id in (str(first["id"]), str(second["id"])):
            row = session.get(Matter, matter_id)
            assert row is not None
            row.description = "ManifestPairUnique shared private evidence."
        session.commit()
    _set_ip_workspace_entitlement(company_id)
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    get_settings.cache_clear()
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()

    class FirstSourceOnlyProvider:
        name = "manifest-first-only"
        model = "caseops-mock-1"

        def generate(self, messages, *, temperature=0.0, max_tokens=1024):
            del temperature, max_tokens
            source_ids = [
                line.split(":", 1)[1].strip()
                for message in messages
                for line in message.content.splitlines()
                if line.startswith("SOURCE_ID:")
            ]
            assert len(source_ids) >= 2
            return LLMCompletion(
                text=json.dumps(
                    {
                        "status": "answered",
                        "answer": "ManifestPairUnique synthesized response.",
                        "confidence": "medium",
                        "used_source_ids": source_ids[:1],
                        "suggested_searches": [],
                    }
                ),
                provider=self.name,
                model=self.model,
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=1,
            )

    monkeypatch.setattr(
        "caseops_api.services.workspace_assistant.build_provider",
        lambda purpose: FirstSourceOnlyProvider(),
    )
    assistant_session = _assistant_session(
        client,
        token,
        scope_type="tenant",
        scope_id=company_id,
    )

    response = _ask_assistant(
        client,
        token,
        assistant_session=assistant_session,
        question="Summarize ManifestPairUnique.",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assistant_turn"]["status"] == "completed"
    assert len(body["assistant_turn"]["citations"]) == 1
    turn_id = str(body["assistant_turn"]["id"])
    with get_session_factory()() as session:
        manifests = list(
            session.scalars(
                select(PrivateSavedOutputAccess).where(
                    PrivateSavedOutputAccess.company_id == company_id,
                    PrivateSavedOutputAccess.assistant_turn_id == turn_id,
                )
            ).all()
        )
        manifested_matter_ids = {
            row.source_id for row in manifests if row.source_type == "matter"
        }
        assert {str(first["id"]), str(second["id"])}.issubset(manifested_matter_ids)
        propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key="iplf-066b-manifest-second-revoked",
            event_type="revoked",
            target_type="matter",
            target_id=str(second["id"]),
            target_version=None,
            reason_code="manifest_source_revoked",
        )
        session.commit()
    turns = client.get(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/turns",
        headers=auth_headers(token),
    )
    assert turns.status_code == 200, turns.text
    saved = next(item for item in turns.json()["items"] if item["id"] == turn_id)
    assert saved["render_status"] == "permission_changed"
    assert saved["citations"] == []
    assert "ManifestPairUnique" not in saved["content"]


@pytest.mark.parametrize(
    ("revocation", "expected_problem_type"),
    (
        ("entitlement", "assistant_private_retrieval_changed"),
        ("rollout", "assistant_private_retrieval_changed"),
        ("policy", "assistant_private_retrieval_changed"),
        ("capability", "assistant_access_changed"),
        ("membership", "assistant_access_changed"),
    ),
)
def test_provider_wait_rechecks_private_activation_before_persisting(
    client: TestClient,
    monkeypatch,
    revocation: str,
    expected_problem_type: str,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "IPLF-066B-POST-WAIT")
    with get_session_factory()() as session:
        row = session.get(Matter, str(matter["id"]))
        assert row is not None
        row.description = "PostWaitUnique current private evidence."
        session.commit()
    _set_ip_workspace_entitlement(company_id)
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    get_settings.cache_clear()
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()

    class EntitlementRevokingProvider:
        name = "post-wait-test"
        model = "caseops-mock-1"

        def generate(self, messages, *, temperature=0.0, max_tokens=1024):
            del messages, temperature, max_tokens
            if revocation == "entitlement":
                _set_ip_workspace_entitlement(company_id, enabled=False)
            elif revocation == "rollout":
                monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "false")
                get_settings.cache_clear()
            elif revocation == "policy":
                with get_session_factory()() as provider_session:
                    policy = provider_session.scalar(
                        select(TenantAIPolicy).where(
                            TenantAIPolicy.company_id == company_id,
                        )
                    )
                    assert policy is not None
                    policy.workspace_assistant_enabled = False
                    provider_session.commit()
            else:
                with get_session_factory()() as provider_session:
                    membership = provider_session.get(CompanyMembership, membership_id)
                    assert membership is not None
                    if revocation == "capability":
                        membership.role = "viewer"
                    else:
                        membership.is_active = False
                    provider_session.commit()
            return LLMCompletion(
                text=json.dumps(
                    {
                        "status": "answered",
                        "answer": "PostWaitUnique",
                        "confidence": "medium",
                        "used_source_ids": [f"matter:{matter['id']}"],
                        "suggested_searches": [],
                    }
                ),
                provider=self.name,
                model=self.model,
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=1,
            )

    monkeypatch.setattr(
        "caseops_api.services.workspace_assistant.build_provider",
        lambda purpose: EntitlementRevokingProvider(),
    )
    assistant_session = _assistant_session(
        client,
        token,
        scope_type="matter",
        scope_id=str(matter["id"]),
    )

    response = _ask_assistant(
        client,
        token,
        assistant_session=assistant_session,
        question="What is PostWaitUnique?",
    )

    assert response.status_code == 409, response.text
    assert response.json()["type"] == expected_problem_type
    with get_session_factory()() as session:
        assert session.scalar(
            select(AssistantTurn.id).where(
                AssistantTurn.company_id == company_id,
                AssistantTurn.session_id == assistant_session["id"],
            )
        ) is None


def test_event_batch_uses_savepoints_and_preserves_other_events(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    first = _matter(client, token, "IPLF-066B-SAVEPOINT-A")
    second = _matter(client, token, "IPLF-066B-SAVEPOINT-B")
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        first_event = enqueue_private_projection_event(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key="iplf-066b-savepoint-fail",
            event_type="revoked",
            target_type="matter",
            target_id=str(first["id"]),
            target_version=None,
            reason_code="forced_failure",
        )
        second_event = enqueue_private_projection_event(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key="iplf-066b-savepoint-pass",
            event_type="revoked",
            target_type="matter",
            target_id=str(second["id"]),
            target_version=None,
            reason_code="normal_revocation",
        )
        first_event_id = str(first_event.id)
        second_event_id = str(second_event.id)
        session.commit()

    real_apply = private_retrieval_jobs.apply_private_projection_event

    def flaky_apply(session, *, event_id):
        event = session.get(PrivateProjectionEvent, event_id)
        assert event is not None
        if event.id == first_event_id:
            projection = session.scalar(
                select(PrivateIndexProjection).where(
                    PrivateIndexProjection.company_id == company_id,
                    PrivateIndexProjection.source_type == "matter",
                    PrivateIndexProjection.source_id == str(first["id"]),
                    PrivateIndexProjection.is_tombstoned.is_(False),
                )
            )
            assert projection is not None
            projection.content_text = "partial mutation that must roll back"
            session.flush()
            raise RuntimeError("forced savepoint regression")
        return real_apply(session, event_id=event_id)

    monkeypatch.setattr(private_retrieval_jobs, "apply_private_projection_event", flaky_apply)
    with get_session_factory()() as session:
        applied = process_pending_private_projection_events(session, company_id=company_id)
        session.commit()
        assert applied == (second_event_id,)
        failed = session.get(PrivateProjectionEvent, first_event_id)
        succeeded = session.get(PrivateProjectionEvent, second_event_id)
        assert failed is not None and failed.status == "failed"
        assert failed.error_code == "RuntimeError"
        assert succeeded is not None and succeeded.status == "applied"
        first_projection = session.scalar(
            select(PrivateIndexProjection).where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.source_type == "matter",
                PrivateIndexProjection.source_id == str(first["id"]),
                PrivateIndexProjection.is_tombstoned.is_(False),
            )
        )
        assert first_projection is not None
        assert "partial mutation" not in first_projection.content_text
        second_live = session.scalar(
            select(PrivateIndexProjection.id).where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.source_type == "matter",
                PrivateIndexProjection.source_id == str(second["id"]),
                PrivateIndexProjection.is_tombstoned.is_(False),
            )
        )
        assert second_live is None


def test_integrity_ignores_stale_retired_generations(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    matter = _matter(client, token, "IPLF-066B-RETIRED")
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()
    with get_session_factory()() as session:
        row = session.get(Matter, str(matter["id"]))
        assert row is not None
        row.description = "Current generation replacement content."
        row.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        session.commit()
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()
        report = inspect_private_index_integrity(session, company_id=company_id)
        assert report.state == "ready"
        assert report.stale_source_count == 0
        assert report.orphan_scope_count == 0
        assert report.generation_manifest_matches is True


def test_private_embedding_provider_has_a_hard_deadline(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    _matter(client, token, "IPLF-066B-DEADLINE")

    class SlowProvider(_SpyEmbeddingProvider):
        def embed(self, texts, *, input_type="document"):
            time.sleep(0.25)
            return super().embed(texts, input_type=input_type)

    started = time.perf_counter()
    with get_session_factory()() as session:
        with pytest.raises(
            PrivateRetrievalInvariantError,
            match="exceeded its bounded deadline",
        ):
            rebuild_private_index(
                session,
                company_id=company_id,
                provider=SlowProvider(),
                allow_external_provider=True,
                provider_deadline_seconds=0.02,
            )
        session.rollback()
    assert time.perf_counter() - started < 0.2


def test_assistant_private_attachment_hydration_has_no_n_plus_one(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "IPLF-066B-BATCH-HYDRATION")
    attachment_ids = [
        _indexed_matter_attachment(
            matter_id=str(matter["id"]),
            membership_id=membership_id,
            text=f"BatchAttachmentUnique evidence number {index}.",
        )
        for index in range(12)
    ]
    _set_ip_workspace_entitlement(company_id)
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    get_settings.cache_clear()
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()
    response = client.post(
        "/api/workspace-assistant/sessions",
        headers=auth_headers(token),
        json={
            "title": "Bounded attachment hydration",
            "scopes": [
                {"scope_type": "matter_document", "scope_id": attachment_id}
                for attachment_id in attachment_ids
            ],
        },
    )
    assert response.status_code == 201, response.text
    assistant_session_id = str(response.json()["id"])

    with get_session_factory()() as session:
        context = _context(company_id, membership_id)
        scope_rows = list(
            session.scalars(
                select(AssistantSessionScope)
                .where(AssistantSessionScope.session_id == assistant_session_id)
                .order_by(AssistantSessionScope.ordinal)
            ).all()
        )
        engine = get_engine()

        def measured(rows):
            count = 0

            def count_query(*_args):
                nonlocal count
                count += 1

            event.listen(engine, "before_cursor_execute", count_query)
            try:
                results = _sources_for_scopes(
                    session,
                    context=context,
                    scope_rows=rows,
                    question="BatchAttachmentUnique",
                )
            finally:
                event.remove(engine, "before_cursor_execute", count_query)
            return count, results

        one_count, one = measured(scope_rows[:1])
        many_count, many = measured(scope_rows)
        assert len(one) == 1
        assert len(many) == len(attachment_ids)
        assert many_count <= one_count + 2
        assert many_count <= 32
