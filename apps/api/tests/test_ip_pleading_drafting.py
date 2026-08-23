from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import Draft, DraftVersion, ModelRun
from caseops_api.db.session import get_session_factory
from caseops_api.services.llm import LLMMessage, LLMProviderError
from tests.test_auth_company import auth_headers
from tests.test_drafting_studio import _seed_authority
from tests.test_ip_opposition_opponent_workflow import _fixture
from tests.test_ip_record_workflow import _docket

_FIXTURE_PACK_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "ip-implementation"
    / "fixtures"
    / "m4"
    / "IPLF-047"
    / "trademark-pleading-fixtures-v1.json"
)


def _legal_fixture(fixture_id: str) -> dict:
    pack = json.loads(_FIXTURE_PACK_PATH.read_text(encoding="utf-8"))
    return next(row for row in pack["fixtures"] if row["id"] == fixture_id)

IP_PLEADING_ROUTE_CONTRACTS = {
    ("get", "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/pleading-templates"),
    ("get", "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts"),
    ("post", "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts"),
    ("get", "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}"),
    ("patch", "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}"),
    (
        "post",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/generate",
    ),
    (
        "post",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/submit",
    ),
    (
        "post",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/request-changes",
    ),
    (
        "post",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/approve",
    ),
    (
        "post",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/finalize",
    ),
    (
        "get",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/export.docx",
    ),
    (
        "get",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/validate",
    ),
    (
        "get",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/compare",
    ),
    (
        "get",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/filing-bundle.zip",
    ),
    (
        "post",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/file",
    ),
    (
        "post",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/reject-filing",
    ),
    (
        "post",
        "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/drafts/{draft_id}/serve",
    ),
}


def _base(docket: dict, proceeding: dict) -> str:
    return f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}"


