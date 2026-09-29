"""Release-owned Draft/document sister proof, not fabricated Review output."""

import hashlib
import json

import pytest
from sqlalchemy import false, func, select

from caseops_api.db.models import (
    AuditEvent,
    AuthorityDocument,
    Company,
    CompanyMembership,
    Draft,
    DraftVersion,
    Matter,
    MatterAttachment,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    Recommendation,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.bootstrap_ip_production_qa import (
    ensure_ip_production_qa,
    ensure_ip_production_qa_saved_manifest_fixture,
)
from caseops_api.services import private_retrieval
from caseops_api.services.private_retrieval_jobs import rebuild_private_index
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers

SHA = "a" * 40
PASSWORD = "ProductionQa2026!Safe"
SLUG = "caseops-ip-qa-saved"


def _fixture(client):
    with get_session_factory()() as session:
        qa = ensure_ip_production_qa(
            session,
            company_name="CaseOps IP QA LLP",
            company_slug=SLUG,
            owner_full_name="IP QA owner",
            owner_email="ip-qa-saved@caseops.ai",
            owner_password=PASSWORD,
        )
        fixture = ensure_ip_production_qa_saved_manifest_fixture(
            session,
            company_id=qa.company_id,
            membership_id=qa.membership_id,
            release_sha=SHA,
            member_password=PASSWORD,
        )
    tokens = []
    for email in ("ip-qa-saved@caseops.ai", fixture["member_email"]):
        response = client.post(
            "/api/auth/login",
            json={
                "company_slug": SLUG,
                "email": email,
                "password": PASSWORD,
            },
        )
        assert response.status_code == 200, response.text
        tokens.append(str(response.json()["access_token"]))
        client.cookies.clear()
    return qa, fixture, tokens[0], tokens[1]


def _lifecycle(client, token, matter_id, status):
    current = client.get(f"/api/matters/{matter_id}", headers=auth_headers(token)).json()
    response = client.patch(
        f"/api/matters/{matter_id}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": status,
            "expected_from_status": current["status"],
            "expected_updated_at": current["updated_at"],
            "reason": "Synthetic saved-manifest QA lifecycle proof.",
        },
    )
    assert response.status_code == 200, response.text


