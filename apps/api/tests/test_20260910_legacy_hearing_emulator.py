import io
import json
from datetime import date, timedelta
from http import HTTPStatus
from urllib.parse import urlencode

import httpx
import pytest

from caseops_api.db.models import TrackedCase
from caseops_api.scripts.docker_acceptance_case_provider import AcceptanceProviderHandler
from caseops_api.services.case_tracking import _validated_sync_snapshot
from caseops_api.services.case_tracking_providers import CaseSearchQuery, EcourtsIndiaApiProvider


def respond(path, *, method="GET", payload=None, authorized=True):
    handler = object.__new__(AcceptanceProviderHandler)
    handler.path = path
    handler.headers = {}
    if authorized:
        handler.headers["Authorization"] = "Bearer emulator-test-only"
    body = json.dumps(payload).encode() if payload is not None else b""
    handler.headers["Content-Length"] = str(len(body))
    handler.rfile = io.BytesIO(body)
    responses = []
    handler._write_json = lambda status, data: responses.append((status, data))
    getattr(handler, f"do_{method}")()
    assert len(responses) == 1
    return responses[0]


@pytest.fixture(autouse=True)
def emulator_token(monkeypatch):
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "emulator-test-only")


@pytest.mark.parametrize(
    "field,value",
    [
        ("caseNumbers", "WP(C) 9123/2026"),
        ("caseNumbers", "9123/2026"),
        ("caseNumbers", "FA/878/2024"),
        ("query", "Original general query"),
    ],
)
def test_old_search_retains_every_original_field_and_date(field, value):
    status, response = respond(f"/api/partner/search?{urlencode({field: value})}")
    assert status == HTTPStatus.OK
    data = response["data"]
    assert data["totalHits"] == 1 and data["hasNextPage"] is False
    assert data["page"] == data["totalPages"] == 1
    assert data["pageSize"] == 20 and data["hasPreviousPage"] is False
    assert data["enumDescriptions"] == data["descriptions"]
    row = data["results"][0]
    original = {
        "cnr": "DLHC010091232026",
        "caseNumber": value,
        "cnrCourtCode": "DLHC",
        "petitioners": ["Local Docker Petitioner"],
        "respondents": ["Local Docker Respondent"],
        "caseStatus": "PENDING",
        "stage": "Arguments",
        "nextHearingDate": f"{date.today() + timedelta(days=21)}T00:00:00Z",
    }
    assert {key: row[key] for key in original} == original


@pytest.mark.parametrize("cnr", ["DLHC010091232026", "DLHC010099992026"])
def test_old_detail_and_refresh_contracts_remain_unchanged(cnr):
    status, payload = respond(f"/api/partner/case/{cnr}")
    assert status == HTTPStatus.OK
    row = payload["data"]["courtCaseData"]
    assert row["cnr"] == cnr and row["caseNumber"] == "WP(C) 9123/2026"
    assert row["registrationNumber"] == "9123/2026" and row["caseType"] == "WP_C"
    assert row["nextHearingDate"] == f"{date.today() + timedelta(days=21)}T00:00:00Z"
    status, refreshed = respond(
        "/api/partner/case/bulk-refresh", method="POST", payload={"cnrs": [cnr]}
    )
    assert status == HTTPStatus.OK
    assert refreshed == {"data": {"refreshed": [cnr], "queued": [], "invalid": []}}
    status, completed = respond(
        "/api/partner/case/bulk-refresh-status", method="POST", payload={"cnrs": [cnr]}
    )
    assert status == HTTPStatus.OK
    result = completed["data"]["results"][0]
    assert result["cnr"] == cnr and result["status"] == "COMPLETED"
    assert (
        result["failureReason"] is None
        and result["creditsCharged"] == 0
        and result["refunded"] is False
    )


@pytest.mark.parametrize("mode", ["cnr", "case"])
def test_prior_dated_journey_matches_official_envelope_without_changing_21_day_result(mode):
    def transport(request):
        status, payload = respond(str(request.url.raw_path, "ascii"))
        return httpx.Response(status, json=payload)

    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.test/api/partner",
        token="emulator-test-only",
        transport=httpx.MockTransport(transport),
    )
    tracked = TrackedCase(
        case_number="WP(C) 9123/2026",
        court_name="Delhi High Court",
        cnr_number="DLHC010091232026" if mode == "cnr" else None,
    )
    query = CaseSearchQuery(
        cnr_number=tracked.cnr_number,
        case_number=tracked.case_number,
        court_name=tracked.court_name,
        require_complete_results=True,
    )
    snapshot = _validated_sync_snapshot(tracked, provider.search_cases(query=query))
    assert snapshot.next_hearing_on == date.today() + timedelta(days=21)


@pytest.mark.parametrize(
    "path,authorized,expected",
    [
        ("/health", False, HTTPStatus.OK),
        ("/api/partner/search?caseNumbers=9123/2026", False, HTTPStatus.UNAUTHORIZED),
        ("/api/partner/search", True, HTTPStatus.BAD_REQUEST),
        ("/api/partner/case/invalid/path", True, HTTPStatus.NOT_FOUND),
        ("/unknown", True, HTTPStatus.NOT_FOUND),
    ],
)
def test_prior_endpoint_guards_are_preserved(path, authorized, expected):
    assert respond(path, authorized=authorized)[0] == expected
