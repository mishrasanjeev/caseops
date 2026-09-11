from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from caseops_api.core.settings import get_settings
from caseops_api.services.hearing_matching import (
    MAX_MATCH_CANDIDATES,
    HearingIdentity,
    provider_identity,
    search_number,
)
from caseops_api.services.http_retries import RETRYABLE_READ_STATUS_CODES

PROVIDER_REQUEST_BUDGET_SECONDS = 30.0
PROVIDER_BULK_BUDGET_SECONDS = 120.0
_MAX_PROVIDER_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_PROVIDER_SOURCE_BYTES = 32 * 1024 * 1024
_PROVIDER_PENDING_MESSAGE = (
    "Provider refresh is queued; automatic status recovery is scheduled. [provider_pending]"
)
_TRANSPORT_DEADLINE: ContextVar[float | None] = ContextVar("case_tracking_deadline", default=None)


@contextmanager
def case_tracking_transport_budget(seconds: float = PROVIDER_BULK_BUDGET_SECONDS) -> Iterator[None]:
    current = _TRANSPORT_DEADLINE.get()
    deadline = time.monotonic() + seconds
    token = _TRANSPORT_DEADLINE.set(min(current, deadline) if current is not None else deadline)
    try:
        yield
    finally:
        _TRANSPORT_DEADLINE.reset(token)


def _remaining_transport_budget(maximum: float) -> float:
    deadline = _TRANSPORT_DEADLINE.get()
    remaining = min(maximum, deadline - time.monotonic()) if deadline is not None else maximum
    if remaining <= 0:
        raise CaseTrackingProviderError(
            "Case tracking provider total deadline exceeded.", response_class="timeout"
        )
    return remaining


class CaseTrackingProviderUnavailable(RuntimeError):
    pass


