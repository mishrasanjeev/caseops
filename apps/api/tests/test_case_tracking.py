from __future__ import annotations

import json
from datetime import date

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import NotificationDeliveryIntent, TrackedCase, TrackedCaseUpdate
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import normalize_cnr, poll_tracked_cases
from caseops_api.services.case_tracking_providers import (
    CaseSearchQuery,
    CaseTrackingProviderError,
    EcourtsIndiaApiProvider,
    ProviderBulkRefreshResult,
    ProviderCaseEvent,
    ProviderCaseSnapshot,
)
from tests.test_auth_company import auth_headers, bootstrap_company


class FakeCaseTrackingProvider:
    provider_key = "ecourtsindia"

    def __init__(self, *, fail_refresh: bool = False) -> None:
        self.fail_refresh = fail_refresh
        self.search_calls: list[CaseSearchQuery] = []
        self.refresh_calls: list[str] = []
        self.bulk_refresh_calls: list[list[str]] = []

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        self.search_calls.append(query)
        return [
            ProviderCaseSnapshot(
                provider=self.provider_key,
                cnr_number=query.cnr_number or "DLHC010012342026",
                case_number=query.case_number or "WP(C) 1/2026",
                court_code=query.court_code,
                court_name="Delhi High Court",
                case_title="Example Petitioner v Example Respondent",
                party_names=["Example Petitioner", "Example Respondent"],
                current_status="Pending",
                current_stage="Arguments",
                next_hearing_on=date(2026, 6, 1),
                source_url="https://provider.example/case",
            )
        ]

    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot:
        self.refresh_calls.append(cnr)
        if self.fail_refresh:
            raise CaseTrackingProviderError("provider token abcdefghijklmnopqrstuvwxyz failed")
        return ProviderCaseSnapshot(
            provider=self.provider_key,
            cnr_number=cnr,
            case_number="WP(C) 1/2026",
            court_code="DLHC",
            court_name="Delhi High Court",
            case_title="Example Petitioner v Example Respondent",
            party_names=["Example Petitioner", "Example Respondent"],
            current_status="Pending",
            current_stage="Arguments",
            next_hearing_on=date(2026, 6, 15),
            orders=[
                ProviderCaseEvent(
                    source_record_key="order:1",
                    title="Order dated 26 May 2026",
                    event_date=date(2026, 5, 26),
                    source_url="https://provider.example/order-1",
                    text="The court issued directions and listed the matter.",
                )
            ],
            source_url="https://provider.example/case",
        )

    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult:
        self.bulk_refresh_calls.append(cnrs)
        snapshots = []
        errors = {}
        for cnr in cnrs:
            try:
                snapshots.append(self.get_case_by_cnr(cnr=cnr))
            except CaseTrackingProviderError as exc:
                errors[cnr] = str(exc)
        return ProviderBulkRefreshResult(snapshots=snapshots, errors=errors)


def _bootstrap(client: TestClient) -> str:
    return str(bootstrap_company(client)["access_token"])


def test_case_tracking_provider_disabled_state_is_safe(client: TestClient) -> None:
    token = _bootstrap(client)
    status = client.get("/api/case-tracking/status", headers=auth_headers(token))
    assert status.status_code == 200, status.text
    assert status.json()["configured"] is False

    search = client.post(
        "/api/case-tracking/search",
        headers=auth_headers(token),
        json={"cnr_number": "DLHC010012342026"},
    )
    assert search.status_code == 503
    assert "disabled" in search.json()["detail"].lower()


def test_case_tracking_search_accepts_general_party_query(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap(client)
    provider = FakeCaseTrackingProvider()
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider",
        lambda: provider,
    )

    search = client.post(
        "/api/case-tracking/search",
        headers=auth_headers(token),
        json={"query": "Example Petitioner", "court_code": "DLHC"},
    )

    assert search.status_code == 200, search.text
    assert search.json()["results"][0]["case_title"] == (
        "Example Petitioner v Example Respondent"
    )
    assert provider.search_calls[0].query == "Example Petitioner"
    assert provider.search_calls[0].court_code == "DLHC"


