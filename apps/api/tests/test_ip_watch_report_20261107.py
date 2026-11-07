"""AI-B05 / AI-R0585: retained watch facts are not an automated-feed claim.

REPORT-01/02, IP-WATCH-02/04, UJ-21/27/33; SEC-003/004 and NFT-005.
All captures are synthetic offline evidence, never a provider readiness probe.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    IpDocketRecord,
    IpJournalPublication,
    IpWatchHit,
    IpWatchProfile,
    MembershipRole,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import ip_watch
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_journal_watch import (
    _colleague,
    _fixture,
    _ingest,
    _profile,
    _publication,
    _word_profile,
)
from tests.test_ip_record_access_workflow import (
    _apply as _apply_access,
)
from tests.test_ip_record_access_workflow import (
    _preview as _preview_access,
)
from tests.test_ip_record_workflow import _application, _asset, _bootstrap_tenant, _particulars
from tests.test_ip_report_foundation import _preview


def _report(client: TestClient, headers: dict[str, str], limit: int = 50) -> dict:
    response = _preview(
        client,
        headers | {"X-CaseOps-Automated-Test": "no-paid-providers"},
        "watch",
        row_limit=limit,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed(client: TestClient) -> tuple[dict, dict, dict, dict, dict]:
    bootstrap, headers, docket, application = _fixture(client)
    profile = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    captured = _ingest(
        client,
        headers=headers,
        key="ai-b05-retained-capture-0001",
        publication=_publication(application_id=application["id"]),
        cost_minor=0,
    )
    assert len(captured["hits"]) == 1
    return bootstrap, headers, docket, profile, captured


def test_watch_report_reproduces_disconnected_adapter_and_preserves_review_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_activation(*_args, **_kwargs) -> None:
        pytest.fail("Retained watch reporting must not activate or call a provider.")

    monkeypatch.setattr(ip_watch, "_assert_automated_watch_available", reject_activation)
    bootstrap, headers, docket, profile, captured = _seed(client)
    hits = list(captured["hits"])
    for index in (2, 3):
        extra = _ingest(
            client,
            headers=headers,
            key=f"ai-b05-retained-capture-{index:04d}",
            publication=_publication(
                application_id=captured["publications"][0]["application_id"],
                application_number=f"TM-AIB05-{index}",
                journal_number=f"TMJ-AIB05-{index}",
            ),
            cost_minor=0,
        )
        hits.extend(extra["hits"])
    assert len(hits) == 3
    for hit, disposition in zip(hits[:2], ("relevant", "monitor"), strict=True):
        reviewed = client.post(
            f"/api/ip/watch/hits/{hit['id']}/disposition",
            headers=headers,
            json={
                "expected_version": hit["version"],
                "disposition": disposition,
                "reason": f"Synthetic offline {disposition} assessment for reporting.",
                "source_confirmed": True,
            },
        )
        assert reviewed.status_code == 200, reviewed.text
    empty_profile = _word_profile(
        client,
        headers,
        docket_id=docket["id"],
        word="ZXQNOHITS",
        recipient=bootstrap["membership"]["id"],
    )
    with get_session_factory()() as session:
        before = {
            model.__tablename__: [
                {column.name: getattr(row, column.name) for column in model.__table__.columns}
                for row in session.scalars(select(model).order_by(model.id))
            ]
            for model in (IpWatchProfile, IpWatchHit, IpJournalPublication)
        }
    body = _report(client, headers)
    assert body["summary"] == {
        "available": True,
        "reason": "Only retained journal-watch records are included; automated journal "
        "coverage is unavailable.",
        "automated_coverage_available": False,
        "total": 4,
        "returned": 4,
        "profile_total": 2,
        "hit_total": 3,
        "new_hits": 1,
        "relevant_hits": 1,
        "reviewed_hits": 2,
        "pending_assessment": 1,
        "counts_are_complete": True,
    }
    assert body["row_count"] == 4 and body["truncated"] is False
    actual_hits = {row["hit_id"]: row for row in body["rows"] if row["hit_id"]}
    assert set(actual_hits) == {hit["id"] for hit in hits}
    first = actual_hits[hits[0]["id"]]
    assert first["profile_id"] == profile["id"]
    assert first["assessment"]["disposition"] == "relevant"
    assert first["assessment"]["decision"]["source_confirmed"] is True
    assert first["classes_goods"] == hits[0]["classes_goods_json"]
    assert first["compared_mark"] == hits[0]["compared_mark_json"]
    assert first["similarity_evidence"]["evidence"] == hits[0]["similarity_evidence_json"]
    assert first["similarity_evidence"]["notice"] == hits[0]["advisory_notice"]
    assert first["source_snapshot"] == hits[0]["source_snapshot_json"]
    assert first["source"]["url"] == captured["publications"][0]["source_url"]
    assert first["source"]["captured_at"]
    assert body["rows"][-1]["profile_id"] == empty_profile["id"]
    assert body["rows"][-1]["assessment"] is None
    assert body["rows"][-1]["hit_id"] is None
    assert body["freshness"]["status"] == "mixed"
    assert body["freshness"]["unavailable_sources"] == ["ip_watch_provider"]
    assert body["freshness"]["source_cutoffs"]["ip_watch_provider"] is None
    assert body["freshness"]["source_cutoffs"]["watch_profiles"]
    assert body["freshness"]["source_cutoffs"]["watch_hits"]
    assert body["freshness"]["source_cutoffs"]["journal_capture"]
    repeated = _report(client, headers)
    assert repeated["snapshot_sha256"] == body["snapshot_sha256"]
    assert repeated["rows"] == body["rows"]
    with get_session_factory()() as session:
        after = {
            model.__tablename__: [
                {column.name: getattr(row, column.name) for column in model.__table__.columns}
                for row in session.scalars(select(model).order_by(model.id))
            ]
            for model in (IpWatchProfile, IpWatchHit, IpJournalPublication)
        }
    assert after == before


@pytest.mark.parametrize("source_status", ["available", "unavailable", "stale"])
def test_watch_report_retains_source_limitations_without_legal_promotion(
    client: TestClient, source_status: str
) -> None:
    bootstrap, headers, docket, application = _fixture(client)
    _word_profile(
        client, headers, docket_id=docket["id"], word="ASTER",
        recipient=bootstrap["membership"]["id"],
    )
    captured = _ingest(
        client,
        headers=headers,
        key="ai-b05-source-limitations-0001",
        publication=_publication(application_id=application["id"], source_status=source_status),
        cost_minor=0,
    )
    body = _report(client, headers)
    assert body["summary"]["hit_total"] == 1
    assert body["summary"]["pending_assessment"] == 1
    assert body["summary"]["automated_coverage_available"] is False
    assert body["rows"][0]["source"]["status"] == source_status
    assert body["rows"][0]["source"]["deadline_confirmation_state"] == "pending_confirmation"
    assert body["rows"][0]["assessment"]["disposition"] == "new"
    assert body["rows"][0]["source_snapshot"] == captured["hits"][0]["source_snapshot_json"]
    assert body["freshness"]["status"] == "mixed"


def test_watch_report_empty_records_are_distinct_from_unavailable_automated_coverage(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    body = _report(client, auth_headers(str(bootstrap["access_token"])))
    assert body["rows"] == [] and body["truncated"] is False
    assert body["summary"]["available"] is True
    assert body["summary"]["automated_coverage_available"] is False
    assert body["summary"]["profile_total"] == body["summary"]["hit_total"] == 0
    assert "No retained journal-watch records match your access" in body["summary"]["reason"]
    assert body["freshness"]["status"] == "mixed"
    assert set(body["freshness"]["source_cutoffs"].values()) == {None}


@pytest.mark.parametrize("denial", ["revoke_grant", "add_wall"])
def test_watch_report_rechecks_source_and_profile_access_without_hidden_counts_or_audit_ids(
    client: TestClient, denial: str
) -> None:
    bootstrap, headers, docket, _profile_row, captured = _seed(client)
    owner_id = bootstrap["membership"]["id"]
    colleague = _colleague(
        client, headers, email="watch-report-reviewer@aster.example", role=MembershipRole.ADMIN
    )
    client.cookies.clear()
    colleague_session = client.get("/api/auth/me", headers=colleague)
    assert colleague_session.status_code == 200, colleague_session.text
    colleague_id = colleague_session.json()["membership"]["id"]
    restricted = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={"title": "PRIVATE WATCH SOURCE", "restricted": True,
              "particulars": _particulars("PRIVATE WATCH SOURCE")},
    )
    assert restricted.status_code == 201, restricted.text
    private_id = restricted.json()["id"]
    private_profile = _word_profile(
        client, headers, docket_id=private_id, word="ASTER", recipient=owner_id
    )
    # The second capture is intentionally attached to the restricted source
    # application but matches the open watch too. An open watch is not a grant
    # to that source's retained snapshot.
    asset = _asset(client, headers, private_id, "PRIVATE WATCH SOURCE")
    application = _application(client, headers, private_id, asset["id"])
    private_capture = _ingest(
        client,
        headers=headers,
        key="ai-b05-private-capture-0001",
        publication=_publication(
            application_id=application["id"], application_number="TM-PRIVATE-AIB05",
            journal_number="TMJ-PRIVATE-AIB05",
        ),
        cost_minor=0,
    )
    assert len(private_capture["hits"]) == 2
    initial = _report(client, colleague)
    assert initial["summary"]["profile_total"] == initial["summary"]["hit_total"] == 1
    assert initial["rows"][0]["hit_id"] == captured["hits"][0]["id"]
    grant_payload = {
        "action": "grant", "expected_access_policy_version": 1,
        "reason": "Synthetic internal watch report access regression.",
        "subject_type": "membership", "subject_id": colleague_id,
    }
    preview = _preview_access(client, headers=headers, docket_id=private_id, payload=grant_payload)
    granted = _apply_access(
        client, headers=headers, docket_id=private_id, payload=grant_payload, preview=preview
    )
    visible = _report(client, colleague)
    assert visible["summary"]["profile_total"] == 2
    assert visible["summary"]["hit_total"] == 3
    assert private_profile["id"] in {row["profile_id"] for row in visible["rows"]}
    denial_payload = {
        "action": denial,
        "expected_access_policy_version": granted["panel"]["access_policy_version"],
        "reason": "Remove synthetic watch report visibility through current policy.",
    }
    if denial == "revoke_grant":
        grant = next(
            row for row in granted["panel"]["grants"]
            if row["subject_id"] == colleague_id and row["revoked_at"] is None
        )
        denial_payload["grant_id"] = grant["id"]
    else:
        denial_payload.update(subject_type="membership", subject_id=colleague_id)
    preview = _preview_access(client, headers=headers, docket_id=private_id, payload=denial_payload)
    _apply_access(
        client, headers=headers, docket_id=private_id, payload=denial_payload, preview=preview
    )
    hidden = _report(client, colleague)
    assert hidden["summary"]["profile_total"] == hidden["summary"]["hit_total"] == 1
    assert hidden["snapshot_sha256"] == initial["snapshot_sha256"]
    serialized = json.dumps(hidden)
    for secret in (private_id, private_profile["id"], application["id"], "TM-PRIVATE-AIB05"):
        assert secret not in serialized
    for hit in private_capture["hits"]:
        assert hit["id"] not in serialized
    with get_session_factory()() as session:
        audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "ip.report.previewed",
                AuditEvent.actor_membership_id == colleague_id,
            )
        ).all()
        metadata = [json.loads(row.metadata_json) for row in audits]
        assert any(row["snapshot_sha256"] == hidden["snapshot_sha256"]
                   and row["row_count"] == 1 for row in metadata)
        assert private_id not in json.dumps(metadata)
    other = _bootstrap_tenant(client, slug="ai-b05-other", email="owner@ai-b05-other.example")
    client.cookies.clear()
    isolated = _report(client, auth_headers(str(other["access_token"])))
    assert isolated["summary"]["profile_total"] == isolated["summary"]["hit_total"] == 0
    assert isolated["rows"] == []
    # Bootstrap did not replace the first actor's bearer scope.
    assert _report(client, headers)["summary"]["profile_total"] == 2
    assert docket["id"] not in json.dumps(isolated)


def test_watch_report_excludes_closed_dockets_without_mutating_retained_evidence(
    client: TestClient,
) -> None:
    _bootstrap, headers, docket, _profile_row, captured = _seed(client)
    assert _report(client, headers)["summary"]["hit_total"] == 1
    closed = client.post(
        f"/api/ip/dockets/{docket['id']}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": docket["lifecycle_version"],
            "to_status": "closed", "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Synthetic watch report terminal-parent regression.",
            "outcome": "closed", "source": "lawyer_review",
            "evidence_ref": "fixture:ai-b05-terminal-parent", "linked_matter_handling": "reviewed",
        },
    )
    assert closed.status_code == 200, closed.text
    body = _report(client, headers)
    assert body["rows"] == []
    assert body["summary"]["profile_total"] == body["summary"]["hit_total"] == 0
    with get_session_factory()() as session:
        retained = session.get(IpWatchHit, captured["hits"][0]["id"])
        assert retained is not None
        assert retained.source_snapshot_json == captured["hits"][0]["source_snapshot_json"]
        assert session.get(IpDocketRecord, docket["id"]).status == "closed"


def test_watch_report_bounds_hydration_and_queries_beyond_row_limit(
    client: TestClient,
) -> None:
    _bootstrap, headers, _docket_row, profile, captured = _seed(client)
    with get_session_factory()() as session:
        original_profile = session.get(IpWatchProfile, profile["id"])
        original_hit = session.get(IpWatchHit, captured["hits"][0]["id"])
        assert original_profile is not None and original_hit is not None
        profile_values = {
            column.name: getattr(original_profile, column.name)
            for column in IpWatchProfile.__table__.columns if column.name != "id"
        }
        hit_values = {
            column.name: getattr(original_hit, column.name)
            for column in IpWatchHit.__table__.columns if column.name not in {"id", "profile_id"}
        }
        extra_ids = [str(uuid4()) for _ in range(1000)]
        session.add_all(IpWatchProfile(id=identity, **profile_values) for identity in extra_ids)
        session.flush()
        session.add_all(IpWatchHit(profile_id=identity, **hit_values) for identity in extra_ids)
        session.commit()
    statements = []
    loaded = []

    def observe(_connection, _cursor, statement, _parameters, context, _many) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append((statement.lower(), getattr(context, "compiled", None)))

    def observe_load(_session, instance) -> None:
        if isinstance(instance, (IpWatchProfile, IpWatchHit, IpJournalPublication)):
            loaded.append(type(instance))

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", observe)
    event.listen(Session, "loaded_as_persistent", observe_load)
    try:
        body = _report(client, headers, limit=7)
    finally:
        event.remove(Session, "loaded_as_persistent", observe_load)
        event.remove(engine, "before_cursor_execute", observe)
    assert body["summary"]["profile_total"] == body["summary"]["hit_total"] == 1001
    assert body["summary"]["total"] == 1001
    assert body["summary"]["new_hits"] == body["summary"]["pending_assessment"] == 1001
    assert body["summary"]["returned"] == body["row_count"] == 7
    assert body["truncated"] is True
    watch_selects = [(sql, compiled) for sql, compiled in statements if "ip_watch_profiles" in sql]
    assert len(watch_selects) == 2, [sql for sql, _ in statements]
    assert len(loaded) == 14
    assert loaded.count(IpWatchProfile) == loaded.count(IpWatchHit) == 7
    assert IpJournalPublication not in loaded
    assert not any("ip_watch_handoffs" in sql or "ip_journal_ingestion_runs" in sql
                   for sql, _ in statements)
    limits = [
        getattr(getattr(compiled.statement, "_limit_clause", None), "value", None)
        for _sql, compiled in watch_selects
    ]
    assert limits.count(7) == 1 and limits.count(None) == 1
