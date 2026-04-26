"""Sprint R3 — drafting template discovery routes.

These endpoints let the web stepper fetch the form schema and field
metadata for a given ``DraftTemplateType``. Generation itself still
happens via the existing `/api/matters/{id}/drafts/{draft_id}/generate`
route — this module is discovery only.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.core.rate_limit import (
    ai_route_rate_limit,
    limiter,
    tenant_aware_key,
)
from caseops_api.schemas.drafting_templates import (
    DraftTemplateSchema,
    DraftTemplateType,
    get_template_schema,
    list_template_schemas,
)
from caseops_api.services.drafting_preview import (
    DraftPreview,
    generate_step_preview,
)
from caseops_api.services.drafting_prompts import get_prompt_parts
from caseops_api.services.drafting_suggestions import (
    FieldSuggestions,
    TemplateSuggestions,
    get_template_suggestions,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.template_recommender import recommend_templates

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


class TemplateRecommendationResponse(BaseModel):
    """Format-to-forum recommendation surfaced on /app/matters/{id}/
    drafts/new above the catch-all template grid (PRD §16.3
    strategic differentiation)."""

    template_type: str
    relevance: str  # 'primary' | 'secondary'
    reason: str


class TemplateRecommendationsResponse(BaseModel):
    forum_level: str
    practice_area: str | None
    recommendations: list[TemplateRecommendationResponse]


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


# Format-to-forum template recommender (PRD §16.3, 2026-04-26).
# Pure-function wrapper over services/template_recommender; no DB
# read, no LLM call. Caller passes (forum_level, practice_area)
# from the matter cockpit; UI ranks the response above the catch-all
# template grid.
@router.get(
    "/templates/recommend",
    response_model=TemplateRecommendationsResponse,
    summary=(
        "Format-to-forum template recommendations. Pure-function; "
        "no LLM. Used by /app/matters/{id}/drafts/new to highlight "
        "1-2 primary templates above the catch-all grid."
    ),
)
async def get_template_recommendations(
    forum_level: str,
    context: CurrentContext,
    practice_area: str | None = None,
) -> TemplateRecommendationsResponse:
    _ = context  # auth-gated; matrix is global (no per-tenant scope)
    recs = recommend_templates(
        forum_level=forum_level, practice_area=practice_area,
    )
    return TemplateRecommendationsResponse(
        forum_level=forum_level,
        practice_area=practice_area,
        recommendations=[
            TemplateRecommendationResponse(
                template_type=r.template_type.value,
                relevance=r.relevance,
                reason=r.reason,
            )
            for r in recs
        ],
    )


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


class DraftPreviewRequest(BaseModel):
    template_type: str
    facts: dict = {}
    step_group: str | None = None


class DraftPreviewResponse(BaseModel):
    template_type: str
    preview_text: str
    step_group: str | None = None
    model: str
    prompt_tokens: int
    completion_tokens: int


@router.post(
    "/preview",
    response_model=DraftPreviewResponse,
    summary=(
        "Sprint R4 — Haiku-backed partial draft preview for the "
        "stepper. Returns a 300-500 word preview reflecting whatever "
        "fields the user has filled so far; unfilled fields render as "
        "'[not yet specified]' instead of invented values."
    ),
)
@limiter.limit(ai_route_rate_limit, key_func=tenant_aware_key)
async def post_drafting_preview(
    request: Request,
    payload: DraftPreviewRequest,
    context: CurrentContext,
    session: DbSession,
) -> DraftPreviewResponse:
    try:
        template = DraftTemplateType(payload.template_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown drafting template '{payload.template_type}'.",
        ) from exc

    # EG-006: pass session + context so the preview goes through the
    # tenant AI policy gate and persists a ModelRun audit row, just
    # like the drafting / recommendations / hearing-pack endpoints.
    preview = generate_step_preview(
        template_type=template,
        facts=payload.facts,
        step_group=payload.step_group,
        session=session,
        context=context,
    )
    return _preview_to_response(preview)


def _preview_to_response(preview: DraftPreview) -> DraftPreviewResponse:
    return DraftPreviewResponse(
        template_type=preview.template_type,
        preview_text=preview.preview_text,
        step_group=preview.step_group,
        model=preview.model,
        prompt_tokens=preview.prompt_tokens,
        completion_tokens=preview.completion_tokens,
    )
