from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    ModelRun,
    TenantAIPolicy,
    utcnow,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ai_token_governance as ai_governance
from caseops_api.services.contract_intelligence import _structured_with_retry
from caseops_api.services.llm import (
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    generate_structured,
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, slug_prefix: str) -> dict[str, object]:
    slug = f"{slug_prefix}-{uuid4().hex[:8]}"
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug_prefix.title()} Firm",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug_prefix.title()} Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": "StrongPass123!",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    body["_company_slug"] = slug
    return body


def _invite_user(
    client: TestClient,
    owner_token: str,
    *,
    company_slug: str,
    email: str,
    role: str,
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": f"AI Token {role.title()}",
            "email": email,
            "password": "MemberPass123!",
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": company_slug,
            "email": email,
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return str(response.json()["membership_id"]), str(login.json()["access_token"])


def _create_matter(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": f"AI Token Governance {code}",
            "matter_code": code,
            "client_name": "AI Token Client",
            "opposing_party": "AI Token Counterparty",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _owner_membership_id(company_id: str) -> str:
    factory = get_session_factory()
    with factory() as session:
        membership_id = session.scalar(
            select(CompanyMembership.id).where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.role == "owner",
            )
        )
        assert membership_id is not None
        return str(membership_id)


def _set_policy(
    company_id: str,
    *,
    firm_quota_tokens: int | None = None,
    user_quota_tokens: int | None = None,
    warning_threshold_percent: int = 90,
) -> None:
    factory = get_session_factory()
    with factory() as session:
        row = session.scalar(
            select(TenantAIPolicy).where(TenantAIPolicy.company_id == company_id)
        )
        if row is None:
            row = TenantAIPolicy(company_id=company_id)
            session.add(row)
        row.monthly_token_budget = firm_quota_tokens
        row.user_monthly_token_budget = user_quota_tokens
        row.token_warning_threshold_percent = warning_threshold_percent
        session.commit()


def _seed_model_run(
    *,
    company_id: str,
    actor_membership_id: str | None,
    matter_id: str | None,
    purpose: str,
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "caseops-mock-1",
) -> None:
    factory = get_session_factory()
    with factory() as session:
        session.add(
            ModelRun(
                company_id=company_id,
                matter_id=matter_id,
                actor_membership_id=actor_membership_id,
                purpose=purpose,
                provider="mock",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=10,
                status="ok",
                created_at=utcnow(),
            )
        )
        session.commit()


class _ToyPayload(BaseModel):
    ok: bool


class _CountingProvider:
    name = "toy"
    model = "toy-model-1"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, messages, temperature, max_tokens):  # noqa: ANN001
        self.calls += 1
        return LLMCompletion(
            provider=self.name,
            model=self.model,
            text='{"ok": true}',
            prompt_tokens=8,
            completion_tokens=3,
            latency_ms=1,
            raw=None,
        )


def test_ai_token_usage_rollup_and_tenant_isolation(client: TestClient) -> None:
    boot_a = _bootstrap(client, "adp02-usage-a")
    boot_b = _bootstrap(client, "adp02-usage-b")
    token_a = str(boot_a["access_token"])
    token_b = str(boot_b["access_token"])
    company_a = str(boot_a["company"]["id"])
    company_b = str(boot_b["company"]["id"])
    owner_a = _owner_membership_id(company_a)
    owner_b = _owner_membership_id(company_b)
    member_a, _member_token = _invite_user(
        client,
        token_a,
        company_slug=str(boot_a["_company_slug"]),
        email=f"member-{uuid4().hex[:8]}@adp02-usage.example",
        role="member",
    )
    matter_a = _create_matter(client, token_a, f"ADP02-A-{uuid4().hex[:4]}")
    matter_b = _create_matter(client, token_b, f"ADP02-B-{uuid4().hex[:4]}")
    _set_policy(company_a, firm_quota_tokens=100, user_quota_tokens=80)
    _seed_model_run(
        company_id=company_a,
        actor_membership_id=owner_a,
        matter_id=matter_a,
        purpose="matter_summary",
        prompt_tokens=30,
        completion_tokens=20,
    )
    _seed_model_run(
        company_id=company_a,
        actor_membership_id=member_a,
        matter_id=matter_a,
        purpose="drafting",
        prompt_tokens=25,
        completion_tokens=15,
        model="caseops-mock-drafting",
    )
    _seed_model_run(
        company_id=company_b,
        actor_membership_id=owner_b,
        matter_id=matter_b,
        purpose="matter_summary",
        prompt_tokens=900,
        completion_tokens=99,
    )

    response = client.get("/api/admin/ai-token-governance", headers=_auth(token_a))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["firm_used_tokens"] == 90
    assert payload["firm_quota_tokens"] == 100
    assert payload["firm_remaining_tokens"] == 10
    assert payload["firm_state"] == "warning"
    assert {row["actor_membership_id"] for row in payload["top_users"]} == {
        owner_a,
        member_a,
    }
    assert [row["matter_id"] for row in payload["usage_by_matter"]] == [matter_a]
    purposes = {row["purpose"] for row in payload["usage_by_purpose_model"]}
    assert purposes == {"matter_summary", "drafting"}
    redacted = json.dumps(payload)
    assert matter_b not in redacted
    assert "prompt" not in redacted.lower()
    assert "answer" not in redacted.lower()
    assert "source" not in redacted.lower()

    empty_range = client.get(
        "/api/admin/ai-token-governance"
        "?since=2030-01-01T00:00:00Z&until=2030-02-01T00:00:00Z",
        headers=_auth(token_a),
    )
    assert empty_range.status_code == 200, empty_range.text
    assert empty_range.json()["firm_used_tokens"] == 0


