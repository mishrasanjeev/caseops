from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.integrations import (
    ConnectorHealthCheckResponse,
    ConnectorHealthListResponse,
    TenantConnectorRegistryResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.connector_health import (
    check_tenant_connector_health,
    list_tenant_connector_health,
)
from caseops_api.services.integrations import tenant_connector_registry
from caseops_api.services.session_context import SessionContext

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


@router.get("/health", response_model=ConnectorHealthListResponse)
def get_admin_integrations_health(
    context: WorkspaceAdmin,
    session: DbSession,
) -> ConnectorHealthListResponse:
    response = list_tenant_connector_health(session, context=context)
    record_from_context(
        session,
        context,
        action="connector_health.viewed",
        target_type="connector_health",
        metadata={"record_count": len(response.health)},
    )
    session.commit()
    return response


@router.post("/health/check", response_model=ConnectorHealthCheckResponse)
def post_admin_integrations_health_check(
    context: WorkspaceAdmin,
    session: DbSession,
) -> ConnectorHealthCheckResponse:
    return check_tenant_connector_health(session, context=context)
