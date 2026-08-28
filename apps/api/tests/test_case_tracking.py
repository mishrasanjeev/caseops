from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    CaseTrackingSupportMatrix,
    Company,
    CompanyMembership,
    Matter,
    MatterActivity,
    NotificationDeliveryIntent,
    TrackedCase,
    TrackedCaseBookmark,
    TrackedCaseProviderOperation,
    TrackedCaseProviderSnapshot,
    TrackedCaseUpdate,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import (
    download_case_tracking_source,
    normalize_cnr,
    poll_tracked_cases,
)
from caseops_api.services.case_tracking_providers import (
    _SOURCE_TEXT_MAX_CHARS,
    CaseSearchQuery,
    CaseTrackingProviderError,
    EcourtsIndiaApiProvider,
    ProviderBulkRefreshResult,
    ProviderCaseEvent,
    ProviderCaseSnapshot,
    _source_text,
)
from caseops_api.services.session_context import SessionContext
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
                    source_url=(
                        "https://provider.example/api/partner/case/"
                        "DLHC010012342026/order/order-1.pdf"
                    ),
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


def test_provider_source_text_is_format_preserving_and_bounded() -> None:
    normalized, truncated = _source_text("heading\r\n\r\nbody\x00")
    assert normalized == "heading\n\nbody"
    assert truncated is False

    bounded, truncated = _source_text("x" * (_SOURCE_TEXT_MAX_CHARS + 1))
    assert bounded is not None
    assert len(bounded) == _SOURCE_TEXT_MAX_CHARS
    assert truncated is True


def _bootstrap(client: TestClient) -> str:
    return str(bootstrap_company(client)["access_token"])


def _context_from_bootstrap(boot: dict[str, object]) -> SessionContext:
    with get_session_factory()() as session:
        company = session.get(Company, str(boot["company"]["id"]))
        user = session.get(User, str(boot["user"]["id"]))
        membership = session.get(CompanyMembership, str(boot["membership"]["id"]))
        assert company is not None
        assert user is not None
        assert membership is not None
        return SessionContext(company=company, user=user, membership=membership)


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


def test_matter_create_auto_links_case_tracking_bookmark_when_provider_configured(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap(client)
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://provider.example")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "server-side-token")
    get_settings.cache_clear()

    create = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Hari auto eCourt sync matter",
            "matter_code": "AUTO-ECT-001",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Example Petitioner",
            "opposing_party": "Example Respondent",
            "case_number": "WP(C) 1/2026",
            "cnr_number": "dlhc-0100-1234-2026",
            "status": "intake",
        },
    )
    assert create.status_code == 200, create.text
    matter_id = create.json()["id"]

    listed = client.get("/api/case-tracking/bookmarks", headers=auth_headers(token))
    assert listed.status_code == 200, listed.text
    bookmarks = listed.json()["bookmarks"]
    assert len(bookmarks) == 1
    assert bookmarks[0]["matter_id"] == matter_id
    assert bookmarks[0]["name"] == "AUTO-ECT-001"
    assert bookmarks[0]["tracked_case"]["cnr_number"] == "DLHC010012342026"
    assert bookmarks[0]["tracked_case"]["case_number"] == "WP(C) 1/2026"
    assert bookmarks[0]["tracked_case"]["court_name"] == "Delhi High Court"

    with get_session_factory()() as session:
        bookmark = session.scalar(select(TrackedCaseBookmark))
        assert bookmark is not None
        assert bookmark.matter_id == matter_id
        activity = session.scalar(
            select(MatterActivity).where(
                MatterActivity.matter_id == matter_id,
                MatterActivity.event_type == "case_tracking_linked",
            )
        )
        assert activity is not None
        created_audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "matter.created",
                AuditEvent.matter_id == matter_id,
            )
        )
        assert created_audit is not None
        created_metadata = json.loads(created_audit.metadata_json or "{}")
        assert created_metadata["case_tracking_auto_link"]["status"] == "linked"
        bookmark_audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "case_tracking.bookmark_created",
                AuditEvent.matter_id == matter_id,
            )
        )
        assert bookmark_audit is not None
        bookmark_metadata = json.loads(bookmark_audit.metadata_json or "{}")
        assert bookmark_metadata["origin"] == "matter_create_auto_link"


