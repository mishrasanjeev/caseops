"""Stable SQL selection before existing communication timeline source caps."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from caseops_api.db.models import Communication, MatterAttachment, MatterNote, PortalUser
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_communications import _create_matter

TIED_AT = datetime(2026, 10, 1, 12, tzinfo=UTC)
SOURCES = {
    "communications": (Communication, "platform", 1, "internal"),
    "notes": (MatterNote, "notes", 2, "internal"),
    "attachments": (MatterAttachment, "attachments", 3, "firm_only"),
}


@pytest.fixture(params=[
    pytest.param("client", id="sqlite"),
    pytest.param("isolated_postgres_client", id="postgres", marks=pytest.mark.postgres),
])
def source_client(request):
    client = request.getfixturevalue(request.param)
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    return client


@pytest.fixture
def owned_matter(source_client):
    bootstrap = bootstrap_company(source_client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter = _create_matter(source_client, headers, "COMMS-ORDER")
    return source_client, bootstrap, headers, matter


def _identity(kind, number):
    return f"{SOURCES[kind][2]:08x}-0000-4000-8000-{number:012x}"


def _rows(kind, bootstrap, matter, numbers, *, at=TIED_AT):
    result = []
    for number in numbers:
        identity = _identity(kind, number)
        row = {"id": identity, "matter_id": matter, "created_at": at}
        if kind == "communications":
            row.update(company_id=bootstrap["company"]["id"], channel="phone",
                       body=f"Recorded communication {number}", occurred_at=at,
                       created_by_membership_id=bootstrap["membership"]["id"],
                       metadata_json={"portal_visible": False})
        elif kind == "notes":
            row.update(author_membership_id=bootstrap["membership"]["id"],
                       body=f"Internal note {number}")
        else:
            row.update(uploaded_by_membership_id=bootstrap["membership"]["id"],
                       original_filename=f"reference-{number}.txt",
                       storage_key=f"read-order/{matter}/{identity}.txt",
                       content_type="text/plain", size_bytes=1, sha256_hex="a" * 64)
        result.append(row)
    return result


def _seed(kind, rows):
    with get_session_factory()() as session:
        session.execute(insert(SOURCES[kind][0]), rows)
        session.commit()


@contextmanager
def _observe_source_orders():
    statements = {}

    def observe(state):
        if state.is_select:
            descriptions = getattr(state.statement, "column_descriptions", [])
            if len(descriptions) == 1:
                model = descriptions[0].get("entity")
                if model in (Communication, MatterNote, MatterAttachment):
                    statements[model] = state.statement

    event.listen(Session, "do_orm_execute", observe)
    try:
        yield statements
    finally:
        event.remove(Session, "do_orm_execute", observe)


@pytest.mark.parametrize("kind", ["notes", "communications", "attachments"])
def test_tied_timeline_source_boundary_is_exact(owned_matter, kind, record_property):
    client, bootstrap, headers, matter = owned_matter
    model, selected_filter, _, visibility = SOURCES[kind]
    other = _create_matter(client, headers, "COMMS-OTHER")
    _seed(kind, _rows(kind, bootstrap, other, [9000], at=TIED_AT - timedelta(days=1)))
    _seed(kind, _rows(kind, bootstrap, matter, range(502, -1, -1)))
    with _observe_source_orders() as statements:
        response = client.get(
            f"/api/matters/{matter}/communications/timeline?filter={selected_filter}",
            headers=headers,
        )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    actual = [item["source_id"] for item in items]
    expected = [_identity(kind, number) for number in range(500)]
    record_property("tied_source_rows", 503)
    record_property("actual_selected_identity_order", json.dumps(actual))
    assert len(actual) == len(set(actual)) == 500
    assert all(item["visibility"] == visibility for item in items)
    assert actual == expected
    assert _identity(kind, 9000) not in actual
    expected_order = ([model.occurred_at.asc(), model.created_at.asc(), model.id.asc()]
                      if kind == "communications" else [model.created_at.asc(), model.id.asc()])
    observed_order = list(statements[model]._order_by_clauses)
    assert len(observed_order) == len(expected_order)
    assert all(
        actual.compare(wanted)
        for actual, wanted in zip(observed_order, expected_order, strict=True)
    )
    assert statements[model]._limit_clause.value == 500
    assert all(item["occurred_at"].startswith("2026-10-01T12:00:00") for item in items)


def test_standalone_list_keeps_descending_time_and_identity_ties(owned_matter):
    client, bootstrap, headers, matter = owned_matter
    rows = _rows("communications", bootstrap, matter, range(4, -1, -1))
    rows += _rows("communications", bootstrap, matter, [100], at=TIED_AT + timedelta(days=1))
    rows += _rows("communications", bootstrap, matter, [200], at=TIED_AT - timedelta(days=1))
    _seed("communications", rows)
    with _observe_source_orders() as statements:
        response = client.get(f"/api/matters/{matter}/communications", headers=headers)
    assert response.status_code == 200, response.text
    expected = [_identity("communications", number) for number in (100, 4, 3, 2, 1, 0, 200)]
    assert [row["id"] for row in response.json()["communications"]] == expected
    actual_order = list(statements[Communication]._order_by_clauses)
    assert len(actual_order) == 2
    assert actual_order[0].compare(Communication.occurred_at.desc())
    assert actual_order[1].compare(Communication.id.desc())
    assert statements[Communication]._limit_clause is None


def test_ordering_preserves_tenant_and_visibility_boundaries(owned_matter):
    client, bootstrap, headers, matter = owned_matter
    internal, imported, visible = _rows("communications", bootstrap, matter, [0, 1, 2])
    imported.update(channel="email", metadata_json={"source": "manual_inbound_email_import"})
    with get_session_factory()() as session:
        portal_user = PortalUser(
            company_id=bootstrap["company"]["id"], email="read-client@example.in",
            full_name="Recorded client", role="client", is_active=True,
        )
        session.add(portal_user)
        session.flush()
        portal_id = portal_user.id
        session.commit()
    visible.update(channel="note", metadata_json={"portal_user_id": portal_id})
    _seed("communications", [visible, imported, internal])
    _seed("notes", _rows("notes", bootstrap, matter, [0]))
    _seed("attachments", _rows("attachments", bootstrap, matter, [0]))
    endpoint = f"/api/matters/{matter}/communications/timeline"
    response = client.get(endpoint, headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    labels = {item["source_id"]: item["visibility"] for item in items}
    assert labels == {
        _identity("communications", 0): "internal",
        _identity("communications", 1): "imported_email",
        _identity("communications", 2): "client_visible",
        _identity("notes", 0): "internal",
        _identity("attachments", 0): "firm_only",
    }
    filtered = client.get(endpoint + "?filter=internal", headers=headers)
    assert filtered.status_code == 200, filtered.text
    assert {item["source_id"] for item in filtered.json()["items"]} == {
        _identity("communications", 0), _identity("notes", 0), _identity("attachments", 0),
    }
    assert "storage_key" not in json.dumps(items)
    assert "sha256" not in json.dumps(items)
    client.cookies.clear()
    other = client.post("/api/bootstrap/company", json={
        "company_name": "Other Read LLP", "company_slug": "other-communication-read",
        "company_type": "law_firm", "owner_full_name": "Other Reader",
        "owner_email": "other-reader@example.in", "owner_password": "OtherReadStrong123!",
    })
    assert other.status_code == 200, other.text
    foreign_headers = auth_headers(other.json()["access_token"])
    for suffix in ("", "/timeline", "/timeline?filter=notes", "/timeline?filter=internal"):
        denied = client.get(
            f"/api/matters/{matter}/communications{suffix}", headers=foreign_headers,
        )
        assert denied.status_code == 404, denied.text
