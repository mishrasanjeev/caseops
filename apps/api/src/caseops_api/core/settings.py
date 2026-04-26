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
    # EG-002 (2026-04-23): default still True for local/dev so the
    # docker-compose stack and pytest fixtures keep their current
    # behaviour. A model_validator below errors out when env is
    # production/cloud AND auto_migrate stayed True — that
    # combination is the multi-instance migration race we banned.
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

    # Hearing reminders (MOD-TS-007 Sprint T first slice — dark-
    # launched on 2026-04-22). Rows accumulate in ``hearing_reminders``
    # the moment a hearing is scheduled. The worker only sends when
    # both the feature flag AND the provider config are set; otherwise
    # it logs "would send" and leaves the row at QUEUED so flipping
    # the flag later doesn't need a backfill.
    hearing_reminders_enabled: bool = Field(default=False)
    hearing_reminder_offsets_hours: list[int] = Field(
        default_factory=lambda: [24, 1],
    )
    sendgrid_api_key: str | None = Field(default=None)
    sendgrid_sender_email: str | None = Field(default=None)
    sendgrid_sender_name: str = Field(default="CaseOps")
    # Public key that SendGrid signs event webhooks with. When set,
    # the webhook endpoint refuses to process events whose signature
    # doesn't verify — keeping an attacker from forging "delivered"
    # events against our tenants.
    sendgrid_webhook_public_key: str | None = Field(default=None)

    # MOD-TS-007 (2026-04-26) — SMS via Twilio. Disabled by default
    # so a fresh deployment never burns money on a test SMS. Flip
    # CASEOPS_TWILIO_ENABLED=true and provide all three other env
    # vars to wire the channel; the worker still respects the
    # per-hearing/per-channel uniqueness constraint so retries don't
    # duplicate billable messages.
    twilio_enabled: bool = Field(default=False)
    twilio_account_sid: str | None = Field(default=None)
    twilio_auth_token: str | None = Field(default=None)
    twilio_from_number: str | None = Field(default=None)

    # MOD-TS-007 (2026-04-26) — WhatsApp via Meta Cloud API. Disabled
    # by default; needs Meta-approved templates per deployment so
    # the integration can send transactional reminders without
    # 24-hour-window restrictions. Flip CASEOPS_WHATSAPP_ENABLED=true
    # plus all three other env vars to wire it.
    whatsapp_enabled: bool = Field(default=False)
    whatsapp_access_token: str | None = Field(default=None)
    whatsapp_phone_number_id: str | None = Field(default=None)
    whatsapp_template_name: str | None = Field(default=None)
    # MSG91 / other Indian SMS providers can land via the same
    # adapter pattern — Twilio first because the developer-experience
    # is well-documented and the SDK isn't required (basic-auth POST).
    msg91_auth_key: str | None = Field(default=None)
    msg91_sender_id: str | None = Field(default=None)

    auth_rate_limit_login_per_minute: int = Field(default=20, ge=1)
    auth_rate_limit_bootstrap_per_hour: int = Field(default=10, ge=1)
    auth_rate_limit_enabled: bool = Field(default=True)
    # EG-004 (2026-04-23): per-session limit on expensive AI generation
    # routes. 30/min is generous for a partner reviewing a matter and
    # far below what runaway abuse would attempt. Bump cautiously —
    # each call is an LLM round-trip and a tenant cost driver.
    ai_route_rate_limit_per_minute: int = Field(default=30, ge=1)

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
    # Hard cross-provider fallback when the primary Anthropic call
    # returns 402 ("credit balance is too low"). Retrying on Haiku
    # would hit the same wall, so we cut over to OpenAI instead.
    # Wire the key via the caseops-openai-api-key Secret Manager
    # secret in production; locally, leave unset and the fallback is
    # silently disabled (the existing 422 message still fires).
    openai_api_key: str | None = Field(default=None)
    openai_fallback_model: str = Field(default="gpt-5.1")
    llm_max_output_tokens: int = Field(default=2048, ge=256)
    # Drafting warrants a bigger ceiling — full bail applications /
    # review memos can hit 8-12k output tokens. Recommendations are
    # structured JSON and stay tight.
    llm_max_output_tokens_drafting: int = Field(default=8192, ge=512)
    llm_max_output_tokens_hearing_pack: int = Field(default=4096, ge=512)
    # BUG-005 2026-04-21: the default 2048 was truncating
    # recommendations mid-rationale — both Sonnet and Haiku ended
    # their JSON at ~2k output tokens on a real matter, and the
    # tolerant JSON loader couldn't parse a doc with no closing
    # brace. Raising to 4096 is the same budget as hearing packs
    # and gives ~500-600 words of rationale per option.
    llm_max_output_tokens_recommendations: int = Field(default=4096, ge=512)
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
    # 2026-04-21 retrieval-quality gap — see
    # docs/SC_2023_QUALITY_INVESTIGATION_2026-04-21.md. The 2026-04-20
    # SC-2023 HNSW probe ran recall@10 = 83.3 % (25/30). Five misses
    # clustered on query-side normalisation (numeric citations,
    # all-caps bench names, punctuated SC reporter cites, Punjabi-
    # script party names). The fix embeds the query variants at
    # search time and unions the HNSW top-k per variant; no re-ingest
    # needed. Flag is on by default so the next probe measures the
    # uplift; operators can flip to False if quality regresses on
    # other surfaces.
    retrieval_query_normalisers_enabled: bool = Field(default=True)
    # Haiku-backed transliteration for Indic-script queries. OFF by
    # default — every non-English query would otherwise pay a Haiku
    # round-trip. Enable once the probe confirms the variant beats the
    # raw query on the Gurmukhi / Devanagari miss bucket.
    retrieval_non_english_translate: bool = Field(default=False)
    # Streaming corpus ingestion caps — keep workstation disk safe.
    corpus_ingest_batch_size: int = Field(default=25, ge=1, le=500)
    corpus_ingest_max_workdir_mb: int = Field(default=500, ge=32, le=20000)
    corpus_ingest_temp_root: str | None = Field(default=None)
    # Voyage spend ledger + daily cap. After the Apr 18-26 incident
    # ($343 over 8 days, no on-DB visibility) every embed call writes
    # a VoyageUsage row and the next batch refuses if today's
    # cumulative cost exceeds voyage_daily_cap_usd. Set to 0 to
    # disable the cap; set voyage_usage_audit_enabled=false to skip
    # writes (e.g., in offline tests where DB isn't reachable).
    voyage_usage_audit_enabled: bool = Field(default=True)
    voyage_daily_cap_usd: float = Field(default=20.0, ge=0.0)
    voyage_price_per_million_tokens_usd: float = Field(default=0.18, ge=0.0)
    # OCR fallback for scanned judgment PDFs. Defaults to rapidocr (pure
    # Python, ONNX, no native binary). Set to `none` to disable.
    ocr_provider: str = Field(default="rapidocr")
    ocr_min_chars_before_fallback: int = Field(default=600, ge=0)
    ocr_render_dpi: int = Field(default=220, ge=72, le=600)
    ocr_max_pages: int = Field(default=40, ge=1, le=1000)
    # Tesseract --lang code (eng, hin, mar, tam, tel, kan). Set to
    # "auto" (Sprint Q2) to auto-detect the dominant script from the
    # first page and pick the matching lang pack per document. Default
    # stays "eng" — operators opt in explicitly with
    # CASEOPS_OCR_LANGUAGES=auto.
    ocr_languages: str = Field(default="eng")
    # Sprint Q4 — per-page quality gate. A page is dropped from the
    # extracted text when either its mean recognition confidence falls
    # below ``ocr_min_page_confidence`` or its character count falls
    # below ``ocr_min_page_chars``. This keeps OCR-garbage (stamps,
    # seals, margin noise, handwritten flourishes the engine couldn't
    # read) out of the embedding pipeline. Leaving both at the defaults
    # rejects pages that are almost certainly noise while keeping
    # genuine short first-pages (eg., cover sheets with "ORDER").
    ocr_min_page_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    ocr_min_page_chars: int = Field(default=50, ge=0, le=10000)

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
    def _reject_auto_migrate_in_non_local(self) -> "Settings":
        """EG-002 (2026-04-23): production / cloud API services MUST
        NOT auto-migrate at startup. Migrations belong in a separate
        Cloud Run Job (caseops-migrate-job) so the multi-instance
        race is impossible and ops gets a clean rollback boundary.

        Local + dev env keeps auto_migrate=True for the docker-compose
        flow + pytest fixtures."""
        if is_non_local_env(self.env) and self.auto_migrate:
            raise ValueError(
                "CASEOPS_AUTO_MIGRATE=true is rejected when "
                f"CASEOPS_ENV={self.env!r}. Set CASEOPS_AUTO_MIGRATE=false "
                "and run alembic via the caseops-migrate-job Cloud Run Job "
                "as a deploy step (see infra/cloudrun/migrate-job.yaml).",
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
