"""DATA-GOV-15: nothing sensitive leaves the process through a log sink.

The requirement: application/provider/audit logs, traces and metrics minimise
and redact message bodies, document text, prompts, mark/client names,
email/phone, tokens and payment data.

Why redaction moved to the SINK. Call-site discipline had already failed in a
way that proves the pattern cannot hold: `services/audit_exports.py` redacted
the exception it PERSISTED (`job.error = redact_provider_error(exc)`) while
logging the very same object raw one line above via `logger.exception`. Two
destinations, one object, one of them sanitised. Redacting in the formatter
means a future call site cannot reintroduce that asymmetry by forgetting.
"""

from __future__ import annotations

import json
import logging

from caseops_api.core.observability import JsonLogFormatter
from caseops_api.core.redaction import (
    redact_log_text,
    redact_provider_error,
)

_DSN = "postgresql://svc_user:S3cretPassw0rd@10.20.30.40:5432/caseops"
_CORRELATION_ID = "7f3a1b2c-1111-2222-3333-444455556677"


def _emit(message: str = "job finished", **extra: object) -> dict:
    record = logging.LogRecord("caseops.test", logging.WARNING, "f.py", 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonLogFormatter().format(record))


class TestSecretsAndPersonalData:
    def test_connection_string_password_never_reaches_the_log(self) -> None:
        payload = _emit(f"could not connect: {_DSN}")
        assert "S3cretPassw0rd" not in json.dumps(payload)
        assert "[url-redacted]" in payload["message"]

    def test_exception_tracebacks_are_redacted(self) -> None:
        # The exact gap left open when persisted errors were redacted: the
        # traceback carries the same message to a different destination.
        try:
            raise RuntimeError(f"connect failed: {_DSN}")
        except RuntimeError:
            import sys

            record = logging.LogRecord(
                "caseops.test", logging.ERROR, "f.py", 2, "job failed", (), sys.exc_info()
            )
            payload = json.loads(JsonLogFormatter().format(record))

        assert "S3cretPassw0rd" not in payload["exc_info"]
        # Still a usable traceback, not an opaque blank.
        assert "RuntimeError" in payload["exc_info"]

    def test_email_phone_and_abbreviated_password_keys_are_redacted(self) -> None:
        payload = _emit("notify lawyer@firm.co.in on +91 98765 43210 pw=hunter2 pwd: s3cret")
        blob = json.dumps(payload)

        assert "lawyer@firm.co.in" not in blob
        assert "98765" not in blob
        # `pw` and `pwd` are what people actually type; only `password`/`passwd`
        # were covered until this was tested.
        assert "hunter2" not in blob
        assert "s3cret" not in blob

    def test_card_numbers_do_not_survive(self) -> None:
        payload = _emit("charge failed", card_number="4111111111111111")
        assert "4111111111111111" not in json.dumps(payload)


class TestContentIsWithheldByFieldName:
    """No pattern recognises privileged prose, so the field name is the signal."""

    def test_document_text_and_prompts_are_withheld(self) -> None:
        payload = _emit(
            "draft generated",
            document_text="The Petitioner submits that the impugned order...",
            prompt="Draft a rejoinder for Acme Corp",
        )

        assert "Petitioner" not in json.dumps(payload)
        assert "Acme Corp" not in json.dumps(payload)
        # Withheld, not deleted: the length still tells an operator what happened.
        assert payload["document_text"].startswith("[content-withheld chars=")
        assert payload["prompt"].startswith("[content-withheld chars=")

    def test_nested_content_fields_are_withheld(self) -> None:
        payload = _emit("provider replied", detail={"raw_preview": "privileged body", "count": 3})

        assert "privileged body" not in json.dumps(payload)
        # Structure survives so log consumers keep their field shapes.
        assert payload["detail"]["count"] == 3

    def test_structural_fields_are_preserved(self) -> None:
        # Over-redaction is its own failure: an operator who cannot find the
        # record cannot act on the alert.
        payload = _emit("docket updated", docket_id="ip-9", attempt=2, status="failed")

        assert payload["docket_id"] == "ip-9"
        assert payload["attempt"] == 2
        assert payload["status"] == "failed"


class TestCorrelationIdentifiersSurvive:
    """Redaction must not cost incident response."""

    def test_uuid_is_preserved_intact_in_logs(self) -> None:
        payload = _emit(f"tenant {_CORRELATION_ID} exceeded quota")

        # Not merely "not masked" - not CORRUPTED either. The phone pattern
        # matches a UUID's digit-and-dash tail, so an earlier attempt produced
        # "7f3a1b2c-[phone-redacted]": the id destroyed, nothing protected.
        assert _CORRELATION_ID in payload["message"]

    def test_persisted_provider_errors_still_mask_identifiers(self) -> None:
        # The two destinations differ deliberately: an operator-facing stored
        # error has no business carrying internal record ids.
        assert "[id-redacted]" in redact_provider_error(f"failed for {_CORRELATION_ID}")
        assert _CORRELATION_ID in redact_log_text(f"failed for {_CORRELATION_ID}")


class TestModelOutputIsNotLogged:
    """The LLM writes draft legal text; a bounded prefix is a bounded leak."""

    def test_response_shape_reveals_no_content(self) -> None:
        from caseops_api.services.llm import _response_shape

        body = "I cannot comply. The Acme Corp mark is confusingly similar to..."
        shape = _response_shape(body)

        assert "Acme" not in shape
        assert "confusingly" not in shape

    def test_response_shape_still_separates_the_failure_modes(self) -> None:
        from caseops_api.services.llm import _response_shape

        # Prose instead of JSON, truncation, and an unstripped fence are the
        # three things an operator needs to tell apart.
        assert "opens:'I'" in _response_shape("I cannot comply with that.")
        assert "balanced:False" in _response_shape('{"options": [{"label": "File writ')
        assert "fenced:True" in _response_shape('```json\n{"a":1}\n```')
        assert _response_shape("") == "shape=empty len=0"

    def test_llm_module_no_longer_logs_raw_completion_text(self) -> None:
        # A guard against the previous form returning: the justification for it
        # ("max_tokens bounds the length") was about size, not sensitivity.
        import inspect

        from caseops_api.services import llm

        source = inspect.getsource(llm)
        assert "raw[:1500]" not in source
        assert "raw preview" not in source
