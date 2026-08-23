from __future__ import annotations

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


def test_ip_pleading_normal_journey_freezes_manifests_and_exports(
    client: TestClient,
) -> None:
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
    assert [row["action"] for row in finalized.json()["reviews"]] == [
        "edit",
        "submit",
        "approve",
        "finalize",
    ]

    exported = client.get(
        f"{base}/drafts/{draft['id']}/export.docx",
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    assert exported.content.startswith(b"PK")
    assert "application/vnd.openxmlformats" in exported.headers["content-type"]


def test_ip_pleading_rejects_template_incompatible_with_side_and_stage(
    client: TestClient,
) -> None:
    bootstrap, _matter, docket, proceeding = _fixture(client)
    response = client.post(
        f"{_base(docket, proceeding)}/drafts",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "title": "Wrong-side counterstatement",
            "template_key": "trademark_counterstatement",
        },
    )
    assert response.status_code == 409
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
    assert response.status_code == 422, response.text

    with get_session_factory()() as session:
        row = session.get(Draft, draft["id"])
        assert row is not None
        assert row.current_version_id is None
        assert (
            session.scalar(
                select(func.count(DraftVersion.id)).where(DraftVersion.draft_id == draft["id"])
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(ModelRun.id)).where(ModelRun.ip_docket_id == docket["id"])
            )
            == 0
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
