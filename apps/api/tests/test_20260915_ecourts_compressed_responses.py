"""eCourtsIndia replies compressed by the provider CDN must reach the UI once decoded.

On 2026-09-15 production returned HTTP 200 for ``/api/partner/case/{cnr}`` but
CaseOps answered 502, because the buffered response kept ``Content-Encoding``
and decoded the already-decoded body a second time. The bookmark kept its stale
court data and the next refresh was held behind the transient-failure cooldown.
"""

from __future__ import annotations

import gzip
import json
import zlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
import zstandard
from fastapi.testclient import TestClient

from caseops_api.scripts.docker_acceptance_case_provider import AcceptanceProviderHandler
from caseops_api.services.case_tracking_providers import (
    CaseSearchQuery,
    CaseTrackingProviderError,
    EcourtsIndiaApiProvider,
    download_provider_source,
)
from tests.test_auth_company import auth_headers, bootstrap_company

CNR = "DLND020389022025"
ENCODERS: dict[str, Callable[[bytes], bytes]] = {
    "gzip": gzip.compress,
    "deflate": zlib.compress,
    "zstd": lambda body: zstandard.ZstdCompressor().compress(body),
}


def _next_hearing() -> str:
    return (datetime.now(UTC).date() + timedelta(days=50)).isoformat()


def _district_case(next_hearing: str) -> dict[str, object]:
    """The live partner detail shape, with synthetic party names."""

    return {
        "caseNumber": "202400191142025",
        "state": "DL",
        "courtCode": 2,
        "courtName": "Chief Metropolitan Magistrate, New Delhi, PHC",
        "courtNo": 2,
        "historyOfCaseHearings": [
            {"hearingDate": "2026-07-31", "purpose": "Appearance"},
        ],
        "purpose": "Misc./ Appearance",
        "stageOfCase": "APPEARANCE",
        "lastHearingDate": "2026-07-31",
        "interimOrders": [],
        "cnr": CNR,
        "cnrCourtCode": "DLND02",
        "caseType": "CC",
        "caseStatus": "PENDING",
        "filingNumber": "38903/2025",
        "registrationNumber": "19114/2025",
        "nextHearingDate": next_hearing,
        "petitioners": ["Synthetic Complainant"],
        "respondents": ["Synthetic Respondent"],
        "judgmentOrders": [],
    }


def _detail_payload(next_hearing: str) -> dict[str, object]:
    return {
        "data": {
            "courtCaseData": _district_case(next_hearing),
            "entityInfo": {"cnr": CNR, "nextDateOfHearing": f"{next_hearing}T00:00:00Z"},
            "files": {"files": []},
            "descriptions": {
                "enumLookup": {
                    "caseStatus": {"PENDING": "Pending"},
                    "courtCode": {"2": "Chief Metropolitan Magistrate, New Delhi, PHC"},
                }
            },
            "caseAiAnalysis": None,
        },
        "meta": {"request_id": "synthetic"},
    }


