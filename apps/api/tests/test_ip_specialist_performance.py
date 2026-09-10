from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.engine import Engine

from caseops_api.db.models import (
    IpDocumentVersion,
    IpRelatedRightObligation,
    MatterDeadline,
    MatterTask,
)
from caseops_api.db.session import get_session_factory
from tests import test_ip_specialist as intake
from tests import test_ip_specialist_workflows as journey

registered_intake = intake.registered_intake


@pytest.fixture(autouse=True)
def retain_sql_diagnosis():
    def failed(context):
        print(f"Specialist test SQL failure: {context.original_exception}")

    event.listen(Engine, "handle_error", failed)
    try:
        yield
    finally:
        event.remove(Engine, "handle_error", failed)


def active_contract(client):
    headers, record, pin = journey.start(client, "licensing")
    instrument = journey.source_set(client, headers, record, pin, "instrument")
    facts = journey.licence_facts(instrument)
    draft = journey.save(client, headers, record, facts, status=201).json()
    active = journey.save(
        client,
        headers,
        record,
        {
            **facts,
            "interpretation": "reviewed",
            "review_reason": "Reviewed source clauses",
            "status": "active",
        },
        draft,
        status=200,
    ).json()
    return headers, record, pin, instrument, active


def obligation(client, headers, record, pin, active, kind="notice", status=201):
    response = client.post(
        journey.url(record, active) + "/obligations",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_version": active["version"],
            "expected_lifecycle_version": record["lifecycle_version"],
            "kind": kind,
            "title": f"Retained {kind} obligation",
            "due_on_as_supplied": "2026-10-01",
            "source": pin,
        },
    )
    assert response.status_code == status, response.text
    return response.json()


@pytest.mark.parametrize("action", ["complete", "cancel", "notice_recorded"])
def test_contract_performance_replay_and_reload(client, registered_intake, action):
    headers, record, pin, _, active = active_contract(client)
    work = obligation(client, headers, record, pin, active)
    path = journey.url(record, active) + f"/obligations/{work['id']}/performance"
    payload = {
        "expected_lifecycle_version": record["lifecycle_version"],
        "action": action,
        "occurred_on": "2026-09-10",
        "account": "Retained performance receipt",
        "source": pin,
    }
    key_headers = {**headers, "Idempotency-Key": str(uuid4())}
    saved = client.post(path, headers=key_headers, json=payload)
    assert saved.status_code == 201, saved.text
    replay = client.post(path, headers=key_headers, json=payload)
    assert replay.status_code == 201 and replay.json() == saved.json(), replay.text
    history = client.get(path, headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["records"] == [saved.json()]
    listed = client.get(journey.url(record, active) + "/obligations", headers=headers)
    expected = {"complete": "completed", "cancel": "cancelled", "notice_recorded": "open"}[action]
    assert listed.status_code == 200, listed.text
    assert listed.json()["records"][0]["status"] == expected
    with get_session_factory()() as session:
        assert (
            session.get(MatterTask, work["task_id"]).status
            == {"complete": "completed", "cancel": "cancelled", "notice_recorded": "todo"}[action]
        )
        assert (
            session.get(MatterDeadline, work["deadline_id"]).status
            == {"complete": "done", "cancel": "cancelled", "notice_recorded": "open"}[action]
        )
    if action != "notice_recorded":
        stale = client.post(
            path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=payload
        )
        assert stale.status_code == 409, stale.text
        assert client.get(path, headers=headers).json()["records"] == [saved.json()]


def test_obligation_requires_current_instrument_not_just_an_accessible_clause(
    client, registered_intake
):
    headers, record, pin, instrument, active = active_contract(client)
    revised = journey.save(
        client,
        headers,
        record,
        {**instrument["facts"], "title": "Corrected instrument set"},
        instrument,
        status=200,
    ).json()
    rejected = obligation(client, headers, record, pin, active, status=409)
    assert "specialist_source_set_stale" in str(rejected)
    assert (
        client.get(journey.url(record, active) + "/obligations", headers=headers).json()["records"]
        == []
    )
    active = journey.save(
        client,
        headers,
        record,
        {**active["facts"], "source_set": {"id": revised["id"], "version": revised["version"]}},
        active,
        status=200,
    ).json()
    obligation(client, headers, record, pin, active)


def test_performance_rejects_retired_contract_source_and_preserves_open_work(
    client, registered_intake
):
    headers, record, pin, _, active = active_contract(client)
    work = obligation(client, headers, record, pin, active)
    _, fresh, _ = intake.observation(
        client, headers, record, content=b"Distinct contract performance receipt " * 20
    )
    with get_session_factory()() as session:
        session.get(IpDocumentVersion, pin["document_version_id"]).state = "superseded"
        session.commit()
    path = journey.url(record, active) + f"/obligations/{work['id']}/performance"
    response = client.post(
        path,
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_lifecycle_version": record["lifecycle_version"],
            "action": "complete",
            "occurred_on": "2026-09-10",
            "account": "New receipt cannot revive retired contract evidence",
            "source": fresh["source"],
        },
    )
    assert response.status_code == 409, response.text
    assert "specialist_source_retired" in response.text
    assert client.get(path, headers=headers).json()["records"] == []
    assert (
        client.get(journey.url(record, active) + "/obligations", headers=headers).json()["records"][
            0
        ]["status"]
        == "open"
    )


