"""Production run 36276564868 (2026-09-27): a Matter must be told *why* it cannot match.

The 2026-09-24 QA journey recorded ``WP(C) <six hex characters>/2026``. The
public-number parser reads digits, so that fixture parsed only when the hex slice
happened to end in a digit and the journey passed 62.5% of runs; on the release
that unified the manual and scheduled identity policy it drew ``6d661b`` and the
page said "Insufficient case identifiers" for a case number that visibly carried
a type, a year and a court. These regressions pin three things:

- the parser reads the common spellings of one case identity and rejects a
  compound entry (two numbers) instead of guessing;
- search, resolve and link name the exact gap (invalid CNR, missing
  identifiers, unreadable case number, case type required) with the recorded
  value, on the same policy as refresh;
- the blocked paid-provider body carries its ``code`` at the top level, which is
  the shape the dated browser specs assert (RFC 7807 flattening);
- review of that change (P1): automatic linking at Matter creation, the scheduled
  existing-Matter backfill, and the refresh and polling of automatic links apply
  the same decision, so a bare number/year can never find a case - or publish a
  hearing date - through an automatic path that manual linking rejects.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_HEADER,
    NO_PAID_PROVIDERS_VALUE,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, Matter, TrackedCaseBookmark
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import poll_tracked_cases
from caseops_api.services.case_tracking_providers import CaseSearchQuery, ProviderCaseSnapshot
from caseops_api.services.hearing_matching import (
    CASE_NUMBER_UNREADABLE,
    CASE_TYPE_REQUIRED,
    CNR_INVALID,
    IDENTITY_REQUIRED,
    HearingIdentity,
    identity_gap,
    public_number,
    search_number,
)
from tests.test_20260904_auto_next_hearing_sync import DatedSyncProvider, _enable_tracking
from tests.test_auth_company import auth_headers
from tests.test_case_tracking import ExplodingLiveCaseTrackingProvider, _bootstrap

COURT = "Delhi High Court"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("WP(C) 6209/2019", ("WPC", "6209", "2019")),
        ("W.P.(C) 6209/2019", ("WPC", "6209", "2019")),
        ("WP(C)/9123/2026", ("WPC", "9123", "2026")),
        ("WP(CIVIL)/6209/2019", ("WPCIVIL", "6209", "2019")),
        ("W.P.(C) No. 6209 of 2019", ("WPC", "6209", "2019")),
        ("WP(C) No.6209/2019", ("WPC", "6209", "2019")),
        ("O.S. No. 45 of 2019", ("OS", "45", "2019")),
        ("CWP-1234-2020", ("CWP", "1234", "2020")),
        ("CRL.A. 123/2019", ("CRLA", "123", "2019")),
        ("CS(COMM) 100/2021", ("CSCOMM", "100", "2021")),
        ("ARB/44/2026", ("ARB", "44", "2026")),
        # Provider registration numbers are untyped number/year values.
        ("6209/2019", ("", "6209", "2019")),
        ("No. 45 of 2019", ("", "45", "2019")),
        ("0045/2019", ("", "45", "2019")),
    ],
)
def test_public_number_reads_one_case_identity_in_its_common_spellings(value, expected):
    assert public_number(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "WP(C) 6d661b/2026",  # the 2026-09-24 fixture that drew a trailing letter
        "WP(C) 9c1234/2026",  # a letter inside the number is still not a number
        "FIR 145/2025 + Crl. M.C. 412/2026",  # two records; never guess which one
        "W.P.(C) 6209/2019 with CM APPL. 12345/2026",
        "ITA No.1234/Del/2019",
        "WP(C) 6209/19",
        "CASE-777",
        "DLHC010317282019",
        "Case number",
        "",
        None,
    ],
)
def test_public_number_rejects_what_is_not_one_registry_number(value):
    assert public_number(value) is None


@pytest.mark.parametrize(
    ("identity", "gap"),
    [
        (HearingIdentity(cnr="DLHC010317282019"), None),
        (HearingIdentity(cnr="DLHC_0103-1728.2019"), None),
        (
            HearingIdentity(cnr="DLHC0103", case_number="WP(C) 1/2026", court_name=COURT),
            "invalid_cnr",
        ),
        (HearingIdentity(case_number="WP(C) 1/2026"), "missing_identifiers"),
        (HearingIdentity(court_name=COURT), "missing_identifiers"),
        (
            HearingIdentity(case_number="WP(C) 6d661b/2026", court_name=COURT),
            "unreadable_case_number",
        ),
        (
            HearingIdentity(
                case_number="WP(C) 6d661b/2026", filing_number="321/2026", court_name=COURT
            ),
            "unreadable_case_number",
        ),
        (HearingIdentity(filing_number="F-321", court_name=COURT), "unreadable_case_number"),
        (HearingIdentity(case_number="6209/2019", court_name=COURT), "case_type_required"),
        (HearingIdentity(case_number="W.P.(C) No. 6209 of 2019", court_name=COURT), None),
        (HearingIdentity(filing_number="321/2026", court_name=COURT), None),
    ],
)
def test_identity_gap_names_exactly_one_reason(identity, gap):
    assert identity_gap(identity) == gap


def _create_matter(client: TestClient, token: str, code: str, **fields: object) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Readability {code}",
            "matter_code": code,
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": COURT,
            "status": "intake",
            **fields,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _enable_case_tracking(monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://webapi.ecourtsindia.com")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "must-not-be-used")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider",
        ExplodingLiveCaseTrackingProvider,
    )


@pytest.mark.parametrize(
    ("fields", "reason", "message"),
    [
        (
            {"case_number": "WP(C) 6d661b/2026"},
            "unreadable_case_number",
            CASE_NUMBER_UNREADABLE,
        ),
        ({"case_number": "6209/2019"}, "case_type_required", CASE_TYPE_REQUIRED),
        ({"case_number": None}, "missing_identifiers", IDENTITY_REQUIRED),
        (
            {"case_number": "WP(C) 1/2026", "cnr_number": "DLHC0103"},
            "invalid_cnr",
            CNR_INVALID,
        ),
    ],
)
def test_resolve_and_search_name_the_gap_before_any_provider_call(
    client: TestClient, monkeypatch, fields, reason, message
) -> None:
    _enable_case_tracking(monkeypatch)
    token = _bootstrap(client)
    matter_id = _create_matter(client, token, f"GAP-{reason.replace('_', '-').upper()}", **fields)

    resolved = client.post(
        f"/api/case-tracking/matters/{matter_id}/resolve", headers=auth_headers(token)
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json() == {
        "status": "insufficient_identifiers",
        "provider": "ecourtsindia",
        "results": [],
        "reason": reason,
        "case_number": fields.get("case_number"),
        "cnr_number": fields.get("cnr_number"),
    }

    searched = client.post(
        "/api/case-tracking/search",
        headers=auth_headers(token),
        json={"matter_id": matter_id, "cnr_number": "DLHC010317282019"},
    )
    assert searched.status_code == 409, searched.text
    assert searched.json()["detail"] == message


def test_a_readable_typed_case_number_reaches_the_paid_provider_gate(
    client: TestClient, monkeypatch
) -> None:
    """The 2026-09-24 QA journey's contract, with a registry-shaped number."""

    _enable_case_tracking(monkeypatch)
    token = _bootstrap(client)
    matter_id = _create_matter(
        client, token, "GAP-READABLE", case_number="W.P.(C) No. 654321 of 2026"
    )
    headers = {**auth_headers(token), NO_PAID_PROVIDERS_HEADER: NO_PAID_PROVIDERS_VALUE}

    resolved = client.post(f"/api/case-tracking/matters/{matter_id}/resolve", headers=headers)

    assert resolved.status_code == 409, resolved.text
    body = resolved.json()
    assert body["code"] == "paid_provider_blocked_for_test"
    assert "no external request was made" in body["detail"]


