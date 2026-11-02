"""B4-ADJ-23: provider-escaped email text is decoded once for presentation.

Gmail returns message snippets HTML-escaped. The calendar-copy candidates on
/app/calendar, the mailbox review list and the matter communications timeline
showed ``Client&#39;s`` and ``&amp;`` verbatim. Stored provider text stays as
evidence; one predicate (``communication_text_is_escaped`` /
``mailbox_text_is_escaped``) decides which stored text is escaped, and every
surface decodes exactly that text exactly once. Text a person pasted or typed
is never decoded, so the same row reads identically on every surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    EmailCalendarCandidate,
    EmailCalendarCandidateStatus,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.email_calendar_candidates import (
    _extract_from_text,
    _source_text,
)
from caseops_api.services.gmail_sync import (
    _default_note_body,
    _message_record,
    set_gmail_provider_for_tests,
)
from caseops_api.services.provider_text import (
    communication_text_is_escaped,
    provider_plain_text,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_communications import _calendar_invite_payload, _create_matter
from tests.test_gmail_sync import StubGmailProvider, _connect_gmail, _message
from tests.test_legalworkspace_calendar_sync import (
    _auth,
    _bootstrap_company,
)
from tests.test_legalworkspace_calendar_sync import (
    _create_matter as _create_calendar_matter,
)

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


def test_one_predicate_names_the_escaped_sources() -> None:
    assert communication_text_is_escaped({"source": "gmail_provider_import", "provider": "gmail"})
    assert communication_text_is_escaped({"source": "mailbox_metadata_review", "provider": "gmail"})
    # Outlook previews, pasted imports and typed logs are plain text.
    for metadata in (
        {"source": "mailbox_metadata_review", "provider": "outlook_mail"},
        {"source": "manual_inbound_email_import", "automation_mode": "manual_only"},
        {"source": "manual_log"},
        None,
        "gmail_provider_import",
    ):
        assert not communication_text_is_escaped(metadata), metadata


def _gmail_matter(client: TestClient, slug: str, code: str, snippet: str):
    provider = StubGmailProvider(
        messages=[
            _message(
                message_id=f"{slug}-invite",
                subject=f"Invitation: Strategy conference {code}",
                snippet=snippet,
            )
        ]
    )
    bootstrap = _bootstrap_company(client, slug=slug, email=f"owner@{slug}.example")
    token = str(bootstrap["access_token"])
    _connect_gmail(client, token, provider)
    matter = _create_calendar_matter(client, token, code)
    imported = client.post("/api/mailbox/gmail/import", headers=_auth(token), json={"limit": 10})
    assert imported.status_code == 200, imported.text
    assert imported.json()["summary"]["imported"] == 1
    return bootstrap, token, matter


def test_gmail_row_reads_identically_on_timeline_list_and_calendar_candidate(
    client: TestClient,
) -> None:
    try:
        bootstrap, token, matter = _gmail_matter(client, "adj23-gmail", "ADJ23-GMAIL", ESCAPED)
        headers = _auth(token)
        with get_session_factory()() as session:
            stored = session.scalar(
                select(Communication).where(Communication.matter_id == matter["id"])
            )
            assert stored is not None
            # The provider's text is kept unchanged as evidence.
            assert stored.body == ESCAPED
            assert stored.metadata_json["source"] == "gmail_provider_import"

        extracted = client.post(
            "/api/calendar/email-invitation-candidates/extract",
            headers=headers,
            json={"matter_id": matter["id"]},
        )
        assert extracted.status_code == 200, extracted.text
        assert extracted.json()["created_count"] == 1
        candidate = extracted.json()["candidates"][0]
        # Read decoded, the venue is not cut at the "&amp;" entity's ";".
        assert candidate["detected_location"] == "Court & Chamber 4"
        assert candidate["source_preview"].endswith(DECODED)

        listed = client.get(
            "/api/calendar/email-invitation-candidates",
            headers=headers,
            params={"matter_id": matter["id"]},
        ).json()["candidates"]
        assert [(row["id"], row["source_preview"], row["detected_location"]) for row in listed] == [
            (candidate["id"], candidate["source_preview"], "Court & Chamber 4")
        ]
        timeline = client.get(
            f"/api/matters/{matter['id']}/communications/timeline", headers=headers
        )
        assert timeline.status_code == 200, timeline.text
        previews = [item["preview"] for item in timeline.json()["items"] if item["preview"]]
        assert previews == [DECODED]
        communications = client.get(
            f"/api/matters/{matter['id']}/communications", headers=headers
        )
        assert communications.status_code == 200, communications.text
        assert [row["body"] for row in communications.json()["communications"]] == [DECODED]
        # The same decoded sentence on every surface.
        assert DECODED in candidate["source_preview"]

        # Rescanning finds the candidate it made; nothing doubles.
        again = client.post(
            "/api/calendar/email-invitation-candidates/extract",
            headers=headers,
            json={"matter_id": matter["id"]},
        )
        assert again.status_code == 200, again.text
        assert again.json()["created_count"] == 0
        assert [row["id"] for row in again.json()["candidates"]] == [candidate["id"]]

        # Reviewing returns the same decoded text.
        rejected = client.patch(
            f"/api/calendar/email-invitation-candidates/{candidate['id']}",
            headers=headers,
            json={"action": "reject"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["source_preview"] == candidate["source_preview"]
        assert rejected.json()["detected_location"] == "Court & Chamber 4"
        assert bootstrap["company"]["id"] == rejected.json()["company_id"]
    finally:
        set_gmail_provider_for_tests(None)


def test_rescan_reuses_a_candidate_stored_before_the_fix(client: TestClient) -> None:
    """Old candidates were extracted from escaped text, so their key differs."""

    try:
        bootstrap, token, matter = _gmail_matter(client, "adj23-legacy", "ADJ23-LEGACY", ESCAPED)
        headers = _auth(token)
        with get_session_factory()() as session:
            row = session.scalar(
                select(Communication).where(Communication.matter_id == matter["id"])
            )
            assert row is not None
            legacy = _extract_from_text(row, _source_text(row))
            assert legacy is not None
            # The pre-fix venue stopped at the entity's ";".
            assert legacy.location == "Court &amp"
            session.add(
                EmailCalendarCandidate(
                    company_id=row.company_id,
                    matter_id=row.matter_id,
                    communication_id=row.id,
                    thread_key=None,
                    normalized_key=legacy.normalized_key,
                    detected_title=legacy.title,
                    detected_start_at=legacy.start_at,
                    detected_end_at=legacy.end_at,
                    detected_location=legacy.location,
                    source_preview=legacy.preview,
                    confidence_band=legacy.confidence_band,
                    status=EmailCalendarCandidateStatus.NEEDS_REVIEW,
                    created_by_membership_id=bootstrap["membership"]["id"],
                )
            )
            session.commit()
        extracted = client.post(
            "/api/calendar/email-invitation-candidates/extract",
            headers=headers,
            json={"matter_id": matter["id"]},
        )
        assert extracted.status_code == 200, extracted.text
        assert extracted.json()["created_count"] == 0
        listed = client.get(
            "/api/calendar/email-invitation-candidates",
            headers=headers,
            params={"matter_id": matter["id"]},
        ).json()["candidates"]
        assert len(listed) == 1
        # The legacy row is still decoded exactly once.
        assert "&#39;" not in listed[0]["source_preview"]
        assert DECODED in listed[0]["source_preview"]
    finally:
        set_gmail_provider_for_tests(None)


def test_pasted_email_text_is_never_decoded_and_reads_the_same_everywhere(
    client: TestClient,
) -> None:
    """The reviewer's probe: one pasted row, two surfaces, one reading."""

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADJ23-001")
    literal = "Calendar invitation for 2026-06-15 at 10:30 AM. Venue: Court &amp; Chamber 4."
    imported = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json=_calendar_invite_payload("adj23-invite-001", body_preview=literal),
    )
    assert imported.status_code == 200, imported.text
    extracted = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=headers,
        json={"matter_id": matter_id},
    )
    assert extracted.status_code == 200, extracted.text
    candidate = extracted.json()["candidates"][0]
    assert literal in candidate["source_preview"]
    timeline = client.get(f"/api/matters/{matter_id}/communications/timeline", headers=headers)
    assert timeline.status_code == 200, timeline.text
    previews = [item["preview"] or "" for item in timeline.json()["items"]]
    assert any(literal in preview for preview in previews), previews
    assert not any("Court & Chamber" in preview for preview in previews)


