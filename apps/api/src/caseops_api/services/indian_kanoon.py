"""Licensed Indian Kanoon adapter with fail-closed commercial controls."""

from __future__ import annotations

import copy
import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityResearchReport,
    AuthorityResearchReportSource,
    BillingSubscription,
    BillingUsageEvent,
    CompanyMembership,
    ProviderCostCategory,
)
from caseops_api.schemas.indian_kanoon import (
    AuthorityLegalSourceReviewResponse,
    IndianKanoonCallMetadata,
    IndianKanoonDocumentResponse,
    IndianKanoonHealthResponse,
    IndianKanoonImportResponse,
    IndianKanoonMetadataResponse,
    IndianKanoonReadinessResponse,
    IndianKanoonSearchResponse,
    IndianKanoonSearchResult,
    IndianKanoonSourceRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.paid_provider_safety import assert_paid_provider_call_allowed
from caseops_api.services.provider_costs import verified_actual_cost_minor
from caseops_api.services.saas_billing import record_usage
from caseops_api.services.session_context import SessionContext
from caseops_api.services.source_actions import inspect_source_action, inspect_source_target_action

PROVIDER_KEY = "indian-kanoon"
SOURCE_KEY = "indian_kanoon_licensed"
ADAPTER_NAME = "caseops-indian-kanoon-licensed-v1"
LICENSE_POLICY_VERSION = "ik-terms-reviewed-runtime-v1"
API_HOST = "api.indiankanoon.org"
PUBLIC_HOST = "indiankanoon.org"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_CACHE_ENTRIES = 128
STALE_CACHE_WINDOW_SECONDS = 24 * 60 * 60
REQUIRED_PERMITTED_USES = {"search", "document_display", "research_storage"}
COST_CATEGORIES = (
    ProviderCostCategory.LEGAL_SOURCE_SEARCH,
    ProviderCostCategory.LEGAL_SOURCE_DOCUMENT,
    ProviderCostCategory.LEGAL_SOURCE_ORIGINAL_DOCUMENT,
    ProviderCostCategory.LEGAL_SOURCE_FRAGMENT,
    ProviderCostCategory.LEGAL_SOURCE_METADATA,
)


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


@dataclass(slots=True)
class _CacheEntry:
    stored_at: datetime
    payload: dict[str, Any]


_cache: dict[str, _CacheEntry] = {}
_cache_lock = threading.Lock()


def clear_indian_kanoon_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _permitted_uses() -> list[str]:
    return sorted(
        {
            item.strip().lower()
            for item in get_settings().indian_kanoon_permitted_uses.split(",")
            if item.strip()
        }
    )


def indian_kanoon_readiness(session: Session | None = None) -> IndianKanoonReadinessResponse:
    settings = get_settings()
    now = _now()
    missing_config: list[str] = []
    invalid_terms: list[str] = []

    parsed_base = urlsplit(settings.indian_kanoon_api_base_url.rstrip("/"))
    if (
        parsed_base.scheme != "https"
        or parsed_base.hostname != API_HOST
        or parsed_base.username
        or parsed_base.password
        or parsed_base.port not in {None, 443}
        or parsed_base.path not in {"", "/"}
    ):
        missing_config.append("INDIAN_KANOON_API_BASE_URL")
    if not settings.indian_kanoon_api_token:
        missing_config.append("INDIAN_KANOON_API_TOKEN")
    if not settings.indian_kanoon_terms_owner:
        missing_config.append("INDIAN_KANOON_TERMS_OWNER")
    if settings.indian_kanoon_terms_approved_at is None:
        missing_config.append("INDIAN_KANOON_TERMS_APPROVED_AT")
    if settings.indian_kanoon_terms_expires_at is None:
        missing_config.append("INDIAN_KANOON_TERMS_EXPIRES_AT")
    permitted = _permitted_uses()
    if not REQUIRED_PERMITTED_USES.issubset(permitted):
        missing_config.append("INDIAN_KANOON_PERMITTED_USES")
    if settings.indian_kanoon_retention_days <= 0:
        missing_config.append("INDIAN_KANOON_RETENTION_DAYS")
    if settings.indian_kanoon_daily_budget_minor <= 0:
        missing_config.append("INDIAN_KANOON_DAILY_BUDGET_MINOR")
    if settings.indian_kanoon_monthly_budget_minor <= 0:
        missing_config.append("INDIAN_KANOON_MONTHLY_BUDGET_MINOR")

    terms_expires_at = _as_utc(settings.indian_kanoon_terms_expires_at)
    terms_approved_at = _as_utc(settings.indian_kanoon_terms_approved_at)
    if terms_expires_at is not None and terms_expires_at <= now:
        invalid_terms.append("INDIAN_KANOON_TERMS_EXPIRES_AT")
    if terms_approved_at is not None and terms_approved_at > now:
        invalid_terms.append("INDIAN_KANOON_TERMS_APPROVED_AT")

    missing_costs: list[str] = []
    if session is None:
        missing_costs = [str(category) for category in COST_CATEGORIES]
    else:
        missing_costs = [
            str(category)
            for category in COST_CATEGORIES
            if verified_actual_cost_minor(session, category=category, provider=PROVIDER_KEY) is None
        ]

    if not settings.indian_kanoon_enabled:
        state = "blocked_disabled"
    elif missing_config:
        state = "blocked_missing_config"
    elif invalid_terms:
        state = "blocked_terms"
    elif missing_costs:
        state = "blocked_costs"
    else:
        state = "ready"
    enabled = state == "ready"
    return IndianKanoonReadinessResponse(
        state=state,
        configured=not missing_config,
        enabled=enabled,
        external_calls_enabled=enabled,
        missing_config_names=sorted(set(missing_config)),
        invalid_terms_config=sorted(set(invalid_terms)),
        missing_approval_keys=[],
        missing_cost_categories=sorted(missing_costs),
        permitted_uses=permitted,
        daily_budget_minor=settings.indian_kanoon_daily_budget_minor,
        monthly_budget_minor=settings.indian_kanoon_monthly_budget_minor,
        retention_days=settings.indian_kanoon_retention_days,
        terms_owner=settings.indian_kanoon_terms_owner,
        terms_approved_at=terms_approved_at,
        terms_expires_at=terms_expires_at,
        limitations=[
            "Only the contracted API host is callable; public-page scraping is disabled.",
            "Provider results require exact-source and subsequent-treatment verification.",
            "The runtime kill switch disables every external call immediately.",
        ],
    )


def indian_kanoon_health(session: Session) -> IndianKanoonHealthResponse:
    readiness = indian_kanoon_readiness(session)
    return IndianKanoonHealthResponse(
        readiness=readiness,
        health="ready" if readiness.external_calls_enabled else "blocked",
        checked_at=_now(),
    )


def _problem(
    *,
    http_status: int,
    code: str,
    message: str,
    retryable: bool = False,
    stale_cache_available: bool = False,
) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={
            "code": code,
            "message": message,
            "provider": PROVIDER_KEY,
            "retryable": retryable,
            "stale_cache_available": stale_cache_available,
        },
    )


