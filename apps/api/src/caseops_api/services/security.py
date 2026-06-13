from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    AuditResult,
    MembershipRole,
    PlatformAdminAuditEvent,
    PlatformAdminMembership,
    TenantSecurityPolicy,
    UserMFARecoveryCode,
    UserMFASetting,
    UserMFAStepUp,
)
from caseops_api.schemas.security import (
    MFAEnrollmentStartResponse,
    MFAEnrollmentVerifyResponse,
    MFARecoveryCodesResponse,
    MFASecurityStatusResponse,
    MFAStepUpResponse,
    TenantSecurityPolicyRecord,
    TenantSecurityPolicyUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.platform_admin import record_platform_audit

TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
RECOVERY_CODE_COUNT = 10
STEP_UP_PURPOSES = {
    "platform_admin_access",
    "cost_profile_change",
    "payment_activation_change",
    "billing_export",
    "connector_credential_change",
    "role_capability_change",
    "bulk_export",
    "destructive_action",
    "step_up",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().auth_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_secret(value: str) -> str:
    return "fernet:" + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_secret(value: str | None) -> str | None:
    if not value or not value.startswith("fernet:"):
        return None
    try:
        raw = _fernet().decrypt(value.removeprefix("fernet:").encode("ascii"))
    except (InvalidToken, ValueError):
        return None
    return raw.decode("utf-8")


def _hash_code(code: str) -> str:
    normalized = code.replace("-", "").replace(" ", "").strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _random_base32_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def _verify_totp(secret: str, code: str, *, at: int | None = None) -> bool:
    normalized = code.strip().replace(" ", "")
    if not normalized.isdigit():
        return False
    timestamp = at or int(time.time())
    counter = timestamp // TOTP_PERIOD_SECONDS
    return any(
        hmac.compare_digest(_hotp(secret, counter + skew), normalized)
        for skew in (-1, 0, 1)
    )


def _svg_qr(otpauth_url: str) -> str:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=4,
        box_size=8,
    )
    qr.add_data(otpauth_url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")


def _setting(session: Session, *, user_id: str, create: bool = False) -> UserMFASetting | None:
    row = session.scalar(select(UserMFASetting).where(UserMFASetting.user_id == user_id))
    if row is None and create:
        row = UserMFASetting(user_id=user_id, status="not_enrolled")
        session.add(row)
        session.flush()
    return row


def _active_recovery_codes(session: Session, *, user_id: str) -> list[UserMFARecoveryCode]:
    return list(
        session.scalars(
            select(UserMFARecoveryCode).where(
                UserMFARecoveryCode.user_id == user_id,
                UserMFARecoveryCode.status == "active",
            )
        )
    )


def _generate_recovery_codes(
    session: Session,
    *,
    user_id: str,
    setting: UserMFASetting,
) -> list[str]:
    for row in _active_recovery_codes(session, user_id=user_id):
        row.status = "superseded"
    raw_codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        code = f"{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
        raw_codes.append(code)
        session.add(
            UserMFARecoveryCode(
                user_id=user_id,
                code_hash=_hash_code(code),
                status="active",
            )
        )
    setting.recovery_codes_generated_at = _now()
    session.add(setting)
    session.flush()
    return raw_codes


def _recent_failure_count(session: Session, *, context: SessionContext) -> int:
    window = _now() - timedelta(minutes=5)
    tenant_failures = int(
        session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.company_id == context.company.id,
                AuditEvent.actor_membership_id == context.membership.id,
                AuditEvent.action == "mfa.challenge_failed",
                AuditEvent.created_at >= window,
            )
        )
        or 0
    )
    platform_failures = int(
        session.scalar(
            select(func.count(PlatformAdminAuditEvent.id)).where(
                PlatformAdminAuditEvent.actor_user_id == context.user.id,
                PlatformAdminAuditEvent.action == "mfa.challenge_failed",
                PlatformAdminAuditEvent.created_at >= window,
            )
        )
        or 0
    )
    return tenant_failures + platform_failures


