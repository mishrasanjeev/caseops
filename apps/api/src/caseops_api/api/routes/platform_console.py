from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy import select

from caseops_api.api.dependencies import DbSession
from caseops_api.core.console_auth import (
    CONSOLE_CSRF_HEADER,
    CONSOLE_SESSION_COOKIE,
    clear_console_cookies,
    issue_console_cookies,
)
from caseops_api.core.problem_details import ProblemHTTPException, problem_json
from caseops_api.core.rate_limit import limiter, login_rate_limit
from caseops_api.db.models import PlatformAdminMembership, PlatformReportAdmin, User
from caseops_api.schemas.activity_reports import ActivityReportResponse
from caseops_api.schemas.platform_console import (
    ConsoleAcceptedResponse,
    ConsoleAdminRecord,
    ConsoleAdminsResponse,
    ConsoleAuthState,
    ConsoleEmptyRequest,
    ConsoleInvitationResponse,
    ConsoleInviteCompleteRequest,
    ConsoleInviteRequest,
    ConsoleLoginRequest,
    ConsoleLogoutResponse,
    ConsoleManagedAdminsResponse,
    ConsoleMFAEnrollmentResponse,
    ConsoleMFAVerifyRequest,
    ConsoleOKResponse,
    ConsoleOverviewResponse,
    ConsoleRemoveRequest,
    ConsoleReportPage,
    ConsoleResetStartRequest,
    ConsoleRevokeRequest,
    ConsoleTokenCompleteRequest,
    ConsoleVersionRequest,
)
from caseops_api.schemas.platform_console_named_reports import (
    ConsoleNamedOverviewResponse,
    ConsoleNamedReportPage,
)
from caseops_api.schemas.platform_leads import ConsoleLeadsResponse
from caseops_api.services import platform_console as console
from caseops_api.services.activity_reports import build_activity_report
from caseops_api.services.platform_console_leads import leads_page
from caseops_api.services.platform_console_reports import overview, report_page


class ConsoleRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def protected_handler(request: Request):
            try:
                response = await handler(request)
            except RequestValidationError:
                # Pydantic's input/error context can contain passwords, setup
                # tokens or MFA secrets. Never reflect those values to clients.
                response = problem_json(
                    422,
                    request=request,
                    detail="Invalid report console request.",
                    problem_type="console_validation_failed",
                    extras={"code": "console_validation_failed"},
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return protected_handler


router = APIRouter(route_class=ConsoleRoute)


def _context(request: Request, session, *, authenticated=True, manager=False, step_up=False):
    csrf = request.headers.get(CONSOLE_CSRF_HEADER, "") if request.method == "POST" else None
    try:
        return console.resolve_console_context(
            session,
            token=request.cookies.get(CONSOLE_SESSION_COOKIE, ""),
            csrf=csrf,
            authenticated=authenticated,
            manager=manager,
            step_up=step_up,
        )
    except ProblemHTTPException as exc:
        if exc.problem_type not in console.AUDITED_CONTEXT_DENIAL_CODES:
            console.audit_access_denial(
                session,
                route=request.scope["route"].path,
                code=exc.problem_type,
            )
        raise


def _automated(request: Request) -> bool:
    return "x-caseops-automated-test" in request.headers


def _cookies(response: Response, issued: console.ConsoleIssuedSession) -> ConsoleAuthState:
    issue_console_cookies(
        response, token=issued.token, csrf=issued.csrf, ttl_seconds=issued.ttl_seconds
    )
    response.headers["Cache-Control"] = "no-store"
    return issued.state


@router.post("/auth/login", response_model=ConsoleAuthState)
@limiter.limit(login_rate_limit)
def login(request: Request, response: Response, payload: ConsoleLoginRequest, session: DbSession):
    return _cookies(
        response, console.login(session, email=str(payload.email), password=payload.password)
    )


@router.get("/auth/session", response_model=ConsoleAuthState)
def current_session(request: Request, response: Response, session: DbSession):
    context = _context(request, session, authenticated=False)
    state = console.auth_state(context)
    console.audit_session_read(session, context)
    response.headers["Cache-Control"] = "no-store"
    return state


@router.post("/auth/mfa/enroll", response_model=ConsoleMFAEnrollmentResponse)
@limiter.limit(login_rate_limit)
def enroll(request: Request, payload: ConsoleEmptyRequest, session: DbSession):
    return console.start_mfa_enrollment(session, _context(request, session, authenticated=False))


@router.post("/auth/mfa/verify", response_model=ConsoleAuthState)
@limiter.limit(login_rate_limit)
def verify(
    request: Request, response: Response, payload: ConsoleMFAVerifyRequest, session: DbSession
):
    context = _context(request, session, authenticated=False)
    return _cookies(
        response,
        console.verify_mfa(
            session,
            context,
            code=payload.code,
            recovery_code=payload.recovery_code,
        ),
    )


@router.post("/auth/logout", response_model=ConsoleLogoutResponse)
def logout(request: Request, response: Response, session: DbSession):
    console.logout(session, _context(request, session, authenticated=False))
    clear_console_cookies(response)
    return ConsoleLogoutResponse()


@router.post("/auth/invitations/complete", response_model=ConsoleAuthState)
@limiter.limit(login_rate_limit)
def complete_invitation(
    request: Request,
    response: Response,
    payload: ConsoleInviteCompleteRequest,
    session: DbSession,
):
    return _cookies(
        response,
        console.complete_invitation(
            session,
            token=payload.token,
            password=payload.password,
            full_name=payload.full_name,
        ),
    )


@router.post("/auth/password-reset/start", response_model=ConsoleAcceptedResponse)
@limiter.limit(login_rate_limit)
def start_reset(
    request: Request,
    payload: ConsoleResetStartRequest,
    session: DbSession,
    background: BackgroundTasks,
):
    claim = console.start_password_reset(
        session, email=str(payload.email), automated=_automated(request)
    )
    if claim:
        background.add_task(console.send_password_reset_claim, claim)
    return ConsoleAcceptedResponse()


@router.post("/auth/invitations/resend", response_model=ConsoleAcceptedResponse)
@limiter.limit(login_rate_limit)
def resend_invitation(
    request: Request,
    payload: ConsoleResetStartRequest,
    session: DbSession,
    background: BackgroundTasks,
):
    claim = console.start_invitation_resend(
        session, email=str(payload.email), automated=_automated(request)
    )
    if claim:
        background.add_task(console.send_password_reset_claim, claim)
    return ConsoleAcceptedResponse()


@router.post("/auth/password-reset/complete", response_model=ConsoleOKResponse)
@limiter.limit(login_rate_limit)
def complete_reset(
    request: Request,
    response: Response,
    payload: ConsoleTokenCompleteRequest,
    session: DbSession,
):
    console.complete_password_reset(session, token=payload.token, password=payload.password)
    clear_console_cookies(response)
    return ConsoleOKResponse()


@router.get("/admins", response_model=ConsoleAdminsResponse)
def admins(
    request: Request,
    session: DbSession,
    cursor: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=100),
):
    context = _context(request, session, manager=True)
    query = (
        select(PlatformReportAdmin, User)
        .join(User, User.id == PlatformReportAdmin.user_id)
        .where(
            PlatformReportAdmin.root_platform_admin_id == context.admin.root_platform_admin_id,
            PlatformReportAdmin.removed_at.is_(None),
        )
    )
    if cursor:
        query = query.where(PlatformReportAdmin.id > cursor)
    rows = list(session.execute(query.order_by(PlatformReportAdmin.id).limit(limit + 1)))
    items = [console.admin_record(admin, user) for admin, user in rows[:limit]]
    result = ConsoleAdminsResponse(
        items=items, next_cursor=items[-1].id if len(rows) > limit else None
    )
    console.audit_report_read(session, context, "admins")
    return result