def _assert_ready(session: Session) -> None:
    readiness = indian_kanoon_readiness(session)
    if readiness.state == "ready":
        return
    code = {
        "blocked_disabled": "provider_disabled",
        "blocked_missing_config": "provider_configuration",
        "blocked_terms": "provider_terms",
        "blocked_costs": "provider_cost_policy",
        "blocked_budget": "provider_budget_exhausted",
    }[readiness.state]
    raise _problem(
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        code=code,
        message=(
            "Indian Kanoon licensed access is not active. Review the provider "
            "readiness record; no external request was made."
        ),
    )


def _validate_document_id(document_id: str) -> str:
    value = document_id.strip()
    if not re.fullmatch(r"[0-9]{1,20}", value):
        raise _problem(
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="unsupported_operation",
            message="Indian Kanoon document IDs must contain digits only.",
        )
    return value


def _cache_key(path: str, params: dict[str, Any]) -> str:
    pairs = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha256(f"{path}?{pairs}".encode()).hexdigest()


def _get_cache(key: str) -> tuple[dict[str, Any], int] | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        age = max(0, int((_now() - entry.stored_at).total_seconds()))
        return copy.deepcopy(entry.payload), age


def _set_cache(key: str, payload: dict[str, Any]) -> None:
    with _cache_lock:
        if len(_cache) >= MAX_CACHE_ENTRIES:
            oldest = min(_cache, key=lambda item: _cache[item].stored_at)
            _cache.pop(oldest, None)
        _cache[key] = _CacheEntry(stored_at=_now(), payload=copy.deepcopy(payload))