def test_ecourts_provider_uses_partner_paths_and_normalizes_payloads() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/api/partner/search":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "results": [
                            {
                                "cnr": "DLHC010012342026",
                                "caseNumber": "WP(C) 1/2026",
                                "cnrCourtCode": "DLHC",
                                "petitioners": ["Example Petitioner"],
                                "respondents": ["Example Respondent"],
                                "caseStatus": "PENDING",
                                "nextHearingDate": "2026-06-15T00:00:00Z",
                            }
                        ],
                        "descriptions": {
                            "enumLookup": {
                                "caseStatus": {"PENDING": "Pending"},
                                "courtCode": {"DLHC": "Delhi High Court"},
                            }
                        },
                    }
                },
            )
        if (
            request.method == "GET"
            and request.url.path == "/api/partner/case/DLHC010012342026"
        ):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "courtCaseData": {
                            "cnr": "DLHC010012342026",
                            "caseNumber": "WP(C) 1/2026",
                            "cnrCourtCode": "DLHC",
                            "petitioners": ["Example Petitioner"],
                            "respondents": ["Example Respondent"],
                            "caseStatus": "PENDING",
                            "nextHearingDate": "2026-06-15T00:00:00Z",
                            "interimOrders": [
                                {
                                    "orderUrl": "order-1.pdf",
                                    "description": "Interim order",
                                    "orderDate": "2026-05-26",
                                }
                            ],
                            "judgmentOrders": [
                                {
                                    "orderUrl": "judgment-1.pdf",
                                    "description": "Final judgment",
                                    "orderDate": "2026-05-27",
                                }
                            ],
                        },
                        "descriptions": {
                            "enumLookup": {
                                "caseStatus": {"PENDING": "Pending"},
                                "courtCode": {"DLHC": "Delhi High Court"},
                            }
                        },
                    }
                },
            )
        if request.method == "POST" and request.url.path == "/api/partner/case/bulk-refresh":
            assert json.loads(request.content) == {"cnrs": ["DLHC010012342026"]}
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"detail": request.url.path})

    provider = EcourtsIndiaApiProvider(
        base_url="https://webapi.ecourtsindia.com",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    results = provider.search_cases(
        query=CaseSearchQuery(query="Example Petitioner", court_code="DLHC")
    )
    assert len(results) == 1
    assert results[0].case_title == "Example Petitioner v Example Respondent"
    assert results[0].court_name == "Delhi High Court"
    assert results[0].current_status == "Pending"
    assert results[0].next_hearing_on == date(2026, 6, 15)
    assert requests[0].url.path == "/api/partner/search"
    assert requests[0].url.params["query"] == "Example Petitioner"
    assert requests[0].url.params["courtCodes"] == "DLHC"

    snapshot = provider.get_case_by_cnr(cnr="DLHC010012342026")
    assert snapshot.orders[0].title == "Interim order dated 2026-05-26"
    assert snapshot.orders[0].source_url == (
        "https://webapi.ecourtsindia.com/api/partner/case/"
        "DLHC010012342026/order/order-1.pdf"
    )
    assert snapshot.judgments[0].title == "Final judgment dated 2026-05-27"
    assert requests[1].url.path == "/api/partner/case/DLHC010012342026"

    refresh = provider.refresh_cases(cnrs=["DLHC010012342026", "DLHC010012342026"])
    assert refresh.errors == {}
    assert len(refresh.snapshots) == 1
    assert requests[2].method == "POST"
    assert requests[2].url.path == "/api/partner/case/bulk-refresh"


def test_case_tracking_search_bookmark_update_and_archive(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap(client)
    provider = FakeCaseTrackingProvider()
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider",
        lambda: provider,
    )

    search = client.post(
        "/api/case-tracking/search",
        headers=auth_headers(token),
        json={"cnr_number": "dlhc-0100-1234-2026"},
    )
    assert search.status_code == 200, search.text
    result = search.json()["results"][0]
    assert result["cnr_number"] == "DLHC010012342026"
    assert provider.search_calls[0].cnr_number == "DLHC010012342026"

    create = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(token),
        json={
            "provider": result["provider"],
            "cnr_number": result["cnr_number"],
            "case_number": result["case_number"],
            "court_code": result["court_code"],
            "court_name": result["court_name"],
            "case_title": result["case_title"],
            "party_names": result["party_names"],
            "current_status": result["current_status"],
            "current_stage": result["current_stage"],
            "next_hearing_on": result["next_hearing_on"],
        },
    )
    assert create.status_code == 201, create.text
    bookmark_id = create.json()["id"]
    duplicate = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(token),
        json={
            "provider": result["provider"],
            "cnr_number": result["cnr_number"],
            "case_number": result["case_number"],
            "court_code": result["court_code"],
            "court_name": result["court_name"],
            "case_title": result["case_title"],
            "party_names": result["party_names"],
            "current_status": result["current_status"],
            "current_stage": result["current_stage"],
            "next_hearing_on": result["next_hearing_on"],
        },
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == bookmark_id
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(TrackedCase).where(
                    TrackedCase.cnr_number == "DLHC010012342026"
                )
            )
            == 1
        )

    listed = client.get("/api/case-tracking/bookmarks", headers=auth_headers(token))
    assert listed.status_code == 200, listed.text
    assert listed.json()["bookmarks"][0]["tracked_case"]["case_title"].startswith("Example")

    patched = client.patch(
        f"/api/case-tracking/bookmarks/{bookmark_id}",
        headers=auth_headers(token),
        json={"notification_enabled": False, "name": "Tracked writ"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["notification_enabled"] is False
    assert patched.json()["name"] == "Tracked writ"

    archived = client.patch(
        f"/api/case-tracking/bookmarks/{bookmark_id}",
        headers=auth_headers(token),
        json={"is_archived": True},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["is_archived"] is True
    assert client.get("/api/case-tracking/bookmarks", headers=auth_headers(token)).json()[
        "bookmarks"
    ] == []


def test_case_tracking_refresh_detects_order_and_enqueues_in_app_idempotently(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap(client)
    provider = FakeCaseTrackingProvider()
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider",
        lambda: provider,
    )
    create = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(token),
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "case_number": "WP(C) 1/2026",
            "court_code": "DLHC",
            "court_name": "Delhi High Court",
            "case_title": "Example Petitioner v Example Respondent",
            "notification_enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    bookmark_id = create.json()["id"]

    refresh = client.post(
        f"/api/case-tracking/bookmarks/{bookmark_id}/refresh",
        headers=auth_headers(token),
    )
    assert refresh.status_code == 200, refresh.text
    body = refresh.json()
    assert body["delivery_status"] == "in_app_only"
    assert len(body["created_updates"]) == 1
    assert body["created_updates"][0]["update_type"] == "new_order"
    assert "lawyer review" in body["created_updates"][0]["ai_summary"]["review_framing"]

    rerun = client.post(
        f"/api/case-tracking/bookmarks/{bookmark_id}/refresh",
        headers=auth_headers(token),
    )
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["created_updates"] == []

    updates = client.get(
        f"/api/case-tracking/bookmarks/{bookmark_id}/updates",
        headers=auth_headers(token),
    )
    assert updates.status_code == 200, updates.text
    assert len(updates.json()["updates"]) == 1

    with get_session_factory()() as session:
        assert session.scalar(select(TrackedCaseUpdate)) is not None
        intents = list(session.scalars(select(NotificationDeliveryIntent)))
        assert len(intents) == 1
        assert intents[0].channel == "in_app"
        assert intents[0].event_type == "case_tracking.new_order"


def test_case_tracking_poll_continues_after_provider_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap(client)
    create = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(token),
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "court_name": "Delhi High Court",
            "case_title": "Example Petitioner v Example Respondent",
        },
    )
    assert create.status_code == 201, create.text
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        provider = FakeCaseTrackingProvider(fail_refresh=True)
        with get_session_factory()() as session:
            runs = poll_tracked_cases(
                session,
                provider=provider,
            )
            assert runs
            assert runs[0].status == "partial"
            assert runs[0].error_count == 1
            assert provider.bulk_refresh_calls == [["DLHC010012342026"]]
            tracked = session.scalar(select(TrackedCase))
            assert tracked is not None
            assert "token" in tracked.last_error
            assert "abcdefghijklmnopqrstuvwxyz" not in tracked.last_error
    finally:
        get_settings.cache_clear()


def test_case_tracking_cnr_normalization() -> None:
    assert normalize_cnr(" dlhc-0100 1234-2026 ") == "DLHC010012342026"
    assert normalize_cnr("   ") is None
