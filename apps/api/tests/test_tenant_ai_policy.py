"""Tenant AI policy schema + resolver (BG-046 schema)."""
from __future__ import annotations

import json

from sqlalchemy import select

from caseops_api.db.models import Company, TenantAIPolicy
from caseops_api.db.session import get_session_factory
from caseops_api.services.tenant_ai_policy import (
    DEFAULT_POLICY,
    is_model_allowed,
    resolve_tenant_policy,
)
from tests.test_auth_company import bootstrap_company


def test_resolver_returns_default_when_no_row(client) -> None:  # noqa: ARG001
    bootstrap_company(client)
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        policy = resolve_tenant_policy(session, company_id=company.id)
    assert policy.allowed_drafting == ()
    assert policy.allowed_assistant == ()
    assert policy.workspace_assistant_enabled is False
    assert policy.assistant_retention_days == 90
    assert policy.policy_version == 1
    assert policy.max_tokens_per_session == DEFAULT_POLICY.max_tokens_per_session
    assert policy.external_share_requires_approval is True


def test_resolver_parses_allowed_models(client) -> None:  # noqa: ARG001
    bootstrap_company(client)
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        row = TenantAIPolicy(
            company_id=company.id,
            allowed_models_drafting_json=json.dumps(["gpt-5.1"]),
            allowed_models_recommendations_json=json.dumps(
                ["gpt-5-mini", "gpt-5.1"]
            ),
            allowed_models_hearing_pack_json=json.dumps([]),
            allowed_models_assistant_json=json.dumps(["caseops-assistant-1"]),
            workspace_assistant_enabled=True,
            assistant_retention_days=120,
            policy_version=3,
            max_tokens_per_session=12000,
            external_share_requires_approval=False,
            training_opt_in=True,
        )
        session.add(row)
        session.commit()

        policy = resolve_tenant_policy(session, company_id=company.id)
    assert policy.allowed_drafting == ("gpt-5.1",)
    assert "gpt-5-mini" in policy.allowed_recommendations
    assert policy.allowed_hearing_pack == ()  # empty list → no restriction
    assert policy.allowed_assistant == ("caseops-assistant-1",)
    assert policy.workspace_assistant_enabled is True
    assert policy.assistant_retention_days == 120
    assert policy.policy_version == 3
    assert policy.max_tokens_per_session == 12000
    assert policy.external_share_requires_approval is False
    assert policy.training_opt_in is True


def test_is_model_allowed_honours_allowlist(client) -> None:  # noqa: ARG001
    bootstrap_company(client)
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        row = TenantAIPolicy(
            company_id=company.id,
            allowed_models_drafting_json=json.dumps(["gpt-5.1"]),
            allowed_models_recommendations_json=json.dumps([]),
            allowed_models_hearing_pack_json=json.dumps([]),
            max_tokens_per_session=16384,
            external_share_requires_approval=True,
            training_opt_in=False,
        )
        session.add(row)
        session.commit()
        policy = resolve_tenant_policy(session, company_id=company.id)

    assert is_model_allowed(
        policy, purpose="drafting", model="gpt-5.1"
    ) is True
    assert is_model_allowed(
        policy, purpose="drafting", model="gpt-5-nano"
    ) is False
    # Empty allowlist on a purpose means no restriction.
    assert is_model_allowed(
        policy, purpose="recommendations", model="anything"
    ) is True
    assert is_model_allowed(
        policy, purpose="assistant", model="anything"
    ) is True


def test_recommendation_subpurpose_honours_recommendations_allowlist(client) -> None:  # noqa: ARG001
    bootstrap_company(client)
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        row = TenantAIPolicy(
            company_id=company.id,
            allowed_models_drafting_json=json.dumps([]),
            allowed_models_recommendations_json=json.dumps(["caseops-approved-rec"]),
            allowed_models_hearing_pack_json=json.dumps([]),
            max_tokens_per_session=16384,
            external_share_requires_approval=True,
            training_opt_in=False,
        )
        session.add(row)
        session.commit()
        policy = resolve_tenant_policy(session, company_id=company.id)

    assert is_model_allowed(
        policy, purpose="recommendation:authority", model="caseops-approved-rec"
    ) is True
    assert is_model_allowed(
        policy, purpose="recommendation:authority", model="caseops-other-rec"
    ) is False


def test_garbage_json_is_treated_as_empty_allowlist(client) -> None:  # noqa: ARG001
    bootstrap_company(client)
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        row = TenantAIPolicy(
            company_id=company.id,
            allowed_models_drafting_json="not-valid-json",
            allowed_models_recommendations_json="[1,2,3]",  # not strings
            allowed_models_hearing_pack_json="{\"oops\": 1}",  # dict
            max_tokens_per_session=16384,
            external_share_requires_approval=True,
            training_opt_in=False,
        )
        session.add(row)
        session.commit()
        policy = resolve_tenant_policy(session, company_id=company.id)
    # Garbage / wrong-shape JSON degrades to empty (no restriction)
    # rather than crashing. Defence in depth — the database should
    # never yield unreadable policy.
    assert policy.allowed_drafting == ()
    assert policy.allowed_recommendations == ()
    assert policy.allowed_hearing_pack == ()
