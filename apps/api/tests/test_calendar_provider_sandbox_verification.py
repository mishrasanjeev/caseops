from __future__ import annotations

from caseops_api.scripts.verify_calendar_provider_sandbox import TARGETS, _safe_result


def test_sandbox_verifier_emits_only_content_minimised_evidence() -> None:
    event_id = "provider-event-secret-id"
    result = _safe_result(
        TARGETS["google"],
        event_id,
        {
            "id": event_id,
            "start_date": "2026-08-20",
            "cancelled": False,
            "provider_revision": "revision-1",
            "provider_updated_at": "2026-08-20T05:00:00Z",
            "title": "must not be printed",
            "attendees": ["must-not-be-printed@example.com"],
        },
    )

    assert result["result"] == "passed"
    assert result["provider_revision_present"] is True
    rendered = str(result)
    assert event_id not in rendered
    assert "must not be printed" not in rendered
    assert "must-not-be-printed@example.com" not in rendered
