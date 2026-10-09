"""HTTP-seeded outer commands overlap a real same-actor indexing worker."""

import os
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    DocumentProcessingJob,
    Matter,
    MatterAttachment,
    PrivateProjectionEvent,
)
from caseops_api.schemas.ip_watch import IpWatchHandoffRequest
from caseops_api.schemas.workspace_assistant import AssistantActionConfirmRequest
from caseops_api.services import assistant_actions, document_jobs, ip_watch
from caseops_api.services.private_retrieval import ensure_active_private_generation
from tests.test_auth_company import bootstrap_company
from tests.test_ip_journal_watch import _fixture as watch_fixture
from tests.test_ip_journal_watch import _ingest, _profile, _publication
from tests.test_matter_writer_admission_postgres import _provider, _Race
from tests.test_postgres_validation import _ip_race_context, _seed_matter
from tests.test_workspace_assistant_actions import _preview, _write_proposal
from tests.test_workspace_assistant_qa import _ask, _enable_assistant, _matter, _session

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("first", ["worker", "outer"])
@pytest.mark.parametrize("command", ["assistant", "watch"])
def test_outer_command_admits_before_actor_and_parent(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    tmp_path,
    request,
    autoflush,
    first,
    command,
):
    client = isolated_postgres_client
    if command == "assistant":
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _enable_assistant(client, token)
        target = _matter(client, token, "OUTER-ADMISSION")
        body, proposal = _write_proposal(
            _ask(
                client,
                token,
                assistant_session=_session(client, token, target["id"]),
                question="Update the client name on this matter.",
                no_paid_providers=True,
            ),
            "field_update",
        )
        assistant_session = body["session"]
        response = _preview(
            client,
            token,
            assistant_session=assistant_session,
            turn_id=body["assistant_turn"]["id"],
            proposal=proposal,
            action_input={"field_name": "client_name", "field_value": "Serialized client"},
        )
        assert response.status_code == 200, response.text
        preview = response.json()
    else:
        bootstrap, headers, docket, application = watch_fixture(client)
        _profile(
            client,
            headers=headers,
            docket_id=docket["id"],
            recipient_id=bootstrap["membership"]["id"],
        )
        result = _ingest(
            client,
            headers=headers,
            key="actor-admission-watch",
            publication=_publication(application_id=application["id"]),
        )
        hit = result["hits"][0]
        response = client.post(
            f"/api/ip/watch/hits/{hit['id']}/disposition",
            headers=headers,
            json={
                "expected_version": hit["version"],
                "disposition": "relevant",
                "reason": "Official source confirms local overlap.",
                "source_confirmed": True,
            },
        )
        assert response.status_code == 200, response.text

    company, actor = bootstrap["company"]["id"], bootstrap["membership"]["id"]
    with Session(http_pg_engine) as seed:
        parent = _seed_matter(seed, company)
        attachment = MatterAttachment(
            matter_id=parent,
            uploaded_by_membership_id=actor,
            original_filename="outer-source.txt",
            storage_key=f"outer/{uuid4()}",
            content_type="text/plain",
            size_bytes=23,
            sha256_hex="a" * 64,
            document_type="other",
        )
        seed.add(attachment)
        seed.flush()
        job = DocumentProcessingJob(
            company_id=company,
            requested_by_membership_id=actor,
            target_type="matter_attachment",
            attachment_id=attachment.id,
            action="initial_index",
        )
        seed.add(job)
        ensure_active_private_generation(seed, company_id=company)
        seed.commit()
        fixture = SimpleNamespace(
            company=company, actor=actor, matter=parent, attachment=attachment.id, job=job.id
        )

    directory = Path(os.environ.get("CASEOPS_ACTOR_AUDIT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (sha256(request.node.nodeid.encode()).hexdigest()[:20] + ".jsonl")
    with path.open("x", encoding="utf-8") as evidence:
        race = _Race(http_pg_engine, evidence, autoflush)
        race.record("test", nodeid=request.node.nodeid)
        _provider(monkeypatch, race, fixture)
        race.pause_role = first
        race.predicate = lambda sql: "FROM companies" in sql and "FOR NO KEY UPDATE" in sql

        def outer_command():
            with race.session("outer") as session:
                context = _ip_race_context(session, company_id=company, membership_id=actor)
                if command == "assistant":
                    result = assistant_actions.confirm_assistant_action(
                        session,
                        context=context,
                        session_id=assistant_session["id"],
                        preview_id=preview["preview_id"],
                        payload=AssistantActionConfirmRequest(
                            expected_version=assistant_session["version"],
                            preview_token=preview["preview_token"],
                        ),
                    )
                    assert result.status == "confirmed"
                else:
                    result = ip_watch.create_watch_handoff(
                        session,
                        context=context,
                        hit_id=hit["id"],
                        payload=IpWatchHandoffRequest(
                            handoff_kind="enforcement_matter",
                            title="Watch admission enforcement",
                            matter_code="WATCH-ADMISSION",
                            assignee_membership_id=actor,
                        ),
                    )
                    assert result.status == "completed"
                return result

        operations = {
            "outer": outer_command,
            "worker": lambda: document_jobs.run_document_processing_job(fixture.job),
        }
        second = "outer" if first == "worker" else "worker"
        try:
            a = race.submit(first, operations[first])
            assert race.paused.wait(10)
            b = race.submit(second, operations[second])
            race.blocked(second, first, "FROM companies")
            race.release.set()
            a.result(15)
            b.result(15)
            locks = [sql for sql in race.sql["outer"] if "FOR " in sql]
            assert "FROM companies" in locks[0] and "FOR NO KEY UPDATE" in locks[0]
            assert any("FROM company_memberships" in sql and "FOR UPDATE" in sql for sql in locks)
        finally:
            race.close()

    with Session(http_pg_engine) as verify:
        assert verify.get(DocumentProcessingJob, fixture.job).status == "completed"
        if command == "assistant":
            assert verify.get(Matter, target["id"]).client_name == "Serialized client"
        else:
            assert verify.scalar(select(Matter.id).where(Matter.matter_code == "WATCH-ADMISSION"))
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(PrivateProjectionEvent.company_id == company)
            )
        )
        assert len(events) >= 2
        assert all(row.actor_membership_id == actor for row in events)
