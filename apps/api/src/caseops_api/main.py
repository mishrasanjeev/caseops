from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware

from caseops_api.api.router import api_router
from caseops_api.core.problem_details import problem_json, register_problem_handlers
from caseops_api.core.rate_limit import RateLimitExceeded, configure_limiter
from caseops_api.core.settings import get_settings
from caseops_api.db.migrations import run_migrations


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.auto_migrate:
        run_migrations()
    yield


def create_application() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.api_name,
        version=settings.api_version,
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
        lifespan=lifespan,
    )
    limiter = configure_limiter()
    application.state.limiter = limiter
    application.add_middleware(SlowAPIMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(
        request: Request, exc: RateLimitExceeded
    ) -> JSONResponse:
        return problem_json(
            429,
            detail=f"Rate limit exceeded: {exc.detail}",
            request=request,
        )

    # RFC 7807 — HTTPException + RequestValidationError get reshaped
    # into application/problem+json with a stable `type` slug so the
    # frontend can render context-aware recovery copy.
    register_problem_handlers(application)

    application.include_router(api_router, prefix="/api")
    return application


app = create_application()
