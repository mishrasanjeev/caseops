from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.services.capabilities import resolve_membership_capabilities
from caseops_api.services.product_guide import (
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    load_product_guide_catalog,
    search_product_guide,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


class ProductGuideSectionResponse(BaseModel):
    id: str
    title: str
    summary: str
    keywords: list[str]
    aliases: list[str]
    href: str


class ProductGuideCatalogResponse(BaseModel):
    schema_version: int
    corpus_id: str
    content_version: str
    display_version: str
    language: str
    canonical_path: str
    updated_on: str
    catalog_fingerprint: str
    sections: list[ProductGuideSectionResponse]


class ProductGuideSearchResultResponse(BaseModel):
    kind: Literal["guide", "command"]
    id: str
    title: str
    summary: str
    href: str
    required_capabilities: list[str]


class ProductGuidePermissionResponse(BaseModel):
    required_capabilities: list[str]
    message: str


class ProductGuideSearchResponse(BaseModel):
    status: Literal["matched", "permission_required", "no_match"]
    version_status: Literal["current", "stale"]
    content_version: str
    catalog_fingerprint: str
    query: str
    results: list[ProductGuideSearchResultResponse]
    permission: ProductGuidePermissionResponse | None
    suggested_queries: list[str]


@router.get(
    "/catalog",
    response_model=ProductGuideCatalogResponse,
    summary="Read the approved, versioned Product Guide section index.",
)
async def get_product_guide_catalog() -> ProductGuideCatalogResponse:
    catalog = load_product_guide_catalog()
    return ProductGuideCatalogResponse(
        schema_version=catalog["schema_version"],
        corpus_id=catalog["corpus_id"],
        content_version=catalog["content_version"],
        display_version=catalog["display_version"],
        language=catalog["language"],
        canonical_path=catalog["canonical_path"],
        updated_on=catalog["updated_on"],
        catalog_fingerprint=catalog["fingerprint"],
        sections=[
            ProductGuideSectionResponse(
                **section,
                href=f"/guide#{section['id']}",
            )
            for section in catalog["sections"]
        ],
    )


@router.get(
    "/search",
    response_model=ProductGuideSearchResponse,
    summary="Search approved help topics and capability-filtered navigation commands.",
)
async def search_product_guide_catalog(
    context: CurrentContext,
    session: DbSession,
    q: Annotated[str, Query(min_length=2, max_length=MAX_QUERY_CHARS)],
    limit: Annotated[int, Query(ge=1, le=MAX_RESULTS)] = 8,
    client_version: Annotated[str | None, Query(max_length=64)] = None,
) -> ProductGuideSearchResponse:
    capabilities = resolve_membership_capabilities(session, context.membership)
    return ProductGuideSearchResponse.model_validate(
        search_product_guide(
            q,
            capabilities=capabilities,
            limit=limit,
            client_version=client_version,
        )
    )