def test_matter_create_with_case_identity_does_not_fail_when_tracking_disabled(
    client: TestClient,
) -> None:
    token = _bootstrap(client)

    create = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Disabled tracking matter",
            "matter_code": "AUTO-ECT-DISABLED",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "case_number": "WP(C) 2/2026",
            "cnr_number": "DLHC010022222026",
            "status": "intake",
        },
    )
    assert create.status_code == 200, create.text
    matter_id = create.json()["id"]
    listed = client.get("/api/case-tracking/bookmarks", headers=auth_headers(token))
    assert listed.status_code == 200, listed.text
    assert listed.json()["bookmarks"] == []

    with get_session_factory()() as session:
        created_audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "matter.created",
                AuditEvent.matter_id == matter_id,
            )
        )
        assert created_audit is not None
        created_metadata = json.loads(created_audit.metadata_json or "{}")
        assert created_metadata["case_tracking_auto_link"] == {
            "status": "skipped",
            "reason": "case_tracking_disabled",
        }


def test_matter_create_auto_link_is_non_blocking_when_support_matrix_blocks_court(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap(client)
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://provider.example")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "server-side-token")
    get_settings.cache_clear()

    with get_session_factory()() as session:
        session.add(
            CaseTrackingSupportMatrix(
                provider="ecourtsindia",
                court="Delhi High Court",
                bench_jurisdiction=None,
                lookup_method="cnr",
                enabled=False,
                tenant_visible=True,
            )
        )
        session.commit()

    create = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Support matrix blocked matter",
            "matter_code": "AUTO-ECT-BLOCKED",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "case_number": "WP(C) 3/2026",
            "cnr_number": "DLHC010033332026",
            "status": "intake",
        },
    )
    assert create.status_code == 200, create.text
    matter_id = create.json()["id"]

    listed = client.get("/api/case-tracking/bookmarks", headers=auth_headers(token))
    assert listed.status_code == 200, listed.text
    assert listed.json()["bookmarks"] == []
    with get_session_factory()() as session:
        assert session.scalar(select(TrackedCaseBookmark)) is None
        created_audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "matter.created",
                AuditEvent.matter_id == matter_id,
            )
        )
        assert created_audit is not None
        created_metadata = json.loads(created_audit.metadata_json or "{}")
        auto_link = created_metadata["case_tracking_auto_link"]
        assert auto_link["status"] == "blocked"
        assert "not enabled" in auto_link["reason"]


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
    assert search.json()["results"][0]["case_title"] == ("Example Petitioner v Example Respondent")
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
        if request.method == "GET" and request.url.path == "/api/partner/case/DLHC010012342026":
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
                                    "markdownContent": "# Interim order\n\nOfficial directions.",
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
        "https://webapi.ecourtsindia.com/api/partner/case/DLHC010012342026/order/order-1.pdf"
    )
    assert snapshot.orders[0].text == "# Interim order\n\nOfficial directions."
    assert snapshot.orders[0].text_truncated is False
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
                select(func.count())
                .select_from(TrackedCase)
                .where(TrackedCase.cnr_number == "DLHC010012342026")
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
    assert (
        client.get("/api/case-tracking/bookmarks", headers=auth_headers(token)).json()["bookmarks"]
        == []
    )


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
    assert body["created_updates"][0]["source_url"].startswith(
        f"/api/case-tracking/bookmarks/{bookmark_id}/updates/",
    )
    assert "provider.example" not in json.dumps(body)
    assert "lawyer review" in body["created_updates"][0]["ai_summary"]["review_framing"]

    with get_session_factory()() as session:
        legacy_update = session.scalar(select(TrackedCaseUpdate))
        assert legacy_update is not None
        legacy_update.source_text = None
        legacy_update.source_text_sha256 = None
        legacy_update.source_text_truncated = False
        session.commit()

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
    assert updates.json()["updates"][0]["source_url"].startswith(
        f"/api/case-tracking/bookmarks/{bookmark_id}/updates/",
    )
    assert "provider.example" not in json.dumps(updates.json())

    with get_session_factory()() as session:
        restored_update = session.scalar(select(TrackedCaseUpdate))
        assert restored_update is not None
        assert restored_update.source_text == (
            "The court issued directions and listed the matter."
        )
        assert restored_update.source_text_sha256
        assert restored_update.source_text_truncated is False
        operations = list(
            session.scalars(
                select(TrackedCaseProviderOperation).order_by(
                    TrackedCaseProviderOperation.created_at
                )
            )
        )
        snapshots = list(session.scalars(select(TrackedCaseProviderSnapshot)))
        assert [row.status for row in operations] == ["succeeded", "no_change"]
        assert [row.response_class for row in operations] == ["success", "no_change"]
        assert len(snapshots) == 2
        assert snapshots[0].raw_hash
        assert snapshots[0].normalized_hash
        assert "current_status" in snapshots[0].normalized_json
        assert operations[0].correlation_id != operations[1].correlation_id
        intents = list(session.scalars(select(NotificationDeliveryIntent)))
        assert len(intents) == 1
        assert intents[0].channel == "in_app"
        assert intents[0].event_type == "case_tracking.new_order"


