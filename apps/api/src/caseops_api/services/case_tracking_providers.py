from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

import httpx

from caseops_api.core.settings import get_settings


class CaseTrackingProviderUnavailable(RuntimeError):
    pass


class CaseTrackingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaseSearchQuery:
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

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]: ...

    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot: ...

    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult: ...


def _compact(value: object, *, limit: int = 500) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] if text else None


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
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


def _snapshot_from_payload(payload: dict[str, object], *, provider: str) -> ProviderCaseSnapshot:
    case = payload.get("case")
    if isinstance(case, dict):
        payload = case
    party_names = payload.get("party_names") or payload.get("parties") or []
    if not isinstance(party_names, list):
        party_names = []
    return ProviderCaseSnapshot(
        provider=provider,
        cnr_number=_compact(payload.get("cnr_number") or payload.get("cnr"), limit=32),
        case_number=_compact(payload.get("case_number"), limit=120),
        court_code=_compact(payload.get("court_code"), limit=80),
        court_name=_compact(payload.get("court_name") or payload.get("court"), limit=255),
        case_title=_compact(payload.get("case_title") or payload.get("title"), limit=500)
        or "Tracked case",
        party_names=[_compact(item, limit=160) or "" for item in party_names[:20]],
        current_status=_compact(payload.get("current_status") or payload.get("status"), limit=160),
        current_stage=_compact(payload.get("current_stage") or payload.get("stage"), limit=160),
        next_hearing_on=_parse_date(
            payload.get("next_hearing_on") or payload.get("next_hearing_date")
        ),
        orders=_events(payload.get("orders") or payload.get("daily_orders"), prefix="order"),
        judgments=_events(
            payload.get("judgments") or payload.get("final_judgments"),
            prefix="judgment",
        ),
        hearings=_events(
            payload.get("hearings") or payload.get("hearing_history"),
            prefix="hearing",
        ),
        source_url=_compact(payload.get("source_url") or payload.get("case_url"), limit=800),
        metadata={
            "provenance": "provider_normalized",
            "has_orders": bool(payload.get("orders") or payload.get("daily_orders")),
            "has_judgments": bool(payload.get("judgments") or payload.get("final_judgments")),
        },
    )


class EcourtsIndiaApiProvider:
    provider_key = "ecourtsindia"

    def __init__(self, *, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(
                    f"{self.base_url}/cases/search",
                    params={
                        "cnr": query.cnr_number,
                        "case_number": query.case_number,
                        "court_code": query.court_code,
                        "state": query.state,
                        "court_name": query.court_name,
                    },
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CaseTrackingProviderError("Case tracking provider search failed.") from exc
        payload = response.json()
        rows = payload.get("results") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            rows = [payload] if isinstance(payload, dict) else []
        return [
            _snapshot_from_payload(row, provider=self.provider_key)
            for row in rows
            if isinstance(row, dict)
        ]

    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot:
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(
                    f"{self.base_url}/cases/{cnr}",
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CaseTrackingProviderError("Case tracking provider refresh failed.") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise CaseTrackingProviderError("Case tracking provider returned invalid data.")
        return _snapshot_from_payload(payload, provider=self.provider_key)

    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        snapshots: list[ProviderCaseSnapshot] = []
        errors: dict[str, str] = {}
        for cnr in cnrs:
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