def test_unregistered_workflow_contract_rejects_intake_version(
    client, registered_intake, monkeypatch
):
    from dataclasses import replace

    from caseops_api.services import ip_domain_catalog as catalog

    headers, record, pin = journey.start(client, "design")
    old = replace(catalog.DOMAIN_BY_ID["design"], contract_version="OTHER-IP-2026-09-09.1")
    monkeypatch.setitem(catalog.DOMAIN_BY_ID, "design", old)
    response = journey.save(
        client,
        headers,
        record,
        {
            "kind": "source_set",
            "purpose": "representations",
            "title": "Not activated by intake approval",
            "members": [{"role": "Front", "source": deepcopy(pin)}],
        },
        status=409,
    )
    assert "specialist_contract_unregistered" in response.text


def test_performance_rolls_back_task_when_deadline_rejects(client, registered_intake, monkeypatch):
    from caseops_api.services import ip_specialist_workflows as service

    headers, record, pin, _, active = active_contract(client)
    work = obligation(client, headers, record, pin, active)

    def reject(*args, **kwargs):
        raise HTTPException(409, "Concurrent calendar change")

    monkeypatch.setattr(service, "update_ip_operational_deadline", reject)
    path = journey.url(record, active) + f"/obligations/{work['id']}/performance"
    response = client.post(
        path,
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_lifecycle_version": 0,
            "action": "complete",
            "occurred_on": "2026-09-10",
            "account": "Receipt",
            "source": pin,
        },
    )
    assert response.status_code == 409, response.text
    with get_session_factory()() as session:
        assert session.get(MatterTask, work["task_id"]).status == "todo"
        assert session.get(MatterDeadline, work["deadline_id"]).status == "open"
        assert session.get(IpRelatedRightObligation, work["id"]).status == "open"
    assert client.get(path, headers=headers).json()["records"] == []


