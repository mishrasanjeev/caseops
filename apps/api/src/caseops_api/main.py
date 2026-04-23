from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware

from caseops_api.api.router import api_router
from caseops_api.core.csrf import CSRFMiddleware
from caseops_api.core.observability import configure_logging, configure_tracing
from caseops_api.core.problem_details import problem_json, register_problem_handlers
from caseops_api.core.rate_limit import RateLimitExceeded, configure_limiter
from caseops_api.core.request_context import RequestContextMiddleware
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
    # Install JSON logging + (optional) OTel before building the app
    # so the FastAPI instrumentor can see the new logger + tracer.
    configure_logging()
    application = FastAPI(
        title=settings.api_name,
        version=settings.api_version,
        # effective_docs_enabled is env-aware: dev/local default ON,
        # cloud/prod/unknown default OFF unless explicitly enabled.
        # Closes Codex finding #9.
        docs_url="/docs" if settings.effective_docs_enabled else None,
        redoc_url="/redoc" if settings.effective_docs_enabled else None,
        openapi_url="/openapi.json" if settings.effective_docs_enabled else None,
        lifespan=lifespan,
    )
    configure_tracing(application)
    limiter = configure_limiter()
    application.state.limiter = limiter
    # Request context runs FIRST so every downstream middleware + handler
    # sees the request_id on every log line.
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(SlowAPIMiddleware)
    # EG-001 (2026-04-23): CSRF middleware. The bearer-auth path is
    # exempt — see core/csrf.py for the policy. Order matters:
    # Starlette wraps later-added middleware OUTSIDE earlier ones,
    # so we add CSRF BEFORE CORS. Effective request flow:
    # CORS → CSRF → SlowAPI → RequestContext → app. That keeps CORS
    # outermost so a 403 from CSRF still picks up
    # ``Access-Control-Allow-Origin`` on the way out and the browser
    # surfaces it as a real HTTP error rather than a generic CORS
    # block.
    application.add_middleware(CSRFMiddleware)
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
