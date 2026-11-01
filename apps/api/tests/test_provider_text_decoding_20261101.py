"""B4-ADJ-23: provider-escaped email text is decoded once for presentation.

Gmail returns message snippets HTML-escaped. The calendar-copy candidates on
/app/calendar, the mailbox review list and the matter communications timeline
showed ``Client&#39;s`` and ``&amp;`` verbatim. Stored provider text stays as
evidence; readers decode it exactly once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.gmail_sync import _message_record
from caseops_api.services.provider_text import provider_plain_text
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_communications import _calendar_invite_payload, _create_matter

ESCAPED = (
    "Calendar invitation for 2026-06-15 at 10:30 AM. Venue: Court &amp; Chamber 4. "
    "Bring the client&#39;s file &lt;urgent&gt;&nbsp;now."
)
DECODED = (
    "Calendar invitation for 2026-06-15 at 10:30 AM. Venue: Court & Chamber 4. "
    "Bring the client's file <urgent> now."
)


def test_provider_plain_text_decodes_entities_once() -> None:
    assert provider_plain_text(ESCAPED) == DECODED
    assert provider_plain_text(None) is None
    assert provider_plain_text("&amp;amp;") == "&amp;"
    assert provider_plain_text("Plain text") == "Plain text"


def test_calendar_copy_candidate_preview_and_location_are_decoded(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADJ23-001")
    imported = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json=_calendar_invite_payload("adj23-invite-001", body_preview=ESCAPED),
    )
    assert imported.status_code == 200, imported.text
    extracted = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=headers,
        json={"matter_id": matter_id},
    )
    assert extracted.status_code == 200, extracted.text
    candidate = extracted.json()["candidates"][0]
    assert "&#39;" not in candidate["source_preview"]
    assert "&amp;" not in candidate["source_preview"]
    assert "client's file <urgent>" in candidate["source_preview"]
    assert candidate["detected_location"] is not None
    assert "&amp;" not in candidate["detected_location"]
    listed = client.get(
        "/api/calendar/email-invitation-candidates",
        headers=headers,
        params={"matter_id": matter_id},
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["candidates"]
    assert [row["id"] for row in rows] == [candidate["id"]]
    assert rows[0]["source_preview"] == candidate["source_preview"]


def test_gmail_copied_communication_timeline_preview_is_decoded_manual_is_not(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADJ23-002")
    with get_session_factory()() as session:
        for source, body in (
            ("gmail_provider_import", "Client&#39;s reply &amp; draft"),
            ("manual_log", "Typed literally: AT&amp;T"),
        ):
            session.add(
                Communication(
                    company_id=bootstrap["company"]["id"],
                    matter_id=matter_id,
                    direction=CommunicationDirection.INBOUND,
                    channel=CommunicationChannel.EMAIL,
                    subject=f"{source} subject",
                    body=body,
                    status=CommunicationStatus.LOGGED,
                    occurred_at=datetime(2026, 10, 30, 6, 0, tzinfo=UTC),
                    created_by_membership_id=bootstrap["membership"]["id"],
                    metadata_json={"source": source, "provider": "gmail"}
                    if source == "gmail_provider_import"
                    else {"source": source},
                )
            )
        session.commit()
    timeline = client.get(f"/api/matters/{matter_id}/communications/timeline", headers=headers)
    assert timeline.status_code == 200, timeline.text
    previews = {item["title"]: item["preview"] for item in timeline.json()["items"]}
    gmail = next(value for key, value in previews.items() if "gmail_provider_import" in key)
    manual = next(value for key, value in previews.items() if "manual_log" in key)
    assert gmail == "Client's reply & draft"
    assert manual == "Typed literally: AT&amp;T"


def test_mailbox_message_record_snippet_is_decoded() -> None:
    now = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)
    row = SimpleNamespace(
        id="row-1",
        company_id="company-1",
        mailbox_connection_id="connection-1",
        connection=SimpleNamespace(provider="gmail"),
        matter_id=None,
        communication_id=None,
        provider_message_id="message-1",
        provider_thread_id=None,
        subject="Hearing notice",
        sender_name="Registry",
        occurred_at=now,
        snippet="Hearing on 15/06/2026 &#39;Court 4&#39; &amp; chambers",
        labels_json=[],
        attachment_count=0,
        status="new",
        last_error_redacted=None,
        attempts=0,
        max_attempts=5,
        next_attempt_at=None,
        dead_letter_reason=None,
        created_at=now,
        updated_at=now,
    )
    assert _message_record(row).snippet == "Hearing on 15/06/2026 'Court 4' & chambers"
