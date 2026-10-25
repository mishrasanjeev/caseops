"""PKCE handoff and rotation serialized by the existing identity fence."""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.native_auth import create_native_access_token, require_native_issuance
from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CompanyMembership,
    NativeAuthorizationCode,
    NativeDeviceSession,
    NativeRefreshToken,
    UserMFASetting,
    UserMFAStepUp,
)
from caseops_api.schemas.native_auth import (
    NativeAuthorizeRequest,
    NativeAuthorizeResponse,
    NativeSessionRecord,
    NativeSessionsResponse,
    NativeTokenRequest,
    NativeTokenResponse,
)
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_oauth,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import (
    _token_precedes_membership_cutoff,
    build_auth_context,
    get_session_context,
)
from caseops_api.services.security import login_mfa_challenge_state
from caseops_api.services.session_context import SessionContext

MAX_DEVICE_SESSIONS = 20
MAX_REFRESH_HISTORY = 10_000


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


def _invalid() -> None:
    raise HTTPException(401, "Native credentials are expired, revoked or invalid. Sign in again.")


def _identity_fence(
    session: Session,
    *,
    membership_id: str,
    source_issued_at: float,
    validate: bool = True,
) -> SessionContext:
    company_id = session.scalar(
        select(CompanyMembership.company_id).where(
            CompanyMembership.id == membership_id,
        )
    )
    if company_id is None:
        _invalid()
    company, actors = lock_company_memberships_for_oauth(
        session,
        company_id=company_id,
        membership_ids=(membership_id,),
    )
    membership = actors.get(membership_id)
    if membership is None or company is None:
        _invalid()
    context = SessionContext(
        company=company,
        user=membership.user,
        membership=membership,
        token_issued_at=source_issued_at,
    )
    if validate:
        _validate_identity(context)
    return context


def _validate_identity(context: SessionContext) -> None:
    if (
        not context.company.is_active
        or not context.membership.is_active
        or not context.user.is_active
        or _token_precedes_membership_cutoff(
            context.membership,
            token_issued_at=context.token_issued_at,
        )
    ):
        _invalid()


def _mfa_proof(
    session: Session,
    context: SessionContext,
    *,
    source_issued_at: float,
) -> tuple[datetime | None, datetime | None]:
    state = login_mfa_challenge_state(session, context=context)
    setting = session.scalar(
        select(UserMFASetting).where(UserMFASetting.user_id == context.user.id)
    )
    if state["mfa_challenge_required"]:
        raise ProblemHTTPException(
            403,
            problem_type="native_mfa_required",
            detail="Complete MFA in the browser before native sign-in.",
        )
    if setting is None or setting.status != "enrolled":
        return None, None
    proof = session.scalar(
        select(UserMFAStepUp)
        .where(
            UserMFAStepUp.user_id == context.user.id,
            UserMFAStepUp.membership_id == context.membership.id,
            UserMFAStepUp.source_token_issued_at == source_issued_at,
            UserMFAStepUp.completed_at >= datetime.fromtimestamp(source_issued_at, UTC),
            UserMFAStepUp.expires_at > _now(),
        )
        .order_by(UserMFAStepUp.completed_at.desc())
        .limit(1)
    )
    if proof is None:
        raise ProblemHTTPException(
            403,
            problem_type="native_mfa_required",
            detail="Complete MFA in this browser session before native sign-in.",
        )
    return proof.completed_at, proof.expires_at


def _check_mfa(
    session: Session,
    context: SessionContext,
    credential: NativeAuthorizationCode | NativeDeviceSession,
) -> None:
    state = login_mfa_challenge_state(session, context=context)
    setting = session.scalar(
        select(UserMFASetting).where(UserMFASetting.user_id == context.user.id)
    )
    enrolled = setting is not None and setting.status == "enrolled"
    if (
        state["mfa_challenge_required"]
        or (
            enrolled
            and (
                credential.mfa_verified_at is None
                or credential.mfa_expires_at is None
                or _aware(credential.mfa_expires_at) <= _now()
                or (
                    setting.verified_at is not None
                    and _aware(setting.verified_at) > _aware(credential.mfa_verified_at)
                )
            )
        )
        or (credential.mfa_verified_at is not None and not enrolled)
    ):
        raise HTTPException(403, "Native MFA authorization has expired or changed. Sign in again.")