def _audit_mfa(
    session: Session,
    context: SessionContext,
    *,
    action: str,
    result: str = AuditResult.SUCCESS,
    platform_admin: PlatformAdminMembership | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    record_from_context(
        session,
        context,
        action=action,
        target_type="user_mfa",
        target_id=context.user.id,
        result=result,
        metadata=metadata,
    )
    if platform_admin is not None:
        record_platform_audit(
            session,
            context=context,
            platform_admin=platform_admin,
            action=action,
            target_type="user_mfa",
            target_id=context.user.id,
            result=result,
            metadata=metadata,
        )


def tenant_security_policy(
    session: Session,
    *,
    company_id: str,
    create: bool = False,
) -> TenantSecurityPolicy | None:
    row = session.scalar(
        select(TenantSecurityPolicy).where(TenantSecurityPolicy.company_id == company_id)
    )
    if row is None and create:
        row = TenantSecurityPolicy(company_id=company_id)
        session.add(row)
        session.flush()
    return row


def _policy_requires_mfa(
    session: Session,
    context: SessionContext,
    *,
    platform_admin: PlatformAdminMembership | None = None,
) -> tuple[bool, datetime | None, dict[str, bool]]:
    flags = {
        "platform_admin_required": False,
        "tenant_admin_required": False,
        "all_users_required": False,
    }
    enforced_at: datetime | None = None
    if platform_admin is not None and platform_admin.mfa_required:
        flags["platform_admin_required"] = True
        enforced_at = _as_aware(platform_admin.mfa_enforced_at)
    policy = tenant_security_policy(session, company_id=context.company.id)
    if policy is not None:
        policy_enforced_at = _as_aware(policy.mfa_enforced_at)
        if policy.all_users_mfa_required:
            flags["all_users_required"] = True
            candidate = policy_enforced_at or _now()
            enforced_at = min(enforced_at, candidate) if enforced_at else candidate
        if (
            policy.tenant_admin_mfa_required
            and context.membership.role in {MembershipRole.OWNER, MembershipRole.ADMIN}
        ):
            flags["tenant_admin_required"] = True
            candidate = policy_enforced_at or _now()
            enforced_at = min(enforced_at, candidate) if enforced_at else candidate
    return any(flags.values()), enforced_at, flags


def recent_step_up_expires_at(
    session: Session,
    *,
    context: SessionContext,
    purpose: str | None = None,
) -> datetime | None:
    filters = [
        UserMFAStepUp.user_id == context.user.id,
        UserMFAStepUp.membership_id == context.membership.id,
        UserMFAStepUp.expires_at > _now(),
    ]
    if purpose:
        filters.append(UserMFAStepUp.purpose == purpose)
    row = session.scalar(
        select(UserMFAStepUp)
        .where(*filters)
        .order_by(UserMFAStepUp.expires_at.desc())
        .limit(1)
    )
    return _as_aware(row.expires_at) if row else None


def mfa_security_status(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership | None = None,
) -> MFASecurityStatusResponse:
    setting = _setting(session, user_id=context.user.id)
    required, enforced_at, flags = _policy_requires_mfa(
        session,
        context,
        platform_admin=platform_admin,
    )
    return MFASecurityStatusResponse(
        mfa_status=setting.status if setting is not None else "not_enrolled",
        mfa_required=required,
        mfa_enforced_at=enforced_at,
        grace_period_ends_at=enforced_at if required else None,
        recent_step_up_expires_at=recent_step_up_expires_at(session, context=context),
        recovery_codes_remaining=len(_active_recovery_codes(session, user_id=context.user.id)),
        **flags,
    )


def login_mfa_challenge_state(
    session: Session,
    *,
    context: SessionContext,
) -> dict[str, object]:
    platform_admin = session.scalar(
        select(PlatformAdminMembership).where(
            PlatformAdminMembership.user_id == context.user.id,
            PlatformAdminMembership.status == "active",
        )
    )
    required, enforced_at, flags = _policy_requires_mfa(
        session,
        context,
        platform_admin=platform_admin,
    )
    enforced_at = _as_aware(enforced_at)
    if not required or enforced_at is None or enforced_at > _now():
        return {
            "mfa_required": required,
            "mfa_challenge_required": False,
            "mfa_enrollment_required": False,
            "mfa_challenge_reason": None,
            **flags,
        }
    setting = _setting(session, user_id=context.user.id)
    if setting is None or setting.status != "enrolled":
        return {
            "mfa_required": True,
            "mfa_challenge_required": True,
            "mfa_enrollment_required": True,
            "mfa_challenge_reason": "MFA enrollment is required before workspace access.",
            **flags,
        }
    if recent_step_up_expires_at(session, context=context):
        return {
            "mfa_required": True,
            "mfa_challenge_required": False,
            "mfa_enrollment_required": False,
            "mfa_challenge_reason": None,
            **flags,
        }
    return {
        "mfa_required": True,
        "mfa_challenge_required": True,
        "mfa_enrollment_required": False,
        "mfa_challenge_reason": "Complete MFA step-up before workspace access.",
        **flags,
    }


def enforce_login_mfa_if_required(
    session: Session,
    *,
    context: SessionContext,
    path: str,
) -> None:
    allowed_prefixes = (
        "/api/auth/security",
        "/api/auth/mfa/",
        "/api/auth/logout",
        "/api/auth/refresh",
    )
    if any(path.startswith(prefix) for prefix in allowed_prefixes):
        return
    state = login_mfa_challenge_state(session, context=context)
    if not state.get("mfa_challenge_required"):
        return
    if state.get("mfa_enrollment_required"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA is required before workspace access.",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Complete MFA step-up before workspace access.",
    )


def start_mfa_enrollment(
    session: Session,
    *,
    context: SessionContext,
) -> MFAEnrollmentStartResponse:
    setting = _setting(session, user_id=context.user.id, create=True)
    assert setting is not None
    secret = _random_base32_secret()
    setting.encrypted_totp_secret = _encrypt_secret(secret)
    setting.status = "pending"
    setting.secret_displayed_at = _now()
    setting.disabled_at = None
    session.add(setting)
    session.flush()
    issuer = "CaseOps"
    label = f"{issuer}:{context.user.email}"
    otpauth_url = (
        "otpauth://totp/"
        f"{quote(label)}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"
    )
    _audit_mfa(session, context, action="mfa.enrollment_started")
    session.commit()
    return MFAEnrollmentStartResponse(
        enrollment_id=setting.id,
        secret=secret,
        otpauth_url=otpauth_url,
        qr_svg=_svg_qr(otpauth_url),
        status="pending",
    )


def verify_mfa_enrollment(
    session: Session,
    *,
    context: SessionContext,
    code: str,
) -> MFAEnrollmentVerifyResponse:
    setting = _setting(session, user_id=context.user.id)
    secret = _decrypt_secret(setting.encrypted_totp_secret if setting else None)
    if setting is None or secret is None or not _verify_totp(secret, code):
        _audit_mfa(session, context, action="mfa.enrollment_failed", result=AuditResult.DENIED)
        session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code.")
    now = _now()
    setting.status = "enrolled"
    setting.enrolled_at = setting.enrolled_at or now
    setting.verified_at = now
    setting.last_challenge_at = now
    codes = _generate_recovery_codes(session, user_id=context.user.id, setting=setting)
    session.add(
        UserMFAStepUp(
            user_id=context.user.id,
            membership_id=context.membership.id,
            purpose="step_up",
            method="totp",
            completed_at=now,
            expires_at=now + timedelta(minutes=get_settings().mfa_step_up_ttl_minutes),
        )
    )
    _audit_mfa(session, context, action="mfa.enrolled")
    session.commit()
    return MFAEnrollmentVerifyResponse(status="enrolled", recovery_codes=codes)


def _consume_recovery_code(session: Session, *, user_id: str, code: str) -> bool:
    digest = _hash_code(code)
    row = session.scalar(
        select(UserMFARecoveryCode).where(
            UserMFARecoveryCode.user_id == user_id,
            UserMFARecoveryCode.code_hash == digest,
            UserMFARecoveryCode.status == "active",
        )
    )
    if row is None:
        return False
    row.status = "used"
    row.used_at = _now()
    session.add(row)
    return True


def complete_step_up(
    session: Session,
    *,
    context: SessionContext,
    code: str,
    purpose: str,
    method: str = "totp",
    platform_admin: PlatformAdminMembership | None = None,
) -> MFAStepUpResponse:
    if _recent_failure_count(session, context=context) >= get_settings().mfa_max_failures_per_5m:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many MFA attempts.",
        )
    setting = _setting(session, user_id=context.user.id)
    secret = _decrypt_secret(setting.encrypted_totp_secret if setting else None)
    if setting is None or setting.status != "enrolled" or secret is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA enrollment is required.",
        )
    used_recovery = False
    valid = False
    if method == "recovery_code":
        valid = _consume_recovery_code(session, user_id=context.user.id, code=code)
        used_recovery = valid
    else:
        valid = _verify_totp(secret, code)
    if not valid:
        _audit_mfa(
            session,
            context,
            action="mfa.challenge_failed",
            result=AuditResult.DENIED,
            platform_admin=platform_admin,
            metadata={"purpose": purpose, "method": method},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid MFA code.")
    now = _now()
    expires_at = now + timedelta(minutes=get_settings().mfa_step_up_ttl_minutes)
    setting.last_challenge_at = now
    session.add(setting)
    session.add(
        UserMFAStepUp(
            user_id=context.user.id,
            membership_id=context.membership.id,
            purpose=purpose if purpose in STEP_UP_PURPOSES else "step_up",
            method="recovery_code" if used_recovery else "totp",
            completed_at=now,
            expires_at=expires_at,
        )
    )
    _audit_mfa(
        session,
        context,
        action="mfa.challenge_succeeded",
        platform_admin=platform_admin,
        metadata={"purpose": purpose, "method": "recovery_code" if used_recovery else "totp"},
    )
    if used_recovery:
        _audit_mfa(
            session,
            context,
            action="mfa.recovery_code_used",
            platform_admin=platform_admin,
            metadata={"purpose": purpose},
        )
    session.commit()
    return MFAStepUpResponse(status="verified", expires_at=expires_at)


def require_recent_step_up(
    session: Session,
    *,
    context: SessionContext,
    purpose: str,
    platform_admin: PlatformAdminMembership | None = None,
    require_if_mfa_enrolled: bool = True,
) -> None:
    setting = _setting(session, user_id=context.user.id)
    should_require = (
        require_if_mfa_enrolled and setting is not None and setting.status == "enrolled"
    )
    policy_required, enforced_at, _ = _policy_requires_mfa(
        session,
        context,
        platform_admin=platform_admin,
    )
    enforced_at = _as_aware(enforced_at)
    if policy_required and enforced_at is not None and enforced_at <= _now():
        should_require = True
    if not should_require:
        return
    if recent_step_up_expires_at(session, context=context, purpose=purpose):
        return
    if purpose != "step_up" and recent_step_up_expires_at(session, context=context):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Complete MFA step-up to continue. Purpose: {purpose}.",
    )


