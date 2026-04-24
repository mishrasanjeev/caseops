"""Phase C-1 hardening (2026-04-24) — actually send the portal magic link.

C-1 shipped the invite + verify flow but only returned ``debug_token``
in non-prod. In prod the token never reached the user's inbox, so
real client invitations were a no-op. This module closes the loop.

The send path mirrors the SendGrid call in
``services.communications._send_via_sendgrid``: a single httpx POST
to the v3 API with a plain-text body. We deliberately do not create a
``Communication`` row for this — magic-link emails are not part of
the matter conversation log; they are infra-level auth artifacts and
belong in ``model_runs``-style traceability, not the comms history.

Failures are non-fatal: an invite that creates the PortalUser + grant
+ magic-link in the DB but fails to dispatch the email returns the
invite as success. The owner can either re-invite (which re-mints a
fresh token) or hand the user a debug-token in non-prod. The audit
event records the dispatch outcome explicitly.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from caseops_api.core.settings import get_settings

logger = logging.getLogger(__name__)


def portal_verify_url(token: str) -> str:
    settings = get_settings()
    base = str(settings.public_app_url).rstrip("/")
    return f"{base}/portal/verify?token={quote(token, safe='')}"


def _is_prod() -> bool:
    env = (get_settings().env or "").lower()
    return env in {"production", "prod"}


def send_portal_magic_link(
    *,
    to_email: str,
    full_name: str,
    company_display_name: str,
    token: str,
) -> tuple[bool, str | None]:
    """Send a magic-link email via SendGrid.

    Returns ``(delivered, error_message)``. ``delivered=True`` means
    SendGrid accepted the request (200/202); the actual delivery
    status surfaces later via the SendGrid event webhook for hearing
    reminders + comms — magic links don't subscribe to that today
    because we never need to retry a one-off auth email.

    In NON-prod this is a no-op (returns ``(False, "non-prod")``) so
    test runs do not burn SendGrid credit. The route response will
    surface ``debug_token`` in non-prod for smoke tests that need to
    drive verify directly.
    """
    settings = get_settings()
    if not (settings.sendgrid_api_key and settings.sendgrid_sender_email):
        return False, "sendgrid not configured"
    if not _is_prod():
        return False, "non-prod"

    verify_url = portal_verify_url(token)
    subject = (
        f"Sign in to your {company_display_name} portal on CaseOps"
    )
    body_text = (
        f"Hi {full_name},\n\n"
        f"{company_display_name} has invited you to their CaseOps "
        "workspace portal. Click the link below to sign in. The link "
        "is single-use and expires in 30 minutes.\n\n"
        f"{verify_url}\n\n"
        "If you did not expect this invitation, you can safely ignore "
        "this email — no account is created on your side until you "
        "click the link.\n\n"
        "— CaseOps"
    )

    try:
        response = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [
                    {"to": [{"email": to_email, "name": full_name}]}
                ],
                "from": {
                    "email": settings.sendgrid_sender_email,
                    "name": settings.sendgrid_sender_name,
                },
                "subject": subject,
                "content": [{"type": "text/plain", "value": body_text}],
            },
            timeout=20,
        )
    except httpx.HTTPError as exc:
        logger.warning("portal_mailer.dispatch.failed", exc_info=exc)
        return False, f"network: {exc!s}"

    if response.status_code in (200, 202):
        return True, None
    return False, f"sendgrid {response.status_code}: {response.text[:200]}"


__all__ = ["portal_verify_url", "send_portal_magic_link"]
