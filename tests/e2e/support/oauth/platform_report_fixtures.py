"""Synthetic data seed for the guarded browser wrapper, never a production module."""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from calendar_oauth_emulator import loopback_origin, require_test_environment

LONG_FIRM_LABEL = (
    "Synthetic International Intellectual Property and Litigation Practice "
    + "SyntheticUnbrokenAccountLabel" * 3
)

def _fixture_environment(*, run_id: str, web_origin: str, automated_marker: str) -> str:
    require_test_environment()
    if str(UUID(run_id)) != run_id:
        raise ValueError("PRA requires a canonical fresh UUID run identity.")
    if loopback_origin(web_origin) != loopback_origin(os.environ["CASEOPS_PUBLIC_APP_URL"]):
        raise ValueError("PRA fixture browser origin must match the isolated API.")

    from caseops_api.core.automated_test_context import NO_PAID_PROVIDERS_VALUE
    from caseops_api.core.settings import get_settings

    if automated_marker != NO_PAID_PROVIDERS_VALUE:
        raise ValueError("PRA fixture requires the canonical no-paid-provider marker.")
    founder_email = (get_settings().platform_super_admin_email or "").strip().lower()
    if not founder_email.endswith("@example.com"):
        raise ValueError("PRA local fixture requires the synthetic configured founder identity.")
    return founder_email


