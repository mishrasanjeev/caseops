"""Phase B M11 slice 2 — email template CRUD + render + send.

Deliberately small surface: list / get / create / update / archive
on the templates catalogue, plus a ``render_template`` helper that
performs the same ``{{var}}`` substitution the send action uses.

The send action lives in ``services.communications`` (via a new
``send_matter_email`` helper) so the resulting ``Communication`` row
is written by the same module that owns the rest of the comms log.
"""
from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import EmailTemplate
from caseops_api.schemas.email_templates import (
    EmailRenderResponse,
    EmailTemplateCreateRequest,
    EmailTemplateListResponse,
    EmailTemplateRecord,
    EmailTemplateUpdateRequest,
)
from caseops_api.services.identity import SessionContext

# {{var_name}} — alphanumeric + underscore only. Whitespace inside
# the braces is tolerated so admins can write {{ client_name }}
# interchangeably with {{client_name}}.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def list_email_templates(
    session: Session, *, context: SessionContext, include_inactive: bool = False,
) -> EmailTemplateListResponse:
    stmt = select(EmailTemplate).where(
        EmailTemplate.company_id == context.company.id,
    )
    if not include_inactive:
        stmt = stmt.where(EmailTemplate.is_active.is_(True))
    stmt = stmt.order_by(EmailTemplate.name)
    rows = list(session.scalars(stmt))
    return EmailTemplateListResponse(
        templates=[EmailTemplateRecord.from_model(r) for r in rows],
    )


def _load(session: Session, *, context: SessionContext, template_id: str) -> EmailTemplate:
    template = session.scalar(
        select(EmailTemplate).where(
            EmailTemplate.id == template_id,
            EmailTemplate.company_id == context.company.id,
        )
    )
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email template not found.",
        )
    return template


def get_email_template(
    session: Session, *, context: SessionContext, template_id: str,
) -> EmailTemplateRecord:
    return EmailTemplateRecord.from_model(
        _load(session, context=context, template_id=template_id),
    )


def create_email_template(
    session: Session,
    *,
    context: SessionContext,
    payload: EmailTemplateCreateRequest,
) -> EmailTemplateRecord:
    template = EmailTemplate(
        company_id=context.company.id,
        name=payload.name.strip(),
        kind=payload.kind.strip(),
        description=payload.description,
        subject_template=payload.subject_template,
        body_template=payload.body_template,
        variables_json=[v.model_dump() for v in payload.variables],
        created_by_membership_id=context.membership.id,
    )
    session.add(template)
    try:
        session.commit()
    except IntegrityError as exc:
        # Hari-pattern (2026-04-22 batch): every uniqueness constraint
        # needs a pre-flight or a clean 409 on the violation. Returning
        # 409 here is the actionable signal the UI surfaces.
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"An email template named {payload.name!r} already exists "
                "in this workspace."
            ),
        ) from exc
    session.refresh(template)
    return EmailTemplateRecord.from_model(template)


def update_email_template(
    session: Session,
    *,
    context: SessionContext,
    template_id: str,
    payload: EmailTemplateUpdateRequest,
) -> EmailTemplateRecord:
    template = _load(session, context=context, template_id=template_id)
    if payload.name is not None:
        template.name = payload.name.strip()
    if payload.kind is not None:
        template.kind = payload.kind.strip()
    if payload.description is not None:
        template.description = payload.description
    if payload.subject_template is not None:
        template.subject_template = payload.subject_template
    if payload.body_template is not None:
        template.body_template = payload.body_template
    if payload.variables is not None:
        template.variables_json = [v.model_dump() for v in payload.variables]
    if payload.is_active is not None:
        template.is_active = payload.is_active
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That template name is already used in this workspace.",
        ) from exc
    session.refresh(template)
    return EmailTemplateRecord.from_model(template)


def archive_email_template(
    session: Session, *, context: SessionContext, template_id: str,
) -> EmailTemplateRecord:
    template = _load(session, context=context, template_id=template_id)
    template.is_active = False
    session.commit()
    session.refresh(template)
    return EmailTemplateRecord.from_model(template)


def render_template(
    *,
    template: EmailTemplate | EmailTemplateRecord,
    variables: dict[str, str],
) -> EmailRenderResponse:
    """Substitute ``{{var}}`` tokens in subject + body with the
    supplied variable values. Tokens with no provided value are kept
    as ``[client_name not set]`` so the lawyer can spot them in the
    preview pane and either provide the variable or edit the template.

    Also returns ``missing_variables`` — the set of declared-required
    variables the caller didn't pass — so the Send button can be
    disabled until the user fills them.
    """
    subject_tpl = template.subject_template
    body_tpl = template.body_template

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in variables and variables[name].strip():
            return variables[name]
        return f"[{name} not set]"

    subject = _PLACEHOLDER_RE.sub(_replace, subject_tpl)
    body = _PLACEHOLDER_RE.sub(_replace, body_tpl)

    declared_required: list[str] = []
    declared = (
        template.variables
        if isinstance(template, EmailTemplateRecord)
        else (template.variables_json or [])
    )
    for v in declared:
        if isinstance(v, dict):
            if v.get("required", True) and v.get("name"):
                declared_required.append(str(v["name"]))
        else:
            if getattr(v, "required", True) and getattr(v, "name", None):
                declared_required.append(v.name)
    missing = [
        n for n in declared_required
        if n not in variables or not variables[n].strip()
    ]
    return EmailRenderResponse(
        subject=subject, body=body, missing_variables=missing,
    )


__all__ = [
    "archive_email_template",
    "create_email_template",
    "get_email_template",
    "list_email_templates",
    "render_template",
    "update_email_template",
]