def test_exact_release_smoke_is_qa_only_costed_and_idempotent(
    client: TestClient,
    monkeypatch,
) -> None:
    release_sha = "a" * 40
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", release_sha)
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://provider.example")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "server-side-token")
    get_settings.cache_clear()
    provider = FakeCaseTrackingProvider()
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider",
        lambda: provider,
    )
    token = _bootstrap(client)
    headers = auth_headers(token)
    create = client.post(
        "/api/case-tracking/bookmarks",
        headers=headers,
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "case_number": "WP(C) 1/2026",
            "court_code": "DLHC",
            "court_name": "Delhi High Court",
            "case_title": "Approved release smoke fixture",
            "notification_enabled": True,
            "metadata": {"release_smoke_fixture": True},
        },
    )
    assert create.status_code == 201, create.text
    bookmark_id = create.json()["id"]

    first = client.post(
        f"/api/case-tracking/bookmarks/{bookmark_id}/release-smoke",
        headers=headers,
        json={"release_sha": release_sha},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["release_sha"] == release_sha
    assert body["response_class"] == "success"
    assert body["reused"] is False
    assert body["bookmark"]["tracked_case"]["freshness_status"] == "fresh"
    assert body["bookmark"]["tracked_case"]["last_provider_successful_at"]
    assert body["source_update"]["source_url"].startswith(
        f"/api/case-tracking/bookmarks/{bookmark_id}/updates/"
    )
    assert "provider.example" not in json.dumps(body)

    second = client.post(
        f"/api/case-tracking/bookmarks/{bookmark_id}/release-smoke",
        headers=headers,
        json={"release_sha": release_sha},
    )
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is True
    assert second.json()["operation_id"] == body["operation_id"]
    assert provider.refresh_calls == ["DLHC010012342026"]

    stale = client.post(
        f"/api/case-tracking/bookmarks/{bookmark_id}/release-smoke",
        headers=headers,
        json={"release_sha": "b" * 40},
    )
    assert stale.status_code == 409
    assert "serving API revision" in stale.json()["detail"]

    with get_session_factory()() as session:
        operation = session.scalar(
            select(TrackedCaseProviderOperation).where(
                TrackedCaseProviderOperation.id == body["operation_id"]
            )
        )
        assert operation is not None
        assert operation.operation_type == "canary"
        assert operation.correlation_id == f"release:{release_sha}"
        assert operation.metadata_json["cost_disclosed"] is True
        audits = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "case_tracking.release_smoke")
            )
        )
        assert len(audits) == 1


def test_release_smoke_rejects_an_untagged_bookmark(
    client: TestClient,
    monkeypatch,
) -> None:
    release_sha = "c" * 40
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", release_sha)
    get_settings.cache_clear()
    token = _bootstrap(client)
    headers = auth_headers(token)
    create = client.post(
        "/api/case-tracking/bookmarks",
        headers=headers,
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010099992026",
            "court_code": "DLHC",
            "court_name": "Delhi High Court",
            "case_title": "Ordinary client bookmark",
        },
    )
    assert create.status_code == 201, create.text
    response = client.post(
        f"/api/case-tracking/bookmarks/{create.json()['id']}/release-smoke",
        headers=headers,
        json={"release_sha": release_sha},
    )
    assert response.status_code == 403
    assert "approved QA fixture" in response.json()["detail"]


