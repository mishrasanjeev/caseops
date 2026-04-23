"""Phase B M11 slice 2 — email template CRUD routes (admin surface)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import (
    DbSession,
    require_capability,
)
from caseops_api.schemas.email_templates import (
    EmailRenderRequest,
    EmailRenderResponse,
    EmailTemplateCreateRequest,
    EmailTemplateListResponse,
    EmailTemplateRecord,
    EmailTemplateUpdateRequest,
)
from caseops_api.services.email_templates import (
    archive_email_template,
    create_email_template,
    get_email_template,
    list_email_templates,
    render_template,
    update_email_template,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()

EmailAdmin = Annotated[
    SessionContext, Depends(require_capability("email_templates:manage")),
]


@router.get(
    "/email-templates",
    response_model=EmailTemplateListResponse,
    summary="List email templates for the current workspace.",
)
async def list_current_company_email_templates(
    context: EmailAdmin,
    session: DbSession,
    include_inactive: bool = False,
) -> EmailTemplateListResponse:
    return list_email_templates(
        session, context=context, include_inactive=include_inactive,
    )


@router.post(
    "/email-templates",
    response_model=EmailTemplateRecord,
    summary="Create an email template.",
)
async def post_current_company_email_template(
    payload: EmailTemplateCreateRequest,
    context: EmailAdmin,
    session: DbSession,
) -> EmailTemplateRecord:
    return create_email_template(session, context=context, payload=payload)


@router.get(
    "/email-templates/{template_id}",
    response_model=EmailTemplateRecord,
    summary="Fetch a single email template.",
)
async def get_current_company_email_template(
    template_id: str,
    context: EmailAdmin,
    session: DbSession,
) -> EmailTemplateRecord:
    return get_email_template(
        session, context=context, template_id=template_id,
    )


@router.patch(
    "/email-templates/{template_id}",
    response_model=EmailTemplateRecord,
    summary="Update an email template.",
)
async def patch_current_company_email_template(
    template_id: str,
    payload: EmailTemplateUpdateRequest,
    context: EmailAdmin,
    session: DbSession,
) -> EmailTemplateRecord:
    return update_email_template(
        session, context=context, template_id=template_id, payload=payload,
    )


@router.delete(
    "/email-templates/{template_id}",
    response_model=EmailTemplateRecord,
    summary="Archive an email template (soft delete).",
)
async def archive_current_company_email_template(
    template_id: str,
    context: EmailAdmin,
    session: DbSession,
) -> EmailTemplateRecord:
    return archive_email_template(
        session, context=context, template_id=template_id,
    )


@router.post(
    "/email-templates/{template_id}/render",
    response_model=EmailRenderResponse,
    summary="Render the template with the supplied variables (preview).",
)
async def render_current_company_email_template(
    template_id: str,
    payload: EmailRenderRequest,
    context: EmailAdmin,
    session: DbSession,
) -> EmailRenderResponse:
    template = get_email_template(
        session, context=context, template_id=template_id,
    )
    return render_template(template=template, variables=payload.variables)