def test_blocked_search_body_carries_its_code_at_the_top_level(
    client: TestClient, monkeypatch
) -> None:
    """Exactly the request the dated production spec sends: CNR only, no Matter."""

    _enable_case_tracking(monkeypatch)
    token = _bootstrap(client)
    headers = {**auth_headers(token), NO_PAID_PROVIDERS_HEADER: NO_PAID_PROVIDERS_VALUE}

    blocked = client.post(
        "/api/case-tracking/search", headers=headers, json={"cnr_number": "DLHC010091232026"}
    )

    assert blocked.status_code == 409, blocked.text
    body = blocked.json()
    assert body["code"] == "paid_provider_blocked_for_test"
    assert body["reason"] == "automated_test_request"
    assert "no external request was made" in body["detail"]
    # The machine-readable code is not nested under ``detail``.
    assert isinstance(body["detail"], str)


# --- Review of 27cb6332 (P1): automatic paths use the same identity decision ----

_CRL_CNR = "DLHC010099992019"
_WPC_CNR = "DLHC010062092019"


def _provider_case(*, cnr: str, number: str, case_type: str, hearing_in_days: int):
    """An eCourtsIndia-shaped result: untyped registration number, typed identity."""

    return ProviderCaseSnapshot(
        provider="ecourtsindia",
        cnr_number=cnr,
        case_number=number,
        court_code="DLHC",
        court_name=COURT,
        case_title=f"{case_type} {number}",
        current_status="Pending",
        next_hearing_on=datetime.now(UTC).date() + timedelta(days=hearing_in_days),
        matching_identity=HearingIdentity(
            cnr=cnr,
            case_number=number,
            case_type=case_type,
            court_code="DLHC",
            court_name=COURT,
        ),
    )


