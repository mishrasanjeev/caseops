"""J03/J04/J20, MOB-10/22/23: caller-observed upload lifecycle admission."""

from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from caseops_api.api.routes import matters as routes
from caseops_api.core.settings import get_settings
from caseops_api.db.models import DocumentProcessingJob, Matter, MatterActivity, MatterAttachment
from caseops_api.schemas.matters import MatterLifecycleStatusRequest
from caseops_api.services import document_storage, matters, virus_scan
from caseops_api.services.identity import get_session_context
from tests.test_native_auth_20261024 import _browser, _device, _headers
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres
CONTENT = b"%PDF-1.4\n% Owned offline upload lifecycle evidence\n%%EOF\n"


@pytest.fixture
def upload_case(isolated_postgres_client, http_pg_engine, monkeypatch):
    client = isolated_postgres_client
    assert http_pg_engine.dialect.name == "postgresql"
    assert client.headers["X-CaseOps-Automated-Test"] == "no-paid-providers"
    auth, browser = _browser(client)
    created = client.post(
        "/api/matters/",
        headers=browser,
        json={
            "title": "Synthetic upload fence",
            "matter_code": "UPLOAD-FENCE",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Synthetic QA Client",
            "opposing_party": "Synthetic QA Respondent",
        },
    )
    assert created.status_code == 200, created.text
    device = _device(client, browser)
    # The native credential, not a caller-selected header, identifies native writes.
    client.headers.pop("X-CaseOps-Client", None)
    native = _headers(device)
    me = client.get("/api/auth/me", headers=native)
    assert me.status_code == 200, me.text
    assert me.json()["membership"]["id"] == auth["membership"]["id"]
    observed = {"scan": 0, "store": 0, "dispatch": 0, "session": None}
    create = routes.create_matter_attachment
    place = document_storage._place_local_temp_file

    def capture(session, **kwargs):
        observed["session"] = session
        assert kwargs["context"].native_session_id == (
            device["session_id"] if kwargs["context"].native_session_id else None
        )
        return create(session, **kwargs)

    def scan(path):
        observed["scan"] += 1
        assert not observed["session"].in_transaction()
        assert path.read_bytes() == CONTENT
        return virus_scan.ScanResult(status="clean", signature=None)

    def store(temp, target):
        observed["store"] += 1
        assert not observed["session"].in_transaction()
        return place(temp, target)

    def dispatch(**kwargs):
        observed["dispatch"] += 1

    monkeypatch.setenv("CASEOPS_CLAMAV_REQUIRED", "true")
    monkeypatch.setattr(routes, "create_matter_attachment", capture)
    monkeypatch.setattr(routes, "dispatch_document_processing_job", dispatch)
    monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
    get_settings.cache_clear()
    return {
        "client": client,
        "engine": http_pg_engine,
        "auth": auth,
        "browser": browser,
        "native": native,
        "matter": created.json(),
        "observed": observed,
    }


def _transition(case, target):
    with Session(case["engine"]) as session:
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        context = get_session_context(session, case["auth"]["membership"]["id"])
        parent = session.get(Matter, case["matter"]["id"])
        return matters.transition_matter_lifecycle_status(
            session,
            context=context,
            matter_id=parent.id,
            payload=MatterLifecycleStatusRequest(
                to_status=target,
                expected_from_status=parent.status,
                expected_updated_at=parent.updated_at,
                reason="Owned synthetic lifecycle regression",
            ),
        )


def _post(case, authority, version):
    data = {} if version is None else {"expected_lifecycle_version": str(version)}
    return case["client"].post(
        f"/api/matters/{case['matter']['id']}/attachments",
        headers=case[authority],
        data=data,
        files={"file": ("source.pdf", CONTENT, "application/pdf")},
    )


