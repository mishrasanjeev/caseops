"""Explicit release-bound report-manager inspection/admission; never a startup hook."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from uuid import UUID

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    PlatformAdminMembership,
    PlatformConsoleDelivery,
    PlatformConsoleToken,
    PlatformReportAdmin,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.platform_console import ConsoleAdminRecord, ConsoleInvitationResponse


class _InvalidArguments(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise _InvalidArguments


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect", action="store_true", help="Inspect only (the default).")
    mode.add_argument("--bootstrap", action="store_true", help="Explicitly admit the manager.")
    parser.add_argument("--expected-release-sha", required=True)
    parser.add_argument("--root-platform-admin-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_release_sha):
        raise _InvalidArguments
    if len(args.root_platform_admin_id) != 36:
        raise _InvalidArguments
    if str(UUID(args.root_platform_admin_id)) != args.root_platform_admin_id:
        raise _InvalidArguments
    if len(args.email) > 320 or "<" in args.email or ">" in args.email:
        raise _InvalidArguments
    if args.full_name is not None and (len(args.full_name) > 255 or not args.full_name.strip()):
        raise _InvalidArguments
    for value in (args.email, args.full_name or ""):
        if any(
            unicodedata.category(char).startswith("C") or char in "\u2028\u2029" for char in value
        ):
            raise _InvalidArguments
    args.email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    if args.full_name is not None:
        args.full_name = args.full_name.strip()
    if args.bootstrap and args.full_name is None:
        raise _InvalidArguments
    return args


def _inspect(session: Session, args: argparse.Namespace) -> dict:
    root = session.execute(
        select(
            PlatformAdminMembership.status,
            PlatformAdminMembership.role,
        )
        .where(PlatformAdminMembership.id == args.root_platform_admin_id)
        .limit(1)
    ).first()
    user = session.execute(
        select(User.id, User.is_active)
        .where(
            User.email == args.email,
        )
        .limit(1)
    ).first()
    grant = None
    delivery = None
    if user:
        grant = session.execute(
            select(
                PlatformReportAdmin.id,
                PlatformReportAdmin.status,
                PlatformReportAdmin.role,
                PlatformReportAdmin.root_platform_admin_id,
            )
            .where(PlatformReportAdmin.user_id == user.id)
            .limit(1)
        ).first()
    if grant:
        delivery = session.scalar(
            select(PlatformConsoleDelivery.status)
            .join(
                PlatformConsoleToken,
                PlatformConsoleToken.id == PlatformConsoleDelivery.token_id,
            )
            .where(
                PlatformConsoleToken.report_admin_id == grant.id,
                PlatformConsoleToken.purpose == "invite",
            )
            .order_by(
                PlatformConsoleDelivery.created_at.desc(),
                PlatformConsoleDelivery.id.desc(),
            )
            .limit(1)
        )
    return {
        "operation": "inspect",
        "status": "inspected",
        "mutation_attempted": False,
        "root": {
            "found": root is not None,
            "active": bool(root and root.status == "active"),
            "super_admin": bool(root and root.role == "super_admin"),
        },
        "user": {"found": user is not None, "active": bool(user and user.is_active)},
        "report_grant": {
            "found": grant is not None,
            "status": grant.status
            if grant and grant.status in {"pending", "active", "revoked"}
            else "not_found"
            if grant is None
            else "unknown",
            "role": grant.role
            if grant and grant.role in {"manager", "viewer"}
            else "not_found"
            if grant is None
            else "unknown",
            "root_matches": bool(
                grant and grant.root_platform_admin_id == args.root_platform_admin_id
            ),
        },
        "delivery_status": delivery
        if delivery in {"pending", "accepted", "failed", "outcome_unknown"}
        else "not_found"
        if delivery is None
        else "unknown",
        "inbox_delivery_confirmed": False,
    }


def _bootstrap(session: Session, **kwargs) -> ConsoleInvitationResponse | ConsoleAdminRecord:
    # Import only after argument/release admission, never for inspect/default.
    from caseops_api.services.platform_console import bootstrap_report_manager

    return bootstrap_report_manager(session, **kwargs)


def _emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse(argv)
    except ValueError:
        _emit({"status": "invalid_arguments", "mutation_attempted": False})
        return 2
    try:
        release = get_settings().release_sha
    except Exception:
        _emit({"status": "invalid_configuration", "mutation_attempted": False})
        return 2
    if not isinstance(release, str) or not re.fullmatch(r"[0-9a-f]{40}", release):
        _emit({"status": "release_mismatch", "mutation_attempted": False})
        return 2
    if release != args.expected_release_sha:
        _emit({"status": "release_mismatch", "mutation_attempted": False})
        return 2
    started = False
    try:
        with get_session_factory()() as session:
            if not args.bootstrap:
                payload = _inspect(session, args)
                code = 0
            else:
                started = True
                result = _bootstrap(
                    session,
                    root_platform_admin_id=args.root_platform_admin_id,
                    email=args.email,
                    full_name=args.full_name,
                )
                if isinstance(result, ConsoleInvitationResponse):
                    status, grant = result.delivery_status, result.admin
                    code = 0 if status == "accepted" else 1
                elif isinstance(result, ConsoleAdminRecord):
                    status, grant, code = "existing_grant", result, 0
                else:
                    raise TypeError("Unexpected bootstrap result")
                payload = {
                    "operation": "bootstrap",
                    "status": status,
                    "grant_status": grant.status,
                    "inbox_delivery_confirmed": False,
                    "automatic_retry": False,
                    "next_action": "inspect",
                }
        _emit(payload)
        return code
    except (Exception, KeyboardInterrupt):
        # Service/close failures can occur after a durable claim or an accepted
        # POST. Do not infer rollback or invite an uncertain mutation replay.
        _emit(
            {
                "status": "outcome_unknown" if started else "operation_failed",
                "mutation_attempted": started,
                "automatic_retry": False,
                "next_action": "inspect",
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