class _RegistryProvider(DatedSyncProvider):
    """Answers a case-number search with exactly the cases the provider publishes."""

    def __init__(self, by_number: dict[str, list[ProviderCaseSnapshot]]) -> None:
        super().__init__(
            _provider_case(cnr=_WPC_CNR, number="1/2000", case_type="X", hearing_in_days=1)
        )
        self.by_number = by_number

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        self.search_calls.append(query)
        key = search_number(HearingIdentity(case_number=query.case_number))
        return list(self.by_number.get(key or "", []))

    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot:
        raise AssertionError("a CNR-less identity must not reach a CNR detail call")


def _searched_numbers(provider: _RegistryProvider) -> set[str | None]:
    return {
        search_number(HearingIdentity(case_number=query.case_number))
        for query in provider.search_calls
    }


def _bookmarks_for(matter_id: str) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(TrackedCaseBookmark)
                .where(TrackedCaseBookmark.matter_id == matter_id)
            )
            or 0
        )


def _auto_link_metadata(matter_id: str) -> dict:
    with get_session_factory()() as session:
        created = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "matter.created", AuditEvent.matter_id == matter_id
            )
        )
        assert created is not None
        return json.loads(created.metadata_json or "{}")["case_tracking_auto_link"]


AUTO_LINK_CASES = [
    (
        "AUTO-BARE",
        {"case_number": "6209/2019"},
        {"status": "skipped", "reason": CASE_TYPE_REQUIRED},
    ),
    (
        "AUTO-HEX",
        {"case_number": "WP(C) 6d661b/2026"},
        {"status": "skipped", "reason": CASE_NUMBER_UNREADABLE},
    ),
    ("AUTO-TYPED", {"case_number": "WP(C) 6209/2019"}, {"status": "linked"}),
    ("AUTO-FILING", {"filing_number": "421/2026"}, {"status": "linked"}),
    # A CNR decides; its bare secondary number is only corroboration.
    (
        "AUTO-CNR",
        {"case_number": "6209/2019", "cnr_number": _WPC_CNR},
        {"status": "linked"},
    ),
]


@pytest.mark.parametrize(("code", "fields", "expected"), AUTO_LINK_CASES)
def test_automatic_link_at_matter_creation_uses_the_manual_identity_decision(
    client: TestClient, monkeypatch, code, fields, expected
) -> None:
    _enable_tracking(monkeypatch)
    token = _bootstrap(client)

    matter_id = _create_matter(client, token, code, **fields)

    auto_link = _auto_link_metadata(matter_id)
    assert {key: auto_link.get(key) for key in expected} == expected
    assert _bookmarks_for(matter_id) == (1 if expected["status"] == "linked" else 0)


