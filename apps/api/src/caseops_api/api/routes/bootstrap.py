from __future__ import annotations

from fastapi import APIRouter, Request, Response

from caseops_api.api.dependencies import DbSession
from caseops_api.core.cookies import issue_session_cookies
from caseops_api.core.rate_limit import bootstrap_rate_limit, limiter
from caseops_api.core.settings import get_settings
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
    response: Response,
    payload: BootstrapCompanyRequest,
    session: DbSession,
) -> AuthSessionResponse:
    auth = register_company_owner(session, payload)
    # EG-001: issue cookies on the just-created session so the web
    # client lands on a logged-in cockpit without an extra /login
    # round-trip.
    settings = get_settings()
    issue_session_cookies(
        response,
        access_token=auth.access_token,
        ttl_seconds=settings.access_token_ttl_minutes * 60,
        env=settings.env,
    )
    return auth
