"""Real HTTP snapshots across an atomic document-worker PostgreSQL commit."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from caseops_api.api.routes import contracts as contract_routes
from caseops_api.api.routes import matters as matter_routes
from caseops_api.db.models import (
    CompanyMembership,
    ContractAttachment,
    DocumentProcessingJob,
    Matter,
    MatterAttachment,
)
from caseops_api.services import contracts, document_jobs, matters
from tests.test_auth_company import auth_headers, bootstrap_company

pytestmark = pytest.mark.postgres
BODY = ("Controlled offline workspace snapshot content. " * 70)[:2838] + "X"
DIGEST = sha256(BODY.encode("ascii")).hexdigest()


def _tuple(row):
    job = row["latest_job"]
    return (
        row["processing_status"],
        row["extracted_char_count"],
        row["sha256_hex"],
        job["id"],
        job["action"],
        job["status"],
        job["processed_char_count"],
        job["error_message"],
        job["attempt_count"],
    )


def _row(client, fixture):
    response = client.get(fixture.path + "/workspace", headers=fixture.headers)
    assert response.status_code == 200, response.text
    return next(row for row in response.json()["attachments"] if row["id"] == fixture.id)


def _fixture(client, monkeypatch, target, *, linked=False):
    if target not in {"matter", "contract"}:
        raise ValueError("Unsupported snapshot fixture target.")
    # Admit through the production HTTP route, but release the real worker only
    # at the barrier. This intercepts dispatch, not indexing or serialization.
    for route in (matter_routes, contract_routes):
        monkeypatch.setattr(route, "dispatch_document_processing_job", lambda **_: None)
    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    matter_id = None
    if target == "matter" or linked:
        response = client.post(
            "/api/matters/",
            headers=headers,
            json={
                "title": "Native snapshot parent",
                "matter_code": uuid4().hex,
                "practice_area": "Civil",
                "forum_level": "high_court",
                "status": "intake",
            },
        )
        assert response.status_code == 200, response.text
        matter_id = response.json()["id"]
    if target == "contract":
        response = client.post(
            "/api/contracts/",
            headers=headers,
            json={
                "title": "Native snapshot contract",
                "contract_code": uuid4().hex,
                "contract_type": "agreement",
                "status": "under_review",
                "linked_matter_id": matter_id,
            },
        )
        assert response.status_code == 200, response.text
        parent_id = response.json()["id"]
    else:
        assert matter_id is not None
        parent_id = matter_id
    path = f"/api/{'matters' if target == 'matter' else 'contracts'}/{parent_id}"
    upload = client.post(
        path + "/attachments",
        headers=headers,
        files={"file": ("snapshot.txt", BODY.encode("ascii"), "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    record = upload.json()
    assert len(BODY) == 2839 and record["sha256_hex"] == DIGEST
    assert record["extracted_char_count"] == 0
    assert record["latest_job"]["status"] == "queued"
    return SimpleNamespace(
        path=path,
        headers=headers,
        id=record["id"],
        job=record["latest_job"]["id"],
        actor=actor,
        matter_id=matter_id,
        model=MatterAttachment if target == "matter" else ContractAttachment,
        service=matters if target == "matter" else contracts,
    )


@pytest.mark.parametrize("target", ["matter", "contract"])
@pytest.mark.parametrize("action", ["initial_index", "reindex"])
def test_http_workspace_never_tears_worker_snapshot(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    record_property,
    target,
    action,
):
    client, engine = isolated_postgres_client, http_pg_engine
    fixture = _fixture(client, monkeypatch, target)
    if action == "reindex":
        assert document_jobs.run_document_processing_job(fixture.job) is True
        response = client.post(
            fixture.path + f"/attachments/{fixture.id}/reindex", headers=fixture.headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["latest_job"]["id"] != fixture.job
        fixture.job = response.json()["latest_job"]["id"]
    before = _tuple(_row(client, fixture))
    assert before[3:6] == (fixture.job, action, "queued")
    if action == "initial_index":
        assert before[0:2] == ("pending", 0)
    entered, release = Event(), Event()
    boundary = {}
    original = fixture.service.load_latest_processing_jobs

    def paused(session, *, target_type, attachment_ids):
        if fixture.id in attachment_ids and not entered.is_set():
            source = next(
                a
                for a in session.identity_map.values()
                if isinstance(a, fixture.model) and a.id == fixture.id
            )
            boundary["cached_source"] = (
                source.processing_status,
                source.extracted_char_count,
                source.sha256_hex,
            )
            boundary["reader_pid"] = session.scalar(text("SELECT pg_backend_pid()"))
            boundary["isolation"] = session.scalar(text("SHOW transaction_isolation"))
            assert boundary["isolation"] == "read committed"
            entered.set()
            assert release.wait(20), "Worker commit barrier was not released"
        return original(session, target_type=target_type, attachment_ids=attachment_ids)

    monkeypatch.setattr(fixture.service, "load_latest_processing_jobs", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        read = pool.submit(_row, client, fixture)
        try:
            assert entered.wait(20), "HTTP workspace did not reach materialized-source boundary"
            with Session(engine) as check:
                job = check.get(DocumentProcessingJob, fixture.job)
                assert job.status == "queued" and job.no_paid_providers is True
                boundary["worker_probe_pid"] = check.scalar(text("SELECT pg_backend_pid()"))
            assert boundary["reader_pid"] != boundary["worker_probe_pid"]
            assert document_jobs.run_document_processing_job(fixture.job) is True
            with Session(engine) as check:
                source, job = (
                    check.get(fixture.model, fixture.id),
                    check.get(DocumentProcessingJob, fixture.job),
                )
                assert source.processing_status == "indexed"
                assert source.extracted_text == BODY and source.extracted_char_count == 2839
                assert source.sha256_hex == DIGEST
                assert (
                    job.status,
                    job.processed_char_count,
                    job.error_message,
                    job.attempt_count,
                ) == ("completed", 2839, None, 1)
                boundary["worker_committed"] = True
        finally:
            release.set()
        raced = _tuple(read.result(20))
    monkeypatch.setattr(fixture.service, "load_latest_processing_jobs", original)
    complete = _tuple(_row(client, fixture))
    assert complete == ("indexed", 2839, DIGEST, fixture.job, action, "completed", 2839, None, 1)
    evidence = {
        "target": target,
        "action": action,
        "before": before,
        "raced": raced,
        "fresh": complete,
        "boundary": boundary,
        "original_production_field": "unknown",
    }
    print("CONTROLLED_SNAPSHOT " + json.dumps(evidence), flush=True)
    record_property("controlled_snapshot", json.dumps(evidence))
    # Overlapping reads may linearize before or after the commit, never across it.
    assert raced in (before, complete), evidence


@pytest.mark.parametrize("target", ["matter", "contract"])
def test_snapshot_does_not_overwrite_unrelated_dirty_metadata(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    target,
):
    fixture = _fixture(isolated_postgres_client, monkeypatch, target)
    with Session(http_pg_engine, autoflush=False, expire_on_commit=False) as session:
        source = session.get(fixture.model, fixture.id)
        source.original_filename = "unsaved-local-metadata.txt"
        fixture.service._attachment_record_map(session, [source])
        assert source.original_filename == "unsaved-local-metadata.txt"
        assert session.is_modified(source)
        with Session(http_pg_engine) as observer:
            assert observer.get(fixture.model, fixture.id).original_filename == "snapshot.txt"
        session.commit()
    with Session(http_pg_engine) as check:
        assert (
            check.get(fixture.model, fixture.id).original_filename == "unsaved-local-metadata.txt"
        )


@pytest.mark.parametrize("target", ["matter", "contract"])
def test_http_workspace_attachment_reads_are_batched(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    target,
):
    client = isolated_postgres_client
    fixture = _fixture(client, monkeypatch, target)
    statements = []

    def capture(conn, _cursor, statement, _parameters, context, _many):
        if conn.engine.url.database == http_pg_engine.url.database and context.compiled:
            if context.compiled.statement.is_select:
                statements.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        _row(client, fixture)
        baseline = len(statements)
        assert sum("document_processing_jobs" in s for s in statements) == 1
        for index in range(5):
            response = client.post(
                fixture.path + "/attachments",
                headers=fixture.headers,
                files={
                    "file": (
                        f"extra-{index}.txt",
                        f"Distinct offline {index}".encode(),
                        "text/plain",
                    )
                },
            )
            assert response.status_code == 200, response.text
        statements.clear()
        response = client.get(fixture.path + "/workspace", headers=fixture.headers)
        assert response.status_code == 200 and len(response.json()["attachments"]) == 6
        assert sum("document_processing_jobs" in s for s in statements) == 1
        assert len(statements) <= baseline + 2, (baseline, len(statements))
    finally:
        event.remove(Engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("target", ["matter", "contract"])
@pytest.mark.parametrize("fence", ["membership", "disposed_matter"])
def test_worker_snapshot_keeps_current_access_and_lifecycle_fences(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    target,
    fence,
):
    client = isolated_postgres_client
    fixture = _fixture(client, monkeypatch, target, linked=fence == "disposed_matter")
    if fence == "membership":
        with Session(http_pg_engine) as session:
            session.get(CompanyMembership, fixture.actor["membership"]["id"]).is_active = False
            session.commit()
        assert client.get(fixture.path + "/workspace", headers=fixture.headers).status_code == 403
    else:
        path = f"/api/matters/{fixture.matter_id}"
        response = client.get(path, headers=fixture.headers)
        assert response.status_code == 200, response.text
        current = response.json()
        disposed = client.patch(
            path + "/lifecycle/status",
            headers=fixture.headers,
            json={
                "to_status": "disposed",
                "expected_from_status": current["status"],
                "expected_updated_at": current["updated_at"],
                "reason": "Native snapshot terminal fence",
            },
        )
        assert disposed.status_code == 200, disposed.text
    with Session(http_pg_engine) as check:
        before_status = check.get(DocumentProcessingJob, fixture.job).status
        expected_status = (
            "failed" if fence == "disposed_matter" and target == "matter" else "queued"
        )
        assert before_status == expected_status
    # The worker reports admission, not success. Disposal already neutralizes
    # Matter jobs; historical human provenance does not cancel company work.
    claimed = document_jobs.run_document_processing_job(fixture.job)
    assert claimed is (before_status == "queued")
    with Session(http_pg_engine) as check:
        source, job = (
            check.get(fixture.model, fixture.id),
            check.get(DocumentProcessingJob, fixture.job),
        )
        assert job.no_paid_providers is True
        if fence == "membership":
            assert source.processing_status == "indexed"
            assert source.extracted_char_count == 2839 and source.extracted_text == BODY
            assert source.sha256_hex == DIGEST
            assert (job.status, job.processed_char_count, job.error_message) == (
                "completed",
                2839,
                None,
            )
            assert (
                check.get(CompanyMembership, fixture.actor["membership"]["id"]).is_active is False
            )
        else:
            assert source.processing_status != "indexed" and source.extracted_char_count == 0
            assert (job.status, job.processed_char_count) == ("failed", 0)
            terminal = check.get(Matter, fixture.matter_id)
            assert terminal.status == "disposed" and terminal.is_active is False
    if fence == "membership":
        assert client.get(fixture.path + "/workspace", headers=fixture.headers).status_code == 403