def test_typed_communication_is_not_decoded_on_the_timeline(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADJ23-002")
    with get_session_factory()() as session:
        session.add(
            Communication(
                company_id=bootstrap["company"]["id"],
                matter_id=matter_id,
                direction=CommunicationDirection.INBOUND,
                channel=CommunicationChannel.EMAIL,
                subject="manual_log subject",
                body="Typed literally: AT&amp;T",
                status=CommunicationStatus.LOGGED,
                occurred_at=datetime(2026, 10, 30, 6, 0, tzinfo=UTC),
                created_by_membership_id=bootstrap["membership"]["id"],
                metadata_json={"source": "manual_log"},
            )
        )
        session.commit()
    timeline = client.get(f"/api/matters/{matter_id}/communications/timeline", headers=headers)
    assert timeline.status_code == 200, timeline.text
    assert [item["preview"] for item in timeline.json()["items"]] == ["Typed literally: AT&amp;T"]
    listed = client.get(f"/api/matters/{matter_id}/communications", headers=headers)
    assert [row["body"] for row in listed.json()["communications"]] == ["Typed literally: AT&amp;T"]


def _mailbox_row(provider: str, snippet: str) -> SimpleNamespace:
    now = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)
    return SimpleNamespace(
        id="row-1",
        company_id="company-1",
        mailbox_connection_id="connection-1",
        connection=SimpleNamespace(provider=provider),
        matter_id=None,
        communication_id=None,
        provider_message_id="message-1",
        provider_thread_id=None,
        subject="Hearing notice",
        sender_name="Registry",
        occurred_at=now,
        snippet=snippet,
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


def test_mailbox_snippet_is_decoded_for_gmail_only() -> None:
    escaped = "Hearing on 15/06/2026 &#39;Court 4&#39; &amp; chambers"
    gmail = _mailbox_row("gmail", escaped)
    assert _message_record(gmail).snippet == "Hearing on 15/06/2026 'Court 4' & chambers"
    # A note made from the Gmail message carries the decoded text once.
    assert _default_note_body(gmail).endswith("Hearing on 15/06/2026 'Court 4' & chambers")
    # Outlook previews are plain text: a literal entity stays as written.
    outlook = _mailbox_row("outlook_mail", "Ask AT&amp;T about it")
    assert _message_record(outlook).snippet == "Ask AT&amp;T about it"
    assert _default_note_body(outlook).endswith("Ask AT&amp;T about it")