def _assert_persistence(case, accepted):
    matter_id = case["matter"]["id"]
    with Session(case["engine"]) as session:
        rows = list(
            session.scalars(
                select(MatterAttachment).where(
                    MatterAttachment.matter_id == matter_id,
                )
            )
        )
        jobs = list(
            session.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.company_id == case["auth"]["company"]["id"],
                )
            )
        )
        activity = session.scalar(
            select(func.count())
            .select_from(MatterActivity)
            .where(
                MatterActivity.matter_id == matter_id,
                MatterActivity.event_type == "attachment_added",
            )
        )
        assert len(rows) == len(jobs) == activity == int(accepted)
        if accepted:
            assert rows[0].sha256_hex == sha256(CONTENT).hexdigest()
            assert rows[0].size_bytes == len(CONTENT)
            assert jobs[0].attachment_id == rows[0].id
    root = Path(get_settings().document_storage_path)
    files = [path for path in root.rglob("*") if path.is_file()]
    assert len(files) == int(accepted)
    if accepted:
        assert files[0].read_bytes() == CONTENT
    workspace = case["client"].get(
        f"/api/matters/{matter_id}/workspace",
        headers=case["native"],
    )
    assert workspace.status_code == 200, workspace.text
    assert len(workspace.json()["attachments"]) == int(accepted)
    return workspace.json()["matter"]


@pytest.mark.parametrize("authority", ["native", "browser"])
@pytest.mark.parametrize(
    "state", ["current", "closed", "reopened", "reopened-current", "missing", "future"]
)
def test_multipart_observed_version_admission(upload_case, authority, state):
    case = upload_case
    version = case["matter"]["lifecycle_version"]
    reopened = state.startswith("reopened")
    if state == "closed" or reopened:
        _transition(case, "disposed")
    if reopened:
        _transition(case, "intake")
    supplied = None if state == "missing" else version + (state == "future")
    if state == "reopened-current":
        supplied = version + 2
    response = _post(case, authority, supplied)
    accepted = state in {"current", "reopened-current"} or (
        state == "missing" and authority == "browser"
    )
    expected = 200 if accepted else (422 if state == "missing" else 409)
    assert response.status_code == expected, response.text
    assert [case["observed"][key] for key in ("scan", "store", "dispatch")] == (
        [1, 1, 1] if accepted else [0, 0, 0]
    )
    parent = _assert_persistence(case, accepted)
    assert parent["lifecycle_version"] == version + (2 if reopened else state == "closed")
    assert parent["status"] == (
        "disposed" if state == "closed" else "intake" if reopened else case["matter"]["status"]
    )
    if accepted:
        assert response.json()["sha256_hex"] == sha256(CONTENT).hexdigest()


@pytest.mark.parametrize("authority", ["native", "browser"])
@pytest.mark.parametrize("version", ["not-an-integer", "1.5", "-1"])
def test_invalid_multipart_version_has_no_upload_side_effects(upload_case, authority, version):
    case = upload_case
    response = _post(case, authority, version)
    assert response.status_code == 422, response.text
    assert any(
        error["loc"] == ["body", "expected_lifecycle_version"]
        for error in response.json()["errors"]
    )
    assert case["observed"] == {"scan": 0, "store": 0, "dispatch": 0, "session": None}
    _assert_persistence(case, False)


@pytest.mark.parametrize("boundary", ["scan", "storage"])
@pytest.mark.parametrize("reopen", [False, True])
def test_post_transport_lifecycle_change_rejects_and_removes_bytes(
    upload_case,
    monkeypatch,
    boundary,
    reopen,
):
    case = upload_case
    observed = case["observed"]
    scan = virus_scan.scan_file_for_viruses
    store = document_storage._place_local_temp_file
    changes = []

    def change():
        assert not observed["session"].in_transaction()
        changes.append(_transition(case, "disposed").lifecycle_version)
        if reopen:
            changes.append(_transition(case, "intake").lifecycle_version)

    def scanning(path):
        result = scan(path)
        if boundary == "scan":
            change()
        return result

    def storing(temp, target):
        result = store(temp, target)
        if boundary == "storage":
            change()
        return result

    monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scanning)
    monkeypatch.setattr(document_storage, "_place_local_temp_file", storing)
    response = _post(case, "native", case["matter"]["lifecycle_version"])
    assert response.status_code == 409, response.text
    assert len(changes) == (2 if reopen else 1)
    assert [observed[key] for key in ("scan", "store", "dispatch")] == [1, 1, 0]
    parent = _assert_persistence(case, False)
    assert parent["status"] == ("intake" if reopen else "disposed")
    assert parent["lifecycle_version"] == changes[-1]