def _encoded(
    status_code: int, payload: object, encoding: str, request: httpx.Request
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={
            "content-type": "application/json; charset=utf-8",
            "content-encoding": encoding,
            "vary": "Accept-Encoding",
        },
        content=ENCODERS[encoding](json.dumps(payload).encode("utf-8")),
        request=request,
    )


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> EcourtsIndiaApiProvider:
    return EcourtsIndiaApiProvider(
        base_url="https://webapi.ecourtsindia.com",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("encoding", sorted(ENCODERS))
def test_compressed_case_detail_and_search_are_decoded_once(encoding: str) -> None:
    next_hearing = _next_hearing()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/partner/case/{CNR}":
            return _encoded(200, _detail_payload(next_hearing), encoding, request)
        if request.url.path == "/api/partner/search":
            return _encoded(
                200,
                {
                    "data": {
                        "results": [_district_case(next_hearing)],
                        "totalHits": 1,
                        "hasNextPage": False,
                    }
                },
                encoding,
                request,
            )
        return _encoded(404, {"detail": "Case not found"}, encoding, request)

    provider = _provider(handler)

    detail = provider.get_case_by_cnr(cnr=CNR)
    assert detail.cnr_number == CNR
    assert detail.case_number == "19114/2025"
    assert detail.court_code == "DLND02"
    assert detail.current_stage == "Misc./ Appearance"
    assert detail.next_hearing_on.isoformat() == next_hearing
    assert len(detail.hearings) == 1

    matches = provider.search_cases(
        query=CaseSearchQuery(
            case_number="19114/2025", court_code="DLND02", require_complete_results=True
        )
    )
    assert [match.cnr_number for match in matches] == [CNR]

    # A compressed provider 404 is still "not found", not a gateway failure.
    with pytest.raises(CaseTrackingProviderError) as missing:
        provider.get_case_by_cnr(cnr="DLND020000012025")
    assert missing.value.response_class == "case_not_found"
    assert missing.value.http_status_code == 404


@pytest.mark.parametrize("encoding", sorted(ENCODERS))
def test_compressed_scheduled_refresh_protocol_is_decoded_once(encoding: str) -> None:
    next_hearing = _next_hearing()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/partner/case/bulk-refresh-status":
            return _encoded(
                200,
                {
                    "data": {
                        "results": [
                            {
                                "cnr": CNR,
                                "status": "COMPLETED",
                                "requestedAt": datetime.now(UTC).isoformat(),
                            }
                        ]
                    }
                },
                encoding,
                request,
            )
        assert request.url.path == f"/api/partner/case/{CNR}"
        return _encoded(200, _detail_payload(next_hearing), encoding, request)

    result = _provider(handler).refresh_cases(cnrs=[CNR])

    assert result.errors == {}
    assert [snapshot.cnr_number for snapshot in result.snapshots] == [CNR]
    assert result.confirmed_cost_minor_by_cnr == {CNR: 150}


def test_compressed_source_download_is_decoded_once() -> None:
    body = b"# Order\n\nListed for appearance."

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "text/markdown; charset=utf-8",
                "content-encoding": "gzip",
                "content-disposition": 'attachment; filename="order-1.md"',
            },
            content=gzip.compress(body),
            request=request,
        )

    response = download_provider_source(
        url=f"https://webapi.ecourtsindia.com/api/partner/case/{CNR}/order/order-1.pdf",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    assert response.content == body
    assert response.headers["content-disposition"] == 'attachment; filename="order-1.md"'
    assert "content-encoding" not in response.headers


def test_docker_acceptance_provider_compresses_like_the_live_cdn(monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "loopback-token")
    server = ThreadingHTTPServer(("127.0.0.1", 0), AcceptanceProviderHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(trust_env=False) as client:
            raw = client.get(
                f"{base_url}/api/partner/case/DLHC010091232026",
                headers={"Authorization": "Bearer loopback-token", "Accept-Encoding": "gzip"},
            )
        assert raw.headers["content-encoding"] == "gzip"

        snapshot = EcourtsIndiaApiProvider(
            base_url=base_url, token="loopback-token"
        ).get_case_by_cnr(cnr="DLHC010091232026")
        assert snapshot.cnr_number == "DLHC010091232026"
        assert snapshot.court_name == "Delhi High Court"
    finally:
        server.shutdown()
        server.server_close()


def test_compressed_refresh_replaces_stale_bookmark_data_in_the_ui_contract(
    client: TestClient,
    monkeypatch,
) -> None:
    next_hearing = _next_hearing()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        assert request.url.path == f"/api/partner/case/{CNR}"
        return _encoded(200, _detail_payload(next_hearing), "gzip", request)

    provider = _provider(handler)
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider",
        lambda: provider,
    )
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)

    stale = client.post(
        "/api/case-tracking/bookmarks",
        headers=headers,
        json={
            "provider": "ecourtsindia",
            "cnr_number": CNR,
            "case_number": "19114/2025",
            "court_code": "DLND02",
            "court_name": "Chief Metropolitan Magistrate, New Delhi, PHC",
            "case_title": "Synthetic Complainant v Synthetic Respondent",
            "current_status": "Pending",
            "current_stage": "Evidence",
            "next_hearing_on": "2026-07-31",
            "notification_enabled": True,
        },
    )
    assert stale.status_code == 201, stale.text
    bookmark_id = stale.json()["id"]

    refresh = client.post(f"/api/case-tracking/bookmarks/{bookmark_id}/refresh", headers=headers)

    assert refresh.status_code == 200, refresh.text
    refreshed = refresh.json()["bookmark"]["tracked_case"]
    assert refreshed["current_stage"] == "Misc./ Appearance"
    assert refreshed["next_hearing_on"] == next_hearing
    assert refreshed["last_error"] is None
    assert refreshed["response_class"] != "provider_error"
    assert refreshed["last_provider_successful_at"] is not None
    assert requests == [f"/api/partner/case/{CNR}"]

    listed = client.get("/api/case-tracking/bookmarks", headers=headers)
    assert listed.status_code == 200, listed.text
    tracked = listed.json()["bookmarks"][0]["tracked_case"]
    assert tracked["current_stage"] == "Misc./ Appearance"
    assert tracked["next_hearing_on"] == next_hearing
    assert tracked["last_error"] is None
