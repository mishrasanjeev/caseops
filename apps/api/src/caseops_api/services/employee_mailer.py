from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from caseops_api.core.settings import get_settings, is_non_local_env

logger = logging.getLogger(__name__)


def employee_account_url(token: str, *, purpose: str) -> str:
    settings = get_settings()
    base = str(settings.public_app_url).rstrip("/")
    route = "reset-password" if purpose == "password_reset" else "setup"
    return f"{base}/account/{route}?token={quote(token, safe='')}"


def send_employee_account_link(
    *,
    to_email: str,
    full_name: str,
    company_display_name: str,
    token: str,
    purpose: str,
) -> tuple[bool, str | None]:
    settings = get_settings()
    if not (settings.sendgrid_api_key and settings.sendgrid_sender_email):
        return False, "sendgrid not configured"
    if not is_non_local_env(settings.env):
        return False, "non-prod"

    account_url = employee_account_url(token, purpose=purpose)
    if purpose == "password_reset":
        subject = f"Reset your {company_display_name} CaseOps password"
        intro = (
            f"{company_display_name} generated a password reset link for "
            "your CaseOps employee account."
        )
        expiry = "This link is single-use and expires in 60 minutes."
    else:
        subject = f"Set up your {company_display_name} CaseOps account"
        intro = (
            f"{company_display_name} created a CaseOps employee account "
            "for you."
        )
        expiry = "This link is single-use and expires in 24 hours."

    body_text = (
        f"Hi {full_name},\n\n"
        f"{intro}\n\n"
        f"{account_url}\n\n"
        f"{expiry} CaseOps will never email you a raw password.\n\n"
        "If you did not expect this message, contact your workspace admin.\n\n"
        "- CaseOps"
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
        logger.warning("employee_mailer.dispatch.failed", exc_info=exc)
        return False, f"network: {exc!s}"

    if response.status_code in (200, 202):
        return True, None
    return False, f"sendgrid {response.status_code}: {response.text[:200]}"


__all__ = ["employee_account_url", "send_employee_account_link"]