def test_scheduled_backfill_never_finds_a_case_from_a_bare_number(
    client: TestClient, monkeypatch
) -> None:
    """The reviewer's scenario: the provider publishes exactly one case of another type."""

    token = _bootstrap(client)
    # Pre-feature state: Matters recorded while automatic linking was off.
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "false")
    get_settings.cache_clear()
    bare = _create_matter(client, token, "POLL-BARE", case_number="6209/2019")
    typed = _create_matter(client, token, "POLL-TYPED", case_number="WP(C) 9123/2026")
    assert _bookmarks_for(bare) == 0
    assert _bookmarks_for(typed) == 0

    _enable_tracking(monkeypatch)
    crl = _provider_case(cnr=_CRL_CNR, number="6209/2019", case_type="CRL.A.", hearing_in_days=5)
    wpc = _provider_case(cnr=_WPC_CNR, number="9123/2026", case_type="WP(C)", hearing_in_days=9)
    provider = _RegistryProvider({"6209/2019": [crl], "9123/2026": [wpc]})

    with get_session_factory()() as session:
        poll_tracked_cases(session, provider=provider, force=True)

    assert "6209/2019" not in _searched_numbers(provider)
    assert "9123/2026" in _searched_numbers(provider)
    assert _bookmarks_for(bare) == 0
    assert _bookmarks_for(typed) == 1
    with get_session_factory()() as session:
        assert session.get(Matter, bare).next_hearing_on is None
        assert session.get(Matter, typed).next_hearing_on == wpc.next_hearing_on


def test_existing_automatic_link_stops_before_the_provider_when_the_type_is_lost(
    client: TestClient, monkeypatch
) -> None:
    """A pre-policy or edited Matter: refresh and polling fail closed with the reason."""

    _enable_tracking(monkeypatch)
    token = _bootstrap(client)
    headers = auth_headers(token)
    matter_id = _create_matter(client, token, "LINKED-BARE", case_number="WP(C) 6209/2019")
    assert _auto_link_metadata(matter_id)["status"] == "linked"
    [bookmark] = client.get("/api/case-tracking/bookmarks", headers=headers).json()["bookmarks"]

    current = client.get(f"/api/matters/{matter_id}", headers=headers).json()
    edited = client.patch(
        f"/api/matters/{matter_id}",
        headers=headers,
        json={"expected_updated_at": current["updated_at"], "case_number": "6209/2019"},
    )
    assert edited.status_code == 200, edited.text

    crl = _provider_case(cnr=_CRL_CNR, number="6209/2019", case_type="CRL.A.", hearing_in_days=5)
    wpc = _provider_case(cnr=_WPC_CNR, number="6209/2019", case_type="WP(C)", hearing_in_days=9)
    provider = _RegistryProvider({"6209/2019": [crl]})
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider", lambda: provider
    )

    refresh_url = f"/api/case-tracking/bookmarks/{bookmark['id']}/refresh"
    refreshed = client.post(refresh_url, headers=headers)
    assert refreshed.status_code == 409, refreshed.text
    assert refreshed.json()["detail"] == CASE_TYPE_REQUIRED
    [listed] = client.get("/api/case-tracking/bookmarks", headers=headers).json()["bookmarks"]
    assert listed["tracked_case"]["manual_refresh_allowed"] is False
    assert listed["tracked_case"]["manual_refresh_disabled_reason"] == CASE_TYPE_REQUIRED

    with get_session_factory()() as session:
        poll_tracked_cases(session, provider=provider, force=True)
    assert provider.search_calls == []
    assert provider.bulk_calls == []
    with get_session_factory()() as session:
        assert session.get(Matter, matter_id).next_hearing_on is None

    # Restoring the type makes the same link usable, and the type decides between
    # the two cases the provider publishes under one number and court.
    current = client.get(f"/api/matters/{matter_id}", headers=headers).json()
    restored = client.patch(
        f"/api/matters/{matter_id}",
        headers=headers,
        json={"expected_updated_at": current["updated_at"], "case_number": "WP(C) 6209/2019"},
    )
    assert restored.status_code == 200, restored.text
    provider.by_number = {"6209/2019": [crl, wpc]}
    refreshed = client.post(refresh_url, headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    with get_session_factory()() as session:
        assert session.get(Matter, matter_id).next_hearing_on == wpc.next_hearing_on