def test_web_native_header_does_not_change_legacy_form_semantics(upload_case):
    case = upload_case
    case["browser"] = {**case["browser"], "X-CaseOps-Client": "native"}
    response = case["client"].post(
        f"/api/matters/{case['matter']['id']}/attachments",
        headers=case["browser"],
        files={"file": ("source.pdf", CONTENT, "application/pdf")},
        data={
            "document_type": "pleading_reply",
            "lifecycle_stage": "pleadings",
            "document_date": "2026-10-25",
            "sequence_index": "3",
        },
    )
    assert response.status_code == 200, response.text
    for field, value in {
        "document_type": "pleading_reply",
        "lifecycle_stage": "pleadings",
        "document_date": "2026-10-25",
        "sequence_index": 3,
    }.items():
        assert response.json()[field] == value
    _assert_persistence(case, True)


def test_openapi_upload_version_is_optional_nonnegative_multipart_integer(upload_case):
    schema = upload_case["client"].app.openapi()
    operation = schema["paths"]["/api/matters/{matter_id}/attachments"]["post"]
    body = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    form = schema["components"]["schemas"][body["$ref"].rsplit("/", 1)[1]]
    assert form["required"] == ["file"]
    assert form["properties"]["expected_lifecycle_version"]["anyOf"] == [
        {"type": "integer", "minimum": 0.0},
        {"type": "null"},
    ]


@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("partial", [False, True])
def test_authenticated_download_is_private_uncached_for_original_inline_and_range(
    upload_case,
    inline,
    partial,
):
    case = upload_case
    uploaded = _post(case, "native", case["matter"]["lifecycle_version"])
    assert uploaded.status_code == 200, uploaded.text
    attachment = uploaded.json()
    path = f"/api/matters/{case['matter']['id']}/attachments/{attachment['id']}/download"
    for terminal in (False, True):
        if terminal:
            _transition(case, "disposed")
        for authority in ("native", "browser"):
            headers = {**case[authority], **({"Range": "bytes=0-0"} if partial else {})}
            response = case["client"].get(
                path, headers=headers, params={"inline": str(inline).lower()}
            )
            assert response.status_code == (206 if partial else 200), response.text
            assert response.content == (CONTENT[:1] if partial else CONTENT)
            assert response.headers["Cache-Control"] == "private, no-store, max-age=0"
            assert response.headers["Pragma"] == "no-cache"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Content-Type"] == "application/pdf"
            assert response.headers["Content-Disposition"].startswith(
                "inline;" if inline else "attachment;"
            )
            assert "X-CaseOps-Checksum" not in response.headers
            if partial:
                assert response.headers["Content-Range"] == f"bytes 0-0/{len(CONTENT)}"
                assert response.headers["Content-Length"] == "1"
            else:
                assert sha256(response.content).hexdigest() == attachment["sha256_hex"]
    with Session(case["engine"]) as session:
        member = get_session_context(session, case["auth"]["membership"]["id"]).membership
        member.is_active = False
        session.commit()
    for authority in ("native", "browser"):
        denied = case["client"].get(path, headers={**case[authority], "Range": "bytes=0-0"})
        assert denied.status_code in {401, 403}, denied.text
        assert denied.content != CONTENT[:1]
