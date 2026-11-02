"""Authenticated, local-only Gmail fixture for the real mailbox import route.

B4-ADJ-23 is about Gmail returning message snippets HTML-escaped. The fixture
gives one fresh batch-4 tester tenant a connected Gmail mailbox whose provider
returns one escaped snippet; the browser journey then calls the product's own
``POST /api/mailbox/gmail/import`` so the Communication is written by the
product code (``gmail_provider_import``), not by a fixture. Every other tenant
keeps the real provider.
"""

import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from calendar_oauth_emulator import require_test_environment

PREFIX = "/_e2e/gmail-import"
TENANT_PREFIX = "bugs4-"
# Escaped exactly as Gmail escapes a snippet; the date is synthetic.
SNIPPET = (
    "Calendar invitation for 2099-06-15 at 10:30 AM. Venue: Court &amp; Chamber 4. "
    "Bring the client&#39;s file &quot;A&quot;&nbsp;now."
)
DECODED = (
    "Calendar invitation for 2099-06-15 at 10:30 AM. Venue: Court & Chamber 4. "
    'Bring the client\'s file "A" now.'
)


class GmailImportEmulator:
    configured = True
    webhook_configured = False
    unavailable_reason = None

    def __init__(self) -> None:
        self.messages: dict[str, list[Any]] = {}
        self.companies: set[str] = set()
        self.lock = threading.Lock()

    def register(self, company_id: str, message: Any) -> str:
        token = "offline-gmail-access-" + uuid4().hex
        with self.lock:
            if len(self.messages) >= 128:
                raise RuntimeError("Offline Gmail fixture inventory limit reached.")
            self.messages[token] = [message]
            self.companies.add(company_id)
        return token

    def list_recent_messages(self, *, token_payload: dict[str, Any], limit: int) -> list[Any]:
        with self.lock:
            messages = self.messages.get(str(token_payload.get("access_token")))
        if messages is None:
            raise RuntimeError("Only a registered offline Gmail fixture can be listed.")
        return messages[:limit]

    def list_history_messages(self, **_: Any) -> list[Any]:
        return []

    def authorization_url(self, *, state: str) -> str:
        raise RuntimeError("The offline Gmail fixture cannot authorize Google accounts.")

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        raise RuntimeError("The offline Gmail fixture cannot exchange Google credentials.")

    def start_watch(self, **_: Any) -> dict[str, Any]:
        raise RuntimeError("The offline Gmail fixture has no Pub/Sub watch.")

    def fetch_attachment(self, **_: Any) -> bytes:
        raise RuntimeError("The offline Gmail fixture has no attachments.")


def install_gmail_import_emulator(app: Any) -> None:
    # Validate before importing application code, mounting routes or overriding providers.
    require_test_environment()

    from fastapi import APIRouter, Depends, HTTPException, Request
    from pydantic import BaseModel, ConfigDict, Field
    from sqlalchemy import select

    from caseops_api.api.dependencies import DbSession, require_capability
    from caseops_api.core.automated_test_context import (
        NO_PAID_PROVIDERS_HEADER,
        NO_PAID_PROVIDERS_VALUE,
    )
    from caseops_api.db.models import (
        MailboxConnectionStatus,
        MailboxProvider,
        Matter,
        UserMailboxConnection,
    )
    from caseops_api.services import gmail_sync
    from caseops_api.services.calendar_sync import _encrypt_token_payload
    from caseops_api.services.session_context import SessionContext

    class FixtureRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        matter_id: str = Field(min_length=36, max_length=36)

    def require_no_paid_marker(request: Request) -> None:
        if request.headers.get(NO_PAID_PROVIDERS_HEADER) != NO_PAID_PROVIDERS_VALUE:
            raise HTTPException(
                403, "The offline Gmail fixture requires the no-paid-provider marker."
            )

    emulator = GmailImportEmulator()
    original_provider = gmail_sync._gmail_provider

    def tenant_scoped_provider(session: Any = None, *, context: Any = None) -> Any:
        # Only a tenant that registered a fixture talks to the emulator.
        if context is not None and context.company.id in emulator.companies:
            return emulator
        return original_provider(session, context=context)

    router = APIRouter(
        prefix=PREFIX, include_in_schema=False, dependencies=[Depends(require_no_paid_marker)],
    )
    owner_dependency = Depends(require_capability("calendar:sync"))

    @router.post("/fixtures")
    def seed_fixture(
        payload: FixtureRequest, session: DbSession,
        context: SessionContext = owner_dependency,
    ) -> dict[str, object]:
        if context.membership.role != "owner" or not context.company.slug.startswith(TENANT_PREFIX):
            raise HTTPException(403, "Only a fresh batch-4 tester owner may use the Gmail fixture.")
        matter = session.get(Matter, payload.matter_id)
        if matter is None or matter.company_id != context.company.id:
            raise HTTPException(404, "Fixture Matter not found.")
        if not matter.is_active:
            raise HTTPException(409, "Fixture Matter must be operational.")
        if session.scalar(select(UserMailboxConnection.id).where(
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.provider == MailboxProvider.GMAIL,
        ).limit(1)):
            raise HTTPException(409, "Offline Gmail fixtures cannot replace a retained mailbox.")
        identity = uuid4().hex
        subject = f"Invitation: Strategy conference {matter.matter_code}"
        message = gmail_sync.GmailMessageMetadata(
            provider_message_id="offline-gmail-message-" + identity,
            provider_thread_id="offline-gmail-thread-" + identity,
            history_id=None,
            subject=subject,
            sender_email="registry-clerk@example.com",
            sender_name="Registry Clerk",
            received_at=datetime.now(UTC),
            snippet=SNIPPET,
            labels=("INBOX",),
            attachments=(),
        )
        token = emulator.register(context.company.id, message)
        connection = UserMailboxConnection(
            company_id=context.company.id, membership_id=context.membership.id,
            provider=MailboxProvider.GMAIL, status=MailboxConnectionStatus.CONNECTED,
            provider_account_id="offline-gmail-" + identity,
            display_email="gmail-emulator@example.com", scopes_json=list(gmail_sync.GMAIL_SCOPES),
            encrypted_token_ref=_encrypt_token_payload({"access_token": token}),
            connected_at=datetime.now(UTC),
        )
        session.add(connection)
        session.commit()
        return {
            "connection_id": connection.id, "matter_id": matter.id, "subject": subject,
            "snippet": SNIPPET, "decoded": DECODED,
        }

    gmail_sync._gmail_provider = tenant_scoped_provider
    app.include_router(router)
