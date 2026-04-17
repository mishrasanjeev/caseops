from __future__ import annotations

from fastapi import APIRouter, Request

from caseops_api.api.dependencies import DbSession
from caseops_api.core.rate_limit import bootstrap_rate_limit, limiter
from caseops_api.schemas.auth import AuthSessionResponse
from caseops_api.schemas.companies import BootstrapCompanyRequest
from caseops_api.services.identity import register_company_owner

router = APIRouter()


@router.post(
    "/company",
    response_model=AuthSessionResponse,
    summary="Create a company and owner",
)
@limiter.limit(bootstrap_rate_limit)
async def bootstrap_company(
    request: Request,
    payload: BootstrapCompanyRequest,
    session: DbSession,
) -> AuthSessionResponse:
    return register_company_owner(session, payload)
