from datetime import date, timedelta
from http import HTTPStatus
from urllib.parse import urlencode

import httpx
import pytest

from caseops_api.db.models import TrackedCase
from caseops_api.scripts.docker_acceptance_case_provider import AcceptanceProviderHandler
from caseops_api.scripts.docker_acceptance_hearing_provider import HearingAcceptanceHandler
from caseops_api.services.case_tracking import _validated_sync_snapshot
from caseops_api.services.case_tracking_providers import (
    CaseSearchQuery,
    CaseTrackingProviderError,
    EcourtsIndiaApiProvider,
    _snapshot_from_payload,
)
from caseops_api.services.hearing_matching import HearingIdentity
from tests import test_20260910_legacy_hearing_emulator as legacy


@pytest.fixture(autouse=True)
def combined_provider(monkeypatch):
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "emulator-test-only")
    monkeypatch.setattr(legacy, "AcceptanceProviderHandler", HearingAcceptanceHandler)


def provider():
    def transport(request):
        status, payload = legacy.respond(str(request.url.raw_path, "ascii"))
        return httpx.Response(status, json=payload)

    return EcourtsIndiaApiProvider(
        base_url="https://provider.test/api/partner",
        token="emulator-test-only",
        transport=httpx.MockTransport(transport),
    )


@pytest.mark.parametrize("mode", ["cnr", "case", "filing"])
def test_combined_service_preserves_september10_nearest_seven_day_fixture(mode):
    cnr = "DLHC010081232026" if mode == "cnr" else None
    number = "421/2026" if mode == "filing" else "WP(C) 8123/2026"
    case = TrackedCase(cnr_number=cnr, case_number=number, court_name="Delhi High Court")
    expected = HearingIdentity(
        cnr=cnr,
        filing_number=number if mode == "filing" else None,
        case_number=number if mode == "case" else None,
        court_name="Delhi High Court",
    )
    snapshots = provider().search_cases(
        query=CaseSearchQuery(
            cnr_number=cnr,
            case_number=number,
            court_name=case.court_name,
            require_complete_results=True,
        )
    )
    assert _validated_sync_snapshot(
        case, snapshots, identities=(expected,)
    ).next_hearing_on == date.today() + timedelta(days=7)


@pytest.mark.parametrize("mode", ["cnr", "case"])
def test_combined_service_preserves_older_twenty_one_day_fixture(mode):
    case = TrackedCase(
        cnr_number="DLHC010091232026" if mode == "cnr" else None,
        case_number="WP(C) 9123/2026",
        court_name="Delhi High Court",
    )
    snapshots = provider().search_cases(
        query=CaseSearchQuery(
            cnr_number=case.cnr_number,
            case_number=case.case_number,
            court_name=case.court_name,
            require_complete_results=True,
        )
    )
    assert _validated_sync_snapshot(case, snapshots).next_hearing_on == date.today() + timedelta(
        days=21
    )


def test_combined_service_keeps_ambiguous_september10_results_unselected():
    case = TrackedCase(case_number="WP(C) 889/2026", court_name="Delhi High Court")
    snapshots = provider().search_cases(
        query=CaseSearchQuery(
            case_number=case.case_number,
            court_name=case.court_name,
            require_complete_results=True,
        )
    )
    assert len(snapshots) == 2
    with pytest.raises(CaseTrackingProviderError) as ambiguous:
        _validated_sync_snapshot(case, snapshots)
    assert ambiguous.value.response_class == "ambiguous_match"


def test_hume_source_path_delegates_before_any_case_detail_interception(monkeypatch):
    source_path = "/api/partner/case/DLHC010091232026/order/summary-20260910"
    routed = []

    def hume_source_handler(self):
        assert self.path == source_path
        routed.append(self.path)
        self._write_json(HTTPStatus.OK, {"source_handler": "Hume"})

    monkeypatch.setattr(AcceptanceProviderHandler, "do_GET", hume_source_handler)
    assert legacy.respond(source_path) == (HTTPStatus.OK, {"source_handler": "Hume"})
    assert routed == [source_path]


def test_official_hearing_date_is_not_business_date_or_order_date():
    snapshot = _snapshot_from_payload(
        {
            "data": {
                "courtCaseData": {
                    "historyOfCaseHearings": [
                        {
                            "businessOnDate": "2026-09-10",
                            "hearingDate": "2026-09-17",
                            "purposeOfListing": "Arguments",
                        }
                    ],
                    "orders": [{"date": "2026-09-09", "hearingDate": "2026-09-17"}],
                }
            }
        },
        provider="ecourtsindia",
    )
    assert [row.event_date for row in snapshot.hearings] == [date(2026, 9, 17)]
    assert [row.event_date for row in snapshot.orders] == [date(2026, 9, 9)]


@pytest.mark.parametrize("query", ["Old general query", "WP(C) 9123/2026"])
def test_older_general_search_routes_remain_owned_by_base_handler(query):
    status, payload = legacy.respond(f"/api/partner/search?{urlencode({'query': query})}")
    assert status == HTTPStatus.OK
    assert payload["data"]["results"][0]["caseNumber"] == query