def test_saved_manifest_fixture_is_real_capture_benignly_retired_and_replay_preserves_it(client):
    qa, fixture, _, token = _fixture(client)
    with get_session_factory()() as session:
        generation = session.get(PrivateIndexGeneration, fixture["captured_generation_id"])
        assert generation.state == "retired"
        assert generation.retired_at is not None
        assert fixture["captured_generation_id"] != fixture["benign_generation_id"]
        assert session.scalar(select(func.count()).select_from(AuthorityDocument)) == 0
        assert session.scalar(select(func.count()).select_from(Recommendation)) == 0
        for case in fixture["cases"].values():
            version = session.get(DraftVersion, case["version_id"])
            manifest = json.loads(version.source_manifest_json)
            assert len(manifest) == 1
            assert manifest[0]["schema"] == private_retrieval.PRIVATE_SAVED_SOURCE_SCHEMA
            assert manifest[0]["source_type"] == "matter_document"
            assert manifest[0]["source_id"] == case["attachment_id"]
            assert manifest[0]["source_version"] == case["source_version"]
            assert manifest[0]["generation_id"] == generation.id
            assert version.model_run_id is None
        counts = [
            session.scalar(select(func.count()).select_from(model))
            for model in (Matter, Draft, DraftVersion, PrivateIndexGeneration, User)
        ]
        repeated = ensure_ip_production_qa_saved_manifest_fixture(
            session,
            company_id=qa.company_id,
            membership_id=qa.membership_id,
            release_sha=SHA,
            member_password=PASSWORD,
        )
        assert repeated == {**fixture, "created_fixture": False}
        assert counts == [
            session.scalar(select(func.count()).select_from(model))
            for model in (Matter, Draft, DraftVersion, PrivateIndexGeneration, User)
        ]
    response = client.get(
        f"/api/matters/{fixture['anchor_id']}/drafts", headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    assert {draft["id"] for draft in response.json()["drafts"]} == {
        case["draft_id"] for case in fixture["cases"].values()
    }


@pytest.mark.parametrize("event", ["access", "tombstone"])
def test_document_sister_draft_stays_revoked_after_restore_rebuild_and_fixture_replay(
    client, monkeypatch, event
):
    qa, fixture, owner, member = _fixture(client)
    case = fixture["cases"][event]
    root = f"/api/matters/{fixture['anchor_id']}/drafts"
    detail = f"{root}/{case['draft_id']}"
    edit = client.patch(
        detail,
        headers=auth_headers(member),
        json={
            "body": f"Synthetic frozen Draft QA evidence: {fixture['matter_code']} {event}. "
            "Not a legal opinion. Manual QA edit."
        },
    )
    assert edit.status_code == 200, edit.text
    assert len(edit.json()["versions"]) == 2
    assert (
        edit.json()["versions"][-1]["source_manifest"]
        == edit.json()["versions"][0]["source_manifest"]
    )
    for extension in ("docx", "pdf"):
        export = client.get(f"{detail}/export.{extension}", headers=auth_headers(member))
        assert export.status_code == 422, export.text
        assert export.json()["type"] == "verified_citations_required"
    if event == "access":
        wall = client.post(
            f"/api/matters/{case['matter_id']}/access/walls",
            headers=auth_headers(owner),
            json={
                "excluded_membership_id": fixture["membership_id"],
                "reason": "Synthetic saved-manifest later access event.",
            },
        )
        assert wall.status_code == 200, wall.text
        denied = client.get(f"/api/matters/{case['matter_id']}", headers=auth_headers(member))
        assert denied.status_code == 404, denied.text
        removed = client.delete(
            f"/api/matters/{case['matter_id']}/access/walls/{wall.json()['id']}",
            headers=auth_headers(owner),
        )
        assert removed.status_code == 204, removed.text
    else:
        _lifecycle(client, owner, case["matter_id"], "disposed")
        _lifecycle(client, owner, case["matter_id"], "intake")
    restored = client.get(f"/api/matters/{case['matter_id']}", headers=auth_headers(member))
    assert restored.status_code == 200, restored.text
    workspace = client.get(
        f"/api/matters/{case['matter_id']}/workspace", headers=auth_headers(member)
    )
    assert workspace.status_code == 200, workspace.text
    document = next(
        row for row in workspace.json()["attachments"] if row["id"] == case["attachment_id"]
    )
    assert document["sha256_hex"] == case["source_version"]
    with get_session_factory()() as session:
        assert (
            session.get(MatterAttachment, case["attachment_id"]).sha256_hex
            == case["source_version"]
        )
        rebuild_private_index(session, company_id=qa.company_id, activate=True)
        session.commit()
        membership = session.get(CompanyMembership, fixture["membership_id"])
        context = SessionContext(
            company=session.get(Company, qa.company_id),
            user=session.get(User, membership.user_id),
            membership=membership,
        )
        frozen = session.get(DraftVersion, case["version_id"])
        manifest = json.loads(frozen.source_manifest_json)
        assert (
            session.get(PrivateIndexProjection, manifest[0]["projection_id"]).is_tombstoned is False
        )
        assert (
            private_retrieval.private_saved_source_manifest_is_current(
                session, context=context, manifest=manifest
            )
            is False
        )
        # This is the exact old fail-open shape: retired rows and current bytes
        # still match after real APIs restore access and rebuild the index.
        with monkeypatch.context() as old_behavior:
            old_behavior.setattr(
                private_retrieval, "_later_event_reaches_projection", lambda: false()
            )
            assert (
                private_retrieval.private_saved_source_manifest_is_current(
                    session, context=context, manifest=manifest
                )
                is True
            )
        assert (
            hashlib.sha256(frozen.source_manifest_json.encode()).hexdigest()
            == case["manifest_sha256"]
        )
        repeated = ensure_ip_production_qa_saved_manifest_fixture(
            session,
            company_id=qa.company_id,
            membership_id=qa.membership_id,
            release_sha=SHA,
            member_password=PASSWORD,
        )
        assert repeated["created_fixture"] is False
    listed = client.get(root, headers=auth_headers(member))
    assert listed.status_code == 200, listed.text
    assert case["draft_id"] not in {draft["id"] for draft in listed.json()["drafts"]}
    assert fixture["cases"]["control"]["draft_id"] in {
        draft["id"] for draft in listed.json()["drafts"]
    }
    for suffix in ("", "/export.docx", "/export.pdf"):
        rejected = client.get(detail + suffix, headers=auth_headers(member))
        assert rejected.status_code == 409, rejected.text
        assert "Private source access or generation changed" in rejected.text


@pytest.mark.parametrize("drift", ["manifest", "body", "document", "credential"])
def test_saved_manifest_fixture_rejects_retained_drift_without_rewriting(client, drift):
    qa, fixture, _, _ = _fixture(client)
    with get_session_factory()() as session:
        case = fixture["cases"]["access"]
        version = session.get(DraftVersion, case["version_id"])
        if drift == "manifest":
            version.source_manifest_json = "[]"
        elif drift == "body":
            version.body = "Unexpected retained content"
        elif drift == "document":
            session.get(
                MatterAttachment, case["attachment_id"]
            ).extracted_text = "Unexpected source bytes"
        session.commit()
        before = version.source_manifest_json, version.body
        with pytest.raises(ValueError, match="drifted"):
            ensure_ip_production_qa_saved_manifest_fixture(
                session,
                company_id=qa.company_id,
                membership_id=qa.membership_id,
                release_sha=SHA,
                member_password="WrongProductionQa2026!" if drift == "credential" else PASSWORD,
            )
        assert (version.source_manifest_json, version.body) == before


@pytest.mark.parametrize("sha", ["", "short", "A" * 40])
def test_saved_manifest_fixture_rejects_non_exact_release(client, sha):
    del client
    with get_session_factory()() as session, pytest.raises(ValueError, match="release SHA"):
        ensure_ip_production_qa_saved_manifest_fixture(
            session,
            company_id="missing",
            membership_id="missing",
            release_sha=sha,
            member_password=PASSWORD,
        )


def test_saved_manifest_fixture_preserves_terminal_source_without_reopen_or_recapture(client):
    qa, fixture, owner, _ = _fixture(client)
    source_id = fixture["cases"]["tombstone"]["matter_id"]
    _lifecycle(client, owner, source_id, "disposed")
    with get_session_factory()() as session:
        generation_ids = list(session.scalars(select(PrivateIndexGeneration.id)))
        repeated = ensure_ip_production_qa_saved_manifest_fixture(
            session,
            company_id=qa.company_id,
            membership_id=qa.membership_id,
            release_sha=SHA,
            member_password=PASSWORD,
        )
        assert repeated == {**fixture, "created_fixture": False}
        assert session.get(Matter, source_id).status == "disposed"
        assert list(session.scalars(select(PrivateIndexGeneration.id))) == generation_ids
        version = session.get(DraftVersion, fixture["cases"]["tombstone"]["version_id"])
        assert (
            hashlib.sha256(version.source_manifest_json.encode()).hexdigest()
            == fixture["cases"]["tombstone"]["manifest_sha256"]
        )


def test_production_seed_completes_canonical_events_and_rebuild_before_paused_browser_qa(client):
    qa, initial, owner, member_token = _fixture(client)
    with get_session_factory()() as session:
        prepared = ensure_ip_production_qa_saved_manifest_fixture(
            session,
            company_id=qa.company_id,
            membership_id=qa.membership_id,
            release_sha=SHA,
            member_password=PASSWORD,
            prepare_later_event_evidence=True,
        )
        assert prepared["post_event_generation_id"] not in {
            initial["captured_generation_id"],
            initial["benign_generation_id"],
        }
        generation = session.get(PrivateIndexGeneration, prepared["post_event_generation_id"])
        assert generation.state == "active"
        for name, ids in prepared["later_event_audit_ids"].items():
            assert len(ids) == 2
            for event_id in ids:
                event = session.get(AuditEvent, event_id)
                assert event.matter_id == initial["cases"][name]["matter_id"]
                assert event.result == "success"
                assert event.actor_membership_id == qa.membership_id
                assert event.created_at <= generation.activated_at
        counts = [
            session.scalar(select(func.count()).select_from(model))
            for model in (AuditEvent, PrivateIndexGeneration, DraftVersion)
        ]
        repeated = ensure_ip_production_qa_saved_manifest_fixture(
            session,
            company_id=qa.company_id,
            membership_id=qa.membership_id,
            release_sha=SHA,
            member_password=PASSWORD,
            prepare_later_event_evidence=True,
        )
        assert repeated == prepared
        assert counts == [
            session.scalar(select(func.count()).select_from(model))
            for model in (AuditEvent, PrivateIndexGeneration, DraftVersion)
        ]
    root = f"/api/matters/{initial['anchor_id']}/drafts"
    listed = client.get(root, headers=auth_headers(member_token))
    assert listed.status_code == 200, listed.text
    assert [draft["id"] for draft in listed.json()["drafts"]] == [
        initial["cases"]["control"]["draft_id"]
    ]
    for name in ("access", "tombstone"):
        for suffix in ("", "/export.docx", "/export.pdf"):
            rejected = client.get(
                f"{root}/{initial['cases'][name]['draft_id']}{suffix}",
                headers=auth_headers(member_token),
            )
            assert rejected.status_code == 409, rejected.text
            assert "Private source access or generation changed" in rejected.text
    # Later terminal state is retained even on production-seed replay.
    source_id = initial["cases"]["tombstone"]["matter_id"]
    _lifecycle(client, owner, source_id, "disposed")
    with get_session_factory()() as session:
        replay = ensure_ip_production_qa_saved_manifest_fixture(
            session,
            company_id=qa.company_id,
            membership_id=qa.membership_id,
            release_sha=SHA,
            member_password=PASSWORD,
            prepare_later_event_evidence=True,
        )
        assert replay == prepared
        assert session.get(Matter, source_id).status == "disposed"
