"""Sprint R3 — drafting template discovery routes.

These endpoints let the web stepper fetch the form schema and field
metadata for a given ``DraftTemplateType``. Generation itself still
happens via the existing `/api/matters/{id}/drafts/{draft_id}/generate`
route — this module is discovery only.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from caseops_api.api.dependencies import get_current_context
from caseops_api.schemas.drafting_templates import (
    DraftTemplateSchema,
    DraftTemplateType,
    get_template_schema,
    list_template_schemas,
)
from caseops_api.services.drafting_prompts import get_prompt_parts
from caseops_api.services.drafting_suggestions import (
    FieldSuggestions,
    TemplateSuggestions,
    get_template_suggestions,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


class DraftTemplateSummary(BaseModel):
    template_type: str
    display_name: str
    summary: str
    statutory_basis: list[str]
    focus: str


class DraftTemplatesListResponse(BaseModel):
    templates: list[DraftTemplateSummary]


@router.get(
    "/templates",
    response_model=DraftTemplatesListResponse,
    summary="List drafting templates (one per DraftTemplateType).",
)
async def list_drafting_templates(
    context: CurrentContext,
) -> DraftTemplatesListResponse:
    # Context is only consumed to enforce auth; templates are not
    # tenant-scoped.
    _ = context
    schemas = list_template_schemas()
    summaries: list[DraftTemplateSummary] = []
    for schema in schemas:
        template_type = DraftTemplateType(schema.template_type)
        prompt = get_prompt_parts(template_type)
        summaries.append(
            DraftTemplateSummary(
                template_type=schema.template_type,
                display_name=schema.display_name,
                summary=schema.summary,
                statutory_basis=list(schema.statutory_basis),
                focus=prompt.focus,
            )
        )
    return DraftTemplatesListResponse(templates=summaries)


@router.get(
    "/templates/{template_type}",
    response_model=DraftTemplateSchema,
    summary="Get the full form schema for a specific template.",
)
async def get_drafting_template(
    template_type: str,
    context: CurrentContext,
) -> DraftTemplateSchema:
    _ = context
    try:
        template = DraftTemplateType(template_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown drafting template '{template_type}'.",
        ) from exc
    return get_template_schema(template)


class FieldSuggestionsResponse(BaseModel):
    field_name: str
    label: str
    options: list[str]


class TemplateSuggestionsResponse(BaseModel):
    template_type: str
    fields: list[FieldSuggestionsResponse]


@router.get(
    "/templates/{template_type}/suggestions",
    response_model=TemplateSuggestionsResponse,
    summary=(
        "Per-type auto-suggest snippets for the stepper (Sprint R9). "
        "Common BNS sections for Bail, s.138 boilerplate for Cheque "
        "Bounce, HMA grounds for Divorce, etc."
    ),
)
async def get_drafting_template_suggestions(
    template_type: str,
    context: CurrentContext,
) -> TemplateSuggestionsResponse:
    _ = context
    try:
        template = DraftTemplateType(template_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown drafting template '{template_type}'.",
        ) from exc
    suggestions = get_template_suggestions(template)
    return TemplateSuggestionsResponse(
        template_type=suggestions.template_type,
        fields=[_field_to_response(f) for f in suggestions.fields],
    )


def _field_to_response(field: FieldSuggestions) -> FieldSuggestionsResponse:
    return FieldSuggestionsResponse(
        field_name=field.field_name,
        label=field.label,
        options=list(field.options),
    )


# Silence unused-import warnings — TemplateSuggestions is re-exported
# via the service module, not needed in the route body directly.
_ = TemplateSuggestions