@router.get("/admins/manage", response_model=ConsoleManagedAdminsResponse)
def managed_admins(
    request: Request, session: DbSession,
    cursor: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=100),
):
    context = _context(request, session, manager=True)
    query = select(PlatformReportAdmin, User).join(
        User, User.id == PlatformReportAdmin.user_id
    ).where(
        PlatformReportAdmin.root_platform_admin_id == context.admin.root_platform_admin_id,
        PlatformReportAdmin.removed_at.is_(None),
    )
    if cursor:
        query = query.where(PlatformReportAdmin.id > cursor)
    rows = list(session.execute(query.order_by(PlatformReportAdmin.id).limit(limit + 1)))
    founder_user_id = session.scalar(select(PlatformAdminMembership.user_id).where(
        PlatformAdminMembership.id == context.admin.root_platform_admin_id
    ))
    items = [console.managed_admin_record(admin, user, context, founder_user_id=founder_user_id)
             for admin, user in rows[:limit]]
    result = ConsoleManagedAdminsResponse(
        items=items, next_cursor=items[-1].id if len(rows) > limit else None
    )
    console.audit_report_read(session, context, "admins_manage")
    return result


@router.post("/admins/invitations", response_model=ConsoleInvitationResponse)
@limiter.limit(login_rate_limit)
def invite(request: Request, payload: ConsoleInviteRequest, session: DbSession):
    context = _context(request, session, manager=True, step_up=True)
    return console.invite(
        session,
        context,
        email=str(payload.email),
        full_name=payload.full_name,
        automated=_automated(request),
        reinvite_revoked=payload.reinvite_revoked,
    )


@router.post("/admins/{admin_id}/revoke", response_model=ConsoleAdminRecord)
def revoke(request: Request, admin_id: str, payload: ConsoleRevokeRequest, session: DbSession):
    context = _context(request, session, manager=True, step_up=True)
    return console.revoke(session, context, admin_id=admin_id, reason=payload.reason,
                          expected_version=payload.expected_version)


@router.post("/admins/{admin_id}/remove", response_model=ConsoleAdminRecord)
def remove(request: Request, admin_id: str, payload: ConsoleRemoveRequest, session: DbSession):
    context = _context(request, session, manager=True, step_up=True)
    return console.remove(session, context, admin_id=admin_id, reason=payload.reason,
                          expected_version=payload.expected_version)


@router.post("/admins/{admin_id}/invitations/resend", response_model=ConsoleInvitationResponse)
@limiter.limit(login_rate_limit)
def resend_admin_invitation(
    request: Request, admin_id: str, payload: ConsoleVersionRequest, session: DbSession,
):
    context = _context(request, session, manager=True, step_up=True)
    return console.resend_invitation(session, context, admin_id=admin_id,
        expected_version=payload.expected_version, automated=_automated(request))


@router.get("/reports/activity", response_model=ActivityReportResponse)
def activity(request: Request, response: Response, session: DbSession):
    context = _context(request, session)
    result = build_activity_report(session, include_internal_accounts=True)
    console.audit_report_read(session, context, "activity")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/leads", response_model=ConsoleLeadsResponse)
def public_leads(
    request: Request,
    session: DbSession,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=25, ge=1, le=100),
):
    context = _context(request, session, manager=True)
    result = leads_page(session, cursor=cursor, limit=limit)
    console.audit_report_read(session, context, "public_leads")
    return result


@router.get(
    "/reports/overview", response_model=ConsoleNamedOverviewResponse | ConsoleOverviewResponse
)
def overview_report(
    request: Request, response: Response, session: DbSession,
    include_account_names: bool = Query(default=False),
):
    context = _context(request, session)
    result = overview(session, include_account_names=include_account_names)
    console.audit_report_read(session, context, "overview")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/reports/{kind}", response_model=ConsoleNamedReportPage | ConsoleReportPage)
def financial_report(
    request: Request,
    response: Response,
    kind: str,
    session: DbSession,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=50, ge=1, le=100),
    include_account_names: bool = Query(default=False),
):
    context = _context(request, session)
    if kind not in {"usage", "profit", "company-profitability", "revenue"}:
        console._fail("console_report_not_found", status=404)
    result = report_page(session, kind=kind, cursor=cursor, limit=limit,
                         include_account_names=include_account_names)
    console.audit_report_read(session, context, kind)
    response.headers["Cache-Control"] = "no-store"
    return result
