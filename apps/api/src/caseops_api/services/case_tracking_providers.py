from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from caseops_api.core.settings import get_settings


class CaseTrackingProviderUnavailable(RuntimeError):
    pass


class CaseTrackingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaseSearchQuery:
    query: str | None = None
    cnr_number: str | None = None
    case_number: str | None = None
    court_code: str | None = None
    state: str | None = None
    court_name: str | None = None


@dataclass(frozen=True)
class ProviderCaseEvent:
    source_record_key: str
    title: str
    event_date: date | None = None
    source_url: str | None = None
    text: str | None = None
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


@dataclass(frozen=True)
class ProviderBulkRefreshResult:
    snapshots: list[ProviderCaseSnapshot]
    errors: dict[str, str] = field(default_factory=dict)


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
        source_key = _compact(
            item.get("id") or item.get("source_record_key") or item.get("pdf_url"),
            limit=160,
        ) or _stable_key(prefix, item)
        events.append(
            ProviderCaseEvent(
                source_record_key=f"{prefix}:{source_key}",
                title=title,
                event_date=_parse_date(
                    item.get("date") or item.get("order_date") or item.get("judgment_date")
                ),
                source_url=_compact(item.get("source_url") or item.get("pdf_url"), limit=800),
                text=_compact(item.get("text") or item.get("order_text"), limit=4000),
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
        return [
            compacted
            for item in value[:limit]
            if (compacted := _compact(item, limit=160))
        ]
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


def _court_name(payload: dict[str, object], descriptions: dict[str, object] | None) -> str | None:
    court_name = _compact(payload.get("court_name") or payload.get("courtName"), limit=255)
    if court_name:
        return court_name
    court_code = _compact(
        payload.get("court_code")
        or payload.get("courtCode")
        or payload.get("cnrCourtCode"),
        limit=80,
    )
    enum_lookup = descriptions.get("enumLookup") if descriptions else None
    if isinstance(enum_lookup, dict):
        court_lookup = enum_lookup.get("courtCode")
        if isinstance(court_lookup, dict) and court_code in court_lookup:
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
) -> list[ProviderCaseEvent]:
    if not isinstance(raw, list):
        return []
    events: list[ProviderCaseEvent] = []
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        order_url = _compact(item.get("orderUrl") or item.get("pdfFile"), limit=800)
        title = _compact(
            item.get("description")
            or item.get("orderType")
            or item.get("title")
            or "Case order",
            limit=500,
        )
        if not title:
            continue
        event_date = _parse_date(item.get("orderDate") or item.get("date"))
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
                text=_compact(item.get("markdownContent") or item.get("text"), limit=4000),
                provider_summary=_compact(item.get("summary") or item.get("aiSummary"), limit=2000),
                metadata={
                    key: str(value)[:500]
                    for key, value in item.items()
                    if key not in {"markdownContent", "text", "summary", "aiSummary"}
                },
            )
        )
    return events


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
    parties = (
        _string_list(case.get("party_names") or case.get("parties"))
        or _string_list(case.get("petitioners"))
        + _string_list(case.get("respondents"))
    )
    orders = _case_order_events(
        _first_list(case.get("orders"), case.get("daily_orders"), case.get("interimOrders")),
        prefix="order",
        cnr=cnr,
        order_download_base_url=order_download_base_url,
    )
    judgments = _case_order_events(
        _first_list(case.get("judgments"), case.get("final_judgments"), case.get("judgmentOrders")),
        prefix="judgment",
        cnr=cnr,
        order_download_base_url=order_download_base_url,
    )
    if not orders:
        orders = _events(case.get("orders") or case.get("daily_orders"), prefix="order")
    if not judgments:
        judgments = _events(case.get("judgments") or case.get("final_judgments"), prefix="judgment")
    return ProviderCaseSnapshot(
        provider=provider,
        cnr_number=cnr,
        case_number=_compact(
            case.get("case_number")
            or case.get("caseNumber")
            or case.get("registrationNumber"),
            limit=120,
        ),
        court_code=_compact(
            case.get("court_code") or case.get("courtCode") or case.get("cnrCourtCode"),
            limit=80,
        ),
        court_name=_court_name(case, descriptions_dict),
        case_title=_display_title(case),
        party_names=parties,
        current_status=_case_status(case, descriptions_dict),
        current_stage=_compact(
            case.get("current_stage") or case.get("stage") or case.get("purpose"),
            limit=160,
        ),
        next_hearing_on=_parse_date(
            case.get("next_hearing_on")
            or case.get("next_hearing_date")
            or case.get("nextHearingDate")
            or entity_info.get("nextDateOfHearing")
        ),
        orders=orders,
        judgments=judgments,
        hearings=_events(
            case.get("hearings")
            or case.get("hearing_history")
            or case.get("historyOfCaseHearings")
            or case.get("businessOnDateEntries"),
            prefix="hearing",
        ),
        source_url=_compact(case.get("source_url") or case.get("case_url"), limit=800),
        metadata={
            "provenance": "provider_normalized",
            "has_orders": bool(orders),
            "has_judgments": bool(judgments),
        },
    )


class EcourtsIndiaApiProvider:
    provider_key = "ecourtsindia"

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def _url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        partner_base = base if base.endswith("/api/partner") else f"{base}/api/partner"
        return f"{partner_base}{path}"

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=30,
            follow_redirects=True,
            transport=self.transport,
        )

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        if query.cnr_number:
            return [self.get_case_by_cnr(cnr=query.cnr_number)]
        search_text = query.query or query.case_number
        try:
            with self._client() as client:
                response = client.get(
                    self._url("/search"),
                    params={
                        "query": search_text,
                        "litigants": query.query,
                        "courtCodes": query.court_code,
                        "state": query.state,
                        "courtName": query.court_name,
                        "pageSize": 20,
                    },
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CaseTrackingProviderError("Case tracking provider search failed.") from exc
        payload = response.json()
        data = _data_payload(payload)
        rows = data.get("results") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            rows = [data] if isinstance(data, dict) else []
        descriptions = data.get("descriptions") if isinstance(data, dict) else None
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
            with self._client() as client:
                response = client.get(
                    self._url(f"/case/{quote(cnr)}"),
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CaseTrackingProviderError("Case tracking provider refresh failed.") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise CaseTrackingProviderError("Case tracking provider returned invalid data.")
        return _snapshot_from_payload(
            payload,
            provider=self.provider_key,
            order_download_base_url=self._url(""),
        )

    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        snapshots: list[ProviderCaseSnapshot] = []
        errors: dict[str, str] = {}
        unique_cnrs = list(dict.fromkeys(cnrs))
        if unique_cnrs:
            try:
                with self._client() as client:
                    response = client.post(
                        self._url("/case/bulk-refresh"),
                        json={"cnrs": unique_cnrs},
                        headers={**self._headers(), "Content-Type": "application/json"},
                    )
                    response.raise_for_status()
            except httpx.HTTPError:
                for cnr in unique_cnrs:
                    errors[cnr] = "Case tracking provider bulk refresh failed."
                return ProviderBulkRefreshResult(snapshots=snapshots, errors=errors)
        for cnr in unique_cnrs:
            try:
                snapshots.append(self.get_case_by_cnr(cnr=cnr))
            except CaseTrackingProviderError as exc:
                errors[cnr] = str(exc)
        return ProviderBulkRefreshResult(snapshots=snapshots, errors=errors)


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