def test_unset_quota_preserves_existing_ai_call_behavior(client: TestClient) -> None:
    boot = _bootstrap(client, "adp02-unset")
    company_id = str(boot["company"]["id"])
    owner_membership_id = _owner_membership_id(company_id)
    provider = _CountingProvider()
    factory = get_session_factory()
    with factory() as session:
        payload, completion = generate_structured(
            provider,
            schema=_ToyPayload,
            messages=[LLMMessage(role="user", content="regular request")],
            context=LLMCallContext(
                tenant_id=company_id,
                actor_membership_id=owner_membership_id,
                purpose="matter_summary",
            ),
            max_tokens=16,
            session=session,
        )

    assert payload.ok is True
    assert completion.prompt_tokens == 8
    assert provider.calls == 1


def test_under_quota_check_does_not_hold_policy_row_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = _bootstrap(client, "adp02-no-lock")
    company_id = str(boot["company"]["id"])
    owner_membership_id = _owner_membership_id(company_id)
    _set_policy(company_id, firm_quota_tokens=10_000)
    provider = _CountingProvider()
    original_policy_lookup = ai_governance._policy_or_default
    lock_requests: list[bool] = []

    def _tracking_policy_lookup(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        lock_requests.append(bool(kwargs.get("for_update", False)))
        return original_policy_lookup(*args, **kwargs)

    monkeypatch.setattr(
        ai_governance,
        "_policy_or_default",
        _tracking_policy_lookup,
    )
    factory = get_session_factory()
    with factory() as session:
        payload, _completion = generate_structured(
            provider,
            schema=_ToyPayload,
            messages=[LLMMessage(role="user", content="regular request")],
            context=LLMCallContext(
                tenant_id=company_id,
                actor_membership_id=owner_membership_id,
                purpose="matter_summary",
            ),
            max_tokens=16,
            session=session,
        )

    assert payload.ok is True
    assert provider.calls == 1
    assert lock_requests == [False]


def test_contract_structured_ai_helper_records_successful_model_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    import httpx
    import openai

    from caseops_api.db.models import ContractAttachment, ContractClause, DocumentProcessingStatus
    from caseops_api.db.session import get_db_session
    from caseops_api.services import contract_intelligence, llm
    from caseops_api.services.contract_ai_phase import current_contract_ai_phase
    from tests.test_contract_intelligence import _create_contract

    boot = _bootstrap(client, "adp02-contract-run")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    owner_membership_id = _owner_membership_id(company_id)
    contract_id = _create_contract(client, token)
    source = "Acme India and Supplier India agree to pay within thirty days."
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    provider = _CountingProvider()
    factory = get_session_factory()
    with factory() as session:
        with pytest.raises(HTTPException) as denied:
            _structured_with_retry(
                provider,
                schema=_ToyPayload,
                messages=[LLMMessage(role="user", content="contract request")],
                context=LLMCallContext(
                    tenant_id=company_id,
                    actor_membership_id=owner_membership_id,
                    purpose="metadata_extract",
                ),
                temperature=0.0,
                max_tokens=16,
                session=session,
                feature="contract token accounting",
            )
        assert denied.value.status_code == 409
        assert provider.name == "toy" and provider.calls == 0
        assert session.scalar(select(ModelRun.id).where(ModelRun.company_id == company_id)) is None
        attachment = ContractAttachment(
            contract_id=contract_id,
            original_filename="offline-governance-source.txt",
            storage_key=f"contracts/{contract_id}/offline-governance-source.txt",
            content_type="text/plain",
            size_bytes=len(source.encode()),
            sha256_hex=source_hash,
            processing_status=DocumentProcessingStatus.INDEXED,
            extracted_char_count=len(source),
            extracted_text=source,
        )
        session.add(attachment)
        session.commit()
        attachment_id = attachment.id
    _set_policy(company_id, firm_quota_tokens=50_000, user_quota_tokens=50_000)

    request_sessions, working_sessions, sdk_clients = [], [], []
    dispatches = []
    real_generate = contract_intelligence.generate_structured
    native_openai = openai.OpenAI

    def request_session():
        with factory() as session:
            request_sessions.append(session)
            yield session

    def observe_generate(*args, **kwargs):
        working_sessions.append(kwargs["session"])
        return real_generate(*args, **kwargs)

    def transport(request):
        assert request.method == "POST"
        assert request.url == "https://contract-governance.invalid/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-luna"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert source in json.dumps(body["messages"])
        assert request_sessions and working_sessions
        assert not any(session.in_transaction() for session in request_sessions)
        working = working_sessions[-1]
        assert not working.in_transaction()
        phase = current_contract_ai_phase(working)
        assert phase is not None and phase.snapshot is not None
        assert (phase.contract_id, phase.company_id, phase.membership_id) == (
            contract_id, company_id, owner_membership_id,
        )
        provider.calls += 1
        dispatches.append(body)
        return httpx.Response(200, json={
            "id": "chatcmpl-offline-governance", "object": "chat.completion", "created": 0,
            "model": "gpt-6-luna",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "refusal": None, "content": json.dumps({"clauses": [{
                    "clause_type": "payment", "title": "Payment within thirty days",
                    "clause_text": source, "risk_level": "medium",
                    "rationale": "The supplied source states the payment period.",
                }]}),
            }}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
        })

    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as offline_http:
        assert not offline_http._mounts

        def offline_openai(**kwargs):
            assert kwargs["api_key"] == "offline"
            assert request_sessions and not any(s.in_transaction() for s in request_sessions)
            sdk = native_openai(
                **kwargs, base_url="https://contract-governance.invalid/v1",
                http_client=offline_http,
            )
            assert sdk._client._transport is offline_http._transport
            sdk_clients.append(sdk)
            return sdk

        monkeypatch.setattr(openai, "OpenAI", offline_openai)
        monkeypatch.setattr(contract_intelligence, "generate_structured", observe_generate)
        monkeypatch.setattr(contract_intelligence, "build_provider", lambda **_: llm.OpenAIProvider(
            model="gpt-6-luna", api_key="offline", max_retries=0,
        ))
        previous = client.app.dependency_overrides.get(get_db_session)
        client.app.dependency_overrides[get_db_session] = request_session
        try:
            response = client.post(
                f"/api/ai/contracts/{contract_id}/clauses/extract", headers=_auth(token),
            )
            assert response.status_code == 200, response.text
            assert response.json()["contract_id"] == contract_id
            assert response.json()["inserted"] == 1
            with factory() as session:
                runs = session.scalars(select(ModelRun).where(
                    ModelRun.company_id == company_id,
                    ModelRun.actor_membership_id == owner_membership_id,
                    ModelRun.purpose == "metadata_extract",
                )).all()
                assert len(runs) == 1
                run = runs[0]
                assert run.status == "ok" and run.provider == "openai"
                assert run.prompt_tokens == 8
                assert run.completion_tokens == 3
                assert run.prompt_hash is not None
                clause = session.scalar(select(ContractClause).where(
                    ContractClause.contract_id == contract_id,
                    ContractClause.created_by_membership_id == owner_membership_id,
                ))
                assert clause is not None and clause.clause_text == source
                retained = session.get(ContractAttachment, attachment_id)
                assert retained.extracted_text == source and retained.sha256_hex == source_hash
            usage = client.get("/api/admin/ai-token-governance", headers=_auth(token))
            assert usage.status_code == 200, usage.text
            assert usage.json()["firm_used_tokens"] == 11
            owner_usage = next(row for row in usage.json()["top_users"] if (
                row["actor_membership_id"] == owner_membership_id
            ))
            assert owner_usage["used_tokens"] == 11
            _set_policy(company_id, firm_quota_tokens=11, user_quota_tokens=11)
            exhausted = client.post(
                f"/api/ai/contracts/{contract_id}/clauses/extract", headers=_auth(token),
            )
            assert exhausted.status_code == 429, exhausted.text
        finally:
            if previous is None:
                client.app.dependency_overrides.pop(get_db_session, None)
            else:
                client.app.dependency_overrides[get_db_session] = previous
            for sdk in sdk_clients:
                sdk.close()
    with factory() as session:
        assert len(session.scalars(select(ModelRun).where(
                ModelRun.company_id == company_id,
                ModelRun.actor_membership_id == owner_membership_id,
                ModelRun.purpose == "metadata_extract",
        )).all()) == 1
    assert provider.calls == 1 and len(dispatches) == 1