def authorize(
    session: Session,
    context: SessionContext,
    payload: NativeAuthorizeRequest,
) -> NativeAuthorizeResponse:
    require_native_issuance(payload.redirect_uri)
    if context.token_issued_at is None:
        _invalid()
    context = _identity_fence(
        session,
        membership_id=context.membership.id,
        source_issued_at=context.token_issued_at,
    )
    verified_at, mfa_expires_at = _mfa_proof(
        session,
        context,
        source_issued_at=context.token_issued_at,
    )
    now = _now()
    pending = session.scalar(
        select(func.count())
        .select_from(NativeAuthorizationCode)
        .where(
            NativeAuthorizationCode.membership_id == context.membership.id,
            NativeAuthorizationCode.consumed_at.is_(None),
            NativeAuthorizationCode.expires_at > now,
        )
    )
    if pending >= 10:
        raise HTTPException(429, "Too many pending native sign-ins. Wait a minute and try again.")
    code = secrets.token_urlsafe(32)
    session.add(
        NativeAuthorizationCode(
            code_hash=_hash(code),
            membership_id=context.membership.id,
            code_challenge=payload.code_challenge,
            platform=payload.platform,
            redirect_uri=payload.redirect_uri,
            source_issued_at=context.token_issued_at,
            mfa_verified_at=verified_at,
            mfa_expires_at=mfa_expires_at,
            expires_at=now + timedelta(seconds=get_settings().native_code_ttl_seconds),
        )
    )
    record_from_context(
        session,
        context,
        action="native.authorized",
        target_type="membership",
        target_id=context.membership.id,
        metadata={"platform": payload.platform},
    )
    session.commit()
    return NativeAuthorizeResponse(
        code=code, state=payload.state, redirect_uri=payload.redirect_uri
    )


def _issue(
    session: Session,
    context: SessionContext,
    device: NativeDeviceSession,
) -> NativeTokenResponse:
    now = _now()
    ttl = get_settings().native_access_ttl_seconds
    expires_at = min(now + timedelta(seconds=ttl), _aware(device.expires_at))
    if device.mfa_expires_at is not None:
        expires_at = min(expires_at, _aware(device.mfa_expires_at))
    expires_in = int((expires_at - now).total_seconds())
    if expires_in <= 0:
        _invalid()
    refresh_token = secrets.token_urlsafe(48)
    session.add(
        NativeRefreshToken(
            session_id=device.id,
            token_hash=_hash(refresh_token),
            expires_at=device.expires_at,
        )
    )
    device.last_used_at = now
    context_response = build_auth_context(session, context)
    return NativeTokenResponse(
        **context_response.model_dump(),
        access_token=create_native_access_token(
            session_id=device.id,
            user_id=context.user.id,
            membership_id=context.membership.id,
            company_id=context.company.id,
            issued_at=now,
            expires_at=expires_at,
        ),
        refresh_token=refresh_token,
        session_id=device.id,
        expires_in=expires_in,
    )