def test_disposed_matter_blocks_case_tracking_refresh_before_provider_call(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Disposed tracked matter",
            "matter_code": "TRACK-DISPOSED",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "active",
        },
    )
    assert matter_response.status_code == 200, matter_response.text
    matter = matter_response.json()
    bookmark = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(token),
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "case_number": "WP(C) 1/2026",
            "court_code": "DLHC",
            "court_name": "Delhi High Court",
            "case_title": "Example Petitioner v Example Respondent",
            "matter_id": matter["id"],
            "notification_enabled": True,
        },
    )
    assert bookmark.status_code == 201, bookmark.text

    disposed = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": "disposed",
            "expected_from_status": "active",
            "expected_updated_at": matter["updated_at"],
            "reason": "Final judgment entered and file formally closed",
        },
    )
    assert disposed.status_code == 200, disposed.text

    forbidden_bookmark = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(token),
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010099992026",
            "case_number": "WP(C) 999/2026",
            "court_code": "DLHC",
            "court_name": "Delhi High Court",
            "case_title": "Disposed matter must not accept new tracking",
            "matter_id": matter["id"],
            "notification_enabled": True,
        },
    )
    assert forbidden_bookmark.status_code == 409, forbidden_bookmark.text

    provider = FakeCaseTrackingProvider()
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider",
        lambda: provider,
    )
    refresh = client.post(
        f"/api/case-tracking/bookmarks/{bookmark.json()['id']}/refresh",
        headers=auth_headers(token),
    )
    assert refresh.status_code == 409, refresh.text
    assert provider.refresh_calls == []

    with get_session_factory()() as session:
        persisted_matter = session.get(Matter, matter["id"])
        assert persisted_matter is not None
        assert persisted_matter.next_hearing_on is None
        assert session.scalar(select(TrackedCaseUpdate)) is None

    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with get_session_factory()() as session:
            runs = poll_tracked_cases(session, provider=provider)
            assert runs
            assert runs[0].checked_count == 0
            assert runs[0].provider_call_count == 0
            assert provider.bulk_refresh_calls == []
    finally:
        get_settings.cache_clear()