def test_firm_quota_blocks_before_provider_call_and_redacts_audit(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "adp02-firm-block")
    company_id = str(boot["company"]["id"])
    owner_membership_id = _owner_membership_id(company_id)
    _set_policy(company_id, firm_quota_tokens=1)
    provider = _CountingProvider()
    sentinel_content = "SENTINEL_CONTENT_LEAK_MARKER"
    factory = get_session_factory()
    with factory() as session:
        with pytest.raises(HTTPException) as exc:
            generate_structured(
                provider,
                schema=_ToyPayload,
                messages=[LLMMessage(role="user", content=sentinel_content)],
                context=LLMCallContext(
                    tenant_id=company_id,
                    actor_membership_id=owner_membership_id,
                    purpose="matter_summary",
                ),
                max_tokens=16,
                session=session,
            )
    assert exc.value.status_code == 429
    assert provider.calls == 0
    with factory() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "ai_token_quota.request_blocked",
            )
        )
        assert audit is not None
        assert audit.result == "denied"
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["status"] == "blocked"
        assert metadata["scope"] == "firm"
        redacted = json.dumps(metadata)
        assert sentinel_content not in redacted
        assert "prompt" not in redacted.lower()
        assert "answer" not in redacted.lower()
        assert "source" not in redacted.lower()