def seed_console_fixture(*, run_id: str, web_origin: str, automated_marker: str) -> dict:
    founder_email = _fixture_environment(
        run_id=run_id, web_origin=web_origin, automated_marker=automated_marker,
    )
    transport = urlsplit(os.environ.get("CASEOPS_CONSOLE_TEST_MAIL_URL", ""))
    if (
        transport.scheme != "http"
        or transport.hostname not in {"127.0.0.1", "::1"}
        or transport.username
        or transport.password
        or transport.query
        or transport.fragment
        or not transport.port
    ):
        raise RuntimeError(
            "PRA deterministic console mail hook is missing; no manager/setup token was created."
        )

    from caseops_api.core.security import hash_password
    from caseops_api.db.models import (
        AuditActorType,
        AuditEvent,
        AuditResult,
        BillingPaymentOrder,
        BillingPaymentOrderStatus,
        BillingProfitRollup,
        BillingUsageAttribution,
        Company,
        CompanyMembership,
        PlatformConsoleToken,
        PlatformReportAdmin,
        User,
    )
    from caseops_api.db.session import get_session_factory
    from caseops_api.services.platform_admin import (
        ensure_configured_platform_super_admin,
    )
    from caseops_api.services.platform_console import bootstrap_report_manager
    from sqlalchemy import func, select

    manager_email = f"pra-manager-{run_id}@example.com"
    prefix = f"PRA {UUID(run_id).int}"
    now = datetime.now(UTC)
    password = f"PRA-tenant!{secrets.token_urlsafe(24)}aA9"
    owner_email = f"pra-owner-{run_id}@example.com"
    definitions = (
        (LONG_FIRM_LABEL, "law_firm", "active", now - timedelta(minutes=1)),
        ("Solo", "solo", "dormant", now - timedelta(days=31)),
        ("Corporate", "corporate_legal", "unknown", None),
        ("Legacy", "unknown", "unknown", now + timedelta(days=7)),
    )
    with get_session_factory()() as session:
        if session.scalar(select(User.id).where(User.email == manager_email)) is not None:
            raise RuntimeError("PRA fixture run already exists; never replay seed or mail implicitly.")
        companies = []
        expected = []
        expected_audits = []
        for index, (label, category, engagement, evidence_at) in enumerate(definitions):
            company = Company(
                id=str(UUID(int=UUID(run_id).int % (1 << 64) + index)),
                name=f"{prefix} {label}",
                slug=f"pra-{run_id}-{index}",
                tenant_key=f"pra-{run_id}-{index}",
                company_type=category,
                timezone="Asia/Kolkata",
                is_active=True,
                created_at=now - timedelta(days=60),
            )
            session.add(company)
            session.flush()
            member_user = User(
                id=str(uuid4()),
                email=owner_email if index == 0 else f"pra-member-{run_id}-{index}@example.com",
                full_name=f"Synthetic {label} member",
                password_hash=hash_password(password),
                is_active=True,
            )
            session.add(member_user)
            session.flush()
            member = CompanyMembership(
                id=str(uuid4()), company_id=company.id, user_id=member_user.id,
                role="owner", is_active=True, created_at=now - timedelta(days=60),
            )
            session.add(member)
            session.flush()
            # Deliberately no EmployeeProfile: engagement cannot require that optional row.
            if evidence_at is not None:
                event = AuditEvent(
                    id=str(uuid4()),
                    company_id=company.id,
                    actor_type=AuditActorType.HUMAN,
                    actor_membership_id=member.id,
                    action="employee.login",
                    target_type="employee",
                    target_id=member.id,
                    result=AuditResult.SUCCESS,
                    metadata_json=json.dumps({"automated": False, "fixture_run": run_id}),
                    created_at=evidence_at,
                )
                session.add(event)
                expected_audits.append((event.id, company.id, member.id, AuditResult.SUCCESS, evidence_at))
            # A failed current login must not make the dormant account active.
            if engagement == "dormant":
                event = AuditEvent(
                    id=str(uuid4()), company_id=company.id, actor_type=AuditActorType.HUMAN,
                    actor_membership_id=member.id,
                    action="employee.login", target_type="employee", target_id=member.id,
                    result=AuditResult.FAILED, created_at=now,
                )
                session.add(event)
                expected_audits.append((event.id, company.id, member.id, AuditResult.FAILED, now))
            companies.append(company)
            expected.append({"id": company.id, "name": company.name,
                             "company_type": category, "engagement": engagement,
                             "last_meaningful_activity_at": evidence_at.isoformat()
                             if evidence_at is not None and evidence_at <= now else None,
                             "active_users": 1})
        # More than the normal25-row page, with exact known grouped source identities.
        usage_features = [f"pra_browser_{index:02d}" for index in range(26)]
        session.add_all([
            BillingUsageAttribution(
                company_id=companies[0].id, feature_key=feature,
                provider_units=index + 1, credits_debited=0,
                estimated_internal_cost_minor=0, tenant_visible=True,
            )
            for index, feature in enumerate(usage_features)
        ])
        rollup_before = session.execute(select(
            func.count(BillingProfitRollup.id),
            func.coalesce(func.sum(BillingProfitRollup.gross_revenue_minor), 0),
            func.coalesce(func.sum(BillingProfitRollup.recognized_revenue_minor), 0),
            func.coalesce(func.sum(BillingProfitRollup.total_variable_cost_minor), 0),
            func.coalesce(func.sum(BillingProfitRollup.gross_profit_minor), 0),
        )).one()
        period_start = datetime(2026, 10, 1, tzinfo=UTC)
        period_end = datetime(2026, 10, 2, tzinfo=UTC)
        paid_at = datetime(2026, 10, 3, 6, tzinfo=UTC)
        profit = BillingProfitRollup(
            id=str(UUID(int=UUID(run_id).int % (1 << 64) + 100)),
            company_id=companies[0].id, period_start=period_start, period_end=period_end,
            gross_revenue_minor=120_000, recognized_revenue_minor=100_000,
            total_variable_cost_minor=25_000, gross_profit_minor=75_000,
            gross_margin_bps=7_500, payment_gateway_cost_minor=25_000, status="estimated",
        )
        payment = BillingPaymentOrder(
            id=str(UUID(int=UUID(run_id).int % (1 << 64) + 200)),
            company_id=companies[0].id, merchant_reference=f"PRA-{run_id}",
            status=BillingPaymentOrderStatus.PAID, amount_minor=118_000,
            amount_paid_minor=118_000, tax_amount_minor=18_000, paid_at=paid_at,
            provider_payload_json={"fixture_run": run_id, "provider_call_performed": False},
        )
        loss = BillingProfitRollup(
            id=str(UUID(int=UUID(run_id).int % (1 << 64) + 101)),
            company_id=companies[2].id, period_start=period_start, period_end=period_end,
            gross_revenue_minor=0, recognized_revenue_minor=0,
            total_variable_cost_minor=37, gross_profit_minor=-37,
            gross_margin_bps=None, payment_gateway_cost_minor=37, status="estimated",
        )
        session.add_all([profit, payment, loss])
        financial = {
            "profit_id": profit.id, "payment_id": payment.id,
            "company_id": companies[0].id,
            "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
            "paid_at": paid_at.isoformat(), "merchant_reference": payment.merchant_reference,
            "gross_revenue_minor": 120_000, "recognized_revenue_minor": 100_000,
            "total_variable_cost_minor": 25_000, "gross_profit_minor": 75_000,
            "gross_margin_bps": 7_500, "amount_paid_minor": 118_000, "tax_amount_minor": 18_000,
            "loss": {"company_id": companies[2].id, "company_name": companies[2].name,
                     "gross_profit_minor": -37},
            "overview": {"rollup_count": rollup_before[0] + 2,
                         "gross_revenue_minor": rollup_before[1] + 120_000,
                         "recognized_revenue_minor": rollup_before[2] + 100_000,
                         "total_variable_cost_minor": rollup_before[3] + 25_037,
                         "gross_profit_minor": rollup_before[4] + 74_963},
        }

        founder = session.scalar(select(User).where(User.email == founder_email))
        if founder is None:
            founder = User(
                email=founder_email, full_name="Synthetic platform founder",
                password_hash=hash_password(secrets.token_urlsafe(48)), is_active=True,
            )
            session.add(founder)
            session.flush()
            # This root owner is provenance, not the report principal's authentication.
            session.add(CompanyMembership(
                company_id=companies[0].id, user_id=founder.id, role="owner", is_active=True,
            ))
            expected[0]["active_users"] += 1
            session.flush()
        if not founder.is_active:
            raise RuntimeError("PRA fixture will not reactivate an existing founder.")
        root = ensure_configured_platform_super_admin(session)
        if root is None:
            raise RuntimeError("PRA synthetic founder provenance is unavailable.")
        root_id = root.id
        session.commit()
        initial = bootstrap_report_manager(
            session, root_platform_admin_id=root_id, email=manager_email,
            full_name="Synthetic report manager",
        )
        if getattr(initial, "delivery_status", None) != "accepted":
            raise RuntimeError(
                "PRA canonical manager bootstrap did not reach the deterministic mail sink. "
                "Retain the failed fixture; do not mint a session or retry the message."
            )
        admin = session.scalar(
            select(PlatformReportAdmin).join(User, User.id == PlatformReportAdmin.user_id)
            .where(User.email == manager_email)
        )
        if admin is None or admin.status != "pending" or admin.mfa_status != "not_enrolled":
            raise RuntimeError("PRA must begin before initial owner setup and MFA.")
        membership_count = session.scalar(
            select(func.count()).select_from(CompanyMembership)
            .where(CompanyMembership.user_id == admin.user_id)
        )
        if membership_count != 0:
            raise RuntimeError("PRA report manager must be tenant-independent.")
        invite = session.scalars(
            select(PlatformConsoleToken).where(
                PlatformConsoleToken.report_admin_id == admin.id,
                PlatformConsoleToken.purpose == "invite",
            )
        ).one()
        # Simulate passage of the actual link TTL, without sleeping or minting a link.
        # Delivery evidence remains real; only this synthetic pending token is aged.
        invite.created_at = now - timedelta(days=2)
        invite.expires_at = now - timedelta(seconds=1)
        session.commit()
        # Scalar projections re-read committed storage, not ORM identity-map values.
        actual_profit = session.execute(select(
            BillingProfitRollup.company_id, BillingProfitRollup.gross_revenue_minor,
            BillingProfitRollup.recognized_revenue_minor, BillingProfitRollup.total_variable_cost_minor,
            BillingProfitRollup.gross_profit_minor, BillingProfitRollup.gross_margin_bps,
            BillingProfitRollup.period_start, BillingProfitRollup.period_end,
        ).where(BillingProfitRollup.id == financial["profit_id"])).one()
        if tuple(actual_profit[:6]) != (financial["company_id"], 120_000, 100_000, 25_000, 75_000, 7_500):
            raise RuntimeError("PRA persisted positive rollup source mismatch.")
        actual_loss = session.execute(select(
            BillingProfitRollup.company_id, BillingProfitRollup.total_variable_cost_minor,
            BillingProfitRollup.gross_profit_minor,
        ).where(BillingProfitRollup.id == loss.id)).one()
        if tuple(actual_loss) != (companies[2].id, 37, -37):
            raise RuntimeError("PRA persisted account loss source mismatch.")
        actual_payment = session.execute(select(
            BillingPaymentOrder.company_id, BillingPaymentOrder.status,
            BillingPaymentOrder.merchant_reference, BillingPaymentOrder.amount_paid_minor,
            BillingPaymentOrder.tax_amount_minor, BillingPaymentOrder.paid_at,
        ).where(BillingPaymentOrder.id == financial["payment_id"])).one()
        if tuple(actual_payment[:5]) != (financial["company_id"], BillingPaymentOrderStatus.PAID,
                                        financial["merchant_reference"], 118_000, 18_000):
            raise RuntimeError("PRA persisted positive payment source mismatch.")
        for actual, expected_at in (
            (actual_profit.period_start, period_start), (actual_profit.period_end, period_end),
            (actual_payment.paid_at, paid_at),
        ):
            if actual is None:
                raise RuntimeError("PRA persisted positive report date is absent.")
            if actual.tzinfo is None:
                actual = actual.replace(tzinfo=UTC)
            if actual != expected_at:
                raise RuntimeError("PRA persisted positive report date differs from its source.")
        persisted = session.execute(select(
            AuditEvent.id, AuditEvent.company_id, AuditEvent.actor_type,
            AuditEvent.actor_membership_id, AuditEvent.action, AuditEvent.result,
            AuditEvent.target_type, AuditEvent.target_id, AuditEvent.created_at,
        ).where(AuditEvent.company_id.in_([row["id"] for row in expected]))).all()
        by_id = {row.id: row for row in persisted}
        if set(by_id) != {row[0] for row in expected_audits}:
            raise RuntimeError("PRA persisted audit inventory differs from the exact fixture sources.")
        audit_sources = []
        for event_id, company_id, membership_id, result, occurred_at in expected_audits:
            row = by_id[event_id]
            persisted_at = row.created_at
            if persisted_at.tzinfo is None:
                persisted_at = persisted_at.replace(tzinfo=UTC)
            if (
                row.company_id != company_id
                or row.actor_type != AuditActorType.HUMAN
                or row.actor_membership_id != membership_id
                or row.action != "employee.login"
                or row.result != result
                or row.target_type != "employee"
                or row.target_id != membership_id
                or persisted_at != occurred_at
            ):
                raise RuntimeError("PRA persisted human/result/source identity mismatch.")
            member_company = session.scalar(select(CompanyMembership.company_id).where(
                CompanyMembership.id == membership_id,
            ))
            if member_company != company_id:
                raise RuntimeError("PRA audit source membership belongs to another account.")
            audit_sources.append({
                "id": event_id, "company_id": company_id, "actor_type": row.actor_type,
                "actor_membership_id": membership_id, "action": row.action,
                "result": row.result, "target_type": row.target_type, "target_id": row.target_id,
            })
        result = {
            "run_id": run_id,
            "account_prefix": prefix,
            "manager": {"id": admin.id, "email": manager_email,
                        "full_name": "Synthetic report manager"},
            "initial_invitation_expired": True,
            "accounts": expected,
            "usage_features": usage_features,
            "audit_sources": audit_sources,
            "financial": financial,
            "tenant": {"slug": companies[0].slug, "email": owner_email, "password": password},
        }
        session.rollback()
        return result


