from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.ip_specialist_workflows import (
    ContractCostCreate,
    ContractCostOption,
    ContractCostOptions,
    ContractCostVoid,
    ContractObligation,
    ContractObligationList,
    ContractObligationRecord,
    ContractPerformance,
    ContractPerformanceList,
    ContractPerformanceRecord,
    WorkflowList,
    WorkflowRecord,
    WorkflowSave,
)
from caseops_api.services import ip_specialist_workflows as service
from caseops_api.services.session_context import SessionContext

router = APIRouter(prefix="/records/{record_id}/workflows", tags=["ip-specialist-workflows"])
Reader = Annotated[SessionContext, Depends(require_capability("ip:read"))]
Writer = Annotated[SessionContext, Depends(require_capability("ip:write"))]
Key = Annotated[str, Header(min_length=1, max_length=200, pattern=r"\S")]


@router.get("/{workflow_id}/cost-options", response_model=ContractCostOptions)
def cost_options(
    record_id: UUID,
    workflow_id: UUID,
    context: Reader,
    session: DbSession,
    cursor: UUID | None = None,
):
    return service.cost_options(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        cursor=cursor,
    )


@router.post("/{workflow_id}/cost-evidence", response_model=ContractCostOption, status_code=201)
def create_cost(
    record_id: UUID,
    workflow_id: UUID,
    payload: ContractCostCreate,
    context: Writer,
    session: DbSession,
    idempotency_key: Key,
):
    return service.record_cost(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/{workflow_id}/cost-evidence/{cost_id}/void", response_model=ContractCostOption)
def void_cost(
    record_id: UUID,
    workflow_id: UUID,
    cost_id: UUID,
    payload: ContractCostVoid,
    context: Writer,
    session: DbSession,
    idempotency_key: Key,
):
    return service.record_cost(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        cost_id=str(cost_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("", response_model=WorkflowList)
def list_workflows(
    record_id: UUID,
    context: Reader,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=10)] = 10,
    cursor: UUID | None = None,
):
    return service.list_workflows(
        session, context=context, record_id=str(record_id), limit=limit, cursor=cursor
    )


@router.post("", response_model=WorkflowRecord, status_code=201)
def create_workflow(
    record_id: UUID,
    payload: WorkflowSave,
    context: Writer,
    session: DbSession,
    idempotency_key: Key,
):
    return service.save_workflow(
        session,
        context=context,
        record_id=str(record_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/{workflow_id}", response_model=WorkflowRecord)
def get_workflow(record_id: UUID, workflow_id: UUID, context: Reader, session: DbSession):
    return service.get_workflow(
        session, context=context, record_id=str(record_id), workflow_id=str(workflow_id)
    )


@router.get("/{workflow_id}/versions/{version}", response_model=WorkflowRecord)
def get_version(
    record_id: UUID,
    workflow_id: UUID,
    version: Annotated[int, Path(ge=1)],
    context: Reader,
    session: DbSession,
):
    return service.get_workflow(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        version=version,
    )


@router.post("/{workflow_id}/revisions", response_model=WorkflowRecord)
def revise_workflow(
    record_id: UUID,
    workflow_id: UUID,
    payload: WorkflowSave,
    context: Writer,
    session: DbSession,
    idempotency_key: Key,
):
    return service.save_workflow(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/{workflow_id}/obligations", response_model=ContractObligationRecord, status_code=201)
def create_obligation(
    record_id: UUID,
    workflow_id: UUID,
    payload: ContractObligation,
    context: Writer,
    session: DbSession,
    idempotency_key: Key,
):
    return service.create_obligation(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/{workflow_id}/obligations/{obligation_id}", response_model=ContractObligationRecord)
def get_obligation(
    record_id: UUID, workflow_id: UUID, obligation_id: UUID, context: Reader, session: DbSession
):
    return service.get_obligation(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        obligation_id=str(obligation_id),
    )


@router.get("/{workflow_id}/obligations", response_model=ContractObligationList)
def list_obligations(
    record_id: UUID,
    workflow_id: UUID,
    context: Reader,
    session: DbSession,
    cursor: UUID | None = None,
):
    return service.list_obligations(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        cursor=cursor,
    )


@router.post(
    "/{workflow_id}/obligations/{obligation_id}/performance",
    response_model=ContractPerformanceRecord,
    status_code=201,
)
def record_performance(
    record_id: UUID,
    workflow_id: UUID,
    obligation_id: UUID,
    payload: ContractPerformance,
    context: Writer,
    session: DbSession,
    idempotency_key: Key,
):
    return service.record_performance(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        obligation_id=str(obligation_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/{workflow_id}/obligations/{obligation_id}/performance", response_model=ContractPerformanceList
)
def performance_history(
    record_id: UUID,
    workflow_id: UUID,
    obligation_id: UUID,
    context: Reader,
    session: DbSession,
    cursor: UUID | None = None,
):
    return service.performance_history(
        session,
        context=context,
        record_id=str(record_id),
        workflow_id=str(workflow_id),
        obligation_id=str(obligation_id),
        cursor=cursor,
    )
