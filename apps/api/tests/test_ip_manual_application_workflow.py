"""IPLF-031B manual application workflow and atomic exception coverage."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter


def _actor(client: TestClient) -> tuple[dict[str, str], str]:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    return auth_headers(token), token


def _payload(*, number: str | None = "TM / 2026 / 00421", **overrides) -> dict:
    payload = {
        "title": "Aster manual filing",
        "asset_title": "ASTER",
        "jurisdiction": "IN",
        "office": "IP India",
        "filing_phase": "filed" if number else "pre_filing",
        "source_pending_identifier_allocation": False,
        "application_number": (
            {
                "raw_value": number,
                "source": "manual",
                "effective_from": "2026-08-21",
                "is_primary": True,
            }
            if number
            else None
        ),
        "particulars": {
            "form_key": "TM-A",
            "form_version": "2026.1",
            "mark_kind": "word",
            "representation": {
                "text": "ASTER",
                "evidence_reference": "attachment:aster-mark",
            },
            "classes": [
                {"class_number": 9, "specification": "Downloadable software"}
            ],
            "use_priority": None,
            "parties": [{"role": "applicant", "name": "Aster Applicant LLP"}],
            "agent": None,
            "filing_manifest": [
                {
                    "key": "representation",
                    "label": "Mark representation",
                    "required": True,
                    "evidence_reference": "attachment:aster-mark",
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_uj03_normal_manual_command_materializes_every_canonical_owner(
    client: TestClient,
) -> None:
    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IPLF-031B-UJ03")

    created = client.post(
        "/api/ip/trademark-applications/manual",
        headers=headers,
        json=_payload(matter_id=matter["id"]),
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["docket"]["matter_id"] == matter["id"]
    assert body["docket"]["primary_identifier"] is None
    assert body["asset"]["title"] == "ASTER"
    assert body["application"]["asset_id"] == body["asset"]["id"]
    assert body["application"]["filing_phase"] == "filed"
    assert body["identifier"]["identifier_kind"] == "application"
    assert body["identifier"]["raw_value"] == "TM / 2026 / 00421"
    assert body["identifier"]["normalized_value"] == "tm202600421"

    core = client.get(
        f"/api/ip/dockets/{body['docket']['id']}/core-records",
        headers=headers,
    )
    assert core.status_code == 200, core.text
    assert len(core.json()["assets"]) == 1
    assert len(core.json()["applications"]) == 1
    assert len(core.json()["identifiers"]) == 1


def test_uj03_exc01_pre_filing_manual_draft_does_not_invent_a_number(
    client: TestClient,
) -> None:
    headers, _token = _actor(client)

    created = client.post(
        "/api/ip/trademark-applications/manual",
        headers=headers,
        json=_payload(number=None),
    )

    assert created.status_code == 201, created.text
    assert created.json()["application"]["filing_phase"] == "pre_filing"
    assert created.json()["identifier"] is None
    assert created.json()["duplicate_candidates"] == []


def test_uj03_exc02_invalid_filed_command_rolls_back_the_whole_record(
    client: TestClient,
) -> None:
    headers, _token = _actor(client)

    refused = client.post(
        "/api/ip/trademark-applications/manual",
        headers=headers,
        json=_payload(number=None, filing_phase="filed"),
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_application_identifier_required"
    listing = client.get("/api/ip/dockets", headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["count"] == 0


def test_manual_duplicate_is_flagged_without_reusing_legacy_docket_identity(
    client: TestClient,
) -> None:
    headers, _token = _actor(client)
    first = client.post(
        "/api/ip/trademark-applications/manual",
        headers=headers,
        json=_payload(title="Original ASTER", filing_phase="draft"),
    )
    second = client.post(
        "/api/ip/trademark-applications/manual",
        headers=headers,
        json=_payload(title="Possible duplicate ASTER", filing_phase="draft"),
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["docket"]["primary_identifier"] is None
    assert second.json()["docket"]["primary_identifier"] is None
    assert second.json()["identifier"]["reconciliation_status"] == "needs_review"
    assert [row["id"] for row in second.json()["duplicate_candidates"]] == [
        first.json()["identifier"]["id"]
    ]
