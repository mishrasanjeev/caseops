import httpx
import pytest

from caseops_api.db.models import TrackedCase
from caseops_api.services.case_tracking import _verified_sync_snapshot_identity
from caseops_api.services.case_tracking_providers import (
    CaseSearchQuery,
    CaseTrackingProviderError,
    EcourtsIndiaApiProvider,
    _snapshot_from_payload,
)
from caseops_api.services.hearing_matching import (
    HearingIdentity,
    identity_matches,
    provider_identity,
    reliable_identity,
    search_number,
)


def snapshot(**changes):
    return _snapshot_from_payload(
        {
            "cnr": "DLHC010091232026",
            "registrationNumber": "9123/2026",
            "caseType": "WP_C",
            "courtCode": "DLHC01",
            "courtName": "Delhi High Court",
            "state": "Delhi",
            "district": "New Delhi",
            "filingNumber": "321/2026",
            "petitioners": ["Example Petitioner"],
            "respondents": ["Example Respondent"],
            "respondentAdvocates": ["Example Counsel"],
            **changes,
        },
        provider="ecourtsindia",
    )


def tracked(**changes):
    return TrackedCase(case_number="WP(C) 9123/2026", court_code="DLHC01", **changes)


def test_typed_matter_number_matches_separate_official_registration_and_type():
    result = snapshot()
    assert _verified_sync_snapshot_identity(tracked(), [result]) is result


def test_reported_ncdrc_public_identity_matches_complete_synthetic_provider_evidence():
    court = "National Consumer Disputes Redressal Commission"
    result = snapshot(
        cnr="NCDR010008782024",
        registrationNumber="878/2024",
        caseType="FA",
        courtName=court,
        courtCode="NCDRC",
    )
    matter_identity = HearingIdentity(case_number="FA/878/2024", court_name=court, city="New Delhi")
    assert (
        _verified_sync_snapshot_identity(
            TrackedCase(case_number="FA/878/2024", court_name=court),
            [result],
            identities=(matter_identity,),
        )
        is result
    )


def test_conflicting_official_case_type_is_not_an_exact_number_match():
    with pytest.raises(CaseTrackingProviderError):
        _verified_sync_snapshot_identity(
            tracked(), [snapshot(registrationNumber="WP(C) 9123/2026", caseType="FA")]
        )


def test_primary_cnr_never_falls_back_to_matching_number_or_names():
    with pytest.raises(CaseTrackingProviderError) as failure:
        _verified_sync_snapshot_identity(tracked(cnr_number="DLHC010099992026"), [snapshot()])
    assert failure.value.response_class == "match_validation_failed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("filing_number", "999/2026"),
        ("state", "Punjab"),
        ("district", "Mumbai"),
        ("parties", ("Different Party",)),
        ("advocates", ("Different Counsel",)),
    ],
)
def test_corroborating_identity_conflicts_fail_closed(field, value):
    expected = HearingIdentity(case_number="WP(C) 9123/2026", court_code="DLHC01", **{field: value})
    assert not identity_matches(expected, snapshot().matching_identity)


@pytest.mark.parametrize("number", ["OA/672/2025", "FA/753/2024", "FA/660/2024", None])
def test_reported_missing_courts_never_match_by_title_or_parties(number):
    expected = HearingIdentity(case_number=number, parties=("Example Petitioner",))
    assert not identity_matches(expected, snapshot().matching_identity)


def test_filing_only_identifier_uses_public_number_and_court():
    expected = HearingIdentity(filing_number="321/2026", court_name="Delhi High Court")
    assert search_number(expected) == "321/2026"
    assert identity_matches(expected, snapshot().matching_identity)


@pytest.mark.parametrize("cnr", ["UNKNOWN", "DLHC01009123202", "1234010091232026"])
def test_malformed_primary_cnr_never_falls_back_to_secondary_identifiers(cnr):
    expected = HearingIdentity(cnr=cnr, case_number="9123/2026", court_code="DLHC01")
    assert not reliable_identity(expected)
    assert not identity_matches(expected, snapshot().matching_identity)


def test_provider_geography_uses_published_enum_label_before_abbreviation():
    actual = provider_identity(
        {
            "state": "DL",
            "stateCode": "26",
            "districtCode": "7",
            "registrationNumber": "9123/2026",
            "courtName": "Delhi High Court",
        },
        {"enumLookup": {"stateCode": {"26": "Delhi"}, "districtCode": {"7": "New Delhi"}}},
    )
    assert identity_matches(
        HearingIdentity(
            case_number="9123/2026",
            court_name="Delhi High Court",
            state="Delhi",
            district="New Delhi",
        ),
        actual,
    )


def test_automatic_search_rejects_missing_public_number_before_transport():
    def unexpected_transport(request):
        pytest.fail("Invalid identity must not dispatch a credit-bearing request")

    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.test/api/partner",
        token="unused-fixture",
        transport=httpx.MockTransport(unexpected_transport),
    )
    with pytest.raises(CaseTrackingProviderError):
        provider.search_cases(
            query=CaseSearchQuery(query="Example Petitioner", require_complete_results=True)
        )


def test_ambiguous_candidates_are_never_selected():
    with pytest.raises(CaseTrackingProviderError) as failure:
        _verified_sync_snapshot_identity(tracked(), [snapshot(), snapshot(cnr="DLHC010091242026")])
    assert failure.value.response_class == "ambiguous_match"


@pytest.mark.parametrize(
    "pagination",
    [
        {"hasNextPage": True},
        {"totalHits": 21},
        {"totalHits": "1"},
        {"hasNextPage": "false"},
    ],
)
def test_automatic_search_rejects_incomplete_or_malformed_candidate_inventory(pagination):
    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.test/api/partner",
        token="unused-fixture",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"data": {"results": [{"cnr": "DLHC010091232026"}], **pagination}},
            )
        ),
    )
    with pytest.raises(CaseTrackingProviderError):
        provider.search_cases(
            query=CaseSearchQuery(
                case_number="9123/2026", court_code="DLHC01", require_complete_results=True
            )
        )


def test_primary_cnr_ignores_secondary_identity_changes_in_provider_response():
    result = snapshot(registrationNumber="888/2027", state="Punjab")
    assert (
        _verified_sync_snapshot_identity(tracked(cnr_number=result.cnr_number), [result]) is result
    )


def test_bounded_official_search_uses_supported_public_number_filter():
    requests = []

    def transport(request):
        requests.append(request)
        assert request.url.params["caseNumbers"] == "9123/2026"
        assert request.url.params["courtCodes"] == "DLHC01"
        assert "courtName" not in request.url.params and "query" not in request.url.params
        return httpx.Response(
            200,
            json={
                "data": {
                    "results": [
                        {
                            "cnr": "DLHC010091232026",
                            "registrationNumber": "9123/2026",
                            "caseType": "WP_C",
                            "courtCode": "DLHC01",
                        }
                    ],
                    "totalHits": 1,
                    "hasNextPage": False,
                }
            },
        )

    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.test/api/partner",
        token="unused-fixture",
        transport=httpx.MockTransport(transport),
    )
    results = provider.search_cases(
        query=CaseSearchQuery(
            case_number="WP(C) 9123/2026",
            court_code="DLHC01",
            court_name="Delhi High Court",
            require_complete_results=True,
        )
    )
    assert _verified_sync_snapshot_identity(tracked(), results).cnr_number == "DLHC010091232026"
    assert len(requests) == 1
