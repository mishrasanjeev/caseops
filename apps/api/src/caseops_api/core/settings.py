from functools import lru_cache

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_AUTH_SECRET = "change-me-change-me-change-me-2026"
NON_LOCAL_ENVS = {"staging", "production", "prod"}
LOCAL_POSTGRES_DATABASE_URL = "postgresql+psycopg://caseops:caseops@127.0.0.1:5432/caseops"


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
    api_docs_enabled: bool = Field(default=True)
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
    llm_model: str = Field(default="caseops-mock-1")
    llm_api_key: str | None = Field(default=None)
    llm_max_output_tokens: int = Field(default=2048, ge=256)
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
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

    @model_validator(mode="after")
    def _reject_placeholder_secret_outside_local(self) -> "Settings":
        if self.env.lower() in NON_LOCAL_ENVS and self.auth_secret == PLACEHOLDER_AUTH_SECRET:
            raise ValueError(
                "CASEOPS_AUTH_SECRET must be set to a non-placeholder value when "
                f"CASEOPS_ENV={self.env!r}.",
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
