from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.contracts import (
    ContractClauseCreateRequest,
    ContractClauseRecord,
    ContractCreateRequest,
    ContractListResponse,
    ContractObligationCreateRequest,
    ContractObligationRecord,
    ContractPlaybookRuleCreateRequest,
    ContractPlaybookRuleRecord,
    ContractRecord,
    ContractUpdateRequest,
    ContractWorkspaceResponse,
)
from caseops_api.services.contracts import (
    create_contract,
    create_contract_clause,
    create_contract_obligation,
    create_contract_playbook_rule,
    get_contract,
    get_contract_workspace,
    list_contracts,
    update_contract,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get(
    "/",
    response_model=ContractListResponse,
    summary="List contracts for the current company",
)
async def current_company_contracts(
    context: CurrentContext,
    session: DbSession,
) -> ContractListResponse:
    return list_contracts(session, context=context)


@router.post("/", response_model=ContractRecord, summary="Create a contract in the current company")
async def create_current_company_contract(
    payload: ContractCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> ContractRecord:
    return create_contract(session, context=context, payload=payload)


@router.get("/{contract_id}", response_model=ContractRecord, summary="Get a contract by id")
async def get_current_company_contract(
    contract_id: str,
    context: CurrentContext,
    session: DbSession,
) -> ContractRecord:
    return get_contract(session, context=context, contract_id=contract_id)


@router.get(
    "/{contract_id}/workspace",
    response_model=ContractWorkspaceResponse,
    summary="Get the full contract workspace",
)
async def get_current_company_contract_workspace(
    contract_id: str,
    context: CurrentContext,
    session: DbSession,
) -> ContractWorkspaceResponse:
    return get_contract_workspace(session, context=context, contract_id=contract_id)


@router.patch("/{contract_id}", response_model=ContractRecord, summary="Update a contract")
async def patch_current_company_contract(
    contract_id: str,
    payload: ContractUpdateRequest,
    context: CurrentContext,
    session: DbSession,
) -> ContractRecord:
    return update_contract(session, context=context, contract_id=contract_id, payload=payload)


@router.post(
    "/{contract_id}/clauses",
    response_model=ContractClauseRecord,
    summary="Add a clause to a contract",
)
async def post_current_company_contract_clause(
    contract_id: str,
    payload: ContractClauseCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> ContractClauseRecord:
    return create_contract_clause(
        session,
        context=context,
        contract_id=contract_id,
        payload=payload,
    )


@router.post(
    "/{contract_id}/obligations",
    response_model=ContractObligationRecord,
    summary="Add an obligation to a contract",
)
async def post_current_company_contract_obligation(
    contract_id: str,
    payload: ContractObligationCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> ContractObligationRecord:
    return create_contract_obligation(
        session,
        context=context,
        contract_id=contract_id,
        payload=payload,
    )


@router.post(
    "/{contract_id}/playbook-rules",
    response_model=ContractPlaybookRuleRecord,
    summary="Add a playbook rule to a contract",
)
async def post_current_company_contract_playbook_rule(
    contract_id: str,
    payload: ContractPlaybookRuleCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> ContractPlaybookRuleRecord:
    return create_contract_playbook_rule(
        session,
        context=context,
        contract_id=contract_id,
        payload=payload,
    )
