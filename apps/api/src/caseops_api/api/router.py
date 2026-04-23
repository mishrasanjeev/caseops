from fastapi import APIRouter

from caseops_api.api.routes import (
    admin,
    ai,
    auth,
    authorities,
    bootstrap,
    calendar,
    clients,
    communications,
    companies,
    contracts,
    courts,
    drafting,
    health,
    intake,
    matters,
    meta,
    notifications,
    outside_counsel,
    payments,
    recommendations,
    teams,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(bootstrap.router, prefix="/bootstrap", tags=["bootstrap"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(matters.router, prefix="/matters", tags=["matters"])
api_router.include_router(drafting.router, prefix="/drafting", tags=["drafting"])
api_router.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
api_router.include_router(
    outside_counsel.router,
    prefix="/outside-counsel",
    tags=["outside_counsel"],
)
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(authorities.router, prefix="/authorities", tags=["authorities"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(recommendations.router, tags=["recommendations"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(courts.router, prefix="/courts", tags=["courts"])
api_router.include_router(intake.router, prefix="/intake", tags=["intake"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(clients.router, prefix="/clients", tags=["clients"])
# Phase B / J08 / M08 — unified calendar feed across hearings,
# tasks, and the generic matter_deadlines table.
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
# Phase B / J12 / M11 — communications log mounted under /matters
# so the URL shape stays consistent with the cockpit's other tabs.
api_router.include_router(
    communications.router, prefix="/matters", tags=["communications"],
)
# Per-matter client-assignment endpoints mount under /matters/... to
# keep the URL shape consistent with the rest of the matter surface.
api_router.include_router(
    clients.matter_scoped_router, prefix="/matters", tags=["clients"],
)
# Hearing-reminders surface (BUG-013): admin list + SendGrid webhook.
api_router.include_router(
    notifications.admin_router, prefix="/admin", tags=["notifications"],
)
api_router.include_router(
    notifications.webhook_router, prefix="/webhooks", tags=["webhooks"],
)