def cleanup_console_fixture(
    *, run_id: str, web_origin: str, automated_marker: str, manager_id: str | None,
    viewer_baseline: dict | None = None,
) -> dict:
    founder_email = _fixture_environment(
        run_id=run_id, web_origin=web_origin, automated_marker=automated_marker,
    )
    if manager_id is not None and str(UUID(manager_id)) != manager_id:
        raise ValueError("PRA cleanup requires the exact canonical manager UUID.")

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
    from caseops_api.services.platform_console import _root_valid
    from sqlalchemy import select

    manager_email = f"pra-manager-{run_id}@example.com"
    allowed_viewer_emails = {f"viewer-{run_id}@example.com", f"csrf-{run_id}@example.com"}
    with get_session_factory()() as session:
        serialize_sqlite_writer(session)
        identity = session.execute(
            select(PlatformReportAdmin.id, PlatformReportAdmin.root_platform_admin_id)
            .join(User, User.id == PlatformReportAdmin.user_id)
            .where(User.email == manager_email)
        ).one_or_none()
        if identity is None:
            if manager_id is not None:
                raise RuntimeError("PRA cleanup cannot find the exact returned manager; no write attempted.")
            session.rollback()
            return {"run_id": run_id, "status": "not_created", "manager_id": None,
                    "retained": True, "deletes": 0, "no_provider_calls": True}
        if manager_id is not None and identity.id != manager_id:
            raise RuntimeError("PRA cleanup manager UUID disagrees with its exact run email.")
        if not _root_valid(session, identity.root_platform_admin_id, fence=True):
            raise RuntimeError("PRA cleanup requires the unchanged canonical synthetic founder grant.")
        root = session.execute(select(
            PlatformAdminMembership.id, PlatformAdminMembership.user_id,
            PlatformAdminMembership.role, PlatformAdminMembership.status, User.email,
        ).join(User, User.id == PlatformAdminMembership.user_id)
          .where(PlatformAdminMembership.id == identity.root_platform_admin_id)).one()
        if root.email != founder_email or str(UUID(root.id)) != root.id:
            raise RuntimeError("PRA cleanup root identity differs from the configured synthetic founder.")
        manager = session.scalars(select(PlatformReportAdmin).where(
            PlatformReportAdmin.id == identity.id,
        ).with_for_update(key_share=True).execution_options(populate_existing=True)).one()
        manager_user = session.scalars(select(User).where(
            User.id == manager.user_id,
        ).with_for_update(key_share=True).execution_options(populate_existing=True)).one()
        if (
            str(UUID(manager.id)) != manager.id
            or manager.role != "manager"
            or manager.created_by_report_admin_id is not None
            or manager.root_platform_admin_id != root.id
            or manager_user.email != manager_email
            or manager_user.id == root.user_id
        ):
            raise RuntimeError("PRA cleanup manager ownership fence failed; no write attempted.")
        viewers = list(session.scalars(select(PlatformReportAdmin).where(
            PlatformReportAdmin.created_by_report_admin_id == manager.id,
        ).order_by(PlatformReportAdmin.id).limit(3).with_for_update(key_share=True)
          .execution_options(populate_existing=True)))
        if len(viewers) > len(allowed_viewer_emails):
            raise RuntimeError("PRA cleanup has unexpected viewer cardinality; no write attempted.")
        for viewer in viewers:
            user = session.scalars(select(User).where(User.id == viewer.user_id)
                                   .with_for_update(key_share=True)).one()
            if (
                str(UUID(viewer.id)) != viewer.id
                or viewer.role != "viewer"
                or viewer.root_platform_admin_id != root.id
                or user.email not in allowed_viewer_emails
                or user.id in {root.user_id, manager_user.id}
            ):
                raise RuntimeError("PRA cleanup viewer ownership fence failed; no write attempted.")
        if viewer_baseline is not None:
            viewer = next((row for row in viewers if row.id == viewer_baseline["viewer_id"]), None)
            if viewer is None or viewer.user_id != viewer_baseline["user_id"]:
                raise RuntimeError("PRA invitation recovery did not preserve its shared User.")
            from caseops_api.db.models import CompanyMembership

            memberships = sorted(session.scalars(select(CompanyMembership.id).where(
                CompanyMembership.user_id == viewer.user_id,
            )))
            audits = set(session.scalars(select(PlatformReportAuditEvent.id).where(
                (PlatformReportAuditEvent.report_admin_id == viewer.id)
                | (PlatformReportAuditEvent.target_id == viewer.id),
            )))
            if memberships != viewer_baseline["membership_ids"] or not set(
                viewer_baseline["audit_ids"]
            ).issubset(audits):
                raise RuntimeError("PRA invitation recovery changed retained tenant/audit identities.")
        admins = [manager, *viewers]
        admin_ids = sorted(admin.id for admin in admins)
        tokens = list(session.scalars(select(PlatformConsoleToken).where(
            PlatformConsoleToken.report_admin_id.in_(admin_ids),
        ).order_by(PlatformConsoleToken.id).with_for_update(key_share=True)))
        sessions = list(session.scalars(select(PlatformConsoleSession).where(
            PlatformConsoleSession.report_admin_id.in_(admin_ids),
        ).order_by(PlatformConsoleSession.id).with_for_update(key_share=True)))
        token_ids = sorted(row.id for row in tokens)
        session_ids = sorted(row.id for row in sessions)
        delivery_ids = sorted(session.scalars(select(PlatformConsoleDelivery.id).where(
            PlatformConsoleDelivery.token_id.in_(token_ids),
        )))
        retained_audits = sorted(session.scalars(select(PlatformReportAuditEvent.id).where(
            PlatformReportAuditEvent.report_admin_id.in_(admin_ids),
        )))
        now = datetime.now(UTC)
        added_audits = []
        for admin in admins:
            if admin.status != "revoked":
                admin.status = "revoked"
                admin.auth_epoch += 1
                audit_id = str(uuid4())
                session.add(PlatformReportAuditEvent(
                    id=audit_id, report_admin_id=admin.id, actor_user_id=None,
                    action="console.e2e_fixture_cleanup", target_id=admin.id,
                    result="success", reason=f"Retained loopback fixture {run_id}",
                ))
                added_audits.append(audit_id)
        for row in [*tokens, *sessions]:
            if row.revoked_at is None:
                row.revoked_at = now
        session.flush()
        states = session.execute(select(PlatformReportAdmin.id, PlatformReportAdmin.status).where(
            PlatformReportAdmin.id.in_(admin_ids),
        )).all()
        if sorted(row.id for row in states) != admin_ids or any(row.status != "revoked" for row in states):
            raise RuntimeError("PRA cleanup did not retain all exact administrators as revoked.")
        for model, expected_ids, predicate in (
            (PlatformConsoleToken, token_ids, PlatformConsoleToken.report_admin_id.in_(admin_ids)),
            (PlatformConsoleSession, session_ids, PlatformConsoleSession.report_admin_id.in_(admin_ids)),
        ):
            rows = session.execute(select(model.id, model.revoked_at).where(predicate)).all()
            if sorted(row.id for row in rows) != expected_ids or any(row.revoked_at is None for row in rows):
                raise RuntimeError("PRA cleanup failed retained token/session revocation.")
        current_deliveries = sorted(session.scalars(select(PlatformConsoleDelivery.id).where(
            PlatformConsoleDelivery.token_id.in_(token_ids),
        )))
        current_audits = sorted(session.scalars(select(PlatformReportAuditEvent.id).where(
            PlatformReportAuditEvent.report_admin_id.in_(admin_ids),
        )))
        if current_deliveries != delivery_ids or current_audits != sorted([*retained_audits, *added_audits]):
            raise RuntimeError("PRA cleanup changed retained delivery/audit membership.")
        receipt = {
            "run_id": run_id, "status": "revoked", "manager_id": manager.id,
            "viewer_ids": sorted(row.id for row in viewers), "admin_ids": admin_ids,
            "token_ids": token_ids, "session_ids": session_ids,
            "delivery_ids": delivery_ids, "retained_audit_ids": retained_audits,
            "cleanup_audit_ids": sorted(added_audits), "root_id": root.id,
            "retained": True, "deletes": 0, "no_provider_calls": True,
        }
        if viewer_baseline is not None:
            receipt["invitation_recovery_retention"] = {
                **viewer_baseline, "user_preserved": True,
                "tenant_memberships_preserved": True, "prior_audits_preserved": True,
            }
        session.commit()
        durable_states = session.execute(select(PlatformReportAdmin.id, PlatformReportAdmin.status)
                                         .where(PlatformReportAdmin.id.in_(admin_ids))).all()
        if sorted(row.id for row in durable_states) != admin_ids or any(
            row.status != "revoked" for row in durable_states
        ):
            raise RuntimeError("PRA cleanup committed administrator readback failed.")
        for model, expected_ids in ((PlatformConsoleToken, token_ids), (PlatformConsoleSession, session_ids)):
            rows = session.execute(select(model.id, model.revoked_at).where(
                model.report_admin_id.in_(admin_ids),
            )).all()
            if sorted(row.id for row in rows) != expected_ids or any(row.revoked_at is None for row in rows):
                raise RuntimeError("PRA cleanup committed token/session readback failed.")
        root_after = session.execute(select(
            PlatformAdminMembership.id, PlatformAdminMembership.user_id,
            PlatformAdminMembership.role, PlatformAdminMembership.status, User.email,
        ).join(User, User.id == PlatformAdminMembership.user_id)
          .where(PlatformAdminMembership.id == root.id)).one()
        if tuple(root_after) != tuple(root):
            raise RuntimeError("PRA cleanup founder grant changed; do not admit a fresh iteration.")
        receipt["persisted_verified"] = True
        receipt["founder_unchanged"] = True
        session.rollback()
        return receipt


