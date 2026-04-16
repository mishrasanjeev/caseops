from fastapi import APIRouter

from caseops_api.api.routes import (
    ai,
    auth,
    bootstrap,
    companies,
    contracts,
    health,
    matters,
    meta,
    payments,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(bootstrap.router, prefix="/bootstrap", tags=["bootstrap"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(matters.router, prefix="/matters", tags=["matters"])
api_router.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