def download_provider_source(
    *,
    url: str,
    token: str,
    transport: httpx.AsyncBaseTransport | None = None,
    budget_seconds: float = PROVIDER_REQUEST_BUDGET_SECONDS,
) -> httpx.Response:
    if not 0 < budget_seconds <= PROVIDER_REQUEST_BUDGET_SECONDS:
        raise ValueError("The source deadline must fit the provider request budget.")

    async def download() -> httpx.Response:
        try:
            async with (
                asyncio.timeout(_remaining_transport_budget(budget_seconds)),
                httpx.AsyncClient(
                    timeout=budget_seconds, follow_redirects=False, transport=transport
                ) as client,
                client.stream(
                    "GET",
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/pdf,application/octet-stream,*/*",
                    },
                ) as response,
            ):
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > _MAX_PROVIDER_SOURCE_BYTES:
                        raise httpx.DecodingError("Provider source exceeds the supported size.")
                    content.extend(chunk)
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=bytes(content),
                    request=response.request,
                )
        except TimeoutError as exc:
            raise httpx.ReadTimeout("Provider source total deadline exceeded.") from exc

    return asyncio.run(download())


class CaseTrackingProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        response_class: str = "provider_error",
        http_status_code: int | None = None,
        confirmed_cost_minor: int | None = None,
        uncertain_charge: bool = False,
    ) -> None:
        super().__init__(message)
        self.response_class = response_class
        self.http_status_code = http_status_code
        self.confirmed_cost_minor = confirmed_cost_minor
        self.uncertain_charge = uncertain_charge


def _http_error_response_class(exc: httpx.HTTPError) -> str:
    if isinstance(exc, (httpx.TimeoutException, httpx.PoolTimeout)):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in {401, 403}:
            return "authentication"
        if exc.response.status_code == 402:
            return "billing"
        if exc.response.status_code == 404:
            return "case_not_found"
        if exc.response.status_code == 429:
            return "rate_limit"
    return "provider_error"


def _provider_http_error(message: str, exc: httpx.HTTPError) -> CaseTrackingProviderError:
    return CaseTrackingProviderError(
        message,
        response_class=_http_error_response_class(exc),
        http_status_code=(
            exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        ),
    )


@dataclass(frozen=True)
class CaseSearchQuery:
    query: str | None = None
    cnr_number: str | None = None
    case_number: str | None = None
    court_code: str | None = None
    state: str | None = None
    court_name: str | None = None
    require_complete_results: bool = False


@dataclass(frozen=True)
class ProviderCaseEvent:
    source_record_key: str
    title: str
    event_date: date | None = None
    source_url: str | None = None
    text: str | None = None
    text_truncated: bool = False
    provider_summary: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCaseSnapshot:
    provider: str
    cnr_number: str | None
    case_number: str | None
    court_code: str | None
    court_name: str | None
    case_title: str
    party_names: list[str] = field(default_factory=list)
    current_status: str | None = None
    current_stage: str | None = None
    next_hearing_on: date | None = None
    orders: list[ProviderCaseEvent] = field(default_factory=list)
    judgments: list[ProviderCaseEvent] = field(default_factory=list)
    hearings: list[ProviderCaseEvent] = field(default_factory=list)
    source_url: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    matching_identity: HearingIdentity | None = None


@dataclass(frozen=True)
class ProviderBulkRefreshResult:
    snapshots: list[ProviderCaseSnapshot]
    errors: dict[str, str] = field(default_factory=dict)
    provider_call_count: int = 1
    confirmed_cost_minor_by_cnr: dict[str, int] = field(default_factory=dict)
    uncertain_charge_cnrs: set[str] = field(default_factory=set)


class CaseTrackingProvider(Protocol):
    provider_key: str

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        raise NotImplementedError

    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot:
        raise NotImplementedError

    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        raise NotImplementedError


def _compact(value: object, *, limit: int = 500) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] if text else None


_SOURCE_TEXT_MAX_CHARS = 512 * 1024


def _source_text(value: object) -> tuple[str | None, bool]:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "").strip()
    if not text:
        return None, False
    if len(text) <= _SOURCE_TEXT_MAX_CHARS:
        return text, False
    return text[:_SOURCE_TEXT_MAX_CHARS].rstrip(), True


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _stable_key(prefix: str, payload: object) -> str:
    blob = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


def _events(raw: object, *, prefix: str) -> list[ProviderCaseEvent]:
    if not isinstance(raw, list):
        return []
    events: list[ProviderCaseEvent] = []
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        title = _compact(
            item.get("title")
            or item.get("order_title")
            or item.get("judgment_title")
            or item.get("description")
            or "Case update",
            limit=500,
        )
        if not title:
            continue
        source_text, source_text_truncated = _source_text(
            item.get("text") or item.get("order_text")
        )
        source_key = _compact(
            item.get("id") or item.get("source_record_key") or item.get("pdf_url"),
            limit=160,
        ) or _stable_key(prefix, item)
        events.append(
            ProviderCaseEvent(
                source_record_key=f"{prefix}:{source_key}",
                title=title,
                event_date=_parse_date(
                    (item.get("hearingDate") if prefix == "hearing" else None)
                    or item.get("date")
                    or item.get("order_date")
                    or item.get("judgment_date")
                ),
                source_url=_compact(item.get("source_url") or item.get("pdf_url"), limit=800),
                text=source_text,
                text_truncated=source_text_truncated,
                provider_summary=_compact(
                    item.get("summary") or item.get("ai_summary"),
                    limit=2000,
                ),
                metadata={
                    key: str(value)[:500]
                    for key, value in item.items()
                    if key
                    not in {
                        "text",
                        "order_text",
                        "raw_payload",
                        "summary",
                        "ai_summary",
                    }
                },
            )
        )
    return events


def _data_payload(payload: object) -> object:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _json_payload(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise CaseTrackingProviderError(
            "Case tracking provider returned invalid JSON.", response_class="parse_error"
        ) from exc


def _first_dict(*values: object) -> dict[str, object] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _first_list(*values: object) -> list[object]:
    for value in values:
        if isinstance(value, list):
            return value
    return []


def _string_list(value: object, *, limit: int = 20) -> list[str]:
    if isinstance(value, list):
        return [compacted for item in value[:limit] if (compacted := _compact(item, limit=160))]
    if text := _compact(value, limit=160):
        return [text]
    return []


def _display_title(payload: dict[str, object]) -> str:
    title = _compact(payload.get("case_title") or payload.get("title"), limit=500)
    if title:
        return title
    petitioners = _string_list(payload.get("petitioners"))
    respondents = _string_list(payload.get("respondents"))
    if petitioners and respondents:
        return f"{petitioners[0]} v {respondents[0]}"
    if petitioners:
        return petitioners[0]
    if respondents:
        return respondents[0]
    return "Tracked case"


def _court_name(
    payload: dict[str, object],
    descriptions: dict[str, object] | None,
    *,
    court_code_override: str | None = None,
) -> str | None:
    court_name = _compact(payload.get("court_name") or payload.get("courtName"), limit=255)
    if court_name:
        return court_name
    raw_court_code = _compact(
        payload.get("court_code") or payload.get("courtCode") or payload.get("cnrCourtCode"),
        limit=80,
    )
    enum_lookup = descriptions.get("enumLookup") if descriptions else None
    if isinstance(enum_lookup, dict):
        court_lookup = enum_lookup.get("courtCode")
        if isinstance(court_lookup, dict):
            # Historical case detail may key descriptions by the short raw
            # value even when CaseOps derives the search-ready code from CNR.
            for court_code in dict.fromkeys((court_code_override, raw_court_code)):
                if court_code in court_lookup:
                    return _compact(court_lookup[court_code], limit=255)
    return None


def _case_status(payload: dict[str, object], descriptions: dict[str, object] | None) -> str | None:
    raw = _compact(payload.get("current_status") or payload.get("caseStatus"), limit=160)
    enum_lookup = descriptions.get("enumLookup") if descriptions else None
    if isinstance(enum_lookup, dict):
        status_lookup = enum_lookup.get("caseStatus")
        if isinstance(status_lookup, dict) and raw in status_lookup:
            return _compact(status_lookup[raw], limit=160)
    return raw


def _case_order_events(
    raw: object,
    *,
    prefix: str,
    cnr: str | None,
    order_download_base_url: str | None = None,
    embedded_files: object = None,
) -> list[ProviderCaseEvent]:
    file_rows = _embedded_order_files(embedded_files)
    if not isinstance(raw, list):
        return []
    events: list[ProviderCaseEvent] = []
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        order_url = _compact(item.get("orderUrl") or item.get("pdfFile"), limit=800)
        title = _compact(
            item.get("description") or item.get("orderType") or item.get("title") or "Case order",
            limit=500,
        )
        if not title:
            continue
        event_date = _parse_date(item.get("orderDate") or item.get("date"))
        embedded_file = _matching_embedded_order_file(
            file_rows,
            cnr=cnr,
            order_url=order_url,
        )
        source_text, source_text_truncated = _source_text(
            item.get("markdownContent")
            or item.get("text")
            or (embedded_file or {}).get("markdownContent")
        )
        source_key = order_url or _stable_key(prefix, item)
        source_url = None
        if cnr and order_url:
            if re.match(r"^https?://", order_url, flags=re.IGNORECASE):
                source_url = order_url
            elif order_download_base_url:
                source_url = (
                    f"{order_download_base_url.rstrip('/')}/case/{quote(cnr)}/order/"
                    f"{quote(order_url, safe='')}"
                )
            else:
                source_url = f"/api/partner/case/{quote(cnr)}/order/{quote(order_url, safe='')}"
        events.append(
            ProviderCaseEvent(
                source_record_key=f"{prefix}:{source_key}",
                title=(
                    f"{title} dated {event_date.isoformat()}"
                    if event_date and "dated" not in title.lower()
                    else title
                ),
                event_date=event_date,
                source_url=source_url,
                text=source_text,
                text_truncated=source_text_truncated,
                provider_summary=_compact(item.get("summary") or item.get("aiSummary"), limit=2000),
                metadata={
                    key: str(value)[:500]
                    for key, value in item.items()
                    if key not in {"markdownContent", "text", "summary", "aiSummary"}
                },
            )
        )
    return events


def _embedded_order_files(raw: object) -> list[dict[str, object]]:
    if isinstance(raw, dict):
        raw = raw.get("files")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)][:100]


def _matching_embedded_order_file(
    files: list[dict[str, object]],
    *,
    cnr: str | None,
    order_url: str | None,
) -> dict[str, object] | None:
    """Match one order URL to the CNR-prefixed case-detail file row."""

    if not order_url:
        return None
    short_name = order_url.rsplit("/", 1)[-1].strip().lower()
    if not short_name:
        return None
    accepted = {short_name}
    if cnr:
        accepted.add(f"{cnr.strip().lower()}-{short_name}")
    matches = []
    for item in files:
        pdf_name = str(item.get("pdfFile") or "").rsplit("/", 1)[-1].strip().lower()
        if pdf_name in accepted:
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _case_number_from_payload(case: dict[str, object]) -> str | None:
    """Keep readable provider case numbers while handling packed detail IDs."""

    explicit = _compact(case.get("case_number"), limit=120)
    if explicit:
        return explicit
    case_number = _compact(case.get("caseNumber"), limit=120)
    registration = _compact(
        case.get("registrationNumber") or case.get("filingNumber"), limit=120
    )
    # Some historical detail payloads expose a packed numeric identifier in
    # caseNumber and the user-facing registration number separately.
    if case_number and (not case_number.isdigit() or not registration):
        return case_number
    return registration or case_number


def _snapshot_from_payload(
    payload: dict[str, object],
    *,
    provider: str,
    order_download_base_url: str | None = None,
) -> ProviderCaseSnapshot:
    data = _data_payload(payload)
    descriptions = None
    if isinstance(data, dict):
        descriptions = data.get("descriptions")
        case = _first_dict(data.get("courtCaseData"), data.get("case"), data)
    else:
        case = payload
    if case is None:
        case = payload
    entity = data.get("entityInfo") if isinstance(data, dict) else None
    entity_info = entity if isinstance(entity, dict) else {}
    descriptions_dict = descriptions if isinstance(descriptions, dict) else None
    cnr = _compact(case.get("cnr_number") or case.get("cnr") or entity_info.get("cnr"), limit=32)
    parties = _string_list(case.get("party_names") or case.get("parties")) or _string_list(
        case.get("petitioners")
    ) + _string_list(case.get("respondents"))
    orders = _case_order_events(
        _first_list(case.get("orders"), case.get("daily_orders"), case.get("interimOrders")),
        prefix="order",
        cnr=cnr,
        order_download_base_url=order_download_base_url,
        embedded_files=data.get("files") if isinstance(data, dict) else None,
    )
    judgments = _case_order_events(
        _first_list(case.get("judgments"), case.get("final_judgments"), case.get("judgmentOrders")),
        prefix="judgment",
        cnr=cnr,
        order_download_base_url=order_download_base_url,
        embedded_files=data.get("files") if isinstance(data, dict) else None,
    )
    if not orders:
        orders = _events(case.get("orders") or case.get("daily_orders"), prefix="order")
    if not judgments:
        judgments = _events(case.get("judgments") or case.get("final_judgments"), prefix="judgment")
    provider_court_code = _compact(
        case.get("court_code") or case.get("courtCode") or case.get("cnrCourtCode"),
        limit=80,
    )
    # Case-detail payloads have historically exposed ``cnrCourtCode`` as either
    # the full search-ready establishment code (DLND02) or its numeric suffix
    # (2). A valid CNR carries the canonical six-character court code, so use
    # it when the payload does not provide a search-ready value. Search results
    # already expose the canonical ``courtCode`` and retain it above.
    if (
        cnr
        and re.fullmatch(r"[A-Z]{4}\d{12}", cnr.upper())
        and (not provider_court_code or provider_court_code.isdigit())
    ):
        provider_court_code = cnr[:6].upper()
    next_hearing_fields = (
        "next_hearing_on",
        "next_hearing_date",
        "nextHearingDate",
    )
    direct_next_present = any(field in case for field in next_hearing_fields) or (
        "nextDateOfHearing" in entity_info
    )
    direct_next_raw = next(
        (case[field] for field in next_hearing_fields if field in case),
        entity_info.get("nextDateOfHearing"),
    )
    direct_next_parsed = _parse_date(direct_next_raw)
    hearing_fields = (
        "hearings",
        "hearing_history",
        "historyOfCaseHearings",
        "businessOnDateEntries",
    )
    hearing_collection_present = any(field in case for field in hearing_fields)
    raw_hearings = next((case[field] for field in hearing_fields if field in case), None)
    hearings = _events(raw_hearings, prefix="hearing")
    if direct_next_present and direct_next_raw not in (None, "") and direct_next_parsed is None:
        next_hearing_evidence_state = "unparseable"
    elif direct_next_parsed is not None:
        next_hearing_evidence_state = "dated"
    elif direct_next_present or hearing_collection_present:
        next_hearing_evidence_state = "confirmed_absent"
    else:
        next_hearing_evidence_state = "unavailable"
    return ProviderCaseSnapshot(
        provider=provider,
        cnr_number=cnr,
        case_number=_case_number_from_payload(case),
        court_code=provider_court_code,
        court_name=_court_name(
            case,
            descriptions_dict,
            court_code_override=provider_court_code,
        ),
        case_title=_display_title(case),
        party_names=parties,
        current_status=_case_status(case, descriptions_dict),
        current_stage=_compact(
            case.get("current_stage") or case.get("stage") or case.get("purpose"),
            limit=160,
        ),
        next_hearing_on=direct_next_parsed,
        orders=orders,
        judgments=judgments,
        hearings=hearings,
        source_url=_compact(case.get("source_url") or case.get("case_url"), limit=800),
        metadata={
            "provenance": "provider_normalized",
            "has_orders": bool(orders),
            "has_judgments": bool(judgments),
            "next_hearing_evidence": {
                "state": next_hearing_evidence_state,
                "direct_field_present": direct_next_present,
                "hearing_collection_present": hearing_collection_present,
                "hearing_event_count": len(hearings),
            },
        },
        matching_identity=replace(
            provider_identity(case, descriptions_dict),
            cnr=cnr,
            court_code=provider_court_code,
            case_number=_case_number_from_payload(case),
            court_name=_court_name(
                case, descriptions_dict, court_code_override=provider_court_code
            ),
        ),
    )


class EcourtsIndiaApiProvider:
    provider_key = "ecourtsindia"

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        request_budget_seconds: float = PROVIDER_REQUEST_BUDGET_SECONDS,
        bulk_budget_seconds: float = PROVIDER_BULK_BUDGET_SECONDS,
    ) -> None:
        if not 0 < request_budget_seconds <= PROVIDER_REQUEST_BUDGET_SECONDS:
            raise ValueError("The request deadline must fit the provider operation budget.")
        if not 0 < bulk_budget_seconds <= PROVIDER_BULK_BUDGET_SECONDS:
            raise ValueError("The bulk deadline must fit the provider operation budget.")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport
        self.request_budget_seconds = request_budget_seconds
        self.bulk_budget_seconds = bulk_budget_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def _url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        partner_base = base if base.endswith("/api/partner") else f"{base}/api/partner"
        return f"{partner_base}{path}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.request_budget_seconds,
            follow_redirects=False,
            transport=self.transport,
        )

    async def _request(
        self, client: httpx.AsyncClient, method: str, path: str, **kwargs: object
    ) -> httpx.Response:
        # Only a received failed HTTP response can be retried without an unknown
        # paid outcome. The caller's absolute deadline includes sleep and body.
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            async with client.stream(
                method, self._url(path), headers=self._headers(), **kwargs
            ) as streamed:
                content = bytearray()
                async for chunk in streamed.aiter_bytes():
                    if len(content) + len(chunk) > _MAX_PROVIDER_RESPONSE_BYTES:
                        raise CaseTrackingProviderError(
                            "Case tracking provider response exceeded the supported size.",
                            response_class="parse_error",
                        )
                    content.extend(chunk)
                response = httpx.Response(
                    streamed.status_code,
                    headers=streamed.headers,
                    content=bytes(content),
                    request=streamed.request,
                )
            if response.status_code not in RETRYABLE_READ_STATUS_CODES or attempt == attempts - 1:
                response.raise_for_status()
                return response
            await asyncio.sleep(0.25 * 2**attempt)
        raise AssertionError("Provider retry loop must return or raise.")  # pragma: no cover

    async def _bounded_request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            async with (
                asyncio.timeout(_remaining_transport_budget(self.request_budget_seconds)),
                self._client() as client,
            ):
                return await self._request(client, method, path, **kwargs)
        except TimeoutError as exc:
            raise httpx.ReadTimeout("Case tracking provider total deadline exceeded.") from exc

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        if query.cnr_number:
            return [self.get_case_by_cnr(cnr=query.cnr_number)]
        if query.require_complete_results and not search_number(
            HearingIdentity(case_number=query.case_number)
        ):
            raise CaseTrackingProviderError(
                "A public case or filing number with year is required for automatic matching.",
                response_class="match_validation_failed",
            )
        search_params = {
            key: value
            for key, value in {
                "query": query.query,
                # v4 exact case-number lookup is a structured filter. Sending
                # a case number as general full text can return HTTP 200 with
                # zero results, which is not a valid round-trip from Case Detail.
                "caseNumbers": search_number(HearingIdentity(case_number=query.case_number))
                if query.require_complete_results
                else query.case_number,
                "litigants": query.query,
                "courtCodes": query.court_code,
                "state": query.state,
                "courtName": None if query.require_complete_results else query.court_name,
                "pageSize": 20,
            }.items()
            if value is not None
        }
        try:
            response = asyncio.run(self._bounded_request("GET", "/search", params=search_params))
        except httpx.HTTPError as exc:
            raise _provider_http_error("Case tracking provider search failed.", exc) from exc
        payload = _json_payload(response)
        data = _data_payload(payload)
        rows = data.get("results") if isinstance(data, dict) else data
        if query.require_complete_results:
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise CaseTrackingProviderError(
                    "The provider search returned malformed match candidates.",
                    response_class="parse_error",
                )
            total = data.get("totalHits") if isinstance(data, dict) else None
            has_next = data.get("hasNextPage") if isinstance(data, dict) else None
            if type(total) is not int or total < len(rows) or type(has_next) is not bool:
                raise CaseTrackingProviderError(
                    "Invalid provider search completeness.", response_class="parse_error"
                )
            if (
                has_next
                or (isinstance(total, int) and total > len(rows))
                or len(rows) > MAX_MATCH_CANDIDATES
            ):
                raise CaseTrackingProviderError(
                    "The bounded provider search is incomplete; "
                    "refine the court and case identifiers.",
                    response_class="ambiguous_match",
                )
        if not isinstance(rows, list):
            rows = [data] if isinstance(data, dict) else []
        descriptions = (
            data.get("descriptions") or data.get("enumDescriptions")
            if isinstance(data, dict)
            else None
        )
        snapshots: list[ProviderCaseSnapshot] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_payload: dict[str, object] = row
            if isinstance(descriptions, dict) and "descriptions" not in row:
                row_payload = {
                    "data": {
                        "courtCaseData": row,
                        "descriptions": descriptions,
                    }
                }
            snapshots.append(
                _snapshot_from_payload(
                    row_payload,
                    provider=self.provider_key,
                    order_download_base_url=self._url(""),
                )
            )
        return snapshots

    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot:
        try:
            response = asyncio.run(self._bounded_request("GET", f"/case/{quote(cnr)}"))
        except httpx.HTTPError as exc:
            raise _provider_http_error("Case tracking provider refresh failed.", exc) from exc
        payload = _json_payload(response)
        if not isinstance(payload, dict):
            raise CaseTrackingProviderError("Case tracking provider returned invalid data.")
        return _snapshot_from_payload(
            payload,
            provider=self.provider_key,
            order_download_base_url=self._url(""),
        )

    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        return asyncio.run(self._refresh_cases(cnrs=list(dict.fromkeys(cnrs))))

    async def _refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        snapshots: list[ProviderCaseSnapshot] = []
        errors: dict[str, str] = {}
        costs = dict.fromkeys(cnrs, 0)
        uncertain: set[str] = set()
        provider_call_count = 0
        if len(cnrs) > 50:
            raise CaseTrackingProviderError("A provider refresh batch cannot exceed 50 cases.")
        if not cnrs:
            return ProviderBulkRefreshResult(snapshots=[], provider_call_count=0)
        try:
            async with (
                asyncio.timeout(_remaining_transport_budget(self.bulk_budget_seconds)),
                self._client() as client,
            ):
                # The status endpoint is free. A pending paid refresh must not
                # be submitted again, including after a worker lease expires.
                provider_call_count += 1
                response = await self._request(
                    client, "POST", "/case/bulk-refresh-status", json={"cnrs": cnrs}
                )
                data = _data_payload(_json_payload(response))
                rows = data.get("results") if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    raise CaseTrackingProviderError(
                        "Provider refresh status is malformed.", response_class="parse_error"
                    )
                statuses: dict[str, dict] = {}
                for row in rows:
                    if (
                        not isinstance(row, dict)
                        or not isinstance(row.get("cnr"), str)
                        or row.get("cnr") not in costs
                        or row["cnr"] in statuses
                    ):
                        raise CaseTrackingProviderError(
                            "Provider refresh status identity is invalid.",
                            response_class="parse_error",
                        )
                    statuses[row["cnr"]] = row
                if set(statuses) != set(cnrs):
                    raise CaseTrackingProviderError(
                        "Provider refresh status is incomplete.", response_class="parse_error"
                    )
                ready: list[str] = []
                submit: list[str] = []
                today = datetime.now(UTC).date()
                for cnr, row in statuses.items():
                    state = row.get("status")
                    if not isinstance(state, str):
                        raise CaseTrackingProviderError(
                            "Provider refresh status is malformed.", response_class="parse_error"
                        )
                    if state == "PENDING":
                        errors[cnr] = _PROVIDER_PENDING_MESSAGE
                    elif state == "COMPLETED" and _parse_date(row.get("requestedAt")) == today:
                        ready.append(cnr)
                    elif state in {"NOT_REQUESTED", "COMPLETED", "FAILED"}:
                        submit.append(cnr)
                    elif state == "INVALID":
                        errors[cnr] = "Provider rejected the case identifier. [case_not_found]"
                    else:
                        raise CaseTrackingProviderError(
                            "Provider refresh status is unsupported.", response_class="parse_error"
                        )
                if submit:
                    provider_call_count += 1
                    uncertain.update(submit)
                    try:
                        # The published bulk minimum is two; one CNR uses the
                        # single refresh endpoint with the same asynchronous contract.
                        if len(submit) == 1:
                            queued_response = await self._request(
                                client, "POST", f"/case/{quote(submit[0])}/refresh"
                            )
                            queued = _data_payload(_json_payload(queued_response))
                            if (
                                not isinstance(queued, dict)
                                or queued.get("cnr") != submit[0]
                                or queued.get("status") != "QUEUED"
                            ):
                                raise CaseTrackingProviderError(
                                    "Provider refresh receipt is malformed.",
                                    response_class="parse_error",
                                )
                        else:
                            queued_response = await self._request(
                                client, "POST", "/case/bulk-refresh", json={"cnrs": submit}
                            )
                            queued = _data_payload(_json_payload(queued_response))
                            if not isinstance(queued, dict) or any(
                                not isinstance(queued.get(key), list)
                                for key in ("refreshed", "queued", "invalid")
                            ):
                                raise CaseTrackingProviderError(
                                    "Provider refresh receipt is malformed.",
                                    response_class="parse_error",
                                )
                            acknowledged = (
                                queued["refreshed"] + queued["queued"] + queued["invalid"]
                            )
                            if (
                                not all(isinstance(value, str) for value in acknowledged)
                                or len(acknowledged) != len(set(acknowledged))
                                or set(acknowledged) != set(submit)
                            ):
                                raise CaseTrackingProviderError(
                                    "Provider refresh receipt identity is invalid.",
                                    response_class="parse_error",
                                )
                            for cnr in queued["invalid"]:
                                uncertain.discard(cnr)
                                errors[cnr] = (
                                    "Provider rejected the case identifier. [case_not_found]"
                                )
                        for cnr in submit:
                            if cnr not in errors:
                                costs[cnr] += 15
                                uncertain.discard(cnr)
                                errors[cnr] = _PROVIDER_PENDING_MESSAGE
                    except httpx.HTTPStatusError:
                        uncertain.difference_update(submit)
                        raise
                for cnr in ready:
                    provider_call_count += 1
                    uncertain.add(cnr)
                    try:
                        async with asyncio.timeout(self.request_budget_seconds):
                            response = await self._request(client, "GET", f"/case/{quote(cnr)}")
                        payload = _json_payload(response)
                        if not isinstance(payload, dict):
                            raise CaseTrackingProviderError(
                                "Case tracking provider returned invalid data."
                            )
                        snapshots.append(
                            _snapshot_from_payload(
                                payload,
                                provider=self.provider_key,
                                order_download_base_url=self._url(""),
                            )
                        )
                        costs[cnr] += 150
                        uncertain.discard(cnr)
                    except (httpx.HTTPError, CaseTrackingProviderError, TimeoutError) as exc:
                        if isinstance(exc, httpx.HTTPStatusError):
                            uncertain.discard(cnr)
                        response_class = (
                            "timeout"
                            if isinstance(exc, TimeoutError)
                            else exc.response_class
                            if isinstance(exc, CaseTrackingProviderError)
                            else _http_error_response_class(exc)
                        )
                        errors[cnr] = f"Case tracking provider refresh failed. [{response_class}]"
        except (httpx.HTTPError, CaseTrackingProviderError, TimeoutError) as exc:
            response_class = (
                "timeout"
                if isinstance(exc, TimeoutError)
                else exc.response_class
                if isinstance(exc, CaseTrackingProviderError)
                else _http_error_response_class(exc)
            )
            completed = {snapshot.cnr_number for snapshot in snapshots}
            for cnr in cnrs:
                if cnr not in completed and cnr not in errors:
                    errors[cnr] = f"Case tracking provider bulk refresh failed. [{response_class}]"
        return ProviderBulkRefreshResult(
            snapshots=snapshots,
            errors=errors,
            provider_call_count=provider_call_count,
            confirmed_cost_minor_by_cnr=costs,
            uncertain_charge_cnrs=uncertain,
        )


def provider_status() -> tuple[bool, str, bool, str | None]:
    settings = get_settings()
    provider = settings.case_tracking_provider
    enabled = bool(settings.case_tracking_enabled)
    configured = (
        enabled
        and provider == "ecourtsindia"
        and bool(settings.ecourtsindia_api_base_url)
        and bool(settings.ecourtsindia_api_token)
    )
    reason = None
    if not enabled:
        reason = "Case tracking is disabled."
    elif provider != "ecourtsindia":
        reason = "No supported case tracking provider is selected."
    elif not settings.ecourtsindia_api_base_url or not settings.ecourtsindia_api_token:
        reason = "eCourtsIndia provider credentials are not configured."
    return enabled, provider, configured, reason


def get_case_tracking_provider() -> CaseTrackingProvider:
    enabled, provider, configured, reason = provider_status()
    if not enabled or not configured or provider != "ecourtsindia":
        raise CaseTrackingProviderUnavailable(reason or "Case tracking provider unavailable.")
    settings = get_settings()
    assert settings.ecourtsindia_api_base_url is not None
    assert settings.ecourtsindia_api_token is not None
    return EcourtsIndiaApiProvider(
        base_url=settings.ecourtsindia_api_base_url,
        token=settings.ecourtsindia_api_token,
    )
