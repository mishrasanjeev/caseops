from fastapi import APIRouter

from caseops_api.api.dependencies import DbSession
from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.schemas.ip_domains import IpDomainCatalogue
from caseops_api.services.ip_capability_catalog import domain_catalogue

router = APIRouter()


@router.get("/ip-domains", response_model=IpDomainCatalogue, summary="IP domain availability")
def ip_domain_availability(session: DbSession) -> IpDomainCatalogue:
    """Public release claims only; no tenant data, permissions or entitlements."""
    return domain_catalogue(session)


@router.get("/meta", summary="Service metadata")
async def metadata() -> dict[str, str]:
    """Public service metadata. In non-local envs we omit the
    environment + app URL fields to avoid handing reconnaissance
    value to attackers — this implements Codex's 2026-04-19
    cybersecurity review finding #9. The same data is still
    available to authenticated callers via /api/auth/me, which is
    where it actually belongs."""
    settings = get_settings()
    body: dict[str, str] = {
        "name": settings.api_name,
        "version": settings.api_version,
    }
    if not is_non_local_env(settings.env):
        # Local/dev keep the chatty response so smoke tests + the
        # operator's own tooling can still introspect cleanly.
        body["environment"] = settings.env
        body["appUrl"] = str(settings.public_app_url)
    return body
