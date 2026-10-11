"""Offline financial-denial regressions for every contract intelligence caller."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select, text

from caseops_api.core.automated_test_context import (
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    Contract,
    ContractAttachment,
    ContractClause,
    ContractObligation,
    ContractPlaybookRule,
    DocumentProcessingStatus,
    ModelRun,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.contracts import PartyClauseExtractionRequest
from caseops_api.services import contract_intelligence as mod
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import LLMCallContext, LLMProviderError
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company
from tests.test_contract_intelligence import _bootstrap, _create_contract

_DENIALS = [
    "AI monthly spending is awaiting reconciliation. No external request was sent.",
    (
        "The shared monthly AI budget is exhausted. Existing work remains available; "
        + "new paid generation is unavailable. No external request was sent."
    ),
    "AI spending controls are temporarily unavailable. No external request was sent.",
]
_WORKFLOWS = [
    "clauses/extract", "obligations/extract", "playbook/compare", "clauses/extract-by-party",
]
_PARTIES = {
    "first_party_name": "Acme India",
    "second_party_name": "Supplier India",
    "represented_party": "first",
}


@pytest.fixture(autouse=True)
def no_paid_marker():
    token = set_automated_test_request("no-paid-providers")
    try:
        yield
    finally:
        reset_automated_test_request(token)


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool


class _DeniedProvider:
    name = "mock"
    model = "caseops-mock-1"

    def __init__(self, detail: str, *, after_transient: bool = False):
        self.detail = detail
        self.after_transient = after_transient
        self.calls = 0
        self.transactions: list[bool] = []
        self.observe_transaction: Callable[[], bool] | None = None

    def generate(self, *_args, **_kwargs):
        assert paid_providers_blocked_for_request()
        self.calls += 1
        if self.observe_transaction is not None:
            self.transactions.append(self.observe_transaction())
        if self.after_transient and self.calls == 1:
            raise LLMProviderError("Offline transient failure.")
        raise AiMoneyBudgetError(self.detail) from RuntimeError("private-account-cause")


def _call_helper(provider, *, session=None):
    return mod._structured_with_retry(
        provider,
        schema=_Answer,
        messages=[],
        context=LLMCallContext(purpose="metadata_extract", tenant_id=None, matter_id=None),
        temperature=0.0,
        max_tokens=512,
        session=session,
        feature="extract clauses",
    )


@pytest.mark.parametrize("detail", _DENIALS)
@pytest.mark.parametrize("after_transient", [False, True])
def test_contract_financial_denial_is_safe_503_without_another_retry(detail, after_transient):
    provider = _DeniedProvider(detail, after_transient=after_transient)
    with pytest.raises(HTTPException) as caught:
        _call_helper(provider)
    assert caught.value.status_code == 503
    assert caught.value.detail == detail
    assert "private-account-cause" not in caught.value.detail
    assert "retry in a minute" not in caught.value.detail.lower()
    assert isinstance(caught.value.__cause__, AiMoneyBudgetError)
    assert provider.calls == (2 if after_transient else 1)


def _seed_contract(client):
    boot = _bootstrap(client)
    contract_id = _create_contract(client, boot["access_token"])
    with get_session_factory()() as session:
        session.add_all([
            ContractAttachment(
                contract_id=contract_id,
                original_filename="offline-source.pdf",
                storage_key=f"contracts/{contract_id}/offline-source.pdf",
                content_type="application/pdf",
                size_bytes=200,
                sha256_hex="0" * 64,
                processing_status=DocumentProcessingStatus.INDEXED,
                extracted_char_count=200,
                extracted_text="Acme India and Supplier India agree to pay within thirty days.",
            ),
            ContractClause(
                contract_id=contract_id, title="Retained automatic clause", clause_type="payment",
                clause_text="Pay within thirty days.", notes="[auto] accepted source",
            ),
            ContractClause(
                contract_id=contract_id, title="Retained human clause", clause_type="payment",
                clause_text="Counsel-reviewed payment terms.", notes="Human-authored",
            ),
            ContractObligation(
                contract_id=contract_id, title="Retained automatic obligation",
                description="[auto] Pay within thirty days.",
            ),
            ContractObligation(
                contract_id=contract_id, title="Retained human obligation",
                description="Counsel-reviewed obligation.",
            ),
            ContractPlaybookRule(
                contract_id=contract_id, rule_name="Retained payment rule", clause_type="payment",
                expected_position="Payment within thirty days.", severity="medium",
            ),
        ])
        session.commit()
    return boot, contract_id


def _snapshot(company_id, contract_id):
    with get_session_factory()() as session:
        targets = [(Contract, Contract.id == contract_id)]
        targets.extend((model, model.contract_id == contract_id) for model in (
            ContractAttachment, ContractClause, ContractObligation, ContractPlaybookRule,
        ))
        targets.extend([
            (ModelRun, ModelRun.company_id == company_id),
            (AuditEvent, AuditEvent.target_id == contract_id),
        ])
        return {
            model.__tablename__: [tuple(row) for row in session.execute(
                select(model.__table__).where(predicate).order_by(model.id)
            )]
            for model, predicate in targets
        }


@pytest.mark.parametrize("workflow", _WORKFLOWS)
@pytest.mark.parametrize("after_transient", [False, True])
def test_contract_http_financial_denial_preserves_all_prior_rows(
    client, monkeypatch, workflow, after_transient,
):
    boot, contract_id = _seed_contract(client)
    before = _snapshot(boot["company"]["id"], contract_id)
    assert len(before["contract_clauses"]) == len(before["contract_obligations"]) == 2
    provider = _DeniedProvider(_DENIALS[1], after_transient=after_transient)
    monkeypatch.setattr(mod, "build_provider", lambda **_: provider)
    response = client.post(
        f"/api/ai/contracts/{contract_id}/{workflow}",
        headers={
            "Authorization": f"Bearer {boot['access_token']}",
            "X-CaseOps-Automated-Test": "no-paid-providers",
        },
        **({"json": _PARTIES} if workflow == "clauses/extract-by-party" else {}),
    )
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == _DENIALS[1]
    expected_calls = 2 if after_transient else 1
    assert provider.calls == expected_calls
    assert _snapshot(boot["company"]["id"], contract_id) == before


@pytest.mark.parametrize("after_transient", [False, True])
def test_contract_financial_denial_does_not_rollback_caller_transaction(client, after_transient):
    provider = _DeniedProvider(_DENIALS[0], after_transient=after_transient)
    with get_session_factory()() as session:
        session.execute(text("SELECT 1"))
        assert session.in_transaction()
        provider.observe_transaction = session.in_transaction
        with pytest.raises(HTTPException) as caught:
            _call_helper(provider, session=session)
        assert caught.value.status_code == 503
        expected_calls = 2 if after_transient else 1
        assert provider.calls == expected_calls
        assert provider.transactions == [True] * expected_calls
        assert session.in_transaction()


@pytest.mark.parametrize("change", ["update", "insert", "delete", "flushed_delete"])
@pytest.mark.parametrize("after_transient", [False, True])
def test_contract_financial_denial_preserves_uncommitted_caller_changes(
    client, change, after_transient,
):
    boot, contract_id = _seed_contract(client)
    before = _snapshot(boot["company"]["id"], contract_id)
    provider = _DeniedProvider(_DENIALS[0], after_transient=after_transient)
    with get_session_factory()() as session:
        contract = session.get(Contract, contract_id)
        if change == "update":
            contract.title = "Uncommitted caller edit"
        elif change == "insert":
            pending = ContractClause(
                contract_id=contract_id, title="Uncommitted caller clause",
                clause_type="payment", clause_text="Retain this pending caller write.",
            )
            session.add(pending)
        else:
            clause = session.scalar(select(ContractClause).where(
                ContractClause.contract_id == contract_id,
            ))
            clause_id = clause.id
            if change == "delete":
                session.delete(clause)
            else:
                session.execute(delete(ContractClause).where(ContractClause.id == clause_id))
                assert session.get(ContractClause, clause_id) is None
        with pytest.raises(HTTPException) as caught:
            _call_helper(provider, session=session)
        assert caught.value.status_code == 503 and caught.value.detail == _DENIALS[0]
        assert provider.calls == (2 if after_transient else 1)
        assert session.in_transaction()
        if change == "update":
            assert contract in session.dirty and contract.title == "Uncommitted caller edit"
        elif change == "insert":
            assert pending in session.new
        elif change == "delete":
            assert clause in session.deleted
        else:
            assert session.get(ContractClause, clause_id) is None
        session.rollback()
    assert _snapshot(boot["company"]["id"], contract_id) == before


@pytest.mark.parametrize("workflow", _WORKFLOWS)
def test_contract_tenant_denial_precedes_financial_admission(client, monkeypatch, workflow):
    boot, contract_id = _seed_contract(client)
    before = _snapshot(boot["company"]["id"], contract_id)
    other = bootstrap_company(client)
    provider = _DeniedProvider(_DENIALS[1])
    monkeypatch.setattr(mod, "build_provider", lambda **_: provider)
    functions = {
        "clauses/extract": mod.extract_clauses,
        "obligations/extract": mod.extract_obligations,
        "playbook/compare": mod.compare_playbook,
        "clauses/extract-by-party": mod.extract_party_clauses,
    }
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, other["membership"]["id"])
        context = SessionContext(
            user=membership.user,
            company=session.get(Company, other["company"]["id"]),
            membership=membership,
        )
        with pytest.raises(ValueError, match="not found in this company"):
            functions[workflow](
                session, context=context, contract_id=contract_id,
                **({"payload": PartyClauseExtractionRequest(**_PARTIES)}
                   if workflow == "clauses/extract-by-party" else {}),
            )
    assert provider.calls == 0
    assert _snapshot(boot["company"]["id"], contract_id) == before
