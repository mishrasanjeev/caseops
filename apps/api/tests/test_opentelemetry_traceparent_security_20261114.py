"""CVE-2026-126360 / GHSA-mf5v-w3w3-f6cg: bounded, offline extraction.

Primary sources (the release backports the parser refinement):
https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg
https://github.com/open-telemetry/opentelemetry-python/commit/faa72dae511ae64a7bf8ca63eff9ad4387d0b939
https://github.com/open-telemetry/opentelemetry-python/commit/78123a2755c907c602e02352aebed4be86aa5350
https://github.com/open-telemetry/opentelemetry-python/releases/tag/v1.45.2

No SDK, instrumentation, exporter, or telemetry initialization is needed.
Core-only collection declares an explicit optional-module skip. The separate
mandatory all-extras CI gate fails if the extra is missing. All input values
are at most 513 characters; rejection ordering replaces timing/DoS probes.
"""

import importlib.metadata
import os
import re
import socket
from types import SimpleNamespace

import pytest

try:
    importlib.metadata.version("opentelemetry-api")
except importlib.metadata.PackageNotFoundError:
    if os.environ.get("CASEOPS_REQUIRE_OBSERVABILITY_TESTS") == "1":
        raise
    pytest.skip(
        "Optional observability extra absent; mandatory all-extras CI gate executes these cases",
        allow_module_level=True,
    )

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace.propagation import tracecontext

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"
CURRENT = f"00-{TRACE_ID}-{SPAN_ID}-01"
FUTURE = f"01-{TRACE_ID}-{SPAN_ID}-01"
FUTURE_PREFIX = FUTURE + "-"
CONTEXT_MARKER = "caseops-traceparent-security-marker"


def _sized_future_header(length: int) -> str:
    return FUTURE_PREFIX + "x" * (length - len(FUTURE_PREFIX))


def _carrier(header: str, list_value: bool) -> dict[str, str | list[str]]:
    return {"traceparent": [header] if list_value else header}


