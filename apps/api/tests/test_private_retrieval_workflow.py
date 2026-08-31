from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AssistantSessionScope,
    AssistantTurn,
    BillingSubscription,
    Company,
    CompanyMembership,
    DataRetentionPolicy,
    DataRetentionPolicyVersion,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateProjectionEvent,
    PrivateSavedOutputAccess,
    TenantAIPolicy,
    TenantDataDispositionCheckpoint,
    TenantDataOperation,
    TenantDataOperationItem,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import data_disposition, private_retrieval, private_retrieval_jobs
from caseops_api.services.data_disposition import (
    DataDispositionInvariantError,
    execute_private_retrieval_disposition,
    tenant_target_reference_hash,
)
from caseops_api.services.embeddings import EmbeddingResult
from caseops_api.services.llm_types import LLMCompletion
from caseops_api.services.matter_access import remove_access_grant
from caseops_api.services.private_retrieval import (
    PrivateRetrievalInvariantError,
    capture_private_retrieval_fence,
    enqueue_private_projection_event,
    hydrate_private_projection_results,
    prefilter_private_projection_ids,
    private_retrieval_activation,
    propagate_private_projection_change,
    retrieve_private_content,
    stream_private_content,
)
from caseops_api.services.private_retrieval_jobs import (
    MAX_PRIVATE_PROVIDER_BATCH,
    inspect_private_index_integrity,
    list_private_maintenance_companies,
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


def _private_search_member(client: TestClient, owner_token: str) -> tuple[str, str]:
    password = "".join(("Private", "Delivery", "123!"))
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Private Delivery Member",
            "email": "private-delivery-member@asterlegal.in",
            "password": password,
            "role": "member",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "private-delivery-member@asterlegal.in",
            "password": password,
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    return str(created.json()["membership_id"]), str(login.json()["access_token"])


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
    assert all(len(batch) <= MAX_PRIVATE_PROVIDER_BATCH for _input_type, batch in spy.calls)

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


def test_stream_autocomplete_and_count_fail_closed_on_acl_epoch_change(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_id, member_token = _private_search_member(client, owner_token)
    _enable_assistant(client, owner_token)
    _set_ip_workspace_entitlement(company_id)
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    get_settings.cache_clear()

    matter_code = "-".join(("PD", "BOUNDARY"))
    matter = _matter(client, owner_token, matter_code)
    restricted = client.post(
        f"/api/matters/{matter['id']}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    grant = client.post(
        f"/api/matters/{matter['id']}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_id, "reason": "Bounded delivery test."},
    )
    assert grant.status_code == 200, grant.text
    secret = "StreamFenceUnique private opposition sequence."
    attachment_id = _indexed_matter_attachment(
        matter_id=str(matter["id"]),
        membership_id=owner_membership_id,
        text="StreamFenceUnique attachment evidence that must stop after revoke.",
    )
    with get_session_factory()() as session:
        row = session.get(Matter, str(matter["id"]))
        assert row is not None
        row.description = secret
        row.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        session.commit()
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()

    query = "StreamFenceUnique"
    request = {
        "query": query,
        "scope_ids": {"matter": [matter["id"]]},
        "limit": 10,
    }
    autocomplete = client.post(
        "/api/private-retrieval/autocomplete",
        headers=auth_headers(member_token),
        json=request,
    )
    assert autocomplete.status_code == 200, autocomplete.text
    assert {item["source_id"] for item in autocomplete.json()["items"]} == {
        matter["id"],
        attachment_id,
    }
    assert all("content" not in item for item in autocomplete.json()["items"])
    assert secret not in autocomplete.text
    counted = client.post(
        "/api/private-retrieval/count",
        headers=auth_headers(member_token),
        json=request,
    )
    assert counted.status_code == 200, counted.text
    assert counted.json() == {
        "visible_match_count": 2,
        "count_limit": 200,
        "count_is_capped": False,
    }
    streamed = client.post(
        "/api/private-retrieval/search/stream",
        headers=auth_headers(member_token),
        json=request,
    )
    assert streamed.status_code == 200, streamed.text
    assert streamed.headers["content-type"].startswith("application/x-ndjson")
    assert streamed.headers["cache-control"] == "no-store"
    assert streamed.headers["x-content-type-options"] == "nosniff"
    frames = [json.loads(line) for line in streamed.text.splitlines() if line]
    assert {frame["source_id"] for frame in frames} == {matter["id"], attachment_id}
    assert any(secret in frame["content"] for frame in frames)
    scope_options = client.get(
        "/api/workspace-assistant/scope-options",
        headers=auth_headers(member_token),
        params={"q": matter_code, "limit": 10},
    )
    assert scope_options.status_code == 200, scope_options.text
    assert any(item["scope_id"] == matter["id"] for item in scope_options.json()["items"])

    with get_session_factory()() as session:
        member_context = _context(company_id, member_id)
        fence = capture_private_retrieval_fence(session, context=member_context)
        candidate_ids = prefilter_private_projection_ids(
            session,
            context=member_context,
            query=query,
            filters={"matter_id": str(matter["id"])},
        )
    assert fence is not None
    assert len(candidate_ids) == 2

    in_flight = stream_private_content(
        fence=fence,
        projection_ids=candidate_ids,
        query=query,
        session_factory=get_session_factory(),
    )
    first_frame = next(in_flight)
    assert first_frame.source_id in {matter["id"], attachment_id}

    # Force the canonical revoke after count candidate selection but before
    # count delivery. This models an adversarial race without relying on test
    # timing and proves the final count fence cannot disclose the stale match.
    original_prefilter = private_retrieval.prefilter_private_projection_ids

    def prefilter_then_revoke(session, **kwargs):
        selected = original_prefilter(session, **kwargs)
        assert selected
        remove_access_grant(
            session,
            context=_context(company_id, owner_membership_id),
            matter_id=str(matter["id"]),
            grant_id=str(grant.json()["id"]),
        )
        return selected

    monkeypatch.setattr(
        private_retrieval,
        "prefilter_private_projection_ids",
        prefilter_then_revoke,
    )
    with get_session_factory()() as session:
        raced_count = private_retrieval.count_private_content(
            session,
            context=_context(company_id, member_id),
            query=query,
            filters={"scope_ids": {"matter": [str(matter["id"])]}},
        )
    assert raced_count == 0
    monkeypatch.setattr(
        private_retrieval,
        "prefilter_private_projection_ids",
        original_prefilter,
    )

    # The stream delivered its first frame while access was current. Advancing
    # it after the revoke must terminate instead of emitting the second source.
    assert list(in_flight) == []

    # A stream that captured the same generation but had not emitted yet must
    # also terminate with zero bytes.
    assert (
        list(
            stream_private_content(
                fence=fence,
                projection_ids=candidate_ids,
                query=query,
                session_factory=get_session_factory(),
            )
        )
        == []
    )

    for path in ("autocomplete", "search/stream"):
        response = client.post(
            f"/api/private-retrieval/{path}",
            headers=auth_headers(member_token),
            json=request,
        )
        assert response.status_code == 200, response.text
        assert str(matter["id"]) not in response.text
        assert secret not in response.text
    revoked_count = client.post(
        "/api/private-retrieval/count",
        headers=auth_headers(member_token),
        json=request,
    )
    assert revoked_count.status_code == 200, revoked_count.text
    assert revoked_count.json()["visible_match_count"] == 0
    revoked_scope_options = client.get(
        "/api/workspace-assistant/scope-options",
        headers=auth_headers(member_token),
        params={"q": matter_code, "limit": 10},
    )
    assert revoked_scope_options.status_code == 200, revoked_scope_options.text
    assert revoked_scope_options.json() == {
        "query": matter_code,
        "items": [],
        "truncated": False,
    }

    other = _other_company(client)
    other_token = str(other["access_token"])
    other_company_id = str(other["company"]["id"])
    _enable_assistant(client, other_token)
    _set_ip_workspace_entitlement(other_company_id)
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=other_company_id, activate=True)
        session.commit()
    for path in ("autocomplete", "search/stream"):
        response = client.post(
            f"/api/private-retrieval/{path}",
            headers=auth_headers(other_token),
            json=request,
        )
        assert response.status_code == 200, response.text
        assert response.text in {'{"items":[]}', ""}
    cross_count = client.post(
        "/api/private-retrieval/count",
        headers=auth_headers(other_token),
        json=request,
    )
    assert cross_count.status_code == 200, cross_count.text
    assert cross_count.json()["visible_match_count"] == 0

    with get_session_factory()() as session:
        owner_context = _context(company_id, owner_membership_id)
        generation = session.scalar(
            select(PrivateIndexGeneration).where(
                PrivateIndexGeneration.company_id == company_id,
                PrivateIndexGeneration.state == "active",
            )
        )
        assert generation is not None
        assert fence.access_policy_generation < generation.access_policy_generation
        assert (
            retrieve_private_content(
                session,
                context=owner_context,
                query=query,
            )
            == ()
        )


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
        assert (
            retrieve_private_content(
                session,
                context=context,
                query="IPLF-066B-EVENT",
            )
            == ()
        )
        assert (
            hydrate_private_projection_results(
                session,
                context=context,
                projection_ids=session.scalars(
                    select(PrivateIndexProjection.id).where(
                        PrivateIndexProjection.company_id == company_id
                    )
                ).all(),
                query="IPLF-066B-EVENT",
            )
            == ()
        )
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
        manifested_matter_ids = {row.source_id for row in manifests if row.source_type == "matter"}
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
    exported = client.get(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/export",
        headers=auth_headers(token),
    )
    assert exported.status_code == 200, exported.text
    exported_saved = next(item for item in exported.json()["turns"] if item["id"] == turn_id)
    assert exported_saved["render_status"] == "permission_changed"
    assert exported_saved["citations"] == []
    assert "ManifestPairUnique" not in exported_saved["content"]


def test_provider_deletion_during_rebuild_fences_stale_projection_writer(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter = _matter(client, token, "IPLF-066B-PROVIDER-DELETE")
    with get_session_factory()() as session:
        row = session.get(Matter, str(matter["id"]))
        assert row is not None
        row.description = "ProviderDeleteUnique private source content."
        session.commit()
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()

    class DeletingProvider(_SpyEmbeddingProvider):
        def __init__(self) -> None:
            super().__init__()
            self.deleted = False

        def embed(self, texts, *, input_type="document"):
            if not self.deleted:
                self.deleted = True
                with get_session_factory()() as concurrent:
                    propagate_private_projection_change(
                        concurrent,
                        company_id=company_id,
                        actor_membership_id=membership_id,
                        idempotency_key="iplf-066b-provider-deletion-during-rebuild",
                        event_type="tombstoned",
                        target_type="matter",
                        target_id=str(matter["id"]),
                        target_version=None,
                        reason_code="provider_deletion_completed",
                    )
                    concurrent.commit()
            return super().embed(texts, input_type=input_type)

    with get_session_factory()() as session:
        with pytest.raises(
            PrivateRetrievalInvariantError,
            match="stale private projection writer",
        ):
            rebuild_private_index(
                session,
                company_id=company_id,
                provider=DeletingProvider(),
                allow_external_provider=True,
                activate=True,
            )

    with get_session_factory()() as session:
        active = session.scalar(
            select(PrivateIndexGeneration).where(
                PrivateIndexGeneration.company_id == company_id,
                PrivateIndexGeneration.state == "active",
            )
        )
        assert active is not None
        source_rows = list(
            session.scalars(
                select(PrivateIndexProjection).where(
                    PrivateIndexProjection.company_id == company_id,
                    PrivateIndexProjection.source_type == "matter",
                    PrivateIndexProjection.source_id == str(matter["id"]),
                )
            )
        )
        assert source_rows
        assert all(row.is_tombstoned for row in source_rows)
        assert all(row.content_text == "" and row.embedding_json is None for row in source_rows)
        assert all(row.generation_id == active.id for row in source_rows)
        context = _context(company_id, membership_id)
        assert (
            retrieve_private_content(
                session,
                context=context,
                query="ProviderDeleteUnique",
            )
            == ()
        )


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
        assert (
            session.scalar(
                select(AssistantTurn.id).where(
                    AssistantTurn.company_id == company_id,
                    AssistantTurn.session_id == assistant_session["id"],
                )
            )
            is None
        )


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

    failed_once = False

    def flaky_apply(session, *, event_id):
        nonlocal failed_once
        event = session.get(PrivateProjectionEvent, event_id)
        assert event is not None
        if event.id == first_event_id and not failed_once:
            failed_once = True
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
        first_attempt_at = datetime.now(UTC)
        applied = process_pending_private_projection_events(
            session,
            company_id=company_id,
            now=first_attempt_at,
        )
        session.commit()
        assert applied == (second_event_id,)
        failed = session.get(PrivateProjectionEvent, first_event_id)
        succeeded = session.get(PrivateProjectionEvent, second_event_id)
        assert failed is not None and failed.status == "pending"
        assert failed.attempt_count == 1
        assert failed.error_code == "RuntimeError"
        assert failed.next_attempt_at is not None
        assert succeeded is not None and succeeded.status == "applied"
        assert succeeded.attempt_count == 1
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

        retried = process_pending_private_projection_events(
            session,
            company_id=company_id,
            now=first_attempt_at + timedelta(seconds=31),
        )
        session.commit()
        assert retried == (first_event_id,)
        recovered = session.get(PrivateProjectionEvent, first_event_id)
        assert recovered is not None and recovered.status == "applied"
        assert recovered.attempt_count == 2
        assert recovered.next_attempt_at is None
        assert recovered.error_code is None


def test_event_worker_exhausts_bounded_backoff_without_hot_looping(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter = _matter(client, token, "IPLF-066B-RETRY-EXHAUSTION")
    with get_session_factory()() as session:
        event = enqueue_private_projection_event(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key="iplf-066b-retry-exhaustion",
            event_type="revoked",
            target_type="matter",
            target_id=str(matter["id"]),
            target_version=None,
            reason_code="forced_terminal_failure",
        )
        event_id = str(event.id)
        session.commit()

    attempts = 0

    def always_fail(_session, *, event_id):
        nonlocal attempts
        attempts += 1
        raise RuntimeError(f"forced failure for {event_id}")

    monkeypatch.setattr(
        private_retrieval_jobs,
        "apply_private_projection_event",
        always_fail,
    )
    started_at = datetime.now(UTC)
    with get_session_factory()() as session:
        assert (
            process_pending_private_projection_events(
                session,
                company_id=company_id,
                now=started_at,
            )
            == ()
        )
        session.commit()
        first = session.get(PrivateProjectionEvent, event_id)
        assert first is not None
        assert first.status == "pending"
        assert first.attempt_count == 1
        assert first.next_attempt_at.replace(tzinfo=UTC) == started_at + timedelta(seconds=30)

        assert (
            process_pending_private_projection_events(
                session,
                company_id=company_id,
                now=started_at + timedelta(seconds=29),
            )
            == ()
        )
        assert attempts == 1

        assert (
            process_pending_private_projection_events(
                session,
                company_id=company_id,
                now=started_at + timedelta(seconds=30),
            )
            == ()
        )
        session.commit()
        second = session.get(PrivateProjectionEvent, event_id)
        assert second is not None
        assert second.status == "pending"
        assert second.attempt_count == 2
        assert second.next_attempt_at.replace(tzinfo=UTC) == started_at + timedelta(seconds=90)

        assert (
            process_pending_private_projection_events(
                session,
                company_id=company_id,
                now=started_at + timedelta(seconds=90),
            )
            == ()
        )
        session.commit()
        terminal = session.get(PrivateProjectionEvent, event_id)
        assert terminal is not None
        assert terminal.status == "failed"
        assert terminal.attempt_count == 3
        assert terminal.next_attempt_at is None
        assert terminal.error_code == "RuntimeError"

        assert (
            process_pending_private_projection_events(
                session,
                company_id=company_id,
                now=started_at + timedelta(days=1),
            )
            == ()
        )
        assert attempts == 3
        report = inspect_private_index_integrity(
            session,
            company_id=company_id,
            now=started_at + timedelta(days=1),
        )
        assert report.failed_event_count == 1
        assert "failed_projection_events" in report.blockers


def test_maintenance_candidate_scan_is_bounded_and_reports_truncation(
    client: TestClient,
) -> None:
    first = bootstrap_company(client)
    second_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Bounded Retrieval Legal",
            "company_slug": "bounded-retrieval-legal",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@bounded-retrieval.in",
            "owner_password": "SecondPass123!",
        },
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    for index, bootstrap in enumerate((first, second), start=1):
        matter = _matter(
            client,
            str(bootstrap["access_token"]),
            f"IPLF-066B-CANDIDATE-{index}",
        )
        with get_session_factory()() as session:
            enqueue_private_projection_event(
                session,
                company_id=str(bootstrap["company"]["id"]),
                actor_membership_id=str(bootstrap["membership"]["id"]),
                idempotency_key=f"iplf-066b-candidate-{index}",
                event_type="revoked",
                target_type="matter",
                target_id=str(matter["id"]),
                target_version=None,
                reason_code="candidate_scan_test",
            )
            session.commit()

    with get_session_factory()() as session:
        candidates = list_private_maintenance_companies(session, limit=1)
        assert len(candidates.company_ids) == 1
        assert candidates.truncated is True


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


def test_approved_tenant_disposition_records_provider_exception_and_blocks_rebuild(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    requester_membership_id, _member_token = _private_search_member(client, token)
    _enable_assistant(client, token)
    matter_code = "IPLF-071-PRIVATE-DISPOSITION"
    matter = _matter(client, token, matter_code)
    with get_session_factory()() as session:
        row = session.get(Matter, str(matter["id"]))
        assert row is not None
        row.description = "Provider deletion delay evidence source."
        session.commit()

    provider = _SpyEmbeddingProvider()
    with get_session_factory()() as session:
        rebuild_private_index(
            session,
            company_id=company_id,
            provider=provider,
            allow_external_provider=True,
            activate=True,
        )
        session.commit()

    now = datetime.now(UTC)
    target_hash = tenant_target_reference_hash(company_id)
    with get_session_factory()() as session:
        dry_run = TenantDataOperation(
            company_id=company_id,
            operation_type="tenant_offboarding",
            execution_mode="dry_run",
            status="dry_run_complete",
            approval_status="requested",
            request_scope_json={"schema_version": 2, "target": target_hash},
            request_scope_hash="a" * 64,
            request_evidence_ref="caseops://test/private-disposition",
            manifest_json={"schema_version": 2, "target": target_hash},
            manifest_hash="b" * 64,
            requested_by_membership_id=requester_membership_id,
            requested_by_membership_company_id=company_id,
            requester_label_snapshot="Disposition Requester",
            dry_run_completed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(dry_run)
        session.flush()
        item = TenantDataOperationItem(
            company_id=company_id,
            operation_id=dry_run.id,
            data_class_id="private_index_projections",
            target_type="tenant",
            target_reference_hash=target_hash,
            item_status="eligible",
            candidate_record_count=1,
            estimated_bytes=0,
            safe_to_execute=False,
        )
        session.add(item)
        execute = TenantDataOperation(
            company_id=company_id,
            operation_type="tenant_offboarding",
            execution_mode="execute",
            status="planned",
            approval_status="approved",
            request_scope_json=dry_run.request_scope_json,
            request_scope_hash=dry_run.request_scope_hash,
            request_evidence_ref=dry_run.request_evidence_ref,
            manifest_json=dry_run.manifest_json,
            manifest_hash=dry_run.manifest_hash,
            requested_by_membership_id=requester_membership_id,
            requested_by_membership_company_id=company_id,
            requester_label_snapshot="Disposition Requester",
            approved_by_membership_id=owner_membership_id,
            approved_by_membership_company_id=company_id,
            approver_label_snapshot="Disposition Approver",
            approved_at=now,
            approves_operation_id=dry_run.id,
            created_at=now,
            updated_at=now,
        )
        session.add(execute)
        session.commit()
        execute_id = str(execute.id)

    real_hold_resolver = data_disposition.resolve_hold_for_target
    monkeypatch.setattr(
        data_disposition,
        "resolve_hold_for_target",
        lambda *_args, **_kwargs: "active-hold",
    )
    with get_session_factory()() as session:
        with pytest.raises(DataDispositionInvariantError, match="currently active"):
            execute_private_retrieval_disposition(
                session,
                operation_id=execute_id,
                provider_retention_days={"external-spy": 30},
                now=now,
            )
        assert session.scalar(select(TenantDataDispositionCheckpoint.id)) is None
        assert (
            session.scalar(
                select(PrivateProjectionEvent.id).where(
                    PrivateProjectionEvent.idempotency_key
                    == f"data-disposition:{execute_id}:private-index"
                )
            )
            is None
        )

    monkeypatch.setattr(
        data_disposition,
        "resolve_hold_for_target",
        real_hold_resolver,
    )
    with get_session_factory()() as session:
        checkpoints = execute_private_retrieval_disposition(
            session,
            operation_id=execute_id,
            provider_retention_days={"external-spy": 30},
            now=now,
        )
        session.commit()
        assert len(checkpoints) == 2
        local = next(row for row in checkpoints if row.subsystem == "private_index")
        provider_row = next(
            row for row in checkpoints if row.subsystem == "provider_embedding:external-spy"
        )
        assert local.status == "completed"
        assert local.outcome_type == "receipt"
        assert local.provider_receipt_ref is not None
        assert provider_row.status == "exception"
        assert provider_row.outcome_type == "deletion_delay_exception"
        assert provider_row.exception_code == "provider_deletion_contract_delay"
        assert provider_row.expected_resolution_at == now + timedelta(days=30)
        assert provider_row.provider_receipt_ref is None
        assert provider_row.evidence_sha256 is not None
        assert (
            session.scalar(
                select(TenantDataDispositionCheckpoint).where(
                    TenantDataDispositionCheckpoint.id == provider_row.id
                )
            )
            is not None
        )
        assert not session.scalars(
            select(PrivateIndexProjection).where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.is_tombstoned.is_(False),
            )
        ).all()

        repeated = execute_private_retrieval_disposition(
            session,
            operation_id=execute_id,
            provider_retention_days={"external-spy": 30},
            now=now + timedelta(minutes=1),
        )
        session.commit()
        assert {row.id for row in repeated} == {row.id for row in checkpoints}
        provider_row.private_event_id = None
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()
        report = inspect_private_index_integrity(session, company_id=company_id)
        assert report.release_blocked is False
        assert report.live_projection_count == 0
        assert report.generation_manifest_matches is True

        blocked_dry_run = TenantDataOperation(
            company_id=company_id,
            operation_type="tenant_offboarding",
            execution_mode="dry_run",
            status="dry_run_complete",
            approval_status="requested",
            request_scope_json={"schema_version": 2, "target": target_hash},
            request_scope_hash="c" * 64,
            request_evidence_ref="caseops://test/private-disposition-blocked",
            manifest_json={"schema_version": 2, "target": target_hash},
            manifest_hash="d" * 64,
            requested_by_membership_id=requester_membership_id,
            requested_by_membership_company_id=company_id,
            requester_label_snapshot="Disposition Requester",
            dry_run_completed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(blocked_dry_run)
        session.flush()
        session.add(
            TenantDataOperationItem(
                company_id=company_id,
                operation_id=blocked_dry_run.id,
                data_class_id="private_index_projections",
                target_type="tenant",
                target_reference_hash=target_hash,
                item_status="blocked",
                candidate_record_count=0,
                estimated_bytes=0,
                safe_to_execute=False,
            )
        )
        blocked_execute = TenantDataOperation(
            company_id=company_id,
            operation_type="tenant_offboarding",
            execution_mode="execute",
            status="planned",
            approval_status="approved",
            request_scope_json=blocked_dry_run.request_scope_json,
            request_scope_hash=blocked_dry_run.request_scope_hash,
            request_evidence_ref=blocked_dry_run.request_evidence_ref,
            manifest_json=blocked_dry_run.manifest_json,
            manifest_hash=blocked_dry_run.manifest_hash,
            requested_by_membership_id=requester_membership_id,
            requested_by_membership_company_id=company_id,
            requester_label_snapshot="Disposition Requester",
            approved_by_membership_id=owner_membership_id,
            approved_by_membership_company_id=company_id,
            approver_label_snapshot="Disposition Approver",
            approved_at=now,
            approves_operation_id=blocked_dry_run.id,
            created_at=now,
            updated_at=now,
        )
        session.add(blocked_execute)
        session.commit()
        with pytest.raises(DataDispositionInvariantError, match="held or blocked"):
            execute_private_retrieval_disposition(
                session,
                operation_id=blocked_execute.id,
            )


def test_private_retention_disposition_revalidates_active_policy(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    requester_membership_id, _member_token = _private_search_member(
        client,
        str(bootstrap["access_token"]),
    )
    now = datetime.now(UTC)
    target_hash = tenant_target_reference_hash(company_id)
    with get_session_factory()() as session:
        policy = DataRetentionPolicy(
            company_id=company_id,
            key="private-retrieval-test",
            name="Private retrieval test policy",
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(policy)
        session.flush()
        disabled_version = DataRetentionPolicyVersion(
            company_id=company_id,
            policy_id=policy.id,
            version=1,
            status="disabled",
            data_class_selector_json=["private_index_projections"],
            purpose="Test execution-time policy revalidation.",
            legal_policy_basis="Synthetic test policy.",
            sensitivity="confidential",
            retention_days=30,
            disposition="purge",
            hold_behavior="block",
            policy_hash="e" * 64,
            proposer_label_snapshot="Disposition Requester",
            reviewer_label_snapshot="Disposition Approver",
            created_at=now,
        )
        session.add(disabled_version)
        session.flush()
        dry_run = TenantDataOperation(
            company_id=company_id,
            operation_type="retention_purge",
            execution_mode="dry_run",
            status="dry_run_complete",
            approval_status="requested",
            retention_policy_version_id=disabled_version.id,
            request_scope_json={"schema_version": 2, "target": target_hash},
            request_scope_hash="f" * 64,
            request_evidence_ref="caseops://test/private-retention-policy",
            manifest_json={"schema_version": 2, "target": target_hash},
            manifest_hash="1" * 64,
            requested_by_membership_id=requester_membership_id,
            requested_by_membership_company_id=company_id,
            requester_label_snapshot="Disposition Requester",
            dry_run_completed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(dry_run)
        session.flush()
        session.add(
            TenantDataOperationItem(
                company_id=company_id,
                operation_id=dry_run.id,
                data_class_id="private_index_projections",
                target_type="tenant",
                target_reference_hash=target_hash,
                item_status="eligible",
                candidate_record_count=0,
                estimated_bytes=0,
                safe_to_execute=False,
            )
        )
        execute = TenantDataOperation(
            company_id=company_id,
            operation_type="retention_purge",
            execution_mode="execute",
            status="planned",
            approval_status="approved",
            retention_policy_version_id=disabled_version.id,
            request_scope_json=dry_run.request_scope_json,
            request_scope_hash=dry_run.request_scope_hash,
            request_evidence_ref=dry_run.request_evidence_ref,
            manifest_json=dry_run.manifest_json,
            manifest_hash=dry_run.manifest_hash,
            requested_by_membership_id=requester_membership_id,
            requested_by_membership_company_id=company_id,
            requester_label_snapshot="Disposition Requester",
            approved_by_membership_id=owner_membership_id,
            approved_by_membership_company_id=company_id,
            approver_label_snapshot="Disposition Approver",
            approved_at=now,
            approves_operation_id=dry_run.id,
            created_at=now,
            updated_at=now,
        )
        session.add(execute)
        session.commit()

        with pytest.raises(DataDispositionInvariantError, match="no longer active"):
            execute_private_retrieval_disposition(
                session,
                operation_id=execute.id,
                now=now,
            )
        assert session.scalar(select(TenantDataDispositionCheckpoint.id)) is None
