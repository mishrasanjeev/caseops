from fastapi import FastAPI

from caseops_api.api.routes import (
    access_reviews,
    admin,
    ai,
    ai_feedback,
    auth,
    authorities,
    billing,
    bootstrap,
    bulk_imports,
    calendar,
    case_tracking,
    cause_lists,
    clients,
    communications,
    companies,
    conflicts,
    contracts,
    courts,
    data_governance,
    drafting,
    drive,
    email_templates,
    health,
    intake,
    integrations,
    intelligent_reviews,
    ip_foreign_associates,
    ip_international,
    ip_operations,
    ip_recordals,
    ip_registry,
    ip_specialist,
    ip_watch,
    judge_mapping,
    machine_readiness,
    mailbox,
    matter_billing,
    matter_tags,
    matters,
    me,
    meta,
    notices,
    notifications,
    outside_counsel,
    payments,
    platform_admin,
    portal,
    portal_ip,
    private_retrieval,
    product_guide,
    provider_operations,
    recommendations,
    source_actions,
    statutes,
    teams,
    workspace_assistant,
)


def register_api_routes(application: FastAPI) -> None:
    application.include_router(
        access_reviews.router, prefix="/api/access-reviews", tags=["access-reviews"]
    )
    """Register each feature directly, without cloning the entire API twice."""
    application.include_router(health.router, prefix="/api", tags=["health"])
    application.include_router(meta.router, prefix="/api", tags=["meta"])
    application.include_router(
        machine_readiness.router,
        prefix="/api/internal/machine-readiness",
        tags=["machine-readiness"],
    )
    application.include_router(bootstrap.router, prefix="/api/bootstrap", tags=["bootstrap"])
    application.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    application.include_router(billing.router, prefix="/api/billing", tags=["billing"])
    application.include_router(bulk_imports.router, prefix="/api/imports", tags=["bulk-imports"])
    application.include_router(companies.router, prefix="/api/companies", tags=["companies"])
    application.include_router(
        ip_foreign_associates.router,
        prefix="/api/ip",
        tags=["ip-foreign-associates"],
    )
    application.include_router(ip_international.router, prefix="/api/ip", tags=["ip-international"])
    application.include_router(ip_specialist.router, prefix="/api/ip", tags=["ip-specialist"])
    application.include_router(ip_operations.router, prefix="/api/ip", tags=["ip-operations"])
    application.include_router(ip_recordals.router, prefix="/api/ip", tags=["ip-recordals"])
    application.include_router(ip_registry.router, prefix="/api/ip", tags=["ip-registry"])
    application.include_router(ip_watch.router, prefix="/api/ip", tags=["ip-watch"])
    application.include_router(matters.router, prefix="/api/matters", tags=["matters"])
    application.include_router(notices.router, prefix="/api/notices", tags=["notices"])
    application.include_router(matter_tags.router, prefix="/api/matter-tags", tags=["matter-tags"])
    application.include_router(me.router, prefix="/api/me", tags=["me"])
    application.include_router(
        product_guide.router,
        prefix="/api/product-guide",
        tags=["product-guide"],
    )
    application.include_router(drafting.router, prefix="/api/drafting", tags=["drafting"])
    application.include_router(contracts.router, prefix="/api/contracts", tags=["contracts"])
    application.include_router(
        outside_counsel.router,
        prefix="/api/outside-counsel",
        tags=["outside_counsel"],
    )
    application.include_router(payments.router, prefix="/api/payments", tags=["payments"])
    application.include_router(authorities.router, prefix="/api/authorities", tags=["authorities"])
    application.include_router(
        source_actions.router,
        prefix="/api/source-actions",
        tags=["source-actions"],
    )
    application.include_router(
        case_tracking.router, prefix="/api/case-tracking", tags=["case-tracking"]
    )
    application.include_router(cause_lists.router, prefix="/api/cause-lists", tags=["cause-lists"])
    application.include_router(ai.router, prefix="/api/ai", tags=["ai"])
    application.include_router(
        ai_feedback.router,
        prefix="/api/ai-feedback",
        tags=["ai-feedback"],
    )
    application.include_router(
        ai_feedback.admin_router,
        prefix="/api/admin",
        tags=["ai-feedback-admin"],
    )
    application.include_router(
        workspace_assistant.router,
        prefix="/api/workspace-assistant",
        tags=["workspace-assistant"],
    )
    application.include_router(
        private_retrieval.router,
        prefix="/api/private-retrieval",
        tags=["private-retrieval"],
    )
    application.include_router(recommendations.router, prefix="/api", tags=["recommendations"])
    application.include_router(
        intelligent_reviews.router,
        prefix="/api/research",
        tags=["intelligent-reviews"],
    )
    application.include_router(conflicts.router, prefix="/api", tags=["conflicts"])
    application.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    application.include_router(
        data_governance.router,
        prefix="/api/admin/data-governance",
        tags=["data-governance"],
    )
    application.include_router(
        platform_admin.router,
        prefix="/api/platform-admin",
        tags=["platform-admin"],
    )
    application.include_router(
        provider_operations.router,
        prefix="/api/admin/provider-operations",
        tags=["provider-operations"],
    )
    application.include_router(
        integrations.router,
        prefix="/api/admin/integrations",
        tags=["integrations"],
    )
    application.include_router(
        matter_billing.router,
        prefix="/api/admin/matter-billing",
        tags=["matter-billing"],
    )
    application.include_router(courts.router, prefix="/api/courts", tags=["courts"])
    application.include_router(
        judge_mapping.router,
        prefix="/api/judge-mapping",
        tags=["judge-mapping"],
    )
    # MOD-TS-017 Slice S2 (2026-04-25) - bare-acts read API powering
    # /app/statutes browser. Slice S4 (2026-04-25) - matter statute
    # reference write API mounted under /api/matters/.
    application.include_router(statutes.router, prefix="/api/statutes", tags=["statutes"])
    application.include_router(
        statutes.matter_scoped_router,
        prefix="/api/matters",
        tags=["statutes"],
    )
    application.include_router(intake.router, prefix="/api/intake", tags=["intake"])
    application.include_router(teams.router, prefix="/api/teams", tags=["teams"])
    application.include_router(clients.router, prefix="/api/clients", tags=["clients"])
    # Phase B / J08 / M08 - unified calendar feed across hearings,
    # tasks, and the generic matter_deadlines table.
    application.include_router(calendar.router, prefix="/api/calendar", tags=["calendar"])
    application.include_router(mailbox.router, prefix="/api/mailbox", tags=["mailbox"])
    application.include_router(drive.router, prefix="/api/drive", tags=["drive"])
    # Phase B / J12 / M11 - communications log mounted under /matters
    # so the URL shape stays consistent with the cockpit's other tabs.
    application.include_router(
        communications.router,
        prefix="/api/matters",
        tags=["communications"],
    )
    # Phase B M11 slice 2 - AutoMail templates admin surface.
    application.include_router(
        email_templates.router,
        prefix="/api/admin",
        tags=["email-templates"],
    )
    # Per-matter client-assignment endpoints mount under /matters/... to
    # keep the URL shape consistent with the rest of the matter surface.
    application.include_router(
        clients.matter_scoped_router,
        prefix="/api/matters",
        tags=["clients"],
    )
    # Hearing-reminders surface (BUG-013): admin list + SendGrid webhook.
    application.include_router(
        notifications.admin_router,
        prefix="/api/admin",
        tags=["notifications"],
    )
    application.include_router(
        notifications.rules_router,
        prefix="/api/notification-rules",
        tags=["notification-rules"],
    )
    application.include_router(
        notifications.preferences_router,
        prefix="/api/notification-preferences",
        tags=["notification-preferences"],
    )
    application.include_router(
        notifications.webhook_router,
        prefix="/api/webhooks",
        tags=["webhooks"],
    )
    # Phase C-1 (2026-04-24, MOD-TS-014) - portal scaffold.
    # /api/portal/auth/* + /api/portal/me are the external surface
    # (PortalUser session); /api/admin/portal/invitations is the
    # internal owner-driven invite endpoint.
    application.include_router(portal.router, prefix="/api/portal", tags=["portal"])
    application.include_router(portal_ip.public_router, prefix="/api/portal", tags=["portal-ip"])
    application.include_router(
        portal.admin_router,
        prefix="/api/admin",
        tags=["portal-admin"],
    )
    application.include_router(portal_ip.admin_router, prefix="/api/admin", tags=["portal-admin"])
    application.include_router(
        portal_ip.internal_router, prefix="/api/ip", tags=["portal-ip-admin"]
    )
