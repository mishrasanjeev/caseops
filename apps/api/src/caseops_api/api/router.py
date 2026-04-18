from fastapi import APIRouter

from caseops_api.api.routes import (
    admin,
    ai,
    auth,
    authorities,
    bootstrap,
    companies,
    contracts,
    courts,
    health,
    intake,
    matters,
    meta,
    outside_counsel,
    payments,
    recommendations,
    teams,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(bootstrap.router, prefix="/bootstrap", tags=["bootstrap"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(matters.router, prefix="/matters", tags=["matters"])
api_router.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
api_router.include_router(
    outside_counsel.router,
    prefix="/outside-counsel",
    tags=["outside_counsel"],
)
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(authorities.router, prefix="/authorities", tags=["authorities"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(recommendations.router, tags=["recommendations"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(courts.router, prefix="/courts", tags=["courts"])
api_router.include_router(intake.router, prefix="/intake", tags=["intake"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