def enforce_platform_mfa(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
) -> None:
    if not platform_admin.mfa_required:
        return
    enforced_at = _as_aware(platform_admin.mfa_enforced_at)
    if enforced_at is None or enforced_at > _now():
        return
    setting = _setting(session, user_id=context.user.id)
    if setting is None or setting.status != "enrolled":
        record_platform_audit(
            session,
            context=context,
            platform_admin=platform_admin,
            action="mfa.platform_access_denied",
            target_type="platform_admin",
            target_id=platform_admin.id,
            result="denied",
            reason="mfa_required",
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "mfa_enrollment_required",
                "detail": "MFA is required for platform administration.",
            },
        )
    require_recent_step_up(
        session,
        context=context,
        purpose="platform_admin_access",
        platform_admin=platform_admin,
        require_if_mfa_enrolled=True,
    )


def regenerate_recovery_codes(
    session: Session,
    *,
    context: SessionContext,
) -> MFARecoveryCodesResponse:
    require_recent_step_up(session, context=context, purpose="step_up")
    setting = _setting(session, user_id=context.user.id)
    if setting is None or setting.status != "enrolled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA enrollment is required.",
        )
    codes = _generate_recovery_codes(session, user_id=context.user.id, setting=setting)
    generated_at = setting.recovery_codes_generated_at or _now()
    _audit_mfa(session, context, action="mfa.recovery_codes_regenerated")
    session.commit()
    return MFARecoveryCodesResponse(recovery_codes=codes, generated_at=generated_at)


