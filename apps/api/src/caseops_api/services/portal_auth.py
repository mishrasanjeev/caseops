"""Phase C-1 (2026-04-24) — magic-link auth for PortalUser.

The plaintext magic-link token is generated, hashed (SHA-256) for
storage, and returned to the caller exactly once so AutoMail can
embed it in an email. After that, only the hash exists; verification
re-hashes the user-supplied token and compares.

All branchy logic in ``request_link`` returns the same shape on hit
or miss to defeat email-existence enumeration.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    MatterPortalGrant,
    PortalMagicLink,
    PortalUser,
    PortalUserRole,
)

# Per D2 in PHASE_C_KICKOFF_2026-04-24.md.
MAGIC_LINK_TTL_MINUTES = 30


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    # 32 bytes = 256 bits of entropy. urlsafe so it fits in an email
    # link without escaping; ~43 chars long, comfortable to type if a
    # client copy-pastes from a webmail preview.
    return secrets.token_urlsafe(32)


def request_magic_link(
    session: Session,
    *,
    company_slug: str,
    email: str,
    request_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str | None, PortalUser | None]:
    """Generate + persist a magic link for (company_slug, email).

    Returns ``(token, portal_user)`` on hit, ``(None, None)`` on miss.
    Callers MUST translate the miss into the same outward response as
    a hit so an attacker cannot probe for valid emails OR slugs.

    The plaintext is returned exactly once; only the hash lives in
    the DB. AutoMail embeds the plaintext in the link sent to the
    user's email.
    """
    email_norm = (email or "").strip().lower()
    if not email_norm:
        return None, None

    company = session.scalars(
        select(Company).where(Company.slug == company_slug.strip().lower())
    ).first()
    if company is None:
        return None, None

    portal_user = session.scalars(
        select(PortalUser).where(
            PortalUser.company_id == company.id,
            PortalUser.email == email_norm,
            PortalUser.is_active.is_(True),
        )
    ).first()
    if portal_user is None:
        return None, None

    token = _generate_token()
    link = PortalMagicLink(
        portal_user_id=portal_user.id,
        token_hash=_hash_token(token),
        expires_at=_utcnow() + timedelta(minutes=MAGIC_LINK_TTL_MINUTES),
        requested_ip=request_ip,
        requested_user_agent=(user_agent or "")[:255] or None,
    )
    session.add(link)
    session.commit()
    session.refresh(portal_user)
    return token, portal_user


class InvalidMagicLink(HTTPException):
    def __init__(self, detail: str = "This link is invalid or expired.") -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


def verify_magic_link(
    session: Session, *, token: str
) -> PortalUser:
    """Consume a magic link, returning the PortalUser on success.

    Single-use: the row is marked ``consumed_at`` on first use; a
    replay attempt returns the same generic error as an unknown
    token, so timing or response-shape leaks cannot distinguish
    "wrong token" from "already used".
    """
    if not token:
        raise InvalidMagicLink()

    link = session.scalars(
        select(PortalMagicLink).where(
            PortalMagicLink.token_hash == _hash_token(token)
        )
    ).first()
    now = _utcnow()
    if link is None or link.consumed_at is not None:
        raise InvalidMagicLink()
    expires = link.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        raise InvalidMagicLink()

    portal_user = session.get(PortalUser, link.portal_user_id)
    if portal_user is None or not portal_user.is_active:
        raise InvalidMagicLink()

    link.consumed_at = now
    portal_user.last_signed_in_at = now
    session.commit()
    session.refresh(portal_user)
    return portal_user


def list_active_grants(
    session: Session, *, portal_user_id: str
) -> list[MatterPortalGrant]:
    return list(
        session.scalars(
            select(MatterPortalGrant)
            .where(
                MatterPortalGrant.portal_user_id == portal_user_id,
                MatterPortalGrant.revoked_at.is_(None),
            )
            .order_by(MatterPortalGrant.granted_at.desc())
        )
    )


def invite_portal_user(
    session: Session,
    *,
    company_id: str,
    inviting_membership_id: str,
    email: str,
    full_name: str,
    role: str,
    matter_ids: list[str],
    scope_json: dict | None = None,
) -> tuple[PortalUser, list[MatterPortalGrant], str]:
    """Internal-membership-driven invite. Creates the PortalUser if
    none exists for (company, email); creates one MatterPortalGrant
    per matter; mints a magic link.

    Returns ``(portal_user, grants, token)``. The plaintext token
    must be sent via AutoMail and never persisted by the caller.
    """
    if role not in {r.value for r in PortalUserRole}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unknown portal role. Use 'client' or 'outside_counsel'."
            ),
        )
    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid email is required.",
        )
    name_clean = (full_name or "").strip()[:255]
    if not name_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name is required.",
        )

    portal_user = session.scalars(
        select(PortalUser).where(
            PortalUser.company_id == company_id,
            PortalUser.email == email_norm,
        )
    ).first()
    if portal_user is None:
        portal_user = PortalUser(
            id=str(uuid4()),
            company_id=company_id,
            email=email_norm,
            full_name=name_clean,
            role=role,
            is_active=True,
            invited_by_membership_id=inviting_membership_id,
        )
        session.add(portal_user)
        session.flush()
    elif portal_user.role != role:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This email is already invited to the workspace under a "
                "different portal role."
            ),
        )

    grants: list[MatterPortalGrant] = []
    for matter_id in matter_ids:
        existing = session.scalars(
            select(MatterPortalGrant).where(
                MatterPortalGrant.portal_user_id == portal_user.id,
                MatterPortalGrant.matter_id == matter_id,
            )
        ).first()
        if existing is None:
            grant = MatterPortalGrant(
                id=str(uuid4()),
                portal_user_id=portal_user.id,
                matter_id=matter_id,
                role=role,
                scope_json=scope_json,
                granted_by_membership_id=inviting_membership_id,
            )
            session.add(grant)
            grants.append(grant)
        else:
            if existing.revoked_at is not None:
                existing.revoked_at = None
                existing.granted_at = _utcnow()
                existing.granted_by_membership_id = inviting_membership_id
            grants.append(existing)
    session.flush()

    token = _generate_token()
    link = PortalMagicLink(
        portal_user_id=portal_user.id,
        token_hash=_hash_token(token),
        expires_at=_utcnow() + timedelta(minutes=MAGIC_LINK_TTL_MINUTES),
    )
    session.add(link)
    session.commit()
    session.refresh(portal_user)
    return portal_user, grants, token


__all__ = [
    "InvalidMagicLink",
    "MAGIC_LINK_TTL_MINUTES",
    "invite_portal_user",
    "list_active_grants",
    "request_magic_link",
    "verify_magic_link",
]