def test_user_quota_blocks_before_provider_call(client: TestClient) -> None:
    boot = _bootstrap(client, "adp02-user-block")
    company_id = str(boot["company"]["id"])
    owner_membership_id = _owner_membership_id(company_id)
    _set_policy(company_id, user_quota_tokens=1)
    provider = _CountingProvider()
    factory = get_session_factory()
    with factory() as session:
        with pytest.raises(HTTPException) as exc:
            generate_structured(
                provider,
                schema=_ToyPayload,
                messages=[LLMMessage(role="user", content="request")],
                context=LLMCallContext(
                    tenant_id=company_id,
                    actor_membership_id=owner_membership_id,
                    purpose="drafting",
                ),
                max_tokens=16,
                session=session,
            )

    assert exc.value.status_code == 429
    assert provider.calls == 0
    with factory() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "ai_token_quota.request_blocked",
            )
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["scope"] == "user"
        assert metadata["actor_membership_id"] == owner_membership_id


def test_admin_ai_token_quota_update_permission_and_audit_redaction(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "adp02-admin")
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    _member_id, member_token = _invite_user(
        client,
        owner_token,
        company_slug=str(boot["_company_slug"]),
        email=f"member-{uuid4().hex[:8]}@adp02-admin.example",
        role="member",
    )

    forbidden = client.patch(
        "/api/admin/ai-token-governance",
        headers=_auth(member_token),
        json={
            "firm_quota_tokens": 1000,
            "user_quota_tokens": 100,
            "warning_threshold_percent": 85,
        },
    )
    assert forbidden.status_code == 403, forbidden.text

    response = client.patch(
        "/api/admin/ai-token-governance",
        headers=_auth(owner_token),
        json={
            "firm_quota_tokens": 1000,
            "user_quota_tokens": 100,
            "warning_threshold_percent": 85,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["firm_quota_tokens"] == 1000
    assert payload["user_quota_tokens"] == 100
    assert payload["warning_threshold_percent"] == 85
    factory = get_session_factory()
    with factory() as session:
        row = session.scalar(
            select(TenantAIPolicy).where(TenantAIPolicy.company_id == company_id)
        )
        assert row is not None
        assert row.monthly_token_budget == 1000
        assert row.user_monthly_token_budget == 100
        assert row.token_warning_threshold_percent == 85
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "ai_token_quota.updated",
            )
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["after"]["firm_quota_tokens"] == 1000
        redacted = json.dumps(metadata)
        assert "prompt" not in redacted.lower()
        assert "answer" not in redacted.lower()
        assert "source" not in redacted.lower()


def test_negative_ai_token_quota_is_rejected(client: TestClient) -> None:
    boot = _bootstrap(client, "adp02-negative")
    token = str(boot["access_token"])

    response = client.patch(
        "/api/admin/ai-token-governance",
        headers=_auth(token),
        json={
            "firm_quota_tokens": -1,
            "user_quota_tokens": None,
            "warning_threshold_percent": 90,
        },
    )

    assert response.status_code == 422, response.text