def test_parent_close_reopen_second_close_retains_obligations_without_resurrection(
    client, registered_intake
):
    headers, record, pin, _, active = active_contract(client)
    work = obligation(client, headers, record, pin, active)
    path = journey.url(record, active) + f"/obligations/{work['id']}/performance"
    payload = {
        "expected_lifecycle_version": 0,
        "action": "complete",
        "occurred_on": "2026-09-10",
        "account": "Receipt",
        "source": pin,
    }
    command = {
        "expected_lifecycle_version": 0,
        "to_status": "closed",
        "effective_at": datetime.now(UTC).isoformat(),
        "reason": "Client closure instruction",
        "outcome": "closed",
        "source": "lawyer_review",
        "evidence_ref": "test:closure",
        "linked_matter_handling": "reviewed",
    }
    lifecycle = f"/api/ip/dockets/{record['docket_id']}/lifecycle"
    closed = client.post(lifecycle, headers=headers, json=command)
    assert closed.status_code == 200, closed.text
    denied = client.post(path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=payload)
    assert denied.status_code == 404, denied.text
    retained = client.get(journey.url(record, active) + "/obligations", headers=headers)
    assert retained.status_code == 200, retained.text
    assert retained.json()["records"][0]["status"] == "cancelled_lifecycle"
    with get_session_factory()() as session:
        neutral = (
            session.get(MatterTask, work["task_id"]).status,
            session.get(MatterDeadline, work["deadline_id"]).status,
        )
    reopened = client.post(
        lifecycle,
        headers=headers,
        json={
            **command,
            "expected_lifecycle_version": 1,
            "to_status": "ready",
            "outcome": "reopened",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert (
        client.post(
            path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=payload
        ).status_code
        == 409
    )
    assert (
        client.post(
            path,
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={**payload, "expected_lifecycle_version": 2},
        ).status_code
        == 409
    )
    with get_session_factory()() as session:
        assert (
            session.get(MatterTask, work["task_id"]).status,
            session.get(MatterDeadline, work["deadline_id"]).status,
        ) == neutral
    second = client.post(
        lifecycle, headers=headers, json={**command, "expected_lifecycle_version": 2}
    )
    assert second.status_code == 200, second.text
    assert second.json()["event"]["id"] != closed.json()["event"]["id"]
    assert (
        client.get(journey.url(record, active), headers=headers).json()["facts"] == active["facts"]
    )
    assert client.get(path, headers=headers).json()["records"] == []


def test_performance_requires_replacement_after_void_and_retains_original_cost(
    client, registered_intake
):
    headers, record, pin, _, active = active_contract(client)
    costs = journey.url(record, active) + "/cost-evidence"
    cost_payload = {
        "expected_lifecycle_version": 0,
        "description": "Source-reported payment",
        "amount_minor": 25000,
        "currency": "INR",
        "source": pin,
    }
    cost_headers = {**headers, "Idempotency-Key": str(uuid4())}
    cost = client.post(costs, headers=cost_headers, json=cost_payload)
    assert cost.status_code == 201, cost.text
    cost_id = cost.json()["id"]
    assert client.post(costs, headers=cost_headers, json=cost_payload).json() == cost.json()
    result = client.post(
        journey.url(record, active) + "/obligations",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_version": active["version"],
            "expected_lifecycle_version": 0,
            "kind": "royalty",
            "title": "Source payment",
            "due_on_as_supplied": "2026-10-01",
            "source": pin,
            "cost_item_id": cost_id,
        },
    )
    assert result.status_code == 201, result.text
    work = result.json()
    voided = client.post(
        f"{costs}/{cost_id}/void",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_lifecycle_version": 0, "reason": "Receipt withdrawn", "source": pin},
    )
    assert voided.status_code == 200, voided.text
    path = journey.url(record, active) + f"/obligations/{work['id']}/performance"
    payload = {
        "expected_lifecycle_version": 0,
        "action": "complete",
        "occurred_on": "2026-09-10",
        "account": "Payment receipt",
        "source": pin,
    }
    rejected = client.post(path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=payload)
    assert rejected.status_code == 409 and "specialist_cost_inactive" in rejected.text
    replacement = client.post(
        costs,
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**cost_payload, "description": "Replacement payment evidence"},
    )
    assert replacement.status_code == 201, replacement.text
    replacement_id = replacement.json()["id"]
    options = client.get(journey.url(record, active) + "/cost-options", headers=headers)
    assert options.status_code == 200, options.text
    assert [row["id"] for row in options.json()["records"]] == [replacement_id]
    performed = client.post(
        path,
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**payload, "replacement_cost_item_id": replacement_id},
    )
    assert performed.status_code == 201, performed.text
    assert performed.json()["cost_item_id"] == replacement_id
    historical = client.get(
        journey.url(record, active) + f"/obligations/{work['id']}", headers=headers
    )
    assert historical.status_code == 200 and historical.json()["cost_item_id"] == cost_id


def test_confidential_cost_options_and_mutations_recheck_financial_access(
    client, registered_intake, monkeypatch
):
    from caseops_api.services import ip_specialist_workflows as service

    headers, record, pin, _, active = active_contract(client)
    costs = journey.url(record, active) + "/cost-evidence"
    payload = {
        "expected_lifecycle_version": 0,
        "description": "Confidential payment",
        "amount_minor": 25000,
        "currency": "INR",
        "source": pin,
    }
    created = client.post(costs, headers={**headers, "Idempotency-Key": str(uuid4())}, json=payload)
    assert created.status_code == 201, created.text
    monkeypatch.setattr(service, "_may_read_confidential_rates", lambda *args, **kwargs: False)
    options = client.get(journey.url(record, active) + "/cost-options", headers=headers)
    assert options.status_code == 200 and options.json() == {"records": [], "next_cursor": None}
    assert (
        client.post(
            costs, headers={**headers, "Idempotency-Key": str(uuid4())}, json=payload
        ).status_code
        == 403
    )
    void = client.post(
        f"{costs}/{created.json()['id']}/void",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_lifecycle_version": 0, "reason": "Not authorized", "source": pin},
    )
    assert void.status_code == 403, void.text
