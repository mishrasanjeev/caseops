"""Observability foundation: request-scoped context + JSON logging + OTel.

Three interlocking pieces:

1. ``RequestContext`` — a ``contextvars``-backed store that carries
   request_id, tenant_id, matter_id, user_id through every log call
   and DB query inside a request. Pure Python, zero framework
   dependencies — background workers set the context manually; the
   request middleware sets it from the HTTP envelope.

2. ``JsonLogFormatter`` — a ``logging.Formatter`` that renders each
   record as one JSON object with the context fields merged in. Cloud
   Logging / Datadog / Grafana Loki all parse this without extra
   config. Local dev stays readable via ``CASEOPS_LOG_FORMAT=text``.

3. ``configure_tracing`` — optional OpenTelemetry setup. When
   ``CASEOPS_OTEL_ENABLED=true``, installs FastAPI + SQLAlchemy +
   httpx instrumentations and an OTLP exporter pointed at
   ``CASEOPS_OTEL_ENDPOINT``. Defaults off so local runs and CI
   have no overhead; Cloud Run turns it on via service env.

The middleware in ``core.request_context_middleware`` glues (1) and
(2) together on every HTTP request.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextvars import ContextVar
from typing import Any

from caseops_api.core.settings import get_settings

# --- Context vars --------------------------------------------------------

# Each var defaults to None. An empty request (or a CLI job without
# setup) renders the field as null in logs rather than ``unknown`` —
# easier to filter in downstream tools.
_request_id: ContextVar[str | None] = ContextVar("caseops_request_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("caseops_tenant_id", default=None)
_matter_id: ContextVar[str | None] = ContextVar("caseops_matter_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("caseops_user_id", default=None)
_membership_id: ContextVar[str | None] = ContextVar(
    "caseops_membership_id", default=None
)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def set_tenant_context(
    *,
    tenant_id: str | None,
    user_id: str | None = None,
    membership_id: str | None = None,
    matter_id: str | None = None,
) -> None:
    """Push tenant-scope identifiers into the current context.

    Call this after ``get_session_context`` resolves the bearer token,
    and again inside route handlers that resolve a matter. Background
    jobs call this after loading the ``company_id`` they own.
    """
    _tenant_id.set(tenant_id)
    _user_id.set(user_id)
    _membership_id.set(membership_id)
    if matter_id is not None:
        _matter_id.set(matter_id)


def set_matter_context(matter_id: str | None) -> None:
    _matter_id.set(matter_id)


def clear_context() -> None:
    for var in (_request_id, _tenant_id, _matter_id, _user_id, _membership_id):
        var.set(None)


def ensure_request_id(candidate: str | None) -> str:
    """Return a usable request id: the caller's X-Request-ID if it
    looks sane, otherwise a freshly minted uuid4."""
    if candidate and 8 <= len(candidate) <= 80 and all(
        c.isalnum() or c in "-_" for c in candidate
    ):
        return candidate
    return uuid.uuid4().hex


# --- JSON log formatter --------------------------------------------------


class JsonLogFormatter(logging.Formatter):
    """Render every record as a one-line JSON object with the context
    vars merged in. Fields that were never set render as ``null`` so
    log consumers can filter ``tenant_id IS NOT NULL`` cleanly.
    """

    # Reserved attributes from the stdlib LogRecord we never want to
    # surface. Everything else in record.__dict__ is treated as an
    # extra field (caller-supplied via ``logger.info("...", extra={...})``).
    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        # `logging.formatTime` delegates to `time.strftime` which on
        # Windows rejects `%f` (microseconds). Format directly via
        # ``datetime.fromtimestamp(...).isoformat()`` for a portable
        # ISO-8601 string.
        from datetime import UTC
        from datetime import datetime as _dt

        ts = _dt.fromtimestamp(record.created, tz=UTC).isoformat()
        payload: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _request_id.get(),
            "tenant_id": _tenant_id.get(),
            "matter_id": _matter_id.get(),
            "user_id": _user_id.get(),
            "membership_id": _membership_id.get(),
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            try:
                json.dumps(value, default=str)
                payload[key] = value
            except TypeError:
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = record.stack_info
        return json.dumps(payload, default=str, separators=(",", ":"))


class TextLogFormatter(logging.Formatter):
    """Human-readable fallback for local dev, with context appended."""

    _DEFAULT_FMT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self._DEFAULT_FMT)

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        bits = [
            ("rid", _request_id.get()),
            ("tenant", _tenant_id.get()),
            ("matter", _matter_id.get()),
        ]
        tail = " ".join(f"{k}={v}" for k, v in bits if v)
        return f"{base}  [{tail}]" if tail else base


def configure_logging() -> None:
    """Install the JSON or text formatter on the root logger based on
    ``CASEOPS_LOG_FORMAT``. Safe to call more than once; subsequent
    calls replace the handler instead of stacking.
    """
    level_name = os.environ.get("CASEOPS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt_name = os.environ.get("CASEOPS_LOG_FORMAT", "json").lower()
    formatter: logging.Formatter
    if fmt_name == "text":
        formatter = TextLogFormatter()
    else:
        formatter = JsonLogFormatter()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    # Drop any previously installed handlers we own.
    for existing in list(root.handlers):
        if getattr(existing, "_caseops", False):
            root.removeHandler(existing)
    handler._caseops = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)


# --- OpenTelemetry (opt-in) ---------------------------------------------


_otel_configured = False


def configure_tracing(application: Any = None) -> None:
    """Wire OpenTelemetry if ``CASEOPS_OTEL_ENABLED=true``.

    Pulled behind an opt-in flag because the instrumentations add
    non-trivial startup cost and network dependencies. Cloud Run turns
    it on via service env; local dev + CI stay fast.
    """
    global _otel_configured
    if _otel_configured:
        return
    settings = get_settings()
    enabled = str(
        os.environ.get(
            "CASEOPS_OTEL_ENABLED", str(getattr(settings, "otel_enabled", False))
        )
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover — only on prod builds
        logging.getLogger(__name__).warning(
            "CASEOPS_OTEL_ENABLED is set but opentelemetry SDK is not "
            "installed: %s. Skipping tracing setup.", exc,
        )
        return

    endpoint = os.environ.get(
        "CASEOPS_OTEL_ENDPOINT", "http://localhost:4318/v1/traces"
    )
    service_name = os.environ.get("CASEOPS_OTEL_SERVICE_NAME", "caseops-api")
    resource = Resource.create(
        {"service.name": service_name, "service.version": settings.api_version}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        if application is not None:
            FastAPIInstrumentor.instrument_app(application)
    except ImportError:  # pragma: no cover
        pass
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
    except ImportError:  # pragma: no cover
        pass
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except ImportError:  # pragma: no cover
        pass
    _otel_configured = True


__all__ = [
    "JsonLogFormatter",
    "TextLogFormatter",
    "clear_context",
    "configure_logging",
    "configure_tracing",
    "ensure_request_id",
    "get_request_id",
    "set_matter_context",
    "set_request_id",
    "set_tenant_context",
]