def exchange(session: Session, payload: NativeTokenRequest) -> NativeTokenResponse:
    require_native_issuance(payload.redirect_uri)
    advisory = session.scalar(
        select(NativeAuthorizationCode).where(
            NativeAuthorizationCode.code_hash == _hash(payload.code),
        )
    )
    if advisory is None:
        _invalid()
    context = _identity_fence(
        session,
        membership_id=advisory.membership_id,
        source_issued_at=advisory.source_issued_at,
    )
    code = session.scalar(
        select(NativeAuthorizationCode)
        .where(
            NativeAuthorizationCode.id == advisory.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if code is None or code.consumed_at is not None or _aware(code.expires_at) <= _now():
        _invalid()
    if (
        not hmac.compare_digest(code.code_challenge, pkce_challenge(payload.code_verifier))
        or code.redirect_uri != payload.redirect_uri
        or code.platform != payload.platform
    ):
        _invalid()
    _check_mfa(session, context, code)
    active = session.scalar(
        select(func.count())
        .select_from(NativeDeviceSession)
        .where(
            NativeDeviceSession.membership_id == context.membership.id,
            NativeDeviceSession.revoked_at.is_(None),
            NativeDeviceSession.expires_at > _now(),
        )
    )
    if active >= MAX_DEVICE_SESSIONS:
        raise HTTPException(409, "Revoke an existing native session before signing in again.")
    now = _now()
    code.consumed_at = now
    device = NativeDeviceSession(
        membership_id=context.membership.id,
        platform=code.platform,
        source_issued_at=code.source_issued_at,
        mfa_verified_at=code.mfa_verified_at,
        mfa_expires_at=code.mfa_expires_at,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=get_settings().native_session_ttl_days),
    )
    session.add(device)
    session.flush()
    result = _issue(session, context, device)
    record_from_context(
        session,
        context,
        action="native.session_created",
        target_type="native_session",
        target_id=device.id,
        metadata={"platform": device.platform},
    )
    session.commit()
    return result


def _revoke(session: Session, device: NativeDeviceSession, reason: str) -> None:
    if device.revoked_at is None:
        device.revoked_at = _now()
        device.revocation_reason = reason
    session.flush()


def rotate(session: Session, refresh_token: str) -> NativeTokenResponse:
    require_native_issuance()
    advisory = session.scalar(
        select(NativeRefreshToken).where(
            NativeRefreshToken.token_hash == _hash(refresh_token),
        )
    )
    if advisory is None:
        _invalid()
    family = session.get(NativeDeviceSession, advisory.session_id)
    if family is None:
        _invalid()
    # Lock identity before the family, but detect replay before validating that
    # identity. Offboarding must not prevent durable family revocation.
    context = _identity_fence(
        session,
        membership_id=family.membership_id,
        source_issued_at=family.source_issued_at,
        validate=False,
    )
    device = session.scalar(
        select(NativeDeviceSession)
        .where(
            NativeDeviceSession.id == family.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    token = session.scalar(
        select(NativeRefreshToken)
        .where(
            NativeRefreshToken.id == advisory.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if token.consumed_at is not None:
        _revoke(session, device, "refresh_replay")
        record_from_context(
            session,
            context,
            action="native.refresh_replay",
            target_type="native_session",
            target_id=device.id,
        )
        session.commit()
        _invalid()
    if device.revoked_at is not None or _aware(device.expires_at) <= _now():
        _invalid()
    _validate_identity(context)
    if _aware(token.expires_at) <= _now():
        _invalid()
    _check_mfa(session, context, device)
    count = session.scalar(
        select(func.count())
        .select_from(NativeRefreshToken)
        .where(
            NativeRefreshToken.session_id == device.id,
        )
    )
    if count >= MAX_REFRESH_HISTORY:
        _revoke(session, device, "rotation_limit")
        session.commit()
        _invalid()
    token.consumed_at = _now()
    result = _issue(session, context, device)
    session.commit()
    return result


def native_context(session: Session, claims: dict) -> SessionContext:
    device = session.get(NativeDeviceSession, claims["sid"])
    if (
        device is None
        or device.membership_id != claims["membership_id"]
        or device.revoked_at is not None
        or _aware(device.expires_at) <= _now()
    ):
        _invalid()
    context = get_session_context(
        session,
        device.membership_id,
        token_issued_at=device.source_issued_at,
    )
    if context.company.id != claims["company_id"] or context.user.id != claims["sub"]:
        _invalid()
    _check_mfa(session, context, device)
    context.native_session_id = device.id
    return context


def logout(session: Session, refresh_token: str) -> None:
    token = session.scalar(
        select(NativeRefreshToken).where(
            NativeRefreshToken.token_hash == _hash(refresh_token),
        )
    )
    if token is not None:
        device = session.scalar(
            select(NativeDeviceSession)
            .where(
                NativeDeviceSession.id == token.session_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if device is not None:
            _revoke(session, device, "logout")
    session.commit()


def list_sessions(
    session: Session,
    context: SessionContext,
    current_id: str | None,
) -> NativeSessionsResponse:
    rows = session.scalars(
        select(NativeDeviceSession)
        .where(
            NativeDeviceSession.membership_id == context.membership.id,
            NativeDeviceSession.expires_at > _now(),
            NativeDeviceSession.revoked_at.is_(None),
        )
        .order_by(NativeDeviceSession.created_at.desc())
        .limit(MAX_DEVICE_SESSIONS)
    )
    return NativeSessionsResponse(
        sessions=[
            NativeSessionRecord(
                id=row.id,
                platform=row.platform,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
                current=row.id == current_id,
            )
            for row in rows
        ]
    )


def revoke_session(session: Session, context: SessionContext, session_id: str) -> None:
    device = session.scalar(
        select(NativeDeviceSession)
        .where(
            NativeDeviceSession.id == session_id,
            NativeDeviceSession.membership_id == context.membership.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if device is None:
        raise HTTPException(404, "Native session not found.")
    _revoke(session, device, "user_revoked")
    record_from_context(
        session,
        context,
        action="native.session_revoked",
        target_type="native_session",
        target_id=device.id,
    )
    session.commit()
