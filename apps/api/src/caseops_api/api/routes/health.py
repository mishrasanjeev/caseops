from fastapi import APIRouter

router = APIRouter()


@router.get("/health", summary="Service health probe")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