def test_case_tracking_source_download_uses_server_side_provider_auth(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
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
    update = refresh.json()["created_updates"][0]
    assert update["source_url"].startswith(
        f"/api/case-tracking/bookmarks/{bookmark_id}/updates/{update['id']}/source"
    )

    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://provider.example")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "server-side-token")
    get_settings.cache_clear()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer server-side-token"
        assert request.url.path == ("/api/partner/case/DLHC010012342026/order/order-1.pdf")
        return httpx.Response(
            200,
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="order-1.pdf"',
            },
            content=b"%PDF-1.4\nsource\n%%EOF",
        )

    try:
        context = _context_from_bootstrap(boot)
        with get_session_factory()() as session:
            download = download_case_tracking_source(
                session,
                context=context,
                bookmark_id=bookmark_id,
                update_id=update["id"],
                transport=httpx.MockTransport(handler),
            )
            assert download.content.startswith(b"%PDF")
            assert download.content_type == "application/pdf"
            assert download.filename == "order-1.pdf"
            assert download.source_format == "provider-document"
            assert requests
            assert (
                session.scalar(
                    select(AuditEvent).where(AuditEvent.action == "case_tracking.source_downloaded")
                )
                is not None
            )

            payment_responses = [
                {
                    "status": 402,
                    "error_code": "INSUFFICIENT_CREDITS",
                    "message": "Provider billing balance is insufficient.",
                },
                {"error": {"code": "SUBSCRIPTION_REQUIRED"}},
                "Payment required",
            ]
            for payment_response in payment_responses:
                def billing_handler(
                    request: httpx.Request,
                    response_body=payment_response,
                ) -> httpx.Response:
                    if isinstance(response_body, str):
                        return httpx.Response(402, text=response_body, request=request)
                    return httpx.Response(402, json=response_body, request=request)

                fallback = download_case_tracking_source(
                    session,
                    context=context,
                    bookmark_id=bookmark_id,
                    update_id=update["id"],
                    transport=httpx.MockTransport(billing_handler),
                )
                assert fallback.content == (
                    b"The court issued directions and listed the matter."
                )
                assert fallback.content_type == "text/markdown; charset=utf-8"
                assert fallback.filename.endswith(".md")
                assert fallback.source_format == "provider-markdown"

            def forbidden_handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(403, text="Forbidden", request=request)

            with pytest.raises(HTTPException) as forbidden:
                download_case_tracking_source(
                    session,
                    context=context,
                    bookmark_id=bookmark_id,
                    update_id=update["id"],
                    transport=httpx.MockTransport(forbidden_handler),
                )
            assert forbidden.value.status_code == 502

            stored = session.get(TrackedCaseUpdate, update["id"])
            assert stored is not None
            stored.source_text_sha256 = "0" * 64
            session.flush()
            with pytest.raises(HTTPException) as corrupted:
                download_case_tracking_source(
                    session,
                    context=context,
                    bookmark_id=bookmark_id,
                    update_id=update["id"],
                    transport=httpx.MockTransport(billing_handler),
                )
            assert corrupted.value.status_code == 409

            stored.source_text_sha256 = hashlib.sha256(
                stored.source_text.encode("utf-8")
            ).hexdigest()
            stored.source_text_truncated = True
            session.flush()
            with pytest.raises(HTTPException) as truncated:
                download_case_tracking_source(
                    session,
                    context=context,
                    bookmark_id=bookmark_id,
                    update_id=update["id"],
                    transport=httpx.MockTransport(billing_handler),
                )
            assert truncated.value.status_code == 503
    finally:
        get_settings.cache_clear()


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
            operation = session.scalar(select(TrackedCaseProviderOperation))
            assert operation is not None
            assert operation.status == "failed"
            assert operation.response_class == "authentication"
            assert operation.error_redacted == tracked.last_error
            assert operation.next_attempt_at is not None
            assert session.scalar(select(TrackedCaseProviderSnapshot)) is None
            page = session.scalar(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.event_type
                    == "case_tracking.provider_unhealthy"
                )
            )
            assert page is not None
            assert page.channel == "in_app"

        provider_calls_before_manual = len(provider.refresh_calls)
        blocked_manual = client.post(
            f"/api/case-tracking/bookmarks/{create.json()['id']}/refresh",
            headers=auth_headers(token),
        )
        assert blocked_manual.status_code == 409, blocked_manual.text
        assert len(provider.refresh_calls) == provider_calls_before_manual

        jobs = client.get(
            "/api/admin/provider-operations/jobs",
            headers=auth_headers(token),
        )
        assert jobs.status_code == 200, jobs.text
        record = next(
            row for row in jobs.json()["operations"] if row["job_kind"] == "case_tracking_record"
        )
        assert record["response_class"] == "authentication"
        assert record["retryable"] is True
        assert record["correlation_ref"]

        quarantined = client.post(
            f"/api/admin/provider-operations/jobs/{record['id']}/ignore",
            headers=auth_headers(token),
            json={"reason": "Poison record isolated while the remaining batch continues."},
        )
        assert quarantined.status_code == 200, quarantined.text
        assert quarantined.json()["operation"]["quarantined"] is True
        with get_session_factory()() as session:
            tracked = session.scalar(select(TrackedCase))
            assert tracked is not None
            assert tracked.quarantined_at is not None
            healthy = FakeCaseTrackingProvider()
            rerun = poll_tracked_cases(session, provider=healthy)
            assert rerun[0].checked_count == 0
            assert rerun[0].skipped_count >= 1
            assert healthy.refresh_calls == []

        preview = client.post(
            "/api/admin/provider-operations/jobs/replay-preview",
            headers=auth_headers(token),
            json={"operation_ids": [record["id"]]},
        )
        assert preview.status_code == 200, preview.text
        replayed = client.post(
            "/api/admin/provider-operations/jobs/replay",
            headers=auth_headers(token),
            json={
                "preview_token": preview.json()["preview_token"],
                "reason": "Retry quarantined record after provider authentication recovery.",
            },
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["operations"][0]["operation"]["status"] == "replay_queued"
        assert replayed.json()["operations"][0]["operation"]["mark_resolved_available"] is True

        premature_close = client.post(
            f"/api/admin/provider-operations/jobs/{record['id']}/resolve-incident",
            headers=auth_headers(token),
            json={
                "root_cause": "Provider authentication expired before the scheduled poll.",
                "prevention": "Alert on authentication response class before the next window.",
                "canary_evidence": "Replay is queued but has not yet succeeded.",
            },
        )
        assert premature_close.status_code == 409, premature_close.text

        with get_session_factory()() as session:
            canary = FakeCaseTrackingProvider()
            rerun = poll_tracked_cases(session, provider=canary)
            assert rerun[0].checked_count == 1
            operations = list(
                session.scalars(
                    select(TrackedCaseProviderOperation).order_by(
                        TrackedCaseProviderOperation.created_at
                    )
                )
            )
            assert [row.status for row in operations] == ["replay_queued", "succeeded"]
            assert operations[1].metadata_json["replay_of_operation_id"] == operations[0].id

        closed = client.post(
            f"/api/admin/provider-operations/jobs/{record['id']}/resolve-incident",
            headers=auth_headers(token),
            json={
                "root_cause": "Provider authentication expired before the scheduled poll.",
                "prevention": "Alert on authentication response class before the next window.",
                "canary_evidence": "Bounded single-record replay completed successfully.",
            },
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["operation"]["status"] == "resolved"
        with get_session_factory()() as session:
            incident = session.scalar(
                select(TrackedCaseProviderOperation).where(
                    TrackedCaseProviderOperation.status == "resolved"
                )
            )
            assert incident is not None
            assert incident.metadata_json["incident_prevention"]
            assert incident.metadata_json["incident_canary_operation_id"]
    finally:
        get_settings.cache_clear()


def test_case_tracking_automatic_retries_are_bounded_and_auto_quarantine(
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
        for attempt in range(1, 4):
            if attempt > 1:
                with get_session_factory()() as session:
                    tracked = session.scalar(select(TrackedCase))
                    retryable = session.scalar(
                        select(TrackedCaseProviderOperation)
                        .where(TrackedCaseProviderOperation.status == "failed")
                        .order_by(TrackedCaseProviderOperation.created_at.desc())
                    )
                    assert tracked is not None
                    assert retryable is not None
                    due = datetime.now(UTC) - timedelta(minutes=1)
                    tracked.next_provider_refresh_at = due
                    retryable.next_attempt_at = due
                    session.commit()
            with get_session_factory()() as session:
                run = poll_tracked_cases(session, provider=provider, force=True)[0]
                assert run.error_count == 1

        with get_session_factory()() as session:
            operations = list(
                session.scalars(
                    select(TrackedCaseProviderOperation).order_by(
                        TrackedCaseProviderOperation.created_at
                    )
                )
            )
            tracked = session.scalar(select(TrackedCase))
            assert tracked is not None
            assert [row.attempts for row in operations] == [1, 2, 3]
            assert [row.status for row in operations] == ["failed", "failed", "quarantined"]
            assert operations[1].metadata_json["retry_of_operation_id"] == operations[0].id
            assert operations[2].metadata_json["retry_of_operation_id"] == operations[1].id
            assert tracked.quarantined_at is not None
            assert tracked.provider_freshness_status == "blocked"

        jobs = client.get(
            "/api/admin/provider-operations/jobs",
            headers=auth_headers(token),
        )
        assert jobs.status_code == 200, jobs.text
        quarantined_record = next(
            row
            for row in jobs.json()["operations"]
            if row["job_kind"] == "case_tracking_record" and row["status"] == "quarantined"
        )
        assert quarantined_record["replay_available"] is True

        poison_probe = FakeCaseTrackingProvider(fail_refresh=True)
        with get_session_factory()() as session:
            run = poll_tracked_cases(session, provider=poison_probe, force=True)[0]
            assert run.checked_count == 0
            assert run.provider_call_count == 0
            assert poison_probe.bulk_refresh_calls == []
    finally:
        get_settings.cache_clear()


def test_case_tracking_cnr_normalization() -> None:
    assert normalize_cnr(" dlhc-0100 1234-2026 ") == "DLHC010012342026"
    assert normalize_cnr("   ") is None