def disable_mfa(
    session: Session,
    *,
    context: SessionContext,
    reason: str,
    code: str | None = None,
    admin_reset: bool = False,
) -> None:
    if not admin_reset:
        if code is None:
            require_recent_step_up(session, context=context, purpose="step_up")
        else:
            complete_step_up(session, context=context, code=code, purpose="step_up")
    setting = _setting(session, user_id=context.user.id)
    if setting is None:
        return
    setting.status = "disabled"
    setting.disabled_at = _now()
    setting.encrypted_totp_secret = None
    for row in _active_recovery_codes(session, user_id=context.user.id):
        row.status = "disabled"
    _audit_mfa(
        session,
        context,
        action="mfa.admin_reset" if admin_reset else "mfa.disabled",
        metadata={"reason": reason},
    )
    session.commit()


def tenant_security_policy_record(row: TenantSecurityPolicy) -> TenantSecurityPolicyRecord:
    return TenantSecurityPolicyRecord(
        tenant_admin_mfa_required=row.tenant_admin_mfa_required,
        all_users_mfa_required=row.all_users_mfa_required,
        mfa_grace_period_days=row.mfa_grace_period_days,
        mfa_enforced_at=row.mfa_enforced_at,
        updated_at=row.updated_at,
    )


def update_tenant_security_policy(
    session: Session,
    *,
    context: SessionContext,
    payload: TenantSecurityPolicyUpdateRequest,
) -> TenantSecurityPolicyRecord:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tenant admins can update MFA policy.",
        )
    require_recent_step_up(session, context=context, purpose="role_capability_change")
    row = tenant_security_policy(session, company_id=context.company.id, create=True)
    assert row is not None
    updates = payload.model_dump(exclude_unset=True)
    if "tenant_admin_mfa_required" in updates:
        row.tenant_admin_mfa_required = bool(updates["tenant_admin_mfa_required"])
    if "all_users_mfa_required" in updates:
        row.all_users_mfa_required = bool(updates["all_users_mfa_required"])
    if "mfa_grace_period_days" in updates and updates["mfa_grace_period_days"] is not None:
        row.mfa_grace_period_days = int(updates["mfa_grace_period_days"])
    if row.tenant_admin_mfa_required or row.all_users_mfa_required:
        row.mfa_enforced_at = _now() + timedelta(days=row.mfa_grace_period_days)
    else:
        row.mfa_enforced_at = None
    row.updated_by_membership_id = context.membership.id
    session.add(row)
    record_from_context(
        session,
        context,
        action="mfa.policy_updated",
        target_type="tenant_security_policy",
        target_id=row.id,
        metadata={"reason": payload.reason},
    )
    session.commit()
    return tenant_security_policy_record(row)