def _period_cost(session: Session, *, company_id: str, start: datetime) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(BillingUsageEvent.estimated_cost_minor), 0)).where(
                BillingUsageEvent.company_id == company_id,
                BillingUsageEvent.usage_type.like("indian_kanoon_%"),
                BillingUsageEvent.created_at >= start,
            )
        )
        or 0
    )


def _assert_budget(
    session: Session,
    *,
    context: SessionContext,
    call_cost_minor: int,
) -> None:
    settings = get_settings()
    now = _now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    daily = _period_cost(session, company_id=context.company.id, start=day_start)
    monthly = _period_cost(session, company_id=context.company.id, start=month_start)
    if (
        daily + call_cost_minor > settings.indian_kanoon_daily_budget_minor
        or monthly + call_cost_minor > settings.indian_kanoon_monthly_budget_minor
    ):
        raise _problem(
            http_status=status.HTTP_429_TOO_MANY_REQUESTS,
            code="provider_budget_exhausted",
            message="The workspace Indian Kanoon cost budget is exhausted.",
        )


def _record_provider_usage(
    session: Session,
    *,
    context: SessionContext,
    category: str,
    cost_minor: int,
    source_id: str,
) -> None:
    subscription_id = session.scalar(
        select(BillingSubscription.id)
        .where(BillingSubscription.company_id == context.company.id)
        .order_by(BillingSubscription.created_at.desc())
        .limit(1)
    )
    record_usage(
        session,
        company_id=context.company.id,
        subscription_id=subscription_id,
        usage_type=f"indian_kanoon_{category}",
        feature_key="licensed_legal_research",
        quantity=1,
        unit="provider_call",
        actor_membership_id=context.membership.id,
        estimated_cost_minor=cost_minor,
        purpose="licensed_legal_source_access",
        display_label="Indian Kanoon licensed legal research",
        source_type="indian_kanoon_document" if source_id.isdigit() else "indian_kanoon_search",
        source_id=source_id[:120],
        metadata={"provider": PROVIDER_KEY, "cost_category": category},
    )


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
        raise _problem(
            http_status=status.HTTP_502_BAD_GATEWAY,
            code="provider_contract_changed",
            message="Provider response exceeded the licensed adapter size boundary.",
        )
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise _problem(
            http_status=status.HTTP_502_BAD_GATEWAY,
            code="provider_contract_changed",
            message="Provider response exceeded the licensed adapter size boundary.",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise _problem(
            http_status=status.HTTP_502_BAD_GATEWAY,
            code="provider_contract_changed",
            message="Provider returned a response outside the documented JSON contract.",
        ) from exc
    if not isinstance(payload, dict):
        raise _problem(
            http_status=status.HTTP_502_BAD_GATEWAY,
            code="provider_contract_changed",
            message="Provider returned an unsupported JSON root.",
        )
    return payload


def _call_provider(
    session: Session,
    *,
    context: SessionContext,
    path: str,
    params: dict[str, Any],
    category: str,
    source_id: str,
    client: httpx.Client | None = None,
) -> tuple[dict[str, Any], IndianKanoonCallMetadata]:
    _assert_ready(session)
    settings = get_settings()
    unit_cost = verified_actual_cost_minor(session, category=category, provider=PROVIDER_KEY)
    if unit_cost is None:
        raise _problem(
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="provider_cost_policy",
            message="The provider cost category is not approved for external calls.",
        )
    key = _cache_key(path, params)
    cached = _get_cache(key)
    if cached and cached[1] <= settings.indian_kanoon_cache_ttl_seconds:
        return cached[0], IndianKanoonCallMetadata(
            cached=True,
            stale=False,
            retrieved_at=_now() - timedelta(seconds=cached[1]),
            estimated_cost_minor=0,
            cost_category=category,
            cost_basis="fresh_cache",
        )
    assert_paid_provider_call_allowed(
        context=context,
        provider=PROVIDER_KEY,
        base_url=settings.indian_kanoon_api_base_url,
        transport_is_mocked=client is not None,
    )
    _assert_budget(session, context=context, call_cost_minor=unit_cost)

    own_client = client is None
    if own_client:
        client = httpx.Client(
            timeout=settings.indian_kanoon_request_timeout_seconds,
            follow_redirects=False,
        )
    assert client is not None
    url = f"{settings.indian_kanoon_api_base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        try:
            response = client.post(
                url,
                params=params,
                headers={
                    "Authorization": f"Token {settings.indian_kanoon_api_token}",
                    "Accept": "application/json",
                    "User-Agent": "CaseOps/1.0 licensed-legal-research",
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if cached and cached[1] <= STALE_CACHE_WINDOW_SECONDS:
                return cached[0], IndianKanoonCallMetadata(
                    cached=True,
                    stale=True,
                    freshness_warning=(
                        "Indian Kanoon is unavailable; showing a stale cached response. "
                        "Verify freshness before reliance."
                    ),
                    retrieved_at=_now() - timedelta(seconds=cached[1]),
                    estimated_cost_minor=0,
                    cost_category=category,
                    cost_basis="stale_cache",
                )
            raise _problem(
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="provider_outage",
                message="Indian Kanoon did not respond within the interactive deadline.",
                retryable=True,
            ) from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            raise _problem(
                http_status=status.HTTP_502_BAD_GATEWAY,
                code="provider_contract_changed",
                message="Provider redirected outside the pinned API contract.",
            )
        if response.status_code in {401, 403}:
            raise _problem(
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="provider_authentication",
                message="Indian Kanoon rejected the configured server credential.",
            )
        if response.status_code in {402, 429}:
            raise _problem(
                http_status=status.HTTP_429_TOO_MANY_REQUESTS,
                code="provider_quota",
                message="Indian Kanoon quota or prepaid balance is unavailable.",
                retryable=response.status_code == 429,
            )
        if response.status_code in {404, 410}:
            raise _problem(
                http_status=status.HTTP_410_GONE,
                code="source_removed",
                message="The requested provider source is unavailable or removed.",
            )
        if response.status_code >= 500:
            if cached and cached[1] <= STALE_CACHE_WINDOW_SECONDS:
                return cached[0], IndianKanoonCallMetadata(
                    cached=True,
                    stale=True,
                    freshness_warning=(
                        "Indian Kanoon is unavailable; showing a stale cached response. "
                        "Verify freshness before reliance."
                    ),
                    retrieved_at=_now() - timedelta(seconds=cached[1]),
                    estimated_cost_minor=0,
                    cost_category=category,
                    cost_basis="stale_cache",
                )
            raise _problem(
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="provider_outage",
                message="Indian Kanoon is temporarily unavailable.",
                retryable=True,
            )
        if response.status_code >= 400:
            raise _problem(
                http_status=status.HTTP_502_BAD_GATEWAY,
                code="provider_contract_changed",
                message="Provider rejected a request that passed the adapter contract.",
            )
        payload = _response_payload(response)
        _set_cache(key, payload)
        _record_provider_usage(
            session,
            context=context,
            category=category,
            cost_minor=unit_cost,
            source_id=source_id,
        )
        return payload, IndianKanoonCallMetadata(
            cached=False,
            stale=False,
            retrieved_at=_now(),
            estimated_cost_minor=unit_cost,
            cost_category=category,
            cost_basis="verified_actual",
        )
    finally:
        if own_client:
            client.close()


def _plain_text(value: object, *, limit: int) -> str:
    if value is None:
        return ""
    parser = _PlainTextParser()
    parser.feed(str(value))
    text = " ".join(parser.parts) if parser.parts else str(value)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def _parse_date(value: object) -> date | None:
    text = _plain_text(value, limit=80)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _source_category(value: str) -> str:
    lowered = value.lower()
    if "supreme" in lowered:
        return "supreme_court"
    if "high court" in lowered:
        return "high_court"
    if any(word in lowered for word in ("tribunal", "commission", "board")):
        return "tribunal"
    if any(word in lowered for word in ("act", "statute", "code", "constitution")):
        return "statutory_bare_act"
    return "other_court_or_legal_source"


def _document_type(value: str) -> str:
    lowered = value.lower()
    if "order" in lowered:
        return "order"
    if any(word in lowered for word in ("act", "statute", "code", "constitution")):
        return "statute"
    if any(word in lowered for word in ("rule", "regulation", "notification")):
        return "regulation"
    return "judgment"


def _canonical_url(document_id: str) -> str:
    return f"https://{PUBLIC_HOST}/doc/{_validate_document_id(document_id)}/"


def _source_record(payload: dict[str, Any], *, fallback_id: str) -> IndianKanoonSourceRecord:
    document_id = _validate_document_id(
        str(_first(payload, "tid", "docid", "doc_id", "id") or fallback_id)
    )
    publisher = (
        _plain_text(_first(payload, "publisher", "docsource", "court", "source"), limit=255)
        or "Indian Kanoon licensed source"
    )
    title = _plain_text(_first(payload, "title", "name"), limit=255) or f"Document {document_id}"
    source_category = _source_category(publisher)
    return IndianKanoonSourceRecord(
        document_id=document_id,
        title=title,
        publisher=publisher,
        issuing_body=_plain_text(_first(payload, "court", "docsource"), limit=255) or None,
        source_category=source_category,
        document_type=_document_type(f"{publisher} {title}"),
        decision_or_publication_date=_parse_date(
            _first(payload, "publishdate", "publish_date", "date", "decision_date")
        ),
        canonical_citation=_plain_text(
            _first(payload, "citation", "citation_text", "neutral_citation"), limit=255
        )
        or None,
        authority_status=(
            "statutory_text_requires_effective_date_verification"
            if source_category == "statutory_bare_act"
            else "provider_record_unreviewed"
        ),
        binding_status="verify_jurisdiction_and_precedential_status",
        canonical_url=_canonical_url(document_id),
        source_action=inspect_source_action(_canonical_url(document_id), verified=True),
    )


def _safe_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(secret in lowered for secret in ("token", "authorization", "password", "secret")):
            continue
        if lowered in {"doc", "document", "content", "body", "text"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key[:80]] = value[:2000] if isinstance(value, str) else value
        elif isinstance(value, list):
            safe[key[:80]] = [
                item[:2000] if isinstance(item, str) else item
                for item in value[:50]
                if isinstance(item, (str, int, float, bool)) or item is None
            ]
    return safe


def search_indian_kanoon(
    session: Session,
    *,
    context: SessionContext,
    query: str,
    page_number: int,
    max_results: int,
    client: httpx.Client | None = None,
) -> IndianKanoonSearchResponse:
    settings = get_settings()
    if page_number > settings.indian_kanoon_max_search_page:
        raise _problem(
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="unsupported_operation",
            message="Search page exceeds the configured licensed-provider boundary.",
        )
    bounded_results = min(max_results, settings.indian_kanoon_max_results)
    payload, call = _call_provider(
        session,
        context=context,
        path="search/",
        params={"formInput": query, "pagenum": page_number},
        category=ProviderCostCategory.LEGAL_SOURCE_SEARCH,
        source_id=hashlib.sha256(query.lower().encode()).hexdigest(),
        client=client,
    )
    raw_results = _first(payload, "docs", "results", "documents") or []
    if not isinstance(raw_results, list):
        raise _problem(
            http_status=status.HTTP_502_BAD_GATEWAY,
            code="provider_contract_changed",
            message="Provider search results changed shape.",
        )
    results: list[IndianKanoonSearchResult] = []
    for raw in raw_results[:bounded_results]:
        if not isinstance(raw, dict):
            continue
        source = _source_record(raw, fallback_id=str(_first(raw, "tid", "id") or ""))
        results.append(
            IndianKanoonSearchResult(
                **source.model_dump(),
                rank=len(results) + 1,
                headline=_plain_text(_first(raw, "headline", "fragment", "snippet"), limit=2000)
                or None,
            )
        )
    session.commit()
    return IndianKanoonSearchResponse(
        query=query,
        page_number=page_number,
        returned_count=len(results),
        results=results,
        call=call,
    )


def fetch_indian_kanoon_document(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    variant: Literal["processed", "original", "fragment"] = "processed",
    fragment_query: str | None = None,
    client: httpx.Client | None = None,
) -> IndianKanoonDocumentResponse:
    document_id = _validate_document_id(document_id)
    if variant == "fragment" and not fragment_query:
        raise _problem(
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="unsupported_operation",
            message="A fragment query is required.",
        )
    path = {
        "processed": f"doc/{document_id}/",
        "original": f"origdoc/{document_id}/",
        "fragment": f"docfragment/{document_id}/",
    }[variant]
    category = {
        "processed": ProviderCostCategory.LEGAL_SOURCE_DOCUMENT,
        "original": ProviderCostCategory.LEGAL_SOURCE_ORIGINAL_DOCUMENT,
        "fragment": ProviderCostCategory.LEGAL_SOURCE_FRAGMENT,
    }[variant]
    params = {"formInput": fragment_query} if fragment_query else {}
    payload, call = _call_provider(
        session,
        context=context,
        path=path,
        params=params,
        category=category,
        source_id=document_id,
        client=client,
    )
    raw_content = _first(payload, "doc", "document", "content", "body", "text")
    content = _plain_text(raw_content, limit=2_000_000)
    if not content:
        raise _problem(
            http_status=status.HTTP_502_BAD_GATEWAY,
            code="provider_contract_changed",
            message="Provider document response did not contain readable content.",
        )
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    source = _source_record(payload, fallback_id=document_id)
    session.commit()
    return IndianKanoonDocumentResponse(
        **source.model_dump(),
        content=content,
        content_hash=content_hash,
        source_version=f"ik:{document_id}:{content_hash[:16]}",
        exact_passage_query=fragment_query,
        call=call,
        provider_metadata=_safe_metadata(payload),
    )


def fetch_indian_kanoon_metadata(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    client: httpx.Client | None = None,
) -> IndianKanoonMetadataResponse:
    document_id = _validate_document_id(document_id)
    payload, call = _call_provider(
        session,
        context=context,
        path=f"docmeta/{document_id}/",
        params={},
        category=ProviderCostCategory.LEGAL_SOURCE_METADATA,
        source_id=document_id,
        client=client,
    )
    source = _source_record(payload, fallback_id=document_id)
    provider_metadata = _safe_metadata(payload)
    provider_hash = _plain_text(_first(payload, "content_hash", "hash"), limit=128) or None
    session.commit()
    return IndianKanoonMetadataResponse(
        **source.model_dump(),
        provider_metadata=provider_metadata,
        content_hash=provider_hash,
        source_version=_plain_text(_first(payload, "version", "updated_at"), limit=120) or None,
        call=call,
    )


def import_indian_kanoon_document(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    expected_content_hash: str | None,
    client: httpx.Client | None = None,
) -> IndianKanoonImportResponse:
    document = fetch_indian_kanoon_document(
        session,
        context=context,
        document_id=document_id,
        client=client,
    )
    if expected_content_hash and expected_content_hash != document.content_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "source_version_conflict",
                "message": "Provider content changed after review. Fetch and review it again.",
            },
        )
    canonical_key = f"{SOURCE_KEY}:{document.document_id}"
    row = session.scalar(
        select(AuthorityDocument).where(AuthorityDocument.canonical_key == canonical_key)
    )
    created = row is None
    if row is None:
        row = AuthorityDocument(canonical_key=canonical_key)
        session.add(row)
    previous_hash = row.content_hash
    changed = bool(previous_hash and previous_hash != document.content_hash)
    invalidated_count = 0
    if changed:
        report_ids = list(
            session.scalars(
                select(AuthorityResearchReportSource.report_id).where(
                    AuthorityResearchReportSource.authority_document_id == row.id,
                    AuthorityResearchReportSource.content_hash == previous_hash,
                )
            )
        )
        if report_ids:
            reports = list(
                session.scalars(
                    select(AuthorityResearchReport).where(
                        AuthorityResearchReport.id.in_(report_ids),
                        AuthorityResearchReport.invalidated_at.is_(None),
                    )
                )
            )
            for report in reports:
                report.invalidated_at = _now()
                report.invalidation_reason = (
                    f"Licensed source {document.document_id} changed from "
                    f"{previous_hash} to {document.content_hash}."
                )
            invalidated_count = len(reports)

    row.source = SOURCE_KEY
    row.adapter_name = ADAPTER_NAME
    row.provider_document_id = document.document_id
    row.publisher_name = document.publisher
    row.jurisdiction = document.jurisdiction
    row.issuing_body = document.issuing_body
    row.source_category = document.source_category
    row.authority_status = document.authority_status
    row.binding_status = document.binding_status
    row.court_name = document.issuing_body or document.publisher
    row.forum_level = (
        "supreme_court"
        if document.source_category == "supreme_court"
        else "high_court"
        if document.source_category == "high_court"
        else "tribunal"
        if document.source_category == "tribunal"
        else "lower_court"
    )
    row.document_type = document.document_type
    row.title = document.title
    row.case_reference = None
    row.bench_name = None
    row.neutral_citation = document.canonical_citation
    row.decision_date = document.decision_or_publication_date
    row.source_reference = document.canonical_url
    row.canonical_url = document.canonical_url
    row.summary = document.content[:500]
    row.document_text = document.content
    row.extracted_char_count = len(document.content)
    row.content_hash = document.content_hash
    row.source_version = document.source_version
    row.retrieved_at = document.call.retrieved_at
    row.source_access_state = "available"
    row.attribution_json = document.attribution.model_dump(mode="json")
    row.license_policy_version = LICENSE_POLICY_VERSION
    row.source_metadata_json = document.provider_metadata
    row.ingested_at = _now()
    if created or changed:
        row.legal_review_status = "unreviewed"
        row.first_reviewed_by_membership_id = None
        row.first_reviewed_at = None
        row.second_reviewed_by_membership_id = None
        row.second_reviewed_at = None
        row.legal_review_note = None

    from caseops_api.db.models import AuthorityDocumentChunk
    from caseops_api.services.authorities import (
        _chunk_text,
        _invalidate_corpus_metrics_cache,
        _rebuild_authority_citations,
    )

    if not created:
        row.chunks.clear()
        session.flush()
    row.chunks = [
        AuthorityDocumentChunk(
            chunk_index=index,
            content=chunk,
            token_count=len(chunk.split()),
        )
        for index, chunk in enumerate(_chunk_text(document.content))
    ]
    session.flush()
    _rebuild_authority_citations(session, documents=[row])
    record_from_context(
        session,
        context,
        action="authority.licensed_source_imported",
        target_type="authority_document",
        target_id=row.id,
        metadata={
            "provider": PROVIDER_KEY,
            "provider_document_id": document.document_id,
            "content_hash": document.content_hash,
            "created": created,
            "changed": changed,
            "invalidated_report_count": invalidated_count,
        },
    )
    session.commit()
    session.refresh(row)
    _invalidate_corpus_metrics_cache()
    return IndianKanoonImportResponse(
        authority_document_id=row.id,
        document_id=document.document_id,
        created=created,
        changed=changed,
        invalidated_report_count=invalidated_count,
        content_hash=document.content_hash,
        source_version=document.source_version,
        legal_review_status=row.legal_review_status,
        source_action=inspect_source_target_action(
            row.source_reference,
            target_type="authority_document",
            target_id=row.id,
            verified=True,
        ),
    )


def review_licensed_authority_source(
    session: Session,
    *,
    context: SessionContext,
    authority_document_id: str,
    decision: Literal["approve", "reject"],
    expected_content_hash: str,
    note: str,
) -> AuthorityLegalSourceReviewResponse:
    row = session.get(AuthorityDocument, authority_document_id)
    if row is None or row.source != SOURCE_KEY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Licensed source not found.",
        )
    if not row.content_hash or row.content_hash != expected_content_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source content changed. Review the current version before deciding.",
        )
    now = _now()
    if decision == "reject":
        row.legal_review_status = "rejected"
        row.legal_review_note = note
    elif row.legal_review_status in {"unreviewed", "rejected"}:
        row.legal_review_status = "first_reviewed"
        row.first_reviewed_by_membership_id = context.membership.id
        row.first_reviewed_at = now
        row.second_reviewed_by_membership_id = None
        row.second_reviewed_at = None
        row.legal_review_note = note
    elif row.legal_review_status == "first_reviewed":
        if row.first_reviewed_by_membership_id == context.membership.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A different reviewer must complete the second legal-source review.",
            )
        first_membership = session.get(CompanyMembership, row.first_reviewed_by_membership_id)
        if first_membership is None or first_membership.company_id != context.company.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Both legal-source reviewers must belong to the same workspace.",
            )
        row.legal_review_status = "verified"
        row.second_reviewed_by_membership_id = context.membership.id
        row.second_reviewed_at = now
        row.legal_review_note = note
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This exact source version is already verified.",
        )
    record_from_context(
        session,
        context,
        action="authority.licensed_source_reviewed",
        target_type="authority_document",
        target_id=row.id,
        metadata={
            "decision": decision,
            "legal_review_status": row.legal_review_status,
            "content_hash": row.content_hash,
        },
    )
    session.commit()
    session.refresh(row)
    return AuthorityLegalSourceReviewResponse(
        authority_document_id=row.id,
        legal_review_status=row.legal_review_status,
        first_reviewed_by_membership_id=row.first_reviewed_by_membership_id,
        first_reviewed_at=row.first_reviewed_at,
        second_reviewed_by_membership_id=row.second_reviewed_by_membership_id,
        second_reviewed_at=row.second_reviewed_at,
        content_hash=row.content_hash,
        note=row.legal_review_note or note,
    )