def _create_notice_draft(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding: dict,
) -> dict:
    response = client.post(
        f"{_base(docket, proceeding)}/drafts",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "title": "Notice of opposition for IPLF-045",
            "template_key": "trademark_opposition_notice",
            "facts": {"lawyer_note": "Preserve placeholders for missing dates."},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _generate_grounded_notice(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding: dict,
) -> dict:
    draft = _create_notice_draft(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    _seed_authority(neutral_citation="2026 SCC OnLine Del 450")
    generated = client.post(
        f"{_base(docket, proceeding)}/drafts/{draft['id']}/generate",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={},
    )
    assert generated.status_code == 200, generated.text
    return generated.json()


def test_ip_pleading_normal_journey_freezes_manifests_and_exports(
    client: TestClient,
) -> None:
    fixture = _legal_fixture("IP-PLEADING-GOLDEN-001")
    expected = fixture["expected_software_behavior"]
    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    base = _base(docket, proceeding)

    templates = client.get(f"{base}/pleading-templates", headers=headers)
    assert templates.status_code == 200, templates.text
    assert [row["key"] for row in templates.json()["templates"]] == ["trademark_opposition_notice"]

    draft = _create_notice_draft(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    assert draft["matter_id"] is None
    assert draft["company_id"] == bootstrap["company"]["id"]
    assert draft["ip_docket_id"] == docket["id"]
    assert draft["ip_proceeding_id"] == proceeding["id"]

    listed = client.get(f"{base}/drafts", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()["drafts"]] == [draft["id"]]
    loaded = client.get(f"{base}/drafts/{draft['id']}", headers=headers)
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["id"] == draft["id"]

    citation = "2026 SCC OnLine Del 450"
    _seed_authority(neutral_citation=citation)
    generated = client.post(
        f"{base}/drafts/{draft['id']}/generate",
        headers=headers,
        json={"focus_note": "Address only the confirmed earlier-mark ground."},
    )
    assert generated.status_code == 200, generated.text
    version = generated.json()["versions"][0]
    assert version["verified_citation_count"] == 1
    assert version["template_manifest"]["key"] == "trademark_opposition_notice"
    generation = version["template_manifest"]["generation"]
    assert generation["provider"] == "mock"
    assert generation["model"] == "caseops-mock-1"
    assert len(generation["prompt_hash"]) == 64
    assert generation["generated_at"]
    assert version["context_manifest"]["docket"]["id"] == docket["id"]
    assert version["context_manifest"]["proceeding"]["id"] == proceeding["id"]
    assert version["context_manifest"]["identifiers"]

    edited_body = version["body"] + f"\n\nLawyer review retained [{citation}]."
    edited = client.patch(
        f"{base}/drafts/{draft['id']}",
        headers=headers,
        json={"body": edited_body},
    )
    assert edited.status_code == 200, edited.text
    edited_version = edited.json()["versions"][1]
    assert edited_version["revision"] == 2
    assert edited_version["template_manifest"] == version["template_manifest"]
    assert edited_version["context_manifest"] == version["context_manifest"]
    assert edited_version["source_manifest"] == version["source_manifest"]

    submitted = client.post(
        f"{base}/drafts/{draft['id']}/submit",
        headers=headers,
        json={"notes": "Ready for partner review."},
    )
    assert submitted.status_code == 200, submitted.text
    changes_requested = client.post(
        f"{base}/drafts/{draft['id']}/request-changes",
        headers=headers,
        json={"notes": "Clarify the confirmed use date before approval."},
    )
    assert changes_requested.status_code == 200, changes_requested.text
    resubmitted = client.post(
        f"{base}/drafts/{draft['id']}/submit",
        headers=headers,
        json={"notes": "Clarification reviewed and retained."},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    approved = client.post(
        f"{base}/drafts/{draft['id']}/approve",
        headers=headers,
        json={"notes": "Citation and pleading particulars reviewed."},
    )
    assert approved.status_code == 200, approved.text
    finalized = client.post(
        f"{base}/drafts/{draft['id']}/finalize",
        headers=headers,
        json={"notes": "Final lawyer-controlled version."},
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "finalized"
    assert [row["action"] for row in finalized.json()["reviews"]] == expected[
        "review_actions"
    ]

    exported = client.get(
        f"{base}/drafts/{draft['id']}/export.docx",
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    assert exported.content.startswith(b"PK")
    assert expected["export_content_type"] in exported.headers["content-type"]


def test_ip_pleading_route_contracts_are_published(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    missing = [
        f"{method.upper()} {path}"
        for method, path in sorted(IP_PLEADING_ROUTE_CONTRACTS)
        if method not in paths.get(path, {})
    ]
    assert not missing


def test_ip_pleading_rejects_template_incompatible_with_side_and_stage(
    client: TestClient,
) -> None:
    fixture = _legal_fixture("IP-PLEADING-GOLDEN-006")
    bootstrap, _matter, docket, proceeding = _fixture(client)
    response = client.post(
        f"{_base(docket, proceeding)}/drafts",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "title": "Wrong-side counterstatement",
            "template_key": "trademark_counterstatement",
        },
    )
    assert response.status_code == fixture["expected_software_behavior"][
        "incompatible_http_status"
    ]
    assert "incompatible" in response.json()["detail"]

    with get_session_factory()() as session:
        assert (
            session.scalar(select(func.count(Draft.id)).where(Draft.ip_docket_id == docket["id"]))
            == 0
        )


def test_ip_pleading_provider_failure_is_atomic(
    client: TestClient,
    monkeypatch,
) -> None:
    fixture = _legal_fixture("IP-PLEADING-GOLDEN-005")
    expected = fixture["expected_software_behavior"]
    bootstrap, _matter, docket, proceeding = _fixture(client)
    draft = _create_notice_draft(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )

    class FailingProvider:
        name = "mock"
        model = "failed-ip-drafting-provider"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            raise LLMProviderError("controlled upstream failure")

    monkeypatch.setattr(
        "caseops_api.services.drafting.build_provider",
        lambda *args, **kwargs: FailingProvider(),
    )
    response = client.post(
        f"{_base(docket, proceeding)}/drafts/{draft['id']}/generate",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={},
    )
    assert response.status_code == expected["http_status"], response.text

    with get_session_factory()() as session:
        row = session.get(Draft, draft["id"])
        assert row is not None
        assert row.current_version_id is None
        assert (
            session.scalar(
                select(func.count(DraftVersion.id)).where(DraftVersion.draft_id == draft["id"])
            )
            == expected["draft_version_count"]
        )
        assert (
            session.scalar(
                select(func.count(ModelRun.id)).where(ModelRun.ip_docket_id == docket["id"])
            )
            == expected["model_run_count"]
        )


def test_ip_pleading_database_rejects_cross_docket_proceeding_target(
    client: TestClient,
) -> None:
    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    other_docket = _docket(client, headers, "IPLF-045 WRONG TARGET")
    draft = _create_notice_draft(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )

    with get_session_factory()() as session:
        row = session.get(Draft, draft["id"])
        assert row is not None
        row.ip_docket_id = other_docket["id"]
        with pytest.raises(IntegrityError):
            session.commit()


def test_ip_pleading_validation_compare_bundle_and_service_lifecycle(
    client: TestClient,
) -> None:
    fixture = _legal_fixture("IP-PLEADING-GOLDEN-007")
    expected = fixture["expected_software_behavior"]
    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    base = _base(docket, proceeding)
    generated = _generate_grounded_notice(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    draft_id = generated["id"]
    revision_one = generated["versions"][0]

    placeholder_body = revision_one["body"] + "\n\nFiling date: [DATE]. See Annexure A."
    edited = client.patch(
        f"{base}/drafts/{draft_id}",
        headers=headers,
        json={"body": placeholder_body},
    )
    assert edited.status_code == 200, edited.text
    validation = client.get(f"{base}/drafts/{draft_id}/validate", headers=headers)
    assert validation.status_code == 200, validation.text
    report = validation.json()
    assert report["can_approve"] is False
    assert report["placeholder_count"] == 1
    assert set(expected["initial_finding_codes"]) <= {
        row["code"] for row in report["findings"]
    }

    submitted = client.post(
        f"{base}/drafts/{draft_id}/submit",
        headers=headers,
        json={"notes": "Validate before approval."},
    )
    assert submitted.status_code == 200, submitted.text
    blocked_approval = client.post(
        f"{base}/drafts/{draft_id}/approve",
        headers=headers,
        json={"notes": "This must fail closed."},
    )
    assert blocked_approval.status_code == expected["initial_approval_http_status"]
    assert "placeholder.unresolved" in blocked_approval.text

    corrected_body = placeholder_body.replace("[DATE]", "24 August 2026").replace(
        " See Annexure A.",
        "",
    )
    corrected = client.patch(
        f"{base}/drafts/{draft_id}",
        headers=headers,
        json={"body": corrected_body},
    )
    assert corrected.status_code == 200, corrected.text
    compare = client.get(
        f"{base}/drafts/{draft_id}/compare",
        headers=headers,
        params={"prev_revision": 1, "next_revision": 3},
    )
    assert compare.status_code == 200, compare.text
    assert compare.json()["lines_added"] >= 1
    assert compare.json()["prev_version_id"] == revision_one["id"]

    for action in ("submit", "approve", "finalize"):
        response = client.post(
            f"{base}/drafts/{draft_id}/{action}",
            headers=headers,
            json={"notes": f"Human-controlled {action}."},
        )
        assert response.status_code == 200, response.text
    bundle = client.get(f"{base}/drafts/{draft_id}/filing-bundle.zip", headers=headers)
    assert bundle.status_code == 200, bundle.text
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        names = set(archive.namelist())
        assert "internal/generation-manifest.json" in names
        assert "internal/filing-checklist.json" in names
        assert any(name.startswith("filed-document/") and name.endswith(".docx") for name in names)
        manifest = json.loads(archive.read("internal/generation-manifest.json"))
        assert manifest["version_id"] == response.json()["current_version_id"]
        assert manifest["template_manifest"]["format_profile"] == (
            "india-trade-marks-registry-v1"
        )

    filed = client.post(
        f"{base}/drafts/{draft_id}/file",
        headers=headers,
        json={"reference": "TM-O/2026/451", "notes": "Registry filing acknowledged."},
    )
    assert filed.status_code == 200, filed.text
    assert filed.json()["status"] == "filed"
    no_method = client.post(
        f"{base}/drafts/{draft_id}/serve",
        headers=headers,
        json={"reference": "SERVICE/2026/9"},
    )
    assert no_method.status_code == 422
    served = client.post(
        f"{base}/drafts/{draft_id}/serve",
        headers=headers,
        json={
            "reference": "SERVICE/2026/9",
            "method": "registered-post",
            "notes": "Service receipt retained.",
        },
    )
    assert served.status_code == 200, served.text
    assert served.json()["status"] == expected["terminal_status"]
    assert served.json()["reviews"][-1]["metadata"]["method"] == "registered-post"


def test_ip_pleading_rejected_filing_preserves_original_filed_revision(
    client: TestClient,
) -> None:
    fixture = _legal_fixture("IP-PLEADING-GOLDEN-008")
    expected = fixture["expected_software_behavior"]
    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    base = _base(docket, proceeding)
    generated = _generate_grounded_notice(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    draft_id = generated["id"]
    original_body = generated["versions"][0]["body"]
    for action in ("submit", "approve", "finalize"):
        response = client.post(
            f"{base}/drafts/{draft_id}/{action}",
            headers=headers,
            json={"notes": action},
        )
        assert response.status_code == 200, response.text
    filed = client.post(
        f"{base}/drafts/{draft_id}/file",
        headers=headers,
        json={"reference": "TM-O/FILED/1"},
    )
    assert filed.status_code == 200, filed.text
    filed_version_id = filed.json()["current_version_id"]
    rejected = client.post(
        f"{base}/drafts/{draft_id}/reject-filing",
        headers=headers,
        json={"reference": "TM-O/REJECTION/1", "notes": "Registry correction required."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == expected["status_after_rejection"]
    corrected = client.patch(
        f"{base}/drafts/{draft_id}",
        headers=headers,
        json={"body": original_body + "\n\nCorrected filing particular."},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["current_version_id"] != filed_version_id
    assert corrected.json()["versions"][0]["body"] == original_body
    file_event = next(row for row in corrected.json()["reviews"] if row["action"] == "file")
    assert file_event["version_id"] == filed_version_id


def test_ip_pleading_source_loss_invalidates_approval(client: TestClient) -> None:
    fixture = _legal_fixture("IP-PLEADING-GOLDEN-004")
    expected = fixture["expected_software_behavior"]
    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    base = _base(docket, proceeding)
    generated = _generate_grounded_notice(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    draft_id = generated["id"]
    with get_session_factory()() as session:
        version = session.get(DraftVersion, generated["current_version_id"])
        assert version is not None
        version.source_manifest_json = json.dumps(
            [
                {
                    "document_version_id": "00000000-0000-0000-0000-000000000046",
                    "sha256": "0" * 64,
                    "state": "approved",
                }
            ]
        )
        session.commit()
    validation = client.get(f"{base}/drafts/{draft_id}/validate", headers=headers)
    assert validation.status_code == 200, validation.text
    assert set(expected["finding_codes"]) <= {
        row["code"] for row in validation.json()["findings"]
    }
    submitted = client.post(
        f"{base}/drafts/{draft_id}/submit",
        headers=headers,
        json={"notes": "Source loss test."},
    )
    assert submitted.status_code == 200, submitted.text
    approval = client.post(
        f"{base}/drafts/{draft_id}/approve",
        headers=headers,
        json={"notes": "Must fail."},
    )
    assert approval.status_code == expected["approval_http_status"]
    assert "source.version_lost" in approval.text


def test_ip_pleading_generation_blocks_conflicting_application_numbers(
    client: TestClient,
) -> None:
    fixture = _legal_fixture("IP-PLEADING-GOLDEN-002")
    expected = fixture["expected_software_behavior"]
    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    second_number = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "application",
            "raw_value": "TM-CONFLICT-046-2026",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "conflict_fixture",
            "effective_from": "2026-08-24",
            "is_primary": False,
            "application_id": proceeding["application_id"],
        },
    )
    assert second_number.status_code == 201, second_number.text
    assert second_number.json()["identifier"]["reconciliation_status"] == "confirmed"
    draft = _create_notice_draft(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    _seed_authority(neutral_citation="2026 SCC OnLine Del 450")
    generated = client.post(
        f"{_base(docket, proceeding)}/drafts/{draft['id']}/generate",
        headers=headers,
        json={},
    )
    assert generated.status_code == expected["http_status"]
    assert "context.identifier_conflict" in generated.text
    with get_session_factory()() as session:
        row = session.get(Draft, draft["id"])
        assert row is not None
        assert row.current_version_id is None