def _assert_remote_span(context: otel_context.Context, flags: str = "01") -> None:
    span = trace.get_current_span(context)
    span_context = span.get_span_context()
    assert span_context.is_valid
    assert span_context.is_remote
    assert span_context.trace_id == int(TRACE_ID, 16)
    assert span_context.span_id == int(SPAN_ID, 16)
    assert int(span_context.trace_flags) == int(flags, 16)
    assert span_context.trace_flags.sampled == bool(int(flags, 16) & 1)
    assert not span.is_recording()


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*args, **kwargs):
        raise AssertionError("Traceparent regression must remain offline")

    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket.socket, "connect_ex", refused)
    monkeypatch.setattr(socket.socket, "sendto", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(socket, "getaddrinfo", refused)


@pytest.fixture
def original_context():
    previous = otel_context.get_current()
    local_span = trace.NonRecordingSpan(
        trace.SpanContext(
            trace_id=1,
            span_id=2,
            is_remote=False,
            trace_flags=trace.TraceFlags(0),
        )
    )
    context = trace.set_span_in_context(
        local_span, otel_context.Context({CONTEXT_MARKER: object()})
    )
    before = dict(context)
    token = otel_context.attach(context)
    try:
        yield context
        assert otel_context.get_current() is context
        assert dict(context) == before
        assert trace.get_current_span(context) is local_span
    finally:
        otel_context.detach(token)
    assert otel_context.get_current() is previous


@pytest.fixture
def traceparent_regex_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    # Couple only to the reviewed upstream pattern and its module-local re
    # binding. Never replace re.search on the shared standard-library module.
    pattern = tracecontext.TraceContextTextMapPropagator._TRACEPARENT_HEADER_FORMAT_RE
    real_search = re.search
    calls = []

    def observed_search(candidate: re.Pattern[str], value: str) -> re.Match[str] | None:
        assert candidate is pattern, "Extraction bypassed the reviewed traceparent pattern"
        calls.append(value)
        assert len(value) <= 512, "Oversized traceparent reached regex before rejection"
        return real_search(candidate, value)

    monkeypatch.setattr(tracecontext, "re", SimpleNamespace(search=observed_search))
    assert re.search is real_search
    return calls


@pytest.mark.parametrize("list_value", [False, True], ids=["string", "list"])
@pytest.mark.parametrize(
    "header",
    [
        pytest.param(_sized_future_header(513), id="future-suffix"),
        pytest.param(" " * (513 - len(CURRENT)) + CURRENT, id="leading-space"),
        pytest.param(CURRENT + "\t" * (513 - len(CURRENT)), id="trailing-tab"),
        pytest.param(
            FUTURE_PREFIX + " " * (513 - len(FUTURE_PREFIX) - 2) + "\nx",
            id="suffix-embedded-lf",
        ),
        pytest.param(
            FUTURE_PREFIX + " " * (513 - len(FUTURE_PREFIX) - 3) + "\r\nx",
            id="suffix-embedded-crlf",
        ),
    ],
)
def test_traceparent_513_is_rejected_before_regex(
    header, list_value, original_context, traceparent_regex_calls
):
    assert len(header) == 513
    propagator = tracecontext.TraceContextTextMapPropagator()
    carrier = _carrier(header, list_value)
    rejected = propagator.extract(carrier, context=original_context)
    assert rejected is original_context
    implicit = propagator.extract(carrier)
    assert dict(implicit) == {}
    assert trace.get_current_span(implicit) is trace.INVALID_SPAN
    assert otel_context.get_current() is original_context
    assert traceparent_regex_calls == []


@pytest.mark.parametrize("list_value", [False, True], ids=["string", "list"])
@pytest.mark.parametrize(
    "header",
    [
        pytest.param(_sized_future_header(512), id="future-suffix"),
        pytest.param(" " * (512 - len(CURRENT)) + CURRENT, id="leading-space"),
        pytest.param(CURRENT + "\t" * (512 - len(CURRENT)), id="trailing-tab"),
    ],
)
def test_traceparent_512_reaches_real_regex_and_is_accepted(
    header, list_value, original_context, traceparent_regex_calls
):
    assert len(header) == 512
    result = tracecontext.TraceContextTextMapPropagator().extract(
        _carrier(header, list_value), context=original_context
    )
    assert traceparent_regex_calls == [header]
    _assert_remote_span(result)
    assert result is not original_context
    assert result[CONTEXT_MARKER] is original_context[CONTEXT_MARKER]
    assert otel_context.get_current() is original_context


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(CURRENT + "-x", id="version-zero-suffix"),
        pytest.param(CURRENT + "-" + " " * 64, id="version-zero-whitespace-suffix"),
        pytest.param(FUTURE + " -x", id="space-before-suffix"),
        pytest.param(FUTURE + "\t-x", id="tab-before-suffix"),
        pytest.param(FUTURE_PREFIX + " " * 64 + "\nx", id="suffix-embedded-lf"),
        pytest.param(FUTURE_PREFIX + " " * 64 + "\r\nx", id="suffix-embedded-crlf"),
        pytest.param(f"00-{TRACE_ID}\r-{SPAN_ID}-01", id="cr-in-fixed-fields"),
        pytest.param(f"00-{TRACE_ID}\n-{SPAN_ID}-01", id="lf-in-fixed-fields"),
        pytest.param(CURRENT + "\r", id="trailing-cr"),
        pytest.param(CURRENT + "\r\n", id="trailing-crlf"),
        pytest.param(CURRENT + "\nx", id="lf-followed-by-data"),
        pytest.param(f"00-{'0' * 32}-{SPAN_ID}-01", id="zero-trace-id"),
        pytest.param(f"00-{TRACE_ID}-{'0' * 16}-01", id="zero-span-id"),
        pytest.param(f"00-{TRACE_ID.upper()}-{SPAN_ID}-01", id="uppercase-trace-id"),
        pytest.param(f"00-{TRACE_ID}-{SPAN_ID.upper()}-01", id="uppercase-span-id"),
        pytest.param(f"00-{TRACE_ID[1:]}-{SPAN_ID}-01", id="short-trace-id"),
        pytest.param(f"00-{TRACE_ID}-{SPAN_ID[1:]}-01", id="short-span-id"),
        pytest.param(f"00-{TRACE_ID}-{SPAN_ID}-0g", id="non-hex-flags"),
        pytest.param(f"ff-{TRACE_ID}-{SPAN_ID}-01", id="forbidden-version"),
        pytest.param(FUTURE + "x", id="unseparated-suffix"),
    ],
)
def test_malformed_bounded_traceparent_preserves_supplied_and_current_context(
    header, original_context, traceparent_regex_calls
):
    assert len(header) <= 512
    result = tracecontext.TraceContextTextMapPropagator().extract(
        {"traceparent": header, "tracestate": "vendor=untrusted"},
        context=original_context,
    )
    assert traceparent_regex_calls == [header]
    assert result is original_context
    assert otel_context.get_current() is original_context
    assert list(trace.get_current_span(result).get_span_context().trace_state.items()) == []


