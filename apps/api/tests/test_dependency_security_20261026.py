"""Reviewed OpenTelemetry tracestate bounds and an offline compatible optional graph."""

import builtins
import importlib.metadata
import logging
import tomllib
from pathlib import Path

import pytest

TRACEPARENT = "00-12345678901234567890123456789012-1234567890123456-01"
TRACE_ID = int("12345678901234567890123456789012", 16)
SPAN_ID = int("1234567890123456", 16)


def _state_headers(length: int, multiple: bool) -> tuple[list[str], dict[str, str]]:
    # Every member is independently valid and the key count remains exactly32.
    # The oversized case therefore distinguishes the propagation length guard
    # from ordinary syntax/member-count rejection, without a timing assertion.
    pairs = {f"k{index:02}": "v" * 251 for index in range(32)}
    pairs["k00"] += "v" * (length - 8191)
    members = [f"{key}={value}" for key, value in pairs.items()]
    headers = [",".join(members[:16]), ",".join(members[16:])] if multiple else [",".join(members)]
    assert sum(map(len, headers)) + len(headers) - 1 == length
    return headers, pairs


def _extract(headers: list[str]):
    from opentelemetry import trace
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    context = TraceContextTextMapPropagator().extract(
        {"traceparent": TRACEPARENT, "tracestate": headers}
    )
    return trace.get_current_span(context).get_span_context()


def test_manifest_lock_and_installed_optional_cohort_match_the_reviewed_patch():
    api = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((api / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((api / "uv.lock").read_text(encoding="utf-8"))
    stable = {
        "opentelemetry-api",
        "opentelemetry-sdk",
        "opentelemetry-proto",
        "opentelemetry-exporter-otlp-proto-common",
        "opentelemetry-exporter-otlp-proto-http",
    }
    beta = {
        "opentelemetry-exporter-http-transport",
        "opentelemetry-exporter-otlp-common",
        "opentelemetry-instrumentation",
        "opentelemetry-instrumentation-asgi",
        "opentelemetry-instrumentation-fastapi",
        "opentelemetry-instrumentation-httpx",
        "opentelemetry-instrumentation-sqlalchemy",
        "opentelemetry-semantic-conventions",
        "opentelemetry-util-http",
    }
    expected = {**dict.fromkeys(stable, "1.45.1"), **dict.fromkeys(beta, "0.66b1")}
    direct = {
        "opentelemetry-api",
        "opentelemetry-sdk",
        "opentelemetry-exporter-otlp-proto-http",
        "opentelemetry-instrumentation-fastapi",
        "opentelemetry-instrumentation-sqlalchemy",
        "opentelemetry-instrumentation-httpx",
    }
    assert set(manifest["project"]["optional-dependencies"]["observability"]) == {
        f"{name}=={expected[name]}" for name in direct
    }
    rows = {row["name"]: row for row in lock["package"] if row["name"].startswith("opentelemetry-")}
    assert set(rows) == set(expected)
    for name, version in expected.items():
        assert rows[name]["version"] == version
        assert rows[name]["wheels"]
        assert all(wheel["hash"].startswith("sha256:") for wheel in rows[name]["wheels"])
        assert importlib.metadata.version(name) == version


@pytest.mark.parametrize("multiple", [False, True], ids=["single-field", "combined-fields"])
@pytest.mark.parametrize("length", [8192, 8193], ids=["at-bound", "over-bound"])
def test_actual_propagator_enforces_combined_length_and_keeps_traceparent(length, multiple):
    headers, pairs = _state_headers(length, multiple)
    actual = _extract(headers)
    assert actual.is_valid
    assert actual.trace_id == TRACE_ID
    assert actual.span_id == SPAN_ID
    assert dict(actual.trace_state.items()) == (pairs if length == 8192 else {})


@pytest.mark.parametrize("whitespace", [" ", "\t"], ids=["spaces", "tabs"])
def test_oversized_malformed_header_never_enters_the_member_parser(monkeypatch, caplog, whitespace):
    from opentelemetry.trace import TraceState

    entered = []

    def forbidden(cls, headers):
        entered.append(True)
        raise AssertionError("Oversized untrusted tracestate reached member parsing")

    monkeypatch.setattr(TraceState, "from_header", classmethod(forbidden))
    with caplog.at_level(logging.WARNING):
        actual = _extract(["a=b" + whitespace * 10_000 + "malformed-synthetic-tail"])
    assert entered == []
    assert actual.trace_id == TRACE_ID
    assert actual.span_id == SPAN_ID
    assert dict(actual.trace_state.items()) == {}
    assert "malformed-synthetic-tail" not in caplog.text
    assert len(caplog.text) < 1024


def test_opted_in_tracing_still_degrades_gracefully_when_optional_import_is_absent(
    monkeypatch, caplog
):
    from caseops_api.core import observability

    original = builtins.__import__

    def without_optional(name, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("Synthetic optional OpenTelemetry package absence")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(observability, "_otel_configured", False)
    monkeypatch.setenv("CASEOPS_OTEL_ENABLED", "true")
    monkeypatch.setattr(builtins, "__import__", without_optional)
    with caplog.at_level(logging.WARNING):
        observability.configure_tracing()
    assert observability._otel_configured is False
    assert "Skipping tracing setup" in caplog.text


def test_disabled_tracing_never_imports_or_initializes_optional_exporters(monkeypatch):
    from caseops_api.core import observability

    original = builtins.__import__

    def forbid_optional(name, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise AssertionError("Disabled tracing attempted to initialize OpenTelemetry")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(observability, "_otel_configured", False)
    monkeypatch.setenv("CASEOPS_OTEL_ENABLED", "false")
    monkeypatch.setattr(builtins, "__import__", forbid_optional)
    observability.configure_tracing()
    assert observability._otel_configured is False


def test_patched_sdk_and_fastapi_instrumentation_export_only_to_memory(monkeypatch):
    import socket

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.metrics import NoOpMeterProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import SpanKind

    def no_network(*args, **kwargs):
        raise AssertionError("Offline telemetry regression must not connect to a remote exporter")

    monkeypatch.setattr(socket, "create_connection", no_network)
    exporter = InMemorySpanExporter()
    provider = TracerProvider(
        resource=Resource({"service.name": "caseops-offline-security-regression"})
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    application = FastAPI()

    @application.get("/telemetry-probe")
    def probe():
        return {"ok": True}

    FastAPIInstrumentor.instrument_app(
        application, tracer_provider=provider, meter_provider=NoOpMeterProvider()
    )
    try:
        headers, _ = _state_headers(8193, multiple=True)
        with TestClient(application) as client:
            response = client.get(
                "/telemetry-probe",
                headers=[
                    ("traceparent", TRACEPARENT),
                    *[("tracestate", value) for value in headers],
                ],
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        spans = exporter.get_finished_spans()
        server = [span for span in spans if span.kind == SpanKind.SERVER]
        assert len(server) == 1
        assert server[0].context.trace_id == TRACE_ID
        assert dict(server[0].context.trace_state.items()) == {}
        assert "tracestate" not in repr(server[0].attributes).lower()
    finally:
        FastAPIInstrumentor.uninstrument_app(application)
        provider.shutdown()
