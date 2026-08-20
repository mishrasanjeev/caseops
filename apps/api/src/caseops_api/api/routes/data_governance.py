"""Evidence-only tenant data-operation routes for IPLF-028B."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.data_governance import (
    TenantDataOperationDryRunRecord,
    TenantDataOperationDryRunRequest,
)
from caseops_api.services.data_governance import (
    create_dry_run_manifest,
    get_dry_run_manifest,
    reject_data_operation_execution,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
DataGovernanceOperator = Annotated[
    SessionContext,
    Depends(require_capability("audit:export")),
]


@router.post(
    "/operations/dry-runs",
    response_model=TenantDataOperationDryRunRecord,
    status_code=201,
    summary="Create a non-executable tenant data-operation dry run",
)
def create_operation_dry_run(
    payload: TenantDataOperationDryRunRequest,
    context: DataGovernanceOperator,
    session: DbSession,
) -> TenantDataOperationDryRunRecord:
    return create_dry_run_manifest(session, context=context, payload=payload)


@router.get(
    "/operations/dry-runs/{operation_id}",
    response_model=TenantDataOperationDryRunRecord,
    summary="Read a non-executable tenant data-operation dry run",
)
def read_operation_dry_run(
    operation_id: str,
    context: DataGovernanceOperator,
    session: DbSession,
) -> TenantDataOperationDryRunRecord:
    return get_dry_run_manifest(session, context=context, operation_id=operation_id)


@router.post(
    "/operations/{operation_id}/execute",
    response_model=None,
    summary="Refuse all tenant data-operation execution",
)
def execute_operation_is_unavailable(
    operation_id: str,
    context: DataGovernanceOperator,
) -> None:
    del context
    reject_data_operation_execution(operation_id=operation_id)
