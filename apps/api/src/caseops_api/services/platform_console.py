"""Reports-only authentication and delegation. No tenant authority is minted here."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit

import httpx
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.core.console_auth import create_console_token, decode_console_token
from caseops_api.core.password_policy import WeakPasswordError, enforce_password_policy
from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.core.security import TokenValidationError, hash_password, verify_password
from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.db.models import (
    PlatformAdminMembership,
    PlatformConsoleDelivery,
    PlatformConsoleSession,
    PlatformConsoleToken,
    PlatformReportAdmin,
    PlatformReportAuditEvent,
    User,
)
from caseops_api.db.session import get_session_factory, serialize_sqlite_writer
from caseops_api.schemas.platform_console import (
    ConsoleAdminRecord,
    ConsoleAdminSelf,
    ConsoleAuthState,
    ConsoleInvitationResponse,
    ConsoleMFAEnrollmentResponse,
)
from caseops_api.services.platform_admin import _configured_founder_user_id
from caseops_api.services.security import (
    _decrypt_secret,
    _encrypt_secret,
    _hash_code,
    _hotp,
    _random_base32_secret,
)
from caseops_api.services.sendgrid_transport import _send_via_sendgrid

CHALLENGE_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(hours=1)
STEP_UP_TTL = timedelta(minutes=10)
LINK_TTL = timedelta(minutes=30)
DELIVERY_LEASE = timedelta(minutes=2)
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))
AUDITED_CONTEXT_DENIAL_CODES = frozenset(
    {
        "console_csrf_invalid",
        "console_mfa_required",
        "console_manager_required",
        "console_step_up_required",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fail(code: str = "console_session_invalid", *, status: int = 401) -> None:
    raise ProblemHTTPException(
        status,
        problem_type=code,
        extras={"code": code},
        detail={
            "console_manager_required": "A report manager is required.",
            "console_mfa_required": "Complete console MFA before continuing.",
            "console_step_up_required": "Verify MFA again before changing report administrators.",
            "console_link_invalid": "This link is invalid, expired or already used.",
            "console_mfa_invalid": "The MFA code is invalid or was already used.",
            "console_mfa_locked": "Too many MFA attempts. Try again later.",
            "console_conflict": "This administrator change conflicts with current state.",
        }.get(code, "The console session or credential is no longer valid."),
    )


def _audit(
    session: Session,
    admin: PlatformReportAdmin | None,
    action: str,
    *,
    target_id: str | None = None,
    result: str = "success",
    reason: str | None = None,
) -> None:
    session.add(
        PlatformReportAuditEvent(
            report_admin_id=admin.id if admin else None,
            actor_user_id=admin.user_id if admin else None,
            action=action,
            target_id=target_id,
            result=result,
            reason=reason,
        )
    )


def _root_valid(session: Session, root_id: str, *, fence: bool = False) -> bool:
    query = select(
        PlatformAdminMembership.user_id,
        PlatformAdminMembership.status,
        PlatformAdminMembership.role,
    ).where(PlatformAdminMembership.id == root_id)
    if fence:
        query = query.with_for_update(read=True, of=PlatformAdminMembership)
    root = session.execute(query).first()
    return bool(
        root
        and root.status == "active"
        and root.role == "super_admin"
        and _configured_founder_user_id(session, user_id=root.user_id) == root.user_id
    )


def _locked_admin(session: Session, admin_id: str) -> tuple[PlatformReportAdmin, User]:
    serialize_sqlite_writer(session)
    # Root grant SHARE -> manager -> manager User -> viewer -> viewer User.
    # Root seeding/revocation updates only the actual legacy grant; SHARE
    # serializes with that writer without dirtying/reseeding shared policy.
    identity = session.execute(
        select(
            PlatformReportAdmin.role,
            PlatformReportAdmin.created_by_report_admin_id,
            PlatformReportAdmin.root_platform_admin_id,
        ).where(PlatformReportAdmin.id == admin_id)
    ).first()
    if identity is None:
        _fail()
    if not _root_valid(session, identity.root_platform_admin_id, fence=True):
        _fail()
    manager_id = admin_id if identity.role == "manager" else identity.created_by_report_admin_id
    manager = session.scalar(
        select(PlatformReportAdmin)
        .where(
            PlatformReportAdmin.id == manager_id,
        )
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if manager is None or manager.role != "manager" or manager.status == "revoked":
        _fail()
    if not _root_valid(session, manager.root_platform_admin_id):
        _fail()
    manager_user = session.scalar(
        select(User)
        .where(User.id == manager.user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if manager_user is None or not manager_user.is_active:
        _fail()
    admin = (
        manager
        if admin_id == manager.id
        else session.scalar(
            select(PlatformReportAdmin)
            .where(PlatformReportAdmin.id == admin_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    )
    if (
        admin is None
        or admin.status == "revoked"
        or admin.root_platform_admin_id != manager.root_platform_admin_id
        or (
            admin.id != manager.id
            and (manager.status != "active" or manager.mfa_status != "enrolled")
        )
    ):
        _fail()
    user = session.scalar(
        select(User)
        .where(User.id == admin.user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active:
        _fail()
    if not _root_valid(session, manager.root_platform_admin_id):
        _fail()
    return admin, user


@dataclass(frozen=True)
class ConsoleAuthContext:
    admin: PlatformReportAdmin
    user: User
    console_session: PlatformConsoleSession


@dataclass(frozen=True)
class ConsoleIssuedSession:
    state: ConsoleAuthState
    token: str = field(repr=False)
    csrf: str = field(repr=False)
    ttl_seconds: int


def admin_record(admin: PlatformReportAdmin, user: User) -> ConsoleAdminRecord:
    return ConsoleAdminRecord(
        id=admin.id,
        email=user.email,
        full_name=user.full_name,
        role=admin.role,
        status=admin.status,
        created_at=_aware(admin.created_at),
    )


def auth_state(context: ConsoleAuthContext) -> ConsoleAuthState:
    full = context.console_session.purpose == "authenticated"
    return ConsoleAuthState(
        state=context.console_session.purpose,
        admin=ConsoleAdminSelf(
            id=context.admin.id,
            email=context.user.email,
            full_name=context.user.full_name,
            role=context.admin.role,
        )
        if full
        else None,
        expires_at=_aware(context.console_session.expires_at),
    )


def _issue(
    session: Session,
    admin: PlatformReportAdmin,
    user: User,
    *,
    purpose: str | None = None,
) -> ConsoleIssuedSession:
    purpose = purpose or (
        "mfa_challenge_required" if admin.mfa_status == "enrolled" else "mfa_enrollment_required"
    )
    now = _now()
    ttl = SESSION_TTL if purpose == "authenticated" else CHALLENGE_TTL
    secret, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    row = PlatformConsoleSession(
        report_admin_id=admin.id,
        secret_hash=_digest(secret),
        csrf_hash=_digest(csrf),
        credential_hash=_digest(user.password_hash),
        factor_hash=_digest(admin.encrypted_totp_secret or ""),
        auth_epoch=admin.auth_epoch,
        purpose=purpose,
        issued_at=now,
        expires_at=now + ttl,
    )
    session.add(row)
    session.flush()
    state = auth_state(ConsoleAuthContext(admin, user, row))
    token = create_console_token(
        user_id=user.id,
        admin_id=admin.id,
        secret=secret,
        purpose=purpose,
        issued_at=now,
        expires_at=row.expires_at,
    )
    return ConsoleIssuedSession(state, token, csrf, int(ttl.total_seconds()))


def resolve_console_context(
    session: Session,
    *,
    token: str,
    csrf: str | None = None,
    authenticated: bool = True,
    manager: bool = False,
    step_up: bool = False,
) -> ConsoleAuthContext:
    try:
        claims = decode_console_token(token)
    except TokenValidationError:
        _fail()
    admin, user = _locked_admin(session, claims["admin_id"])
    row = session.scalar(
        select(PlatformConsoleSession)
        .where(
            PlatformConsoleSession.secret_hash == _digest(claims["jti"]),
            PlatformConsoleSession.report_admin_id == admin.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = _now()
    if (
        row is None
        or row.revoked_at is not None
        or _aware(row.expires_at) <= now
        or row.auth_epoch != admin.auth_epoch
        or claims["sub"] != user.id
        or row.purpose != claims["purpose"]
        or not hmac.compare_digest(row.credential_hash, _digest(user.password_hash))
        or not hmac.compare_digest(row.factor_hash, _digest(admin.encrypted_totp_secret or ""))
        or (
            user.sessions_valid_after is not None
            and _aware(row.issued_at) < _aware(user.sessions_valid_after)
        )
    ):
        _fail()

    def deny(code: str) -> None:
        # Attribute only after the signed realm, live grant, session and
        # credential fences above establish the actual principal.
        _audit(
            session,
            admin,
            "console.access_denied",
            target_id="admin_change" if manager or step_up else "console_access",
            result="denied",
            reason=code,
        )
        session.commit()
        _fail(code, status=403)

    if csrf is not None and not hmac.compare_digest(row.csrf_hash, _digest(csrf)):
        deny("console_csrf_invalid")
    if authenticated and (
        row.purpose != "authenticated" or admin.status != "active" or admin.mfa_status != "enrolled"
    ):
        deny("console_mfa_required")
    if manager and admin.role != "manager":
        deny("console_manager_required")
    if step_up and (row.purpose != "authenticated" or _aware(row.issued_at) + STEP_UP_TTL <= now):
        deny("console_step_up_required")
    return ConsoleAuthContext(admin, user, row)


def login(session: Session, *, email: str, password: str) -> ConsoleIssuedSession:
    admin_id = session.scalar(
        select(PlatformReportAdmin.id)
        .join(
            User,
            User.id == PlatformReportAdmin.user_id,
        )
        .where(User.email == email.strip().lower())
    )
    try:
        if admin_id is None:
            _fail()
        admin, user = _locked_admin(session, admin_id)
    except ProblemHTTPException:
        # Exactly one scrypt verification even when grant/provenance resolution
        # fails before a live credential is available. Never hash per request.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        session.rollback()
        _audit(session, None, "console.login", result="denied")
        session.commit()
        _fail()
    credential_valid = verify_password(password, user.password_hash)
    locked = admin.login_locked_until and _aware(admin.login_locked_until) > _now()
    if not credential_valid or admin.status != "active" or locked:
        if not locked:
            admin.login_failures += 1
            if admin.login_failures >= 5:
                admin.login_locked_until = _now() + timedelta(minutes=5)
                admin.login_failures = 0
        _audit(session, admin, "console.login", result="denied")
        session.commit()
        _fail()
    admin.login_failures = 0
    admin.login_locked_until = None
    if admin.mfa_status == "pending":
        admin.mfa_status = "not_enrolled"
        admin.encrypted_totp_secret = None
    issued = _issue(session, admin, user)
    _audit(session, admin, "console.login")
    session.commit()
    return issued


def start_mfa_enrollment(
    session: Session, context: ConsoleAuthContext
) -> ConsoleMFAEnrollmentResponse:
    admin, row = context.admin, context.console_session
    if row.purpose != "mfa_enrollment_required" or admin.mfa_status != "not_enrolled":
        _fail("console_conflict", status=409)
    secret = _random_base32_secret()
    admin.encrypted_totp_secret = _encrypt_secret(secret)
    admin.mfa_status = "pending"
    row.factor_hash = _digest(admin.encrypted_totp_secret)
    url = (
        f"otpauth://totp/{quote('CaseOps Reports:' + context.user.email, safe='')}"
        f"?secret={secret}&issuer=CaseOps%20Reports&algorithm=SHA1&digits=6&period=30"
    )
    _audit(session, admin, "console.mfa_enrollment_started")
    session.commit()
    return ConsoleMFAEnrollmentResponse(secret=secret, otpauth_url=url)


def verify_mfa(
    session: Session,
    context: ConsoleAuthContext,
    *,
    code: str | None,
    recovery_code: str | None = None,
) -> ConsoleIssuedSession:
    admin = context.admin
    now = _now()
    if admin.mfa_locked_until and _aware(admin.mfa_locked_until) > now:
        _fail("console_mfa_locked", status=429)
    secret = _decrypt_secret(admin.encrypted_totp_secret)
    if not secret or admin.mfa_status not in {"pending", "enrolled"}:
        _fail("console_mfa_required", status=403)
    matched_counter = None
    recovery_hashes = list(admin.recovery_code_hashes or [])
    valid = False
    if code is not None:
        counter = int(now.timestamp()) // 30
        matched_counter = next(
            (
                n
                for n in (counter - 1, counter, counter + 1)
                if n >= 0 and hmac.compare_digest(_hotp(secret, n), code)
            ),
            None,
        )
        valid = matched_counter is not None and (
            admin.last_totp_counter is None or matched_counter > admin.last_totp_counter
        )
    elif recovery_code and admin.mfa_status == "enrolled":
        hashed = _hash_code(recovery_code)
        valid = any(hmac.compare_digest(item, hashed) for item in recovery_hashes)
        if valid:
            admin.recovery_code_hashes = [item for item in recovery_hashes if item != hashed]
    if not valid:
        admin.mfa_failures += 1
        if admin.mfa_failures >= 5:
            admin.mfa_locked_until = now + timedelta(minutes=5)
            admin.mfa_failures = 0
        _audit(session, admin, "console.mfa_failed", result="denied")
        session.commit()
        _fail("console_mfa_invalid")
    recovery_codes = None
    if admin.mfa_status == "pending":
        recovery_codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(10)]
        admin.recovery_code_hashes = [_hash_code(item) for item in recovery_codes]
    admin.mfa_status = "enrolled"
    if matched_counter is not None:
        admin.last_totp_counter = matched_counter
    admin.mfa_failures = 0
    admin.mfa_locked_until = None
    context.console_session.revoked_at = now
    issued = _issue(session, admin, context.user, purpose="authenticated")
    issued.state.recovery_codes = recovery_codes
    _audit(session, admin, "console.mfa_verified")
    session.commit()
    return issued


def logout(session: Session, context: ConsoleAuthContext) -> None:
    context.console_session.revoked_at = _now()
    _audit(session, context.admin, "console.logout")
    session.commit()


def _password_policy(password: str) -> None:
    try:
        enforce_password_policy(password)
    except WeakPasswordError as exc:
        raise ProblemHTTPException(
            400, problem_type="password_policy_violation", detail=str(exc)
        ) from exc


def _new_token(
    session: Session,
    admin: PlatformReportAdmin,
    user: User,
    *,
    purpose: str,
) -> tuple[PlatformConsoleToken, str, str, PlatformConsoleDelivery]:
    # Explicit reissue invalidates previous links, including uncertain sends.
    session.execute(
        update(PlatformConsoleToken)
        .where(
            PlatformConsoleToken.report_admin_id == admin.id,
            PlatformConsoleToken.purpose == purpose,
            PlatformConsoleToken.consumed_at.is_(None),
            PlatformConsoleToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    raw, claim = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    token = PlatformConsoleToken(
        report_admin_id=admin.id,
        token_hash=_digest(raw),
        purpose=purpose,
        credential_hash=_digest(user.password_hash),
        auth_epoch=admin.auth_epoch,
        expires_at=_now() + LINK_TTL,
    )
    session.add(token)
    session.flush()
    delivery = PlatformConsoleDelivery(
        token_id=token.id,
        status="pending",
        claim_hash=_digest(claim),
        claim_expires_at=_now() + DELIVERY_LEASE,
    )
    session.add(delivery)
    session.flush()
    return token, raw, claim, delivery


def _block_claim(session: Session, *, delivery_id: str, claim: str) -> str:
    session.execute(
        update(PlatformConsoleDelivery)
        .where(
            PlatformConsoleDelivery.id == delivery_id,
            PlatformConsoleDelivery.claim_hash == _digest(claim),
            PlatformConsoleDelivery.status == "pending",
            PlatformConsoleDelivery.started_at.is_(None),
        )
        .values(status="failed", error_code="authorization_no_longer_valid", completed_at=_now())
    )
    session.commit()
    return "failed"


def _auth_mail_ready(settings, *, automated: bool) -> bool:
    if (
        automated
        or not is_non_local_env(settings.env)
        or not (settings.sendgrid_api_key or "").strip()
        or not settings.sendgrid_sender_email
    ):
        return False
    try:
        validate_email(
            settings.sendgrid_sender_email, check_deliverability=False, allow_display_name=False
        )
    except EmailNotValidError:
        return False
    destination = urlsplit(str(settings.public_app_url))
    return bool(
        destination.scheme == "https"
        and destination.hostname
        and not destination.username
        and not destination.password
        and not destination.query
        and not destination.fragment
    )


def _test_mail_ready(settings, adapter: str) -> bool:
    try:
        destination = urlsplit(adapter)
        if (
            destination.scheme != "http"
            or destination.hostname not in {"127.0.0.1", "::1"}
            or not destination.port
            or destination.username
            or destination.password
            or destination.query
            or destination.fragment
            or any(
                os.environ.get(key)
                for key in (
                    "K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB",
                    "GOOGLE_CLOUD_PROJECT",
                )
            )
        ):
            return False
        if settings.env == "local":
            return True
        if (
            settings.env != "e2e"
            or os.environ.get("CASEOPS_E2E_OAUTH_EMULATOR") != "calendar-20261008"
            or not paid_providers_blocked_for_request()
            or (settings.sendgrid_api_key or "").strip()
        ):
            return False
        origin = urlsplit(str(settings.public_app_url))
        if (
            origin.scheme != "http"
            or origin.hostname not in {"localhost", "127.0.0.1", "::1"}
            or not origin.port
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
        ):
            return False
        database = urlsplit(settings.database_url)
        return bool(
            (database.scheme == "sqlite+pysqlite" and database.path)
            or (
                database.scheme == "postgresql+psycopg"
                and database.hostname in {"localhost", "127.0.0.1", "postgres"}
                and database.path == "/caseops"
            )
        )
    except ValueError:
        return False


def _send_claim(
    session: Session,
    *,
    delivery_id: str,
    claim: str,
    email: str,
    full_name: str,
    raw_token: str,
    purpose: str,
    automated: bool = False,
) -> str:
    # Caller committed the hash-only claim. Capture every transport input before
    # that commit so ORM expiration cannot accidentally reopen a transaction.
    if session.in_transaction():
        raise RuntimeError("Console transport requires a closed transaction.")
    identity = session.execute(
        select(PlatformConsoleDelivery.token_id).where(
            PlatformConsoleDelivery.id == delivery_id,
            PlatformConsoleDelivery.claim_hash == _digest(claim),
            PlatformConsoleDelivery.status == "pending",
            PlatformConsoleDelivery.started_at.is_(None),
        )
    ).first()
    if identity is None:
        session.rollback()
        return "outcome_unknown"
    token = session.get(PlatformConsoleToken, identity.token_id)
    try:
        admin, user = _locked_admin(session, token.report_admin_id)
    except ProblemHTTPException:
        session.rollback()
        return _block_claim(session, delivery_id=delivery_id, claim=claim)
    if (
        token.purpose != purpose
        or token.token_hash != _digest(raw_token)
        or token.auth_epoch != admin.auth_epoch
        or token.consumed_at
        or token.revoked_at
        or _aware(token.expires_at) <= _now()
        or user.email != email
        or token.credential_hash != _digest(user.password_hash)
    ):
        session.rollback()
        return _block_claim(session, delivery_id=delivery_id, claim=claim)
    started = session.execute(
        update(PlatformConsoleDelivery)
        .where(
            PlatformConsoleDelivery.id == delivery_id,
            PlatformConsoleDelivery.status == "pending",
            PlatformConsoleDelivery.started_at.is_(None),
            PlatformConsoleDelivery.claim_expires_at > _now(),
            PlatformConsoleDelivery.claim_hash == _digest(claim),
        )
        .values(started_at=_now())
    )
    if started.rowcount != 1:
        session.rollback()
        return "outcome_unknown"
    session.commit()
    page = "setup" if purpose == "invite" else "reset-password"
    app_url = str(get_settings().public_app_url).rstrip("/")
    url = f"{app_url}/platform/{page}#token={quote(raw_token, safe='')}"
    settings = get_settings()
    adapter = os.environ.get("CASEOPS_CONSOLE_TEST_MAIL_URL", "").strip()
    subject = (
        "CaseOps reports console setup" if purpose == "invite" else "CaseOps reports password reset"
    )
    body = (
        f"Use this one-time link within 30 minutes:\n{url}\n"
        "Ignore it if you did not expect this request."
    )
    try:
        if adapter:
            if not _test_mail_ready(settings, adapter):
                status, message_id, error = "failed", None, "test_transport_not_admitted"
            else:
                response = httpx.post(
                    adapter,
                    json={"to": email, "subject": subject, "body": body},
                    timeout=5,
                    follow_redirects=False,
                    trust_env=False,
                )
                status = "accepted" if response.status_code == 202 else "failed"
                message_id, error = (
                    None,
                    None if status == "accepted" else "test_transport_rejected",
                )
        elif not _auth_mail_ready(
            settings, automated=automated or paid_providers_blocked_for_request()
        ):
            status, message_id, error = "failed", None, "transport_not_admitted"
        else:
            # Auth mail deliberately does not consult tenant notification
            # suppressions (see services.email_suppression's explicit contract).
            accepted, message_id, _ = _send_via_sendgrid(
                to_email=email,
                recipient_name=full_name,
                subject=subject,
                body_text=body,
            )
            status = "accepted" if accepted else "failed"
            error = None if accepted else "provider_rejected"
    except (httpx.HTTPError, TimeoutError, OSError):
        # A network exception cannot prove the provider did not accept the POST.
        status, message_id, error = "outcome_unknown", None, "transport_outcome_unknown"
    row = session.scalar(
        select(PlatformConsoleDelivery)
        .where(
            PlatformConsoleDelivery.id == delivery_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.status != "pending"
        or not hmac.compare_digest(row.claim_hash, _digest(claim))
    ):
        session.rollback()
        return "outcome_unknown"
    if _aware(row.claim_expires_at) <= _now():
        status, error = "outcome_unknown", "claim_expired"
    row.status, row.error_code = status, error
    row.provider_message_id = (
        message_id[:255] if message_id and raw_token not in message_id else None
    )
    row.completed_at = _now()
    token = session.get(PlatformConsoleToken, row.token_id)
    admin = session.get(PlatformReportAdmin, token.report_admin_id) if token else None
    _audit(session, admin, "console.delivery_finished", target_id=row.id, result=status)
    session.commit()
    return status


def recover_expired_delivery_claims(session: Session) -> int:
    """Bounded housekeeping only; never replay a claimed mail send."""
    ids = list(
        session.scalars(
            select(PlatformConsoleDelivery.id)
            .where(
                PlatformConsoleDelivery.status == "pending",
                PlatformConsoleDelivery.claim_expires_at <= _now(),
            )
            .order_by(PlatformConsoleDelivery.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
    )
    if ids:
        session.execute(
            update(PlatformConsoleDelivery)
            .where(
                PlatformConsoleDelivery.id.in_(ids),
                PlatformConsoleDelivery.status == "pending",
            )
            .values(status="outcome_unknown", error_code="claim_expired", completed_at=_now())
        )
    session.commit()
    return len(ids)


def invite(
    session: Session,
    context: ConsoleAuthContext,
    *,
    email: str,
    full_name: str,
    automated: bool = False,
) -> ConsoleInvitationResponse:
    if context.admin.role != "manager":
        _fail("console_manager_required", status=403)
    normalized = email.strip().lower()
    user = session.scalar(select(User).where(User.email == normalized).with_for_update())
    new_user = user is None
    if user is None:
        user = User(
            email=normalized,
            full_name=full_name.strip(),
            password_hash=hash_password(secrets.token_urlsafe(48)),
        )
        session.add(user)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            _fail("console_conflict", status=409)
    if not user.is_active:
        _fail("console_conflict", status=409)
    existing = session.scalar(
        select(PlatformReportAdmin).where(PlatformReportAdmin.user_id == user.id)
    )
    if existing is not None:
        if (
            existing.role != "viewer"
            or existing.status != "pending"
            or existing.created_by_report_admin_id != context.admin.id
            or existing.root_platform_admin_id != context.admin.root_platform_admin_id
        ):
            _fail("console_conflict", status=409)
        # Replay observes the durable claim only. Recovery belongs exclusively
        # to the explicit, cooldown-fenced pending invitation resend endpoint.
        status = session.scalar(
            select(PlatformConsoleDelivery.status)
            .join(PlatformConsoleToken, PlatformConsoleToken.id == PlatformConsoleDelivery.token_id)
            .where(
                PlatformConsoleToken.report_admin_id == existing.id,
                PlatformConsoleToken.purpose == "invite",
            )
            .order_by(PlatformConsoleToken.created_at.desc(), PlatformConsoleToken.id.desc())
            .limit(1)
        ) or "outcome_unknown"
        record = admin_record(existing, user)
        _audit(session, context.admin, "console.invitation_replayed", target_id=existing.id,
               result=status)
        session.commit()
        return ConsoleInvitationResponse(admin=record, delivery_status=status)
    else:
        admin = PlatformReportAdmin(
            user_id=user.id,
            role="viewer",
            status="pending",
            initializes_password=new_user,
            root_platform_admin_id=context.admin.root_platform_admin_id,
            created_by_report_admin_id=context.admin.id,
        )
        session.add(admin)
    session.flush()
    _, raw, claim, delivery = _new_token(session, admin, user, purpose="invite")
    record = admin_record(admin, user)
    delivery_id, send_email, send_name = delivery.id, user.email, user.full_name
    _audit(session, context.admin, "console.invited", target_id=admin.id)
    session.commit()
    status = _send_claim(
        session,
        delivery_id=delivery_id,
        claim=claim,
        email=send_email,
        full_name=send_name,
        raw_token=raw,
        purpose="invite",
        automated=automated,
    )
    return ConsoleInvitationResponse(admin=record, delivery_status=status)


def bootstrap_report_manager(
    session: Session,
    *,
    root_platform_admin_id: str,
    email: str,
    full_name: str,
) -> ConsoleInvitationResponse | ConsoleAdminRecord:
    """Explicit operational admission, never called by startup or tenant login.

    The caller must separately admit this post-release operation. There is no
    HTTP endpoint, environment auto-seed, founder promotion or tenant creation.
    Replay returns the existing grant and never automatically re-sends mail.
    """
    if not _root_valid(session, root_platform_admin_id, fence=True):
        _fail(status=403)
    user = session.scalar(select(User).where(User.email == email.strip().lower()).with_for_update())
    new_user = user is None
    if user is None:
        user = User(
            email=email.strip().lower(),
            full_name=full_name.strip(),
            password_hash=hash_password(secrets.token_urlsafe(48)),
        )
        session.add(user)
        session.flush()
    if not user.is_active:
        _fail("console_conflict", status=409)
    existing = session.scalar(
        select(PlatformReportAdmin).where(PlatformReportAdmin.user_id == user.id)
    )
    if existing is not None:
        if existing.role != "manager" or existing.root_platform_admin_id != root_platform_admin_id:
            _fail("console_conflict", status=409)
        return admin_record(existing, user)
    admin = PlatformReportAdmin(
        user_id=user.id,
        root_platform_admin_id=root_platform_admin_id,
        role="manager",
        status="pending",
        initializes_password=new_user,
    )
    session.add(admin)
    session.flush()
    _, raw, claim, delivery = _new_token(session, admin, user, purpose="invite")
    record, delivery_id, send_email, send_name = (
        admin_record(admin, user),
        delivery.id,
        user.email,
        user.full_name,
    )
    _audit(session, admin, "console.manager_bootstrapped")
    session.commit()
    status = _send_claim(
        session,
        delivery_id=delivery_id,
        claim=claim,
        email=send_email,
        full_name=send_name,
        raw_token=raw,
        purpose="invite",
    )
    return ConsoleInvitationResponse(admin=record, delivery_status=status)


def _consume_link(
    session: Session,
    *,
    raw: str,
    purpose: str,
) -> tuple[PlatformConsoleToken, PlatformReportAdmin, User]:
    identity = session.execute(
        select(PlatformConsoleToken.id, PlatformConsoleToken.report_admin_id).where(
            PlatformConsoleToken.token_hash == _digest(raw),
            PlatformConsoleToken.purpose == purpose,
        )
    ).first()
    if identity is None:
        _fail("console_link_invalid")
    admin, user = _locked_admin(session, identity.report_admin_id)
    token = session.scalar(
        select(PlatformConsoleToken)
        .where(PlatformConsoleToken.id == identity.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        token is None
        or token.consumed_at
        or token.revoked_at
        or _aware(token.expires_at) <= _now()
        or token.auth_epoch != admin.auth_epoch
        or not hmac.compare_digest(token.credential_hash, _digest(user.password_hash))
    ):
        _fail("console_link_invalid")
    token.consumed_at = _now()
    return token, admin, user


def complete_invitation(
    session: Session,
    *,
    token: str,
    password: str,
    full_name: str,
) -> ConsoleIssuedSession:
    _, admin, user = _consume_link(session, raw=token, purpose="invite")
    if admin.status != "pending":
        _fail("console_link_invalid")
    if admin.initializes_password:
        _password_policy(password)
        user.password_hash = hash_password(password)
        user.sessions_valid_after = _now()
        user.full_name = full_name.strip()
        admin.initializes_password = False
    elif not verify_password(password, user.password_hash):
        session.rollback()
        _fail("console_link_invalid")
    # Status alone never grants reports: every read also requires an enrolled
    # factor and an authenticated, credential/factor-bound session.
    admin.status = "active"
    issued = _issue(session, admin, user)
    _audit(session, admin, "console.invitation_completed")
    session.commit()
    return issued


@dataclass(frozen=True)
class ConsoleMailClaim:
    delivery_id: str
    claim: str = field(repr=False)
    email: str
    full_name: str
    raw_token: str = field(repr=False)
    purpose: str
    automated: bool


def send_password_reset_claim(claim: ConsoleMailClaim) -> None:
    with get_session_factory()() as session:
        _send_claim(session, **claim.__dict__)


def start_invitation_resend(
    session: Session,
    *,
    email: str,
    automated: bool = False,
) -> ConsoleMailClaim | None:
    admin_id = session.scalar(
        select(PlatformReportAdmin.id)
        .join(User, User.id == PlatformReportAdmin.user_id)
        .where(User.email == email.strip().lower(), PlatformReportAdmin.status == "pending")
    )
    if admin_id is None:
        session.rollback()
        return None
    try:
        admin, user = _locked_admin(session, admin_id)
    except ProblemHTTPException:
        session.rollback()
        return None
    recent = session.scalar(
        select(PlatformConsoleToken.id)
        .where(
            PlatformConsoleToken.report_admin_id == admin.id,
            PlatformConsoleToken.purpose == "invite",
            PlatformConsoleToken.created_at > _now() - timedelta(minutes=5),
        )
        .limit(1)
    )
    if recent:
        session.rollback()
        return None
    _, raw, claim, delivery = _new_token(session, admin, user, purpose="invite")
    result = ConsoleMailClaim(
        delivery.id, claim, user.email, user.full_name, raw, "invite", automated
    )
    _audit(session, admin, "console.invitation_resend_requested")
    session.commit()
    return result


def start_password_reset(
    session: Session,
    *,
    email: str,
    automated: bool = False,
) -> ConsoleMailClaim | None:
    admin_id = session.scalar(
        select(PlatformReportAdmin.id)
        .join(User, User.id == PlatformReportAdmin.user_id)
        .where(User.email == email.strip().lower(), PlatformReportAdmin.status == "active")
    )
    if admin_id is None:
        session.rollback()
        return None
    try:
        admin, user = _locked_admin(session, admin_id)
    except ProblemHTTPException:
        session.rollback()
        return None
    # Durable per-principal cooldown bounds mail even across multiple workers.
    recent = session.scalar(
        select(PlatformConsoleToken.id)
        .where(
            PlatformConsoleToken.report_admin_id == admin.id,
            PlatformConsoleToken.purpose == "password_reset",
            PlatformConsoleToken.created_at > _now() - timedelta(minutes=5),
        )
        .limit(1)
    )
    if recent:
        session.rollback()
        return None
    _, raw, claim, delivery = _new_token(session, admin, user, purpose="password_reset")
    delivery_id, send_email, send_name = delivery.id, user.email, user.full_name
    _audit(session, admin, "console.password_reset_requested")
    session.commit()
    # The route schedules transport after the generic response, using a fresh
    # session. Only the hash-only durable claim survives a process interruption.
    return ConsoleMailClaim(
        delivery_id, claim, send_email, send_name, raw, "password_reset", automated
    )


def complete_password_reset(session: Session, *, token: str, password: str) -> None:
    _password_policy(password)
    _, admin, user = _consume_link(session, raw=token, purpose="password_reset")
    if admin.status != "active":
        _fail("console_link_invalid")
    user.password_hash = hash_password(password)
    user.sessions_valid_after = _now()
    admin.auth_epoch += 1
    _audit(session, admin, "console.password_reset_completed")
    session.commit()


def revoke(
    session: Session, context: ConsoleAuthContext, *, admin_id: str, reason: str
) -> ConsoleAdminRecord:
    if context.admin.role != "manager":
        _fail("console_manager_required", status=403)
    target = session.scalar(
        select(PlatformReportAdmin)
        .where(PlatformReportAdmin.id == admin_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if (
        target is None
        or target.role != "viewer"
        or target.created_by_report_admin_id != context.admin.id
    ):
        _fail("console_conflict", status=409)
    target.status = "revoked"
    target.auth_epoch += 1
    user = session.get(User, target.user_id)
    record = admin_record(target, user)
    _audit(session, context.admin, "console.revoked", target_id=target.id, reason=reason.strip())
    session.commit()
    return record


def audit_report_read(session: Session, context: ConsoleAuthContext, report: str) -> None:
    _audit(session, context.admin, "console.report_read", target_id=report)
    session.commit()


def audit_access_denial(session: Session, *, route: str, code: str) -> None:
    session.rollback()
    _audit(session, None, "console.access_denied", target_id=route, result="denied", reason=code)
    session.commit()


def audit_session_read(session: Session, context: ConsoleAuthContext) -> None:
    _audit(session, context.admin, "console.session_read")
    session.commit()
