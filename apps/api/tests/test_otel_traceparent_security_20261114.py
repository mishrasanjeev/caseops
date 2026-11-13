"""Bounded CVE-2026-126360 regression without a load-sensitive timing oracle."""

from __future__ import annotations

import unittest
from importlib.metadata import PackageNotFoundError, version
from types import SimpleNamespace
from unittest.mock import patch

try:
    version("opentelemetry-api")
except PackageNotFoundError:
    OBSERVABILITY_INSTALLED = False
else:
    OBSERVABILITY_INSTALLED = True
    from opentelemetry import trace
    from opentelemetry.context import Context
    from opentelemetry.trace.propagation import tracecontext

TRACE_ID = "1234567890abcdef1234567890abcdef"
SPAN_ID = "1234567890abcdef"
PARENT = f"00-{TRACE_ID}-{SPAN_ID}-01"


@unittest.skipUnless(OBSERVABILITY_INSTALLED, "Observability extra is not installed")
class TraceparentBoundsTests(unittest.TestCase):
    def extract(self, carrier):
        original = tracecontext.re
        calls = []

        def search(pattern, value):
            calls.append(value)
            return original.search(pattern, value)

        context = Context({"owned-sentinel": "retained"})
        # Shadow only this module's reference; never patch process-global re.
        with patch.object(tracecontext, "re", SimpleNamespace(search=search)):
            result = tracecontext.TraceContextTextMapPropagator().extract(carrier, context)
        return context, result, calls

    def test_first_oversized_valid_parent_is_rejected_before_regex(self):
        prefix = f"01-{TRACE_ID}-{SPAN_ID}-01-"
        parent = prefix + "a" * (513 - len(prefix))
        context, result, calls = self.extract({"traceparent": parent})
        self.assertIs(result, context)
        self.assertEqual(calls, [])

    def test_small_whitespace_newline_witness_is_rejected_before_regex(self):
        parent = PARENT + " " * 513 + "\nx"
        context, result, calls = self.extract({"traceparent": parent})
        self.assertIs(result, context)
        self.assertEqual(calls, [])

    def test_exact_maximum_valid_future_parent_still_executes_the_parser(self):
        prefix = f"01-{TRACE_ID}-{SPAN_ID}-01-"
        parent = prefix + "a" * (512 - len(prefix))
        context, result, calls = self.extract({"traceparent": parent})
        actual = trace.get_current_span(result).get_span_context()
        self.assertTrue(actual.is_valid)
        self.assertTrue(actual.is_remote)
        self.assertEqual(actual.trace_id, int(TRACE_ID, 16))
        self.assertEqual(actual.span_id, int(SPAN_ID, 16))
        self.assertEqual(calls, [parent])
        self.assertEqual(result["owned-sentinel"], context["owned-sentinel"])

    def test_whitespace_padded_boundary_accepts_512_and_rejects_513(self):
        for size in (512, 513):
            with self.subTest(size=size):
                parent = PARENT + " " * (size - len(PARENT))
                context, result, calls = self.extract({"traceparent": parent})
                if size == 512:
                    self.assertTrue(trace.get_current_span(result).get_span_context().is_valid)
                    self.assertEqual(calls, [parent])
                else:
                    self.assertIs(result, context)
                    self.assertEqual(calls, [])

    def test_short_embedded_newline_with_suffix_remains_invalid(self):
        parent = PARENT + " \nx"
        context, result, calls = self.extract({"traceparent": parent})
        self.assertIs(result, context)
        self.assertEqual(calls, [parent])

    def test_invalid_identifiers_and_reserved_version_remain_rejected(self):
        parents = (
            f"00-{'0' * 32}-{SPAN_ID}-01",
            f"00-{TRACE_ID}-{'0' * 16}-01",
            f"ff-{TRACE_ID}-{SPAN_ID}-01",
        )
        for parent in parents:
            with self.subTest(parent=parent):
                context, result, calls = self.extract({"traceparent": parent})
                self.assertIs(result, context)
                self.assertEqual(calls, [parent])

    def test_missing_parent_keeps_original_context_without_regex(self):
        context, result, calls = self.extract({})
        self.assertIs(result, context)
        self.assertEqual(calls, [])

    def test_valid_parent_and_tracestate_keep_exact_fields_and_injection(self):
        _, result, calls = self.extract({"traceparent": PARENT, "tracestate": "vendor=reviewed"})
        actual = trace.get_current_span(result).get_span_context()
        self.assertTrue(actual.is_valid)
        self.assertTrue(actual.is_remote)
        self.assertEqual(actual.trace_id, int(TRACE_ID, 16))
        self.assertEqual(actual.span_id, int(SPAN_ID, 16))
        self.assertEqual(int(actual.trace_flags), 1)
        self.assertEqual(actual.trace_state.get("vendor"), "reviewed")
        self.assertEqual(calls, [PARENT])
        carrier = {}
        tracecontext.TraceContextTextMapPropagator().inject(carrier, context=result)
        self.assertEqual(carrier, {"traceparent": PARENT, "tracestate": "vendor=reviewed"})

    def test_oversized_first_header_does_not_fall_back_to_second_header(self):
        context, result, calls = self.extract({"traceparent": [PARENT + " " * 513, PARENT]})
        self.assertIs(result, context)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