@pytest.mark.parametrize("version", ["00", "01"])
@pytest.mark.parametrize("flags", ["00", "01", "02", "ff"])
def test_valid_traceparent_preserves_exact_ids_flags_and_non_span_context(
    version, flags, original_context
):
    result = tracecontext.TraceContextTextMapPropagator().extract(
        {"traceparent": f"{version}-{TRACE_ID}-{SPAN_ID}-{flags}", "tracestate": "vendor=offline"},
        context=original_context,
    )
    _assert_remote_span(result, flags)
    assert result is not original_context
    assert result[CONTEXT_MARKER] is original_context[CONTEXT_MARKER]
    assert list(trace.get_current_span(result).get_span_context().trace_state.items()) == [
        ("vendor", "offline")
    ]
    assert otel_context.get_current() is original_context


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(CURRENT, id="current-version"),
        pytest.param(CURRENT + " \t ", id="trailing-space-and-tab"),
        pytest.param(" \t" + CURRENT, id="leading-space-and-tab"),
        pytest.param(FUTURE + "-x", id="future-suffix"),
        pytest.param(FUTURE_PREFIX + " " * 64, id="future-whitespace-suffix"),
        pytest.param(FUTURE + "-x \t", id="future-suffix-with-padding"),
        # Upstream retains a $ anchor: one terminal LF still matches. Do not
        # mistake the ReDoS patch for blanket CR/LF validation of HTTP headers.
        pytest.param(CURRENT + "\n", id="upstream-terminal-lf-compatibility"),
    ],
)
def test_patched_suffix_and_whitespace_compatibility(
    header, original_context, traceparent_regex_calls
):
    result = tracecontext.TraceContextTextMapPropagator().extract(
        {"traceparent": header}, context=original_context
    )
    assert traceparent_regex_calls == [header]
    _assert_remote_span(result)
    assert result[CONTEXT_MARKER] is original_context[CONTEXT_MARKER]
    assert otel_context.get_current() is original_context


@pytest.mark.parametrize(
    "carrier",
    [{}, {"traceparent": []}, {"tracestate": "vendor=untrusted"}],
    ids=["missing", "empty-values", "tracestate-only"],
)
def test_absent_traceparent_preserves_context_without_regex(
    carrier, original_context, traceparent_regex_calls
):
    assert (
        tracecontext.TraceContextTextMapPropagator().extract(carrier, context=original_context)
        is original_context
    )
    assert traceparent_regex_calls == []
    assert otel_context.get_current() is original_context


def test_extraction_without_explicit_context_does_not_replace_ambient_context(original_context):
    result = tracecontext.TraceContextTextMapPropagator().extract({"traceparent": CURRENT})
    _assert_remote_span(result)
    assert CONTEXT_MARKER not in result
    assert otel_context.get_current() is original_context
