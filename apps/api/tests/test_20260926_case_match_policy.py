"""BUG-032 (Ram, 2026-09-26): one Matter/provider identity policy everywhere.

Manual search, resolve and link used a private matcher that rejected a
CNR-identical eCourts case when free-text court or party wording differed,
while refresh, polling and next-hearing sync accepted the same case on its CNR.
The tester saw "Does not match this Matter" for a case the Matter already
identified. These regressions pin the shared policy: a normalized CNR decides;
without a CNR the exact case number (including its provider case type) plus
court is required; and search tells the user which visible Matter already
records the case.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import Matter, TrackedCaseBookmark
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import (
    _snapshot_matching_identity,
    _verified_sync_snapshot_identity,
)
from caseops_api.services.case_tracking_providers import CaseSearchQuery, ProviderCaseSnapshot
from caseops_api.services.hearing_matching import HearingIdentity, identity_matches
from caseops_api.services.hearing_matching_scopes import matter_identity
from tests.test_auth_company import auth_headers
from tests.test_case_tracking import FakeCaseTrackingProvider, _bootstrap
from tests.test_today_view_matter_access import _invite_member

CNR = "DLHC010317282019"


def _create_matter(
    client: TestClient,
    token: str,
    *,
    cnr: str | None,
    code: str = "BUG032-001",
    court: str = "Delhi High Court",
    client_name: str = "Satish Kumar Mehani",
    opposing: str = "Punjab National Bank",
    case_number: str = "WP(CIVIL)/6209/2019",
) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Satish Kumar Mehani v Punjab National Bank",
            "matter_code": code,
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": court,
            "client_name": client_name,
            "opposing_party": opposing,
            "case_number": case_number,
            "cnr_number": cnr,
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _provider_snapshot(**changes: object) -> ProviderCaseSnapshot:
    """A provider result shaped like eCourtsIndia v4, with its matching identity."""

    base = ProviderCaseSnapshot(
        provider="ecourtsindia",
        cnr_number=CNR,
        case_number="6209/2019",
        court_code="DLHC01",
        court_name="High Court of Delhi",
        case_title="Satish Kumar Mehani v Punjab National Bank & ORS.",
        party_names=["Satish Kumar Mehani", "Punjab National Bank & ORS."],
        current_status="Pending",
        current_stage="AFTER NOTICE MISC. MATTERS",
        next_hearing_on=date(2026, 11, 25),
        source_url=None,
        matching_identity=HearingIdentity(
            cnr=CNR,
            case_number="6209/2019",
            case_type="WP(CIVIL)",
            court_code="DLHC01",
            court_name="High Court of Delhi",
            parties=("Satish Kumar Mehani", "Punjab National Bank & ORS."),
        ),
    )
    return replace(base, **changes)


class _ScriptedProvider(FakeCaseTrackingProvider):
    def __init__(self, snapshots: list[ProviderCaseSnapshot]) -> None:
        super().__init__()
        self.snapshots = snapshots

    def search_cases(self, *, query: CaseSearchQuery) -> list[ProviderCaseSnapshot]:
        self.search_calls.append(query)
        return list(self.snapshots)


def _use(monkeypatch, provider: FakeCaseTrackingProvider) -> None:
    monkeypatch.setattr(
        "caseops_api.services.case_tracking.get_case_tracking_provider", lambda: provider
    )


def _bookmark_count(matter_id: str) -> int:
    with get_session_factory()() as session:
        return session.scalar(
            select(func.count())
            .select_from(TrackedCaseBookmark)
            .where(TrackedCaseBookmark.matter_id == matter_id)
        )


def _matter_search(client: TestClient, token: str, matter_id: str) -> dict:
    response = client.post(
        "/api/case-tracking/search",
        headers=auth_headers(token),
        json={"cnr_number": CNR, "matter_id": matter_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_cnr_identifies_the_case_despite_court_and_party_wording(
    client: TestClient, monkeypatch
) -> None:
    token = _bootstrap(client)
    matter_id = _create_matter(client, token, cnr=CNR)
    _use(monkeypatch, _ScriptedProvider([_provider_snapshot()]))

    searched = _matter_search(client, token, matter_id)
    [result] = searched["results"]
    assert result["link_token"], "a CNR-identical case must be linkable, not 'Does not match'"
    assert [row["matter_id"] for row in result["existing_matters"]] == [matter_id]

    resolved = client.post(
        f"/api/case-tracking/matters/{matter_id}/resolve", headers=auth_headers(token)
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "matched"

    linked = client.post(
        f"/api/case-tracking/matters/{matter_id}/link",
        headers=auth_headers(token),
        json={"link_token": result["link_token"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["matter_id"] == matter_id

    again = _matter_search(client, token, matter_id)
    assert again["results"][0]["linked_to_matter"] is True
    with get_session_factory()() as session:
        bookmarks = session.scalars(
            select(TrackedCaseBookmark).where(TrackedCaseBookmark.matter_id == matter_id)
        ).all()
        assert len(bookmarks) == 1


def test_a_different_cnr_never_matches_even_with_identical_wording(
    client: TestClient, monkeypatch
) -> None:
    token = _bootstrap(client)
    matter_id = _create_matter(client, token, cnr=CNR)
    other = "DLHC010999992019"
    _use(
        monkeypatch,
        _ScriptedProvider(
            [
                _provider_snapshot(
                    cnr_number=other,
                    court_name="Delhi High Court",
                    matching_identity=HearingIdentity(
                        cnr=other,
                        case_number="6209/2019",
                        case_type="WP(CIVIL)",
                        court_name="Delhi High Court",
                        parties=("Satish Kumar Mehani", "Punjab National Bank"),
                    ),
                )
            ]
        ),
    )
    [result] = _matter_search(client, token, matter_id)["results"]
    assert result["link_token"] is None
    assert result["existing_matters"] == []
    resolved = client.post(
        f"/api/case-tracking/matters/{matter_id}/resolve", headers=auth_headers(token)
    )
    assert resolved.json() == {"status": "no_match", "provider": "ecourtsindia", "results": []}


def test_without_a_cnr_the_case_number_needs_the_provider_case_type_and_court(
    client: TestClient, monkeypatch
) -> None:
    token = _bootstrap(client)
    matter_id = _create_matter(client, token, cnr=None, court="Delhi High Court")
    exact = HearingIdentity(
        cnr="DLHC010317282019",
        case_number="6209/2019",
        case_type="WP(CIVIL)",
        court_name="Delhi High Court",
        parties=("Satish Kumar Mehani", "Punjab National Bank"),
    )
    cases = {
        "exact": (exact, "matched"),
        # The same number and year of another case type is a different case.
        "other_type": (replace(exact, case_type="CRL.A."), "no_match"),
        # A bare number/year cannot prove which case it is.
        "no_type": (replace(exact, case_type=None), "no_match"),
        # Without a CNR, the court is part of the identity.
        "other_court": (replace(exact, court_name="Bombay High Court"), "no_match"),
    }
    for label, (identity, expected) in cases.items():
        _use(
            monkeypatch,
            _ScriptedProvider(
                [
                    _provider_snapshot(
                        case_number="6209/2019",
                        court_name=identity.court_name,
                        matching_identity=identity,
                    )
                ]
            ),
        )
        resolved = client.post(
            f"/api/case-tracking/matters/{matter_id}/resolve", headers=auth_headers(token)
        )
        assert resolved.status_code == 200, (label, resolved.text)
        assert resolved.json()["status"] == expected, label


def test_search_and_refresh_share_one_identity_policy(
    client: TestClient, monkeypatch
) -> None:
    """Search must issue a link token exactly when the refresh matcher accepts."""

    token = _bootstrap(client)
    matter_id = _create_matter(client, token, cnr=CNR)
    with get_session_factory()() as session:
        identity = matter_identity(session.get(Matter, matter_id))
    variants = {
        "court_alias": _provider_snapshot(),
        "party_suffix": _provider_snapshot(
            party_names=["Satish Kumar Mehani", "PNB & Others"],
            matching_identity=replace(
                _provider_snapshot().matching_identity,
                parties=("Satish Kumar Mehani", "PNB & Others"),
            ),
        ),
        "other_cnr": _provider_snapshot(
            cnr_number="DLHC010000012019",
            matching_identity=replace(
                _provider_snapshot().matching_identity, cnr="DLHC010000012019"
            ),
        ),
    }
    for label, snapshot in variants.items():
        _use(monkeypatch, _ScriptedProvider([snapshot]))
        [result] = _matter_search(client, token, matter_id)["results"]
        refresh_accepts = identity_matches(identity, _snapshot_matching_identity(snapshot))
        assert bool(result["link_token"]) is refresh_accepts, label

        class _Tracked:
            cnr_number = CNR

        try:
            _verified_sync_snapshot_identity(_Tracked(), [snapshot], identities=(identity,))
            refresh_ok = True
        except Exception:  # noqa: BLE001 - the refresh verifier fails closed by raising
            refresh_ok = False
        assert refresh_ok is refresh_accepts, label


def test_global_search_reports_only_visible_existing_matters(
    client: TestClient, monkeypatch
) -> None:
    token = _bootstrap(client)
    visible = _create_matter(client, token, cnr=CNR, code="BUG032-VISIBLE")
    # Case numbers are unique per company; CNRs are not. The hidden Matter
    # records the same CNR in a different case (lower case, as typed).
    hidden = _create_matter(
        client, token, cnr=CNR.lower(), code="BUG032-HIDDEN", case_number="WP(CIVIL)/6210/2019"
    )
    _, member_token = _invite_member(client, token, "bug032-member@example.com")
    # The invite helper signs in as the member, and cookie-first authentication
    # outranks a bearer token; clear the shared cookie before each identity.
    client.cookies.clear()
    with get_session_factory()() as session:
        restricted = session.get(Matter, hidden)
        assert restricted is not None
        restricted.restricted_access = True
        session.commit()
    _use(monkeypatch, _ScriptedProvider([_provider_snapshot()]))

    owner = client.post(
        "/api/case-tracking/search", headers=auth_headers(token), json={"cnr_number": CNR}
    )
    assert owner.status_code == 200, owner.text
    [owner_result] = owner.json()["results"]
    assert {row["matter_id"] for row in owner_result["existing_matters"]} == {visible, hidden}
    assert owner_result["link_token"] is None
    assert owner_result["linked_to_matter"] is False

    client.cookies.clear()
    member = client.post(
        "/api/case-tracking/search",
        headers=auth_headers(member_token),
        json={"cnr_number": CNR},
    )
    assert member.status_code == 200, member.text
    [member_result] = member.json()["results"]
    assert [row["matter_id"] for row in member_result["existing_matters"]] == [visible]


def test_link_rejects_a_selection_without_signed_provider_identity(
    client: TestClient, monkeypatch
) -> None:
    """Selections issued before this change carry no candidate identity."""

    import base64
    import hashlib
    import hmac
    import json

    from caseops_api.core.settings import get_settings
    from caseops_api.services import case_tracking

    token = _bootstrap(client)
    matter_id = _create_matter(client, token, cnr=CNR)
    _use(monkeypatch, _ScriptedProvider([_provider_snapshot()]))
    [result] = _matter_search(client, token, matter_id)["results"]
    # With case tracking enabled, creating a CNR Matter already auto-links it;
    # the rejected legacy selection must add nothing to whatever exists.
    before = _bookmark_count(matter_id)
    encoded, _ = result["link_token"].split(".", 1)
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    claims.pop("candidate")
    body = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.digest(
        get_settings().auth_secret.encode("utf-8"),
        case_tracking._MATTER_SELECTION_DOMAIN + body,
        hashlib.sha256,
    )
    legacy = f"{base64.urlsafe_b64encode(body).decode().rstrip('=')}.{signature.hex()}"
    rejected = client.post(
        f"/api/case-tracking/matters/{matter_id}/link",
        headers=auth_headers(token),
        json={"link_token": legacy},
    )
    assert rejected.status_code == 409, rejected.text
    assert _bookmark_count(matter_id) == before
