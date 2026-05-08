from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.auth import AuthContextResponse
from caseops_api.schemas.companies import (
    CompanyProfileResponse,
    CompanyProfileUpdateRequest,
    CompanyUserCreateRequest,
    CompanyUserRecord,
    CompanyUsersResponse,
    CompanyUserUpdateRequest,
    MembershipRoleLiteral,
)
from caseops_api.schemas.custom_roles import (
    CapabilityCatalogResponse,
    CustomRoleCreateRequest,
    CustomRoleListResponse,
    CustomRoleRecord,
    CustomRoleUpdateRequest,
    EmployeeCustomRoleAssignRequest,
)
from caseops_api.schemas.employees import (
    EmployeeAuditResponse,
    EmployeeCreateRequest,
    EmployeeCreateResponse,
    EmployeeImportCommitResponse,
    EmployeeImportJobResponse,
    EmployeeListResponse,
    EmployeeOffboardingCommitResponse,
    EmployeeOffboardingPreviewResponse,
    EmployeeOffboardingRequest,
    EmployeeRecord,
    EmployeeTokenDelivery,
    EmployeeUpdateRequest,
    EmploymentStatusLiteral,
)
from caseops_api.services.custom_roles import (
    assign_employee_custom_role,
    create_custom_role,
    delete_custom_role,
    get_custom_role,
    list_capability_catalog,
    list_custom_roles,
    update_custom_role,
)
from caseops_api.services.employee_imports import (
    EMPLOYEE_IMPORT_MAX_BYTES,
    cancel_employee_import,
    commit_employee_import,
    employee_import_template,
    preview_employee_import,
)
from caseops_api.services.employees import (
    commit_employee_offboarding,
    create_employee,
    get_employee,
    issue_employee_password_reset,
    list_employee_audit,
    list_employees,
    preview_employee_offboarding,
    resend_employee_setup,
    update_employee,
)
from caseops_api.services.identity import (
    SessionContext,
    build_auth_context,
    create_company_user,
    get_company_profile,
    list_company_users,
    update_company_profile,
    update_company_user,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
ProfileManager = Annotated[
    SessionContext, Depends(require_capability("company:manage_profile"))
]
UserManager = Annotated[
    SessionContext, Depends(require_capability("company:manage_users"))
]


@router.get(
    "/current",
    response_model=AuthContextResponse,
    summary="Get the current company context",
)
async def current_company(
    context: CurrentContext,
    session: DbSession,
) -> AuthContextResponse:
    return build_auth_context(session, context)


@router.get(
    "/current/profile",
    response_model=CompanyProfileResponse,
    summary="Get the current company profile",
)
async def current_company_profile(context: CurrentContext) -> CompanyProfileResponse:
    return get_company_profile(context)


@router.patch(
    "/current/profile",
    response_model=CompanyProfileResponse,
    summary="Update the current company profile",
)
async def patch_current_company_profile(
    payload: CompanyProfileUpdateRequest,
    context: ProfileManager,
    session: DbSession,
) -> CompanyProfileResponse:
    return update_company_profile(session, context=context, payload=payload)


@router.get(
    "/current/users",
    response_model=CompanyUsersResponse,
    summary="List users for the current company",
)
async def current_company_users(
    context: CurrentContext,
    session: DbSession,
) -> CompanyUsersResponse:
    return list_company_users(session, context)


@router.post(
    "/current/users",
    response_model=CompanyUserRecord,
    summary="Create a user in the current company",
)
async def create_current_company_user(
    payload: CompanyUserCreateRequest,
    context: UserManager,
    session: DbSession,
) -> CompanyUserRecord:
    return create_company_user(session, context=context, payload=payload)


@router.patch(
    "/current/users/{membership_id}",
    response_model=CompanyUserRecord,
    summary="Update a company user's role or active status",
)
async def update_current_company_user(
    membership_id: str,
    payload: CompanyUserUpdateRequest,
    context: UserManager,
    session: DbSession,
) -> CompanyUserRecord:
    return update_company_user(
        session,
        context=context,
        membership_id=membership_id,
        payload=payload,
    )


@router.get(
    "/current/employees",
    response_model=EmployeeListResponse,
    summary="List employee directory records for the current company",
)
async def current_company_employees(
    context: UserManager,
    session: DbSession,
    q: str | None = None,
    role: MembershipRoleLiteral | None = None,
    status: EmploymentStatusLiteral | None = None,
    department: str | None = None,
) -> EmployeeListResponse:
    return list_employees(
        session,
        context=context,
        q=q,
        role=role,
        status_filter=status,
        department=department,
    )


@router.post(
    "/current/employees",
    response_model=EmployeeCreateResponse,
    summary="Create an employee with a secure account setup link",
)
async def create_current_company_employee(
    payload: EmployeeCreateRequest,
    context: UserManager,
    session: DbSession,
) -> EmployeeCreateResponse:
    return create_employee(session, context=context, payload=payload)


@router.get(
    "/current/employees/import-template",
    summary="Download a CSV/XLSX employee import template",
)
async def current_company_employee_import_template(
    context: UserManager,
    format: Literal["csv", "xlsx"] = Query(default="csv"),
) -> Response:
    del context
    body, content_type, filename = employee_import_template(format)
    return Response(
        content=body,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/current/employees/imports/preview",
    response_model=EmployeeImportJobResponse,
    summary="Preview a bulk employee import with row-level validation",
)
async def preview_current_company_employee_import(
    context: UserManager,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> EmployeeImportJobResponse:
    content = await file.read(EMPLOYEE_IMPORT_MAX_BYTES + 1)
    return preview_employee_import(
        session,
        context=context,
        filename=file.filename or "employees",
        content_type=file.content_type,
        content=content,
    )


@router.post(
    "/current/employees/imports/{job_id}/commit",
    response_model=EmployeeImportCommitResponse,
    summary="Commit a validated bulk employee import",
)
async def commit_current_company_employee_import(
    job_id: str,
    context: UserManager,
    session: DbSession,
) -> EmployeeImportCommitResponse:
    return commit_employee_import(session, context=context, job_id=job_id)


@router.post(
    "/current/employees/imports/{job_id}/cancel",
    response_model=EmployeeImportJobResponse,
    summary="Cancel a previewed bulk employee import",
)
async def cancel_current_company_employee_import(
    job_id: str,
    context: UserManager,
    session: DbSession,
) -> EmployeeImportJobResponse:
    return cancel_employee_import(session, context=context, job_id=job_id)


@router.get(
    "/current/employees/{membership_id}",
    response_model=EmployeeRecord,
    summary="Read one employee directory record",
)
async def current_company_employee(
    membership_id: str,
    context: UserManager,
    session: DbSession,
) -> EmployeeRecord:
    return get_employee(session, context=context, membership_id=membership_id)


@router.patch(
    "/current/employees/{membership_id}",
    response_model=EmployeeRecord,
    summary="Update employee directory metadata",
)
async def update_current_company_employee(
    membership_id: str,
    payload: EmployeeUpdateRequest,
    context: UserManager,
    session: DbSession,
) -> EmployeeRecord:
    return update_employee(
        session,
        context=context,
        membership_id=membership_id,
        payload=payload,
    )


@router.post(
    "/current/employees/{membership_id}/resend-setup",
    response_model=EmployeeTokenDelivery,
    summary="Resend an employee account setup link",
)
async def resend_current_company_employee_setup(
    membership_id: str,
    context: UserManager,
    session: DbSession,
) -> EmployeeTokenDelivery:
    return resend_employee_setup(
        session,
        context=context,
        membership_id=membership_id,
    )


@router.post(
    "/current/employees/{membership_id}/reset-password",
    response_model=EmployeeTokenDelivery,
    summary="Issue an employee password reset link",
)
async def reset_current_company_employee_password(
    membership_id: str,
    context: UserManager,
    session: DbSession,
) -> EmployeeTokenDelivery:
    return issue_employee_password_reset(
        session,
        context=context,
        membership_id=membership_id,
    )


@router.get(
    "/current/employees/{membership_id}/audit",
    response_model=EmployeeAuditResponse,
    summary="List employee audit and lifecycle history",
)
async def current_company_employee_audit(
    membership_id: str,
    context: UserManager,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=200),
) -> EmployeeAuditResponse:
    return list_employee_audit(
        session,
        context=context,
        membership_id=membership_id,
        limit=limit,
    )


@router.post(
    "/current/employees/{membership_id}/offboarding/preview",
    response_model=EmployeeOffboardingPreviewResponse,
    summary="Preview employee offboarding impact",
)
async def preview_current_company_employee_offboarding(
    membership_id: str,
    payload: EmployeeOffboardingRequest,
    context: UserManager,
    session: DbSession,
) -> EmployeeOffboardingPreviewResponse:
    return preview_employee_offboarding(
        session,
        context=context,
        membership_id=membership_id,
        payload=payload,
    )


@router.post(
    "/current/employees/{membership_id}/offboarding/commit",
    response_model=EmployeeOffboardingCommitResponse,
    summary="Commit employee offboarding and supported reassignment",
)
async def commit_current_company_employee_offboarding(
    membership_id: str,
    payload: EmployeeOffboardingRequest,
    context: UserManager,
    session: DbSession,
) -> EmployeeOffboardingCommitResponse:
    return commit_employee_offboarding(
        session,
        context=context,
        membership_id=membership_id,
        payload=payload,
    )


@router.get(
    "/current/capabilities",
    response_model=CapabilityCatalogResponse,
    summary="List approved capabilities available for custom role templates",
)
async def current_company_capabilities(context: UserManager) -> CapabilityCatalogResponse:
    del context
    return list_capability_catalog()


@router.get(
    "/current/roles",
    response_model=CustomRoleListResponse,
    summary="List custom role templates for the current company",
)
async def current_company_custom_roles(
    context: UserManager,
    session: DbSession,
    include_inactive: bool = Query(default=False),
) -> CustomRoleListResponse:
    return list_custom_roles(
        session,
        context=context,
        include_inactive=include_inactive,
    )


@router.post(
    "/current/roles",
    response_model=CustomRoleRecord,
    summary="Create a custom role template",
)
async def create_current_company_custom_role(
    payload: CustomRoleCreateRequest,
    context: UserManager,
    session: DbSession,
) -> CustomRoleRecord:
    return create_custom_role(session, context=context, payload=payload)


@router.get(
    "/current/roles/{role_id}",
    response_model=CustomRoleRecord,
    summary="Read one custom role template",
)
async def current_company_custom_role(
    role_id: str,
    context: UserManager,
    session: DbSession,
) -> CustomRoleRecord:
    return get_custom_role(session, context=context, role_id=role_id)


@router.patch(
    "/current/roles/{role_id}",
    response_model=CustomRoleRecord,
    summary="Update a custom role template",
)
async def update_current_company_custom_role(
    role_id: str,
    payload: CustomRoleUpdateRequest,
    context: UserManager,
    session: DbSession,
) -> CustomRoleRecord:
    return update_custom_role(session, context=context, role_id=role_id, payload=payload)


@router.delete(
    "/current/roles/{role_id}",
    response_model=CustomRoleRecord,
    summary="Revoke a custom role template",
)
async def delete_current_company_custom_role(
    role_id: str,
    context: UserManager,
    session: DbSession,
) -> CustomRoleRecord:
    return delete_custom_role(session, context=context, role_id=role_id)


@router.post(
    "/current/employees/{membership_id}/role",
    response_model=EmployeeRecord,
    summary="Assign or clear an employee's custom role template",
)
async def assign_current_company_employee_custom_role(
    membership_id: str,
    payload: EmployeeCustomRoleAssignRequest,
    context: UserManager,
    session: DbSession,
) -> EmployeeRecord:
    assign_employee_custom_role(
        session,
        context=context,
        membership_id=membership_id,
        payload=payload,
    )
    return get_employee(session, context=context, membership_id=membership_id)
