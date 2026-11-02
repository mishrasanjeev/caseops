"""Caller-observed native work writes; HTTP proofs, not device acceptance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from caseops_api.db.models import AuditEvent, MatterActivity, MatterHearing, MatterTask
from caseops_api.db.session import get_session_factory
from tests.test_native_auth_20261024 import _browser, _device, _headers

KINDS = ("task", "hearing")


PROBLEM_MESSAGES = {
    "native_matter_lifecycle_required": "Reload the matter and include expected_lifecycle_version.",
    "native_task_version_required": "Reload the task and include expected_updated_at.",
    "native_hearing_version_required": "Reload the hearing and include expected_record_version.",
    "matter_lifecycle_changed": "The matter lifecycle changed. Reload before saving work.",
    "matter_task_changed": "The task changed. Reload before saving.",
    "matter_hearing_changed": "The hearing changed. Reload before saving.",
    "native_work_changes_required": "Include at least one changed work field.",
    "matter_task_lifecycle_history_immutable": (
        "This task is immutable lifecycle history. Create a new task after reopening instead."
    ),
    "matter_hearing_lifecycle_history_immutable": (
        "This hearing is immutable lifecycle history. Create a new hearing after reopening instead."
    ),
}


def assert_work_problem(response, code):
    """HTTP problem details expose a string detail and top-level extension code."""
    body = response.json()
    assert response.headers["content-type"].split(";", 1)[0] == "application/problem+json"
    assert body["status"] == response.status_code
    assert body["code"] == code
    assert body["detail"] == PROBLEM_MESSAGES[code]



def work_case(client):
    auth, browser = _browser(client)
    created = client.post(
        "/api/matters/",
        headers=browser,
        json={
            "title": "Observed native work",
            "matter_code": "NATIVE-WORK-FENCE",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Synthetic client",
            "opposing_party": "Synthetic respondent",
        },
    )
    assert created.status_code == 200, created.text
    native = _headers(_device(client, browser))
    # Native identity comes from the device credential, never this optional header.
    client.headers.pop("X-CaseOps-Client", None)
    return {
        "client": client,
        "browser": browser,
        "native": native,
        "matter": created.json(),
        "auth": auth,
    }


def endpoint(case, kind, record=None):
    assert kind in KINDS
    base = f"/api/matters/{case['matter']['id']}/{'tasks' if kind == 'task' else 'hearings'}"
    return base if record is None else f"{base}/{record['id']}"


def create_payload(kind):
    assert kind in KINDS
    if kind == "task":
        return {
            "title": "Retained task",
            "description": "Original description",
            "due_on": "2026-10-30",
            "priority": "medium",
        }
    return {
        "hearing_on": "2026-10-30",
        "forum_name": "Synthetic court",
        "purpose": "Recorded review",
        "reminder_channels": ["in_app"],
        "reminder_offsets_hours": [24],
    }


def create_record(case, kind, *, native=False):
    payload = create_payload(kind)
    if native:
        payload["expected_lifecycle_version"] = case["matter"]["lifecycle_version"]
    result = case["client"].post(
        endpoint(case, kind), headers=case["native" if native else "browser"], json=payload
    )
    assert result.status_code == 200, result.text
    return result.json()


def patch_payload(case, kind, record):
    assert kind in KINDS
    result = {"expected_lifecycle_version": case["matter"]["lifecycle_version"]}
    if kind == "task":
        result.update(expected_updated_at=record["updated_at"], description=None)
    else:
        result.update(expected_record_version=record["record_version"], outcome_note="Reviewed")
    return result


def current_workspace(case):
    response = case["client"].get(
        f"/api/matters/{case['matter']['id']}/workspace", headers=case["native"]
    )
    assert response.status_code == 200, response.text
    return response.json()


def transition(case, target):
    current = current_workspace(case)["matter"]
    response = case["client"].patch(
        f"/api/matters/{current['id']}/lifecycle/status",
        headers=case["browser"],
        json={
            "to_status": target,
            "expected_from_status": current["status"],
            "expected_updated_at": current["updated_at"],
            "reason": "Owned work fence regression",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def persistence(case):
    with get_session_factory()() as session:
        result = []
        for model in (MatterTask, MatterHearing, MatterActivity):
            rows = list(
                session.scalars(select(model).where(model.matter_id == case["matter"]["id"]))
            )
            result.append(
                sorted(
                    [{c.key: getattr(row, c.key) for c in model.__table__.columns} for row in rows],
                    key=lambda row: row["id"],
                )
            )
        result.append(session.scalar(select(func.count()).select_from(AuditEvent)))
        return result


def exercise_required_and_current(client, kind):
    case = work_case(client)
    missing = client.post(endpoint(case, kind), headers=case["native"], json=create_payload(kind))
    assert missing.status_code == 422, missing.text
    assert_work_problem(missing, "native_matter_lifecycle_required")
    record = create_record(case, kind, native=True)
    assert record["immutable_lifecycle_history"] is False
    for key in ("created_at", "updated_at") if kind == "task" else ():
        assert datetime.fromisoformat(record[key].replace("Z", "+00:00")).utcoffset() == timedelta(
            0
        )
    if kind == "hearing":
        assert record["record_version"].startswith("mhv1:")
        assert len(record["record_version"]) == 69
    original = persistence(case)
    supplied = patch_payload(case, kind, record)
    supplied.pop("expected_updated_at" if kind == "task" else "expected_record_version")
    refused = client.patch(endpoint(case, kind, record), headers=case["native"], json=supplied)
    assert refused.status_code == 422, refused.text
    assert_work_problem(
        refused,
        "native_task_version_required" if kind == "task" else "native_hearing_version_required",
    )
    assert persistence(case) == original
    result = client.patch(
        endpoint(case, kind, record), headers=case["native"], json=patch_payload(case, kind, record)
    )
    assert result.status_code == 200, result.text
    changed = result.json()
    if kind == "task":
        assert changed["description"] is None
        for key in ("title", "due_on", "priority", "owner_membership_id"):
            assert changed[key] == record[key]
        with get_session_factory()() as session:
            row = session.get(MatterTask, record["id"])
            assert not hasattr(row, "expected_lifecycle_version")
            assert not hasattr(row, "expected_updated_at")
    else:
        assert changed["outcome_note"] == "Reviewed"
        assert changed["record_version"] != record["record_version"]
        assert changed["hearing_on"] == record["hearing_on"]
    reloaded = current_workspace(case)
    assert (
        next(
            r
            for r in reloaded["tasks" if kind == "task" else "hearings"]
            if r["id"] == record["id"]
        )
        == changed
    )


def exercise_close_reopen(client, kind, operation):
    assert operation in ("create", "update")
    case = work_case(client)
    record = create_record(case, kind)
    old_version = case["matter"]["lifecycle_version"]
    closed = transition(case, "disposed")
    closed_workspace = current_workspace(case)
    retained = next(
        r
        for r in closed_workspace["tasks" if kind == "task" else "hearings"]
        if r["id"] == record["id"]
    )
    assert retained["cancelled_by_matter_disposal"] is True
    assert retained["immutable_lifecycle_history"] is True
    reopened = transition(case, "intake")
    assert reopened["lifecycle_version"] == old_version + 2
    assert closed["lifecycle_version"] == old_version + 1
    before = persistence(case)
    payload = create_payload(kind) if operation == "create" else patch_payload(case, kind, record)
    payload["expected_lifecycle_version"] = old_version
    invoke = client.post if operation == "create" else client.patch
    path = endpoint(case, kind, None if operation == "create" else record)
    for authority in ("native", "browser"):
        response = invoke(path, headers=case[authority], json=payload)
        assert response.status_code == 409, response.text
        assert_work_problem(response, "matter_lifecycle_changed")
        assert persistence(case) == before
    # Closed-history children remain immutable even after a fresh parent read.
    if operation == "update":
        payload["expected_lifecycle_version"] = reopened["lifecycle_version"]
        payload["expected_updated_at" if kind == "task" else "expected_record_version"] = (
            retained["updated_at"] if kind == "task" else retained["record_version"]
        )
        response = client.patch(path, headers=case["native"], json=payload)
        assert response.status_code == 409, response.text
        assert_work_problem(response, f"matter_{kind}_lifecycle_history_immutable")
        assert persistence(case) == before


def exercise_stale_child(client, kind):
    case = work_case(client)
    record = create_record(case, kind)
    update = (
        {"title": "Browser revision"} if kind == "task" else {"outcome_note": "Browser revision"}
    )
    winner = client.patch(endpoint(case, kind, record), headers=case["browser"], json=update)
    assert winner.status_code == 200, winner.text
    before = persistence(case)
    for authority in ("native", "browser"):
        stale = client.patch(
            endpoint(case, kind, record),
            headers=case[authority],
            json=patch_payload(case, kind, record),
        )
        assert stale.status_code == 409, stale.text
        assert_work_problem(
            stale, "matter_task_changed" if kind == "task" else "matter_hearing_changed"
        )
        assert persistence(case) == before
    fresh = client.patch(
        endpoint(case, kind, record),
        headers=case["native"],
        json=patch_payload(case, kind, winner.json()),
    )
    assert fresh.status_code == 200, fresh.text


@pytest.mark.parametrize("kind", KINDS)
def test_native_work_requires_observed_parent_and_current_child(client, kind):
    exercise_required_and_current(client, kind)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("operation", ["create", "update"])
def test_work_stale_parent_close_reopen_and_retained_history(client, kind, operation):
    exercise_close_reopen(client, kind, operation)


@pytest.mark.parametrize("kind", KINDS)
def test_native_stale_child_rejects_without_audit_or_sibling_mutation(client, kind):
    exercise_stale_child(client, kind)


@pytest.mark.parametrize("kind", KINDS)
def test_native_control_only_patch_refuses_but_legacy_browser_omission_remains(client, kind):
    case = work_case(client)
    record = create_record(case, kind)
    controls = patch_payload(case, kind, record)
    controls.pop("description" if kind == "task" else "outcome_note")
    before = persistence(case)
    response = client.patch(endpoint(case, kind, record), headers=case["native"], json=controls)
    assert response.status_code == 422, response.text
    assert_work_problem(response, "native_work_changes_required")
    assert persistence(case) == before
    legacy = client.patch(
        endpoint(case, kind, record),
        headers={**case["browser"], "X-CaseOps-Client": "native"},
        json={},
    )
    assert legacy.status_code == 200, legacy.text


@pytest.mark.parametrize("value", [True, False, -1, 1.5, "0"])
def test_work_lifecycle_dto_rejects_noninteger_observation(value):
    from pydantic import ValidationError

    from caseops_api.schemas.matters import (
        MatterHearingCreateRequest,
        MatterHearingUpdateRequest,
        MatterTaskCreateRequest,
        MatterTaskUpdateRequest,
    )

    for model, fields in [
        (MatterTaskCreateRequest, create_payload("task")),
        (MatterHearingCreateRequest, create_payload("hearing")),
        (MatterTaskUpdateRequest, {"title": "Changed"}),
        (MatterHearingUpdateRequest, {"outcome_note": "Changed"}),
    ]:
        with pytest.raises(ValidationError):
            model(**fields, expected_lifecycle_version=value)


def test_hearing_content_version_covers_hidden_fields_company_and_key_without_history_claim(
    monkeypatch,
):
    from copy import deepcopy

    from caseops_api.core.settings import get_settings
    from caseops_api.services.matters import _hearing_content_version

    hearing = MatterHearing(
        id="hearing-one",
        company_id="company-one",
        matter_id="matter-one",
        hearing_on=datetime(2026, 10, 30).date(),
        forum_name="Synthetic court",
        purpose="Synthetic review",
        status="scheduled",
        created_at=datetime(2026, 10, 27, tzinfo=UTC),
        reminder_policy_json={"recipient_membership_ids": ["hidden-member"]},
    )
    original = _hearing_content_version(hearing)
    hearing.created_at = hearing.created_at.replace(tzinfo=None)
    assert _hearing_content_version(hearing) == original  # Known SQLite UTC equals PG UTC.
    for field, value in [
        ("company_id", "company-two"),
        ("id", "hearing-two"),
        ("meeting_url", "https://synthetic.invalid/other"),
        ("attendee_membership_ids_json", ["other-member"]),
        ("reminder_policy_json", {"recipient_membership_ids": ["other-member"]}),
        ("outcome_note", "Revised"),
        ("cancelled_by_matter_disposal", True),
    ]:
        old = deepcopy(getattr(hearing, field))
        setattr(hearing, field, value)
        assert _hearing_content_version(hearing) != original
        setattr(hearing, field, old)
        assert _hearing_content_version(hearing) == original  # Exact state ABA is explicit.
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_secret", "different-owned-test-key-at-least32bytes")
    assert _hearing_content_version(hearing) != original


@pytest.mark.parametrize("value", ["2026-10-27T01:02:03", 0, True, 1.5])
def test_task_expected_updated_at_requires_offset_and_rejects_epoch_coercion(value):
    from pydantic import ValidationError

    from caseops_api.schemas.matters import MatterTaskUpdateRequest

    with pytest.raises(ValidationError):
        MatterTaskUpdateRequest(description=None, expected_updated_at=value)


def test_task_expected_updated_at_normalizes_an_explicit_client_offset():
    from caseops_api.schemas.matters import MatterTaskUpdateRequest

    value = MatterTaskUpdateRequest(
        description=None,
        expected_updated_at="2026-10-27T06:32:03+05:30",
    )
    assert value.expected_updated_at == datetime(2026, 10, 27, 1, 2, 3, tzinfo=UTC)
