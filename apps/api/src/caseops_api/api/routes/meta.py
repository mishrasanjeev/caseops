from fastapi import APIRouter

from caseops_api.core.settings import get_settings

router = APIRouter()


@router.get("/meta", summary="Service metadata")
async def metadata() -> dict[str, str]:
    settings = get_settings()
    return {
        "name": settings.api_name,
        "version": settings.api_version,
        "environment": settings.env,
        "appUrl": str(settings.public_app_url),
    }
