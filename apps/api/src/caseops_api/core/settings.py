from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    database_url: str = Field(default="sqlite+pysqlite:///./caseops.db")
    auth_secret: str = Field(default="change-me-change-me-change-me-2026", min_length=32)
    access_token_ttl_minutes: int = Field(default=120)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    auto_migrate: bool = Field(default=True)
    document_storage_path: str = Field(default="./storage/documents")
    max_attachment_size_bytes: int = Field(default=25 * 1024 * 1024)
    pine_labs_api_base_url: str | None = Field(default=None)
    pine_labs_payment_link_path: str | None = Field(default=None)
    pine_labs_payment_status_path: str | None = Field(default=None)
    pine_labs_merchant_id: str | None = Field(default=None)
    pine_labs_api_key: str | None = Field(default=None)
    pine_labs_api_secret: str | None = Field(default=None)
    pine_labs_webhook_secret: str | None = Field(default=None)
    pine_labs_webhook_signature_header: str = Field(default="X-PineLabs-Signature")
    pine_labs_request_timeout_seconds: int = Field(default=30)


@lru_cache
def get_settings() -> Settings:
    return Settings()
