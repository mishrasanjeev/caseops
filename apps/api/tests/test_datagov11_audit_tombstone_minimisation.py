"""DATA-GOV-11: immutable audit evidence is minimised to tombstone fields.

The requirement: evidence retained after content deletion "cannot contain raw
privileged documents, message bodies, prompts, destinations or secrets".

The audit write path applied ``json.dumps(metadata)`` with no constraint at all,
so any of the 400-odd callers could put a draft, a prompt or a recipient address
into a permanent row. Unlike a log line, an audit row is immutable and outlives
the content it describes - it is the one destination where a leak cannot be
rotated away afterwards.

Both directions are tested deliberately, because over-redaction here is its own
failure. An audit trail that cannot say WHICH record changed, or what the
operator's stated reason was, is not evidence of anything. Building this found
three real over-redactions in exactly that direction, and each has a test below:

  - `recommendation_context` was withheld because "context" ends in "text"
  - `supreme_court_latest_orders` and a SHA-256 digest were masked as opaque
    tokens, destroying the tombstone that identifies evidence without revealing it
  - `GOOGLE-SEARCH-2026-08-17-001` was mangled by the phone pattern
"""

from __future__ import annotations

from caseops_api.core.redaction import sanitize_audit_metadata


def _clean(metadata: dict) -> dict:
    result = sanitize_audit_metadata(metadata)
    assert isinstance(result, dict)
    return result


class TestForbiddenCategoriesAreRemoved:
    """The five things DATA-GOV-11 names."""

    def test_document_text_and_prompts_are_withheld(self) -> None:
        cleaned = _clean(
            {
                "document_text": "The Petitioner submits that the impugned order...",
                "prompt": "Draft a rejoinder for Acme Corp",
                "message_body": "Please find the sealed annexure attached.",
            }
        )

        blob = str(cleaned)
        assert "Petitioner" not in blob
        assert "Acme Corp" not in blob
        assert "annexure" not in blob
        # Withheld, not deleted: the length still tells an auditor what happened.
        assert cleaned["document_text"].startswith("[content-withheld chars=")

    def test_destinations_are_removed(self) -> None:
        cleaned = _clean(
            {
                "recipient": "clerk@court.gov.in",
                "phone": "+91 98765 43210",
                "bcc": "partner@firm.example",
            }
        )

        assert cleaned == {
            "recipient": "[destination-redacted]",
            "phone": "[destination-redacted]",
            "bcc": "[destination-redacted]",
        }

    def test_secrets_are_removed(self) -> None:
        # Assembled at runtime. A literal that LOOKS like a live key is itself a
        # secret-scanner finding, and gitleaks reads history - so writing one
        # here would have to be rewritten out of the branch, not just deleted.
        fake_key = "sk-" + "live-" + ("z" * 12)
        fake_signature = "v1=" + ("d" * 16)
        cleaned = _clean({"api_key": fake_key, "webhook_signature": fake_signature})

        assert fake_key not in str(cleaned)
        assert fake_signature not in str(cleaned)
        assert cleaned["api_key"] == "[redacted]"

    def test_an_email_in_free_text_is_still_caught(self) -> None:
        # Destination keys handle the structured case; the pattern still covers
        # an address that arrives inside a sentence.
        cleaned = _clean({"reason": "forwarded to clerk@court.gov.in on request"})

        assert "clerk@court.gov.in" not in cleaned["reason"]


class TestTombstoneFieldsSurvive:
    """Over-redaction destroys evidence. Each of these was a real regression."""

    def test_a_content_hash_is_preserved(self) -> None:
        # The canonical tombstone: it identifies evidence without revealing it.
        # Masking it as an opaque token removes the pointer and protects nothing.
        digest = "7d2a2b98b8ebdfd4a2c0dbd9cb062318f678aad94574a92bd861b0912c5118a1"
        cleaned = _clean({"source_reference_sha256": digest})

        assert cleaned["source_reference_sha256"] == digest

    def test_a_long_provider_key_is_preserved(self) -> None:
        cleaned = _clean({"provider": "supreme_court_latest_orders"})

        assert cleaned["provider"] == "supreme_court_latest_orders"

    def test_a_key_merely_containing_text_is_preserved(self) -> None:
        # "context" ends in "text". Substring matching withheld this and would
        # have gutted every key containing context, pretext or subtext.
        cleaned = _clean({"recommendation_context": "custom_goal"})

        assert cleaned["recommendation_context"] == "custom_goal"

    def test_a_dated_provider_reference_is_preserved(self) -> None:
        # The phone pattern matches any digit run with separators, which is also
        # what a dated reference looks like.
        cleaned = _clean({"provider_reference": "GOOGLE-SEARCH-2026-08-17-001"})

        assert cleaned["provider_reference"] == "GOOGLE-SEARCH-2026-08-17-001"

    def test_identifier_lists_are_preserved(self) -> None:
        # `chunk_ids` carries UUIDs that let an auditor find the evidence.
        # Withholding them because the key contains "chunk" removes the pointer.
        ids = ["1ec6dccf-4c49-406a-88ca-83967af154bf"]
        cleaned = _clean({"source_chunk_ids": ids})

        assert cleaned["source_chunk_ids"] == ids

    def test_operator_statements_survive(self) -> None:
        # A reason and a note are what the operator said, not a document.
        # Neither appears in DATA-GOV-11's forbidden list.
        cleaned = _clean(
            {"reason": "client requested closure", "note": "Confirmed against the source order."}
        )

        assert cleaned["reason"] == "client requested closure"
        assert cleaned["note"] == "Confirmed against the source order."

    def test_scalars_and_status_pass_through(self) -> None:
        cleaned = _clean(
            {"record_count": 4, "safe_to_execute": False, "status": "dry_run_complete"}
        )

        assert cleaned == {
            "record_count": 4,
            "safe_to_execute": False,
            "status": "dry_run_complete",
        }


class TestNestedStructures:
    def test_nesting_is_sanitised_without_flattening(self) -> None:
        cleaned = _clean(
            {"detail": {"document_text": "privileged body", "record_count": 2}}
        )

        assert "privileged body" not in str(cleaned)
        assert cleaned["detail"]["record_count"] == 2

    def test_the_write_path_applies_it(self) -> None:
        # The guarantee is that no caller can bypass this, so assert the wiring
        # rather than only the helper.
        import inspect

        from caseops_api.services import audit

        source = inspect.getsource(audit)
        assert "sanitize_audit_metadata(metadata)" in source