def age_pending_viewer_invitation(
    *, run_id: str, web_origin: str, automated_marker: str, manager_id: str,
    viewer_id: str, manager_session: str, manager_csrf: str,
) -> dict:
    """One fixed local-fixture clock operation, never a production clock override."""
    founder_email = _fixture_environment(
        run_id=run_id, web_origin=web_origin, automated_marker=automated_marker,
    )
    for origin in (web_origin, os.environ["CASEOPS_PUBLIC_APP_URL"]):
        parsed = urlsplit(origin)
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("PRA invitation aging requires exact loopback origins.")
    if any(str(UUID(value)) != value for value in (manager_id, viewer_id)):
        raise ValueError("PRA invitation aging requires exact canonical fixture identities.")
    if not manager_session or not manager_csrf:
        raise ValueError("PRA invitation aging requires the live manager and CSRF pair.")

    from caseops_api.db.models import (
        CompanyMembership,
        PlatformAdminMembership,
        PlatformConsoleToken,
        PlatformReportAdmin,
        PlatformReportAuditEvent,
        User,
    )
    from caseops_api.db.session import get_session_factory
    from caseops_api.services.platform_console import (
        _locked_admin,
        resolve_console_context,
    )
    from sqlalchemy import select

    with get_session_factory()() as session:
        context = resolve_console_context(
            session, token=manager_session, csrf=manager_csrf, manager=True, step_up=True,
        )
        manager, manager_user = context.admin, context.user
        root_email = session.scalar(select(User.email).join(
            PlatformAdminMembership, PlatformAdminMembership.user_id == User.id,
        ).where(PlatformAdminMembership.id == manager.root_platform_admin_id))
        if (
            manager.id != manager_id or manager.role != "manager" or manager.status != "active"
            or manager.created_by_report_admin_id is not None
            or manager_user.email != f"pra-manager-{run_id}@example.com"
            or root_email != founder_email or viewer_id == manager_id
        ):
            raise ValueError("PRA invitation aging manager/run ownership mismatch.")
        viewer, user = _locked_admin(session, viewer_id)
        if (
            viewer.role != "viewer" or viewer.status != "pending" or viewer.removed_at is not None
            or viewer.created_by_report_admin_id != manager_id
            or viewer.root_platform_admin_id != manager.root_platform_admin_id
            or user.email != f"viewer-{run_id}@example.com" or not user.is_active
        ):
            raise ValueError("PRA invitation aging requires its exact pending synthetic viewer.")
        token = session.scalar(select(PlatformConsoleToken).where(
            PlatformConsoleToken.report_admin_id == viewer_id,
            PlatformConsoleToken.purpose == "invite",
        ).order_by(PlatformConsoleToken.created_at.desc(), PlatformConsoleToken.id.desc())
          .limit(1).with_for_update())
        now = datetime.now(UTC)
        def aware(value):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value
        if (
            token is None or token.consumed_at is not None or token.revoked_at is not None
            or aware(token.expires_at) <= now or token.auth_epoch != viewer.auth_epoch
            or token.credential_hash != sha256(user.password_hash.encode()).hexdigest()
            or not now - timedelta(minutes=5) < aware(token.created_at) <= now + timedelta(seconds=5)
        ):
            raise ValueError("PRA invitation aging requires the fresh current unconsumed link.")
        before = {column.name: getattr(token, column.name)
                  for column in PlatformConsoleToken.__table__.columns if column.name != "created_at"}
        user_before = {column.name: getattr(user, column.name) for column in User.__table__.columns}
        epoch = viewer.auth_epoch
        memberships = list(session.scalars(select(CompanyMembership.id).where(
            CompanyMembership.user_id == user.id,
        ).order_by(CompanyMembership.id).limit(17)))
        audits = list(session.scalars(select(PlatformReportAuditEvent.id).where(
            (PlatformReportAuditEvent.report_admin_id == viewer.id)
            | (PlatformReportAuditEvent.target_id == viewer.id),
        ).order_by(PlatformReportAuditEvent.id).limit(65)))
        if len(memberships) > 16 or len(audits) > 64:
            raise ValueError("PRA invitation aging exceeds its synthetic fixture inventory.")
        token.created_at = now - timedelta(minutes=6)
        token_id, user_id = token.id, user.id
        session.commit()
        session.expire_all()
        persisted = session.get(PlatformConsoleToken, token_id)
        retained_user = session.get(User, user_id)
        if (
            persisted is None or retained_user is None
            or {name: getattr(persisted, name) for name in before} != before
            or {name: getattr(retained_user, name) for name in user_before} != user_before
            or session.scalar(select(PlatformReportAdmin.auth_epoch).where(
                PlatformReportAdmin.id == viewer_id,
            )) != epoch
            or aware(persisted.created_at) != now - timedelta(minutes=6)
        ):
            raise RuntimeError("PRA fixed invitation aging changed another persisted fact.")
        return {
            "run_id": run_id, "manager_id": manager_id, "viewer_id": viewer_id,
            "aged_minutes": 6, "only_created_at_changed": True,
            "expiry_hash_credential_epoch_preserved": True, "no_provider_calls": True,
            "viewer_baseline": {"viewer_id": viewer_id, "user_id": user_id,
                                "membership_ids": memberships, "audit_ids": audits},
        }
