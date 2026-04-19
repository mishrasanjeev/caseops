from functools import lru_cache

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_AUTH_SECRET = "change-me-change-me-change-me-2026"

# Codex's 2026-04-19 cybersecurity review (finding #3) flagged that
# Cloud Run's `CASEOPS_ENV=cloud` was treated as local because the
# allow-list only enumerated staging/production/prod. That meant the
# placeholder-auth-secret guard and CORS auto-augment didn't fire on
# the actual deployed profile. Inverted to a strict local allow-list
# so any unknown env (including "cloud", "gke", "ee-prod", etc.)
# defaults to non-local — fail closed.
LOCAL_ENVS = {"local", "dev", "test", "ci", "e2e"}
# Kept for backwards-compatible imports; downstream code should
# prefer the helper `is_non_local_env(env)` below.
NON_LOCAL_ENVS = {"staging", "production", "prod", "cloud", "gke"}
LOCAL_POSTGRES_DATABASE_URL = "postgresql+psycopg://caseops:caseops@127.0.0.1:5432/caseops"


def is_non_local_env(env_value: str | None) -> bool:
    """Strict allow-list of local/dev environments. Anything else —
    including unknown names — is treated as non-local so security
    guards (auth secret, strict CORS, docs gating) apply."""
    return (env_value or "").strip().lower() not in LOCAL_ENVS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CASEOPS_",
        extra="ignore",
    )

    env: str = Field(default="local")
    api_name: str = Field(default="CaseOps API")
    api_version: str = Field(default="0.1.0")
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    # Codex's 2026-04-19 cybersecurity review (finding #9): docs were
    # opt-out, which means an accidental cloud deploy with default
    # CASEOPS_API_DOCS_ENABLED would expose /docs + /openapi.json
    # publicly and increase reconnaissance value. The flag still
    # exists, but the effective default is now env-aware (see
    # `effective_docs_enabled`). Operators can still force-enable
    # docs in prod by setting the env explicitly.
    api_docs_enabled: bool | None = Field(default=None)
    public_app_url: AnyHttpUrl = Field(default="http://localhost:3000")
    database_url: str = Field(default=LOCAL_POSTGRES_DATABASE_URL)
    auth_secret: str = Field(default=PLACEHOLDER_AUTH_SECRET, min_length=32)
    access_token_ttl_minutes: int = Field(default=120)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    auto_migrate: bool = Field(default=True)
    document_storage_backend: str = Field(default="local")
    document_storage_path: str = Field(default="./storage/documents")
    document_storage_cache_path: str = Field(default="./storage/document-cache")
    document_storage_gcs_bucket: str | None = Field(default=None)
    document_storage_gcs_prefix: str = Field(default="documents")
    gcp_project_id: str | None = Field(default=None)
    max_attachment_size_bytes: int = Field(default=25 * 1024 * 1024)
    tesseract_command: str | None = Field(default=None)
    document_worker_poll_interval_seconds: int = Field(default=10, ge=1)
    document_worker_batch_size: int = Field(default=5, ge=1)
    document_processing_stale_after_minutes: int = Field(default=15, ge=1)
    document_retry_after_hours: int = Field(default=6, ge=0)
    document_reindex_after_hours: int = Field(default=168, ge=0)
    document_reprocessing_batch_size: int = Field(default=10, ge=1)
    court_sync_worker_batch_size: int = Field(default=3, ge=1)
    court_sync_stale_after_minutes: int = Field(default=15, ge=1)
    pine_labs_api_base_url: str | None = Field(default=None)
    pine_labs_payment_link_path: str | None = Field(default=None)
    pine_labs_payment_status_path: str | None = Field(default=None)
    pine_labs_merchant_id: str | None = Field(default=None)
    pine_labs_api_key: str | None = Field(default=None)
    pine_labs_api_secret: str | None = Field(default=None)
    pine_labs_webhook_secret: str | None = Field(default=None)
    pine_labs_webhook_signature_header: str = Field(default="X-PineLabs-Signature")
    pine_labs_request_timeout_seconds: int = Field(default=30)

    auth_rate_limit_login_per_minute: int = Field(default=20, ge=1)
    auth_rate_limit_bootstrap_per_hour: int = Field(default=10, ge=1)
    auth_rate_limit_enabled: bool = Field(default=True)

    llm_provider: str = Field(default="mock")
    # Fallback model when a purpose-specific one is not set. Per-purpose
    # routing (below) exists because legal drafting benefits from Opus
    # while metadata extraction is fine on Haiku. Using one model for
    # every call is either paying Opus prices for extraction or shipping
    # Haiku-quality briefs.
    llm_model: str = Field(default="caseops-mock-1")
    llm_model_drafting: str | None = Field(default=None)
    llm_model_recommendations: str | None = Field(default=None)
    llm_model_hearing_pack: str | None = Field(default=None)
    llm_model_metadata_extract: str | None = Field(default=None)
    llm_model_eval: str | None = Field(default=None)
    llm_api_key: str | None = Field(default=None)
    llm_max_output_tokens: int = Field(default=2048, ge=256)
    # Drafting warrants a bigger ceiling — full bail applications /
    # review memos can hit 8-12k output tokens. Recommendations are
    # structured JSON and stay tight.
    llm_max_output_tokens_drafting: int = Field(default=8192, ge=512)
    llm_max_output_tokens_hearing_pack: int = Field(default=4096, ge=512)
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    # Anthropic ephemeral prompt caching (5-min TTL) on the large
    # system prompt. When true, repeated calls within 5 min share the
    # cache block and pay ~10% of the full prompt cost.
    llm_prompt_cache_enabled: bool = Field(default=True)
    # LLM cassette — record real provider responses to a JSON file in
    # "record" mode, replay them deterministically in "replay" mode,
    # bypass entirely in "off" mode (default). Powers Sprint 11 offline
    # eval runs: capture once with credentials, replay forever in CI.
    llm_cassette_mode: str = Field(default="off")
    llm_cassette_path: str | None = Field(default=None)
    recommendation_review_required_default: bool = Field(default=True)

    embedding_provider: str = Field(default="mock")
    embedding_model: str = Field(default="caseops-mock-embed")
    embedding_api_key: str | None = Field(default=None)
    embedding_dimensions: int = Field(default=1024, ge=64, le=4096)
    # Streaming corpus ingestion caps — keep workstation disk safe.
    corpus_ingest_batch_size: int = Field(default=25, ge=1, le=500)
    corpus_ingest_max_workdir_mb: int = Field(default=500, ge=32, le=20000)
    corpus_ingest_temp_root: str | None = Field(default=None)
    # OCR fallback for scanned judgment PDFs. Defaults to rapidocr (pure
    # Python, ONNX, no native binary). Set to `none` to disable.
    ocr_provider: str = Field(default="rapidocr")
    ocr_min_chars_before_fallback: int = Field(default=600, ge=0)
    ocr_render_dpi: int = Field(default=220, ge=72, le=600)
    ocr_max_pages: int = Field(default=40, ge=1, le=1000)
    ocr_languages: str = Field(default="eng")

    # Observability. JSON logging is the default; text mode is for
    # local dev. OTel is opt-in because the exporter + instrumentations
    # need a live collector to be useful.
    log_format: str = Field(default="json")
    log_level: str = Field(default="INFO")
    otel_enabled: bool = Field(default=False)
    otel_endpoint: str = Field(default="http://localhost:4318/v1/traces")
    otel_service_name: str = Field(default="caseops-api")

    @property
    def effective_docs_enabled(self) -> bool:
        """Resolve the docs flag with an env-aware default. Local/dev
        get docs ON by default; non-local envs get docs OFF unless the
        operator explicitly set ``CASEOPS_API_DOCS_ENABLED=true``.

        This implements Codex's 2026-04-19 finding #9 fix: an
        accidental cloud deploy without the flag set no longer
        publishes /docs + /openapi.json."""
        if self.api_docs_enabled is not None:
            return bool(self.api_docs_enabled)
        return not is_non_local_env(self.env)

    @model_validator(mode="after")
    def _reject_placeholder_secret_outside_local(self) -> "Settings":
        if is_non_local_env(self.env) and self.auth_secret == PLACEHOLDER_AUTH_SECRET:
            raise ValueError(
                "CASEOPS_AUTH_SECRET must be set to a non-placeholder value when "
                f"CASEOPS_ENV={self.env!r}.",
            )
        return self

    @model_validator(mode="after")
    def _augment_local_cors_origins(self) -> "Settings":
        """In non-prod envs, auto-allow common dev ports so the local
        dev server, the Playwright e2e prod build (port 3100), and ad-
        hoc probes (3500) all reach the API without CORS preflight
        blocks. Production envs keep the strict configured list — a
        stale dev port slipping into a deployed allow-list would be a
        real security smell.

        The bug this fixes: a Playwright run on http://127.0.0.1:3100
        kept hitting CORS preflight failures because the dev .env
        only listed :3000. Browser blocked POST /api/auth/login,
        mutation onError fired, and the page never left /sign-in —
        the exact symptom Codex reported on 2026-04-19."""
        if is_non_local_env(self.env):
            return self
        DEV_PORTS = ("3000", "3100", "3500")
        DEV_HOSTS = ("localhost", "127.0.0.1")
        augmented: list[str] = list(self.cors_origins)
        for host in DEV_HOSTS:
            for port in DEV_PORTS:
                candidate = f"http://{host}:{port}"
                if candidate not in augmented:
                    augmented.append(candidate)
        # Pydantic-settings stores the list as immutable on the model;
        # reassign via object.__setattr__ to bypass the freeze.
        object.__setattr__(self, "cors_origins", augmented)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
