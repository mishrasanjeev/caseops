"""Phase C-1 (2026-04-24) — /api/portal/* surface.

The portal is the external-user entry point: clients (P8) and
outside counsel (P9) sign in here via magic link. Two router groups
land in this module:

- ``router`` — the unauthenticated / portal-session-protected calls
  (request-link, verify-link, logout, me).
- ``admin_router`` — the inviting endpoints, mounted under /admin so
  workspace owners and admins can mint PortalUsers and grants.

The two share zero auth surface: the admin router rides on the
internal ``get_current_context`` dependency; the public router
either takes no auth (request/verify) or rides on
``get_current_portal_user``.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    get_current_portal_user,
    require_capability,
)
from caseops_api.core.cookies import (
    clear_portal_session_cookie,
    issue_portal_session_cookie,
)
from caseops_api.core.security import (
    PORTAL_SESSION_TTL_MINUTES,
    create_portal_session_token,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import PortalUser
from caseops_api.services.identity import SessionContext
from caseops_api.services.portal_auth import (
    invite_portal_user,
    list_active_grants,
    request_magic_link,
    verify_magic_link,
)

router = APIRouter()
admin_router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
CurrentPortalUser = Annotated[PortalUser, Depends(get_current_portal_user)]
PortalInviter = Annotated[
    SessionContext, Depends(require_capability("portal:invite")),
]


# ---------- request schemas ----------


class PortalRequestLinkPayload(BaseModel):
    company_slug: str = Field(min_length=2, max_length=120)
    email: EmailStr


class PortalVerifyLinkPayload(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class PortalGrantInput(BaseModel):
    matter_id: str = Field(min_length=10, max_length=64)


class PortalInvitePayload(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: Literal["client", "outside_counsel"]
    matter_ids: list[str] = Field(default_factory=list, max_length=50)
    can_upload: bool = False
    can_invoice: bool = False
    can_reply: bool = True


# ---------- response schemas ----------


class PortalGrantRecord(BaseModel):
    id: str
    matter_id: str
    role: Literal["client", "outside_counsel"]
    scope_json: dict | None
    granted_at: str
    revoked_at: str | None = None


class PortalUserRecord(BaseModel):
    id: str
    company_id: str
    email: str
    full_name: str
    role: Literal["client", "outside_counsel"]
    last_signed_in_at: str | None = None


class PortalSessionResponse(BaseModel):
    portal_user: PortalUserRecord
    grants: list[PortalGrantRecord]


class PortalRequestLinkResponse(BaseModel):
    """Always 200 with the same shape regardless of whether the email
    matched a real PortalUser. Prevents email-enumeration through
    response timing or shape diff."""

    delivered: Literal[True] = True
    # In NON-prod environments only, the test harness can read this
    # field to drive the verify call without scraping email. In prod
    # this is always None and the real magic link is sent via
    # AutoMail; see PHASE_C_KICKOFF_2026-04-24.md.
    debug_token: str | None = None


class PortalInviteResponse(BaseModel):
    portal_user: PortalUserRecord
    grants: list[PortalGrantRecord]
    debug_token: str | None = None  # NON-prod only.


# ---------- helpers ----------


def _portal_user_record(user: PortalUser) -> PortalUserRecord:
    last = user.last_signed_in_at.isoformat() if user.last_signed_in_at else None
    return PortalUserRecord(
        id=user.id,
        company_id=user.company_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,  # type: ignore[arg-type]
        last_signed_in_at=last,
    )


def _grant_record(grant) -> PortalGrantRecord:
    return PortalGrantRecord(
        id=grant.id,
        matter_id=grant.matter_id,
        role=grant.role,  # type: ignore[arg-type]
        scope_json=grant.scope_json,
        granted_at=grant.granted_at.isoformat(),
        revoked_at=grant.revoked_at.isoformat() if grant.revoked_at else None,
    )


def _is_non_prod() -> bool:
    env = (get_settings().env or "").lower()
    # The debug_token escape hatch lives in dev / test / e2e only.
    return env not in {"production", "prod"}


# ---------- public routes ----------


@router.post(
    "/auth/request-link",
    response_model=PortalRequestLinkResponse,
    summary="Request a magic-link sign-in for a portal user",
    description=(
        "Always returns 200 with the same shape regardless of whether "
        "the email is registered, to prevent email enumeration. In "
        "non-prod environments the response embeds the magic-link "
        "token so smoke tests can verify without scraping email. In "
        "prod the token is sent via AutoMail and the response carries "
        "no token."
    ),
)
async def post_portal_request_link(
    payload: PortalRequestLinkPayload,
    session: DbSession,
    request: Request,
) -> PortalRequestLinkResponse:
    token = request_magic_link(
        session,
        company_slug=payload.company_slug,
        email=str(payload.email),
        request_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return PortalRequestLinkResponse(
        delivered=True,
        debug_token=token if (token and _is_non_prod()) else None,
    )


@router.post(
    "/auth/verify-link",
    response_model=PortalSessionResponse,
    summary="Verify a magic-link token, set the portal session cookie",
)
async def post_portal_verify_link(
    payload: PortalVerifyLinkPayload,
    response: Response,
    session: DbSession,
) -> PortalSessionResponse:
    portal_user = verify_magic_link(session, token=payload.token)
    token = create_portal_session_token(
        portal_user_id=portal_user.id,
        company_id=portal_user.company_id,
        role=portal_user.role,
    )
    issue_portal_session_cookie(
        response,
        access_token=token,
        ttl_seconds=PORTAL_SESSION_TTL_MINUTES * 60,
        env=get_settings().env,
    )
    return PortalSessionResponse(
        portal_user=_portal_user_record(portal_user),
        grants=[_grant_record(g) for g in list_active_grants(
            session, portal_user_id=portal_user.id,
        )],
    )


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear the portal session cookie",
)
async def post_portal_logout(response: Response) -> None:
    clear_portal_session_cookie(response, env=get_settings().env)


@router.get(
    "/me",
    response_model=PortalSessionResponse,
    summary="Current portal user + active matter grants",
)
async def get_portal_me(
    portal_user: CurrentPortalUser,
    session: DbSession,
) -> PortalSessionResponse:
    return PortalSessionResponse(
        portal_user=_portal_user_record(portal_user),
        grants=[
            _grant_record(g)
            for g in list_active_grants(
                session, portal_user_id=portal_user.id,
            )
        ],
    )


# ---------- admin (workspace-owner) routes ----------


@admin_router.post(
    "/portal/invitations",
    response_model=PortalInviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a client or outside counsel into the portal",
)
async def post_portal_invitation(
    payload: PortalInvitePayload,
    context: PortalInviter,
    session: DbSession,
) -> PortalInviteResponse:
    if not payload.matter_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one matter_id is required for the invite scope.",
        )
    portal_user, grants, token = invite_portal_user(
        session,
        company_id=context.company.id,
        inviting_membership_id=context.membership.id,
        email=str(payload.email),
        full_name=payload.full_name,
        role=payload.role,
        matter_ids=payload.matter_ids,
        scope_json={
            "can_upload": bool(payload.can_upload),
            "can_invoice": bool(payload.can_invoice),
            "can_reply": bool(payload.can_reply),
        },
    )
    return PortalInviteResponse(
        portal_user=_portal_user_record(portal_user),
        grants=[_grant_record(g) for g in grants],
        debug_token=token if _is_non_prod() else None,
    )
