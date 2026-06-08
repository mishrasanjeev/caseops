from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.integrations import TenantConnectorRegistryResponse
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.integrations import tenant_connector_registry

router = APIRouter()
WorkspaceAdmin = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]


@router.get("", response_model=TenantConnectorRegistryResponse)
def get_admin_integrations(
    context: WorkspaceAdmin,
    session: DbSession,
) -> TenantConnectorRegistryResponse:
    connectors = tenant_connector_registry(session, context=context)
    record_from_context(
        session,
        context,
        action="connector_registry.viewed",
        target_type="connector_registry",
        metadata={"connector_count": len(connectors)},
    )
    session.commit()
    return TenantConnectorRegistryResponse(connectors=connectors)
