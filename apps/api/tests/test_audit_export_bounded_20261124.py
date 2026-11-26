"""Bounded synchronous audit export (GET /api/admin/audit/export).

The export used to load every row of the window into memory before streaming
one chunk per row, with no ceiling. These checks pin the replacement: rows come
from a bounded server-side cursor, a window over the documented row cap gets a
typed 422 before any byte is sent, a window that grows while streaming aborts
instead of ending as a complete-looking file, and the cap is counted per tenant.

The bodies take the client so the PostgreSQL module can replay them unchanged.
"""

from __future__ import annotations

import csv
import gc
import io
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, insert, select

from caseops_api.api.routes import admin as admin_routes
from caseops_api.db.models import AuditEvent, EthicalWall
from caseops_api.db.session import get_engine, get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_access_foundation import _invite_member, _particulars

EXPORT = "/api/admin/audit/export"
PROBE_ACTION = "audit.bounded_export_probe"


def _second_tenant(client: TestClient) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Bounded Export Tenant B",
            "company_slug": "bounded-export-b",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "owner@bounded-export-b.in",
            "owner_password": "BetaPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed(
    company_id: str,
    count: int,
    *,
    action: str = PROBE_ACTION,
    target_type: str = "bounded_export_probe",
    ip_docket_id: str | None = None,
) -> list[str]:
    """Insert `count` audit rows inside the default 30-day window, in a known
    (created_at, id) order, without building ORM objects in the test."""
    start = datetime.now(UTC) - timedelta(days=2)
    rows = [
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "actor_type": "system",
            "actor_label": "bounded-export-fixture",
            "action": action,
            "target_type": target_type,
            "ip_docket_id": ip_docket_id,
            "target_id": f"probe-{index}",
            "result": "success",
            "metadata_json": json.dumps({"index": index, "pad": "x" * 64}),
            "created_at": start + timedelta(milliseconds=index),
        }
        for index in range(count)
    ]
    with get_session_factory()() as session:
        for offset in range(0, count, 5_000):
            session.execute(insert(AuditEvent), rows[offset : offset + 5_000])
        session.commit()
    return [row["id"] for row in rows]


def _export_events(company_id: str) -> list[AuditEvent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "audit.exported",
                )
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            )
        )


def _live_audit_event_objects() -> int:
    return sum(1 for obj in gc.get_objects() if isinstance(obj, AuditEvent))


def streams_in_bounded_batches(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    batch = 100
    total = 3_000
    monkeypatch.setattr(admin_routes, "AUDIT_EXPORT_BATCH_SIZE", batch, raising=False)
    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    seeded = _seed(company_id, total)

    # Sample how many AuditEvent ORM objects are alive while rows are being
    # serialized. Loading the whole window first keeps all `total` alive.
    original_row = admin_routes._event_row
    peak = {"live": 0, "calls": 0}

    def sampling_row(audit_event: AuditEvent) -> dict[str, object]:
        peak["calls"] += 1
        if peak["calls"] % 250 == 1:
            peak["live"] = max(peak["live"], _live_audit_event_objects())
        return original_row(audit_event)

    monkeypatch.setattr(admin_routes, "_event_row", sampling_row)

    statements: list[tuple[str, dict, bool]] = []
    engine = get_engine()

    def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        # Reads may open with a CTE (the IP wall filter's team scope), so match
        # every non-write statement that reads audit_events.
        is_write = statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        if "FROM audit_events" in statement and not is_write:
            server_side = type(cursor).__name__ == "ServerCursor"
            statements.append((statement, dict(context.execution_options), server_side))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            EXPORT,
            params={"action": PROBE_ACTION, "format": "csv"},
            headers=auth_headers(str(boot["access_token"])),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [row["id"] for row in rows] == seeded
    assert {row["company_id"] for row in rows} == {company_id}

    # Every read of the window is bounded: a capped COUNT, then one ordered
    # read fetched `batch` rows per round trip. No unbounded fetch.
    reads = [s for s in statements if "audit_events.metadata_json" in s[0]]
    assert len(reads) == 1, statements
    statement, options, server_side = reads[0]
    assert "LIMIT" in statement.upper()
    assert options.get("yield_per") == batch
    assert options.get("stream_results") is True
    if engine.dialect.name == "postgresql":
        assert server_side, "PostgreSQL export must read through a server-side cursor"
    for sql, _options, _server in statements:
        assert "LIMIT" in sql.upper(), sql

    assert peak["calls"] == total
    assert peak["live"] <= 4 * batch, peak

    exports = _export_events(company_id)
    assert len(exports) == 1
    assert exports[0].result == "success"
    assert json.loads(exports[0].metadata_json)["row_count"] == total


def refuses_window_over_cap(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cap = 25
    monkeypatch.setattr(admin_routes, "AUDIT_EXPORT_MAX_ROWS", cap, raising=False)
    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    headers = auth_headers(str(boot["access_token"]))
    at_cap = _seed(company_id, cap, action="audit.at_cap_probe")
    _seed(company_id, cap + 1, action="audit.over_cap_probe")

    exact = client.get(EXPORT, params={"action": "audit.at_cap_probe"}, headers=headers)
    assert exact.status_code == 200, exact.text
    assert [json.loads(line)["id"] for line in exact.text.splitlines()] == at_cap

    over = client.get(
        EXPORT, params={"action": "audit.over_cap_probe", "format": "csv"}, headers=headers
    )
    assert over.status_code == 422, over.text
    assert over.headers["content-type"].startswith("application/problem+json")
    assert "content-disposition" not in over.headers
    problem = over.json()
    assert problem["type"] == "audit_export_row_cap_exceeded"
    assert problem["row_cap"] == cap
    # The admin page shows `detail` verbatim, so it must say what to do.
    assert f"more than {cap:,} audit events" in problem["detail"]
    assert "Narrow the Since and Until dates" in problem["detail"]

    # An explicit `limit` at or under the cap is a request for the first rows;
    # a `limit` above the cap is not a way around it.
    first = client.get(
        EXPORT, params={"action": "audit.over_cap_probe", "limit": 5}, headers=headers
    )
    assert first.status_code == 200, first.text
    assert len(first.text.splitlines()) == 5
    above = client.get(
        EXPORT, params={"action": "audit.over_cap_probe", "limit": cap * 10}, headers=headers
    )
    assert above.status_code == 422, above.text

    exports = _export_events(company_id)
    assert [row.result for row in exports] == ["success", "denied", "success", "denied"]
    denied = json.loads(exports[1].metadata_json)
    assert denied["reason"] == "audit_export_row_cap_exceeded"
    assert denied["row_cap"] == cap
    assert denied["action_filter"] == "audit.over_cap_probe"
    assert json.loads(exports[0].metadata_json)["row_count"] == cap
    assert json.loads(exports[2].metadata_json)["row_count"] == 5


def real_cap_refuses_one_row_over(client: TestClient) -> None:
    # The documented cap. Read with a default so the old route, which had no
    # cap, fails on behaviour (it streamed every row) rather than on a name.
    cap = getattr(admin_routes, "AUDIT_EXPORT_MAX_ROWS", 50_000)
    assert cap == 50_000
    boot = bootstrap_company(client)
    _seed(boot["company"]["id"], cap + 1)
    response = client.get(
        EXPORT,
        params={"action": PROBE_ACTION},
        headers=auth_headers(str(boot["access_token"])),
    )
    assert response.status_code == 422, response.status_code
    assert response.json()["type"] == "audit_export_row_cap_exceeded"
    assert response.json()["row_cap"] == cap


def aborts_when_window_grows_while_streaming(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap = 25
    monkeypatch.setattr(admin_routes, "AUDIT_EXPORT_MAX_ROWS", cap, raising=False)
    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    _seed(company_id, cap)
    original_record = admin_routes.record_from_context

    def record_then_late_commit(*args, **kwargs):  # noqa: ANN002, ANN003
        recorded = original_record(*args, **kwargs)
        if kwargs.get("action") == "audit.exported":
            # A row committed late, timestamped inside the counted window.
            _seed(company_id, 1)
        return recorded

    monkeypatch.setattr(admin_routes, "record_from_context", record_then_late_commit)
    with pytest.raises(RuntimeError, match=f"grew past {cap} rows"):
        client.get(
            EXPORT,
            params={"action": PROBE_ACTION},
            headers=auth_headers(str(boot["access_token"])),
        )


def cap_is_counted_per_tenant(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cap = 25
    monkeypatch.setattr(admin_routes, "AUDIT_EXPORT_MAX_ROWS", cap, raising=False)
    boot_a = bootstrap_company(client)
    boot_b = _second_tenant(client)
    company_a = boot_a["company"]["id"]
    company_b = boot_b["company"]["id"]
    assert company_a != company_b
    _seed(company_a, cap * 3)
    seeded_b = _seed(company_b, cap)

    # The client keeps the last bootstrap's session cookie, and a cookie wins
    # over a bearer token; clear it so each request is the tenant it names.
    client.cookies.clear()
    # Tenant A's 75 rows neither appear in B's file nor count against B's cap.
    export_b = client.get(
        EXPORT,
        params={"action": PROBE_ACTION},
        headers=auth_headers(str(boot_b["access_token"])),
    )
    assert export_b.status_code == 200, export_b.text
    rows_b = [json.loads(line) for line in export_b.text.splitlines()]
    assert [row["id"] for row in rows_b] == seeded_b
    assert {row["company_id"] for row in rows_b} == {company_b}

    # Tenant A is refused on its own rows; B's rows do not rescue or leak in.
    client.cookies.clear()
    export_a = client.get(
        EXPORT,
        params={"action": PROBE_ACTION},
        headers=auth_headers(str(boot_a["access_token"])),
    )
    assert export_a.status_code == 422, export_a.text
    assert company_b not in export_a.text

    # Each refusal or download is audited only in the caller's tenant.
    assert [row.result for row in _export_events(company_b)] == ["success"]
    assert [row.result for row in _export_events(company_a)] == ["denied"]


def _walled_docket(client: TestClient) -> dict:
    """Owner, an admin member walled off one unrestricted IP docket, and the
    docket. The member is an owner-role admin with audit:export."""
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    owner_membership_id = str(boot["membership"]["id"])
    member_id, member_headers = _invite_member(client, owner_token)
    client.cookies.clear()
    created = client.post(
        "/api/ip/dockets",
        headers=auth_headers(owner_token),
        json={
            "title": "Walled ASTER",
            "restricted": False,
            "particulars": _particulars("ASTER"),
        },
    )
    assert created.status_code == 201, created.text
    docket = created.json()
    with get_session_factory()() as session:
        session.add(
            EthicalWall(
                company_id=company_id,
                ip_docket_id=docket["id"],
                excluded_membership_id=member_id,
                reason="Conflict on this mark.",
                created_by_membership_id=owner_membership_id,
            )
        )
        session.commit()
    return {
        "company_id": company_id,
        "owner_headers": auth_headers(owner_token),
        "member_headers": member_headers,
        "docket": docket,
    }


def _export(client: TestClient, headers: dict[str, str], **params: object):  # noqa: ANN202
    # A cookie from an earlier login wins over the bearer token; drop it so the
    # request is the principal its headers name.
    client.cookies.clear()
    return client.get(EXPORT, headers=headers, params=params)


def _rows(response) -> list[dict]:  # noqa: ANN001
    if response.headers["content-type"].startswith("text/csv"):
        return list(csv.DictReader(io.StringIO(response.text)))
    return [json.loads(line) for line in response.text.splitlines() if line]


def ethical_wall_hides_walled_ip_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = _walled_docket(client)
    company_id = setup["company_id"]
    docket_id = setup["docket"]["id"]
    walled = set(
        _seed(company_id, 30, target_type="ip_docket_record", ip_docket_id=docket_id)
    )
    open_rows = set(_seed(company_id, 20))

    monkeypatch.setattr(admin_routes, "AUDIT_EXPORT_MAX_ROWS", 60, raising=False)
    for fmt in ("jsonl", "csv"):
        # The walled admin sees neither the seeded docket rows nor the docket's
        # own creation event, in either format.
        member = _export(client, setup["member_headers"], action=PROBE_ACTION, format=fmt)
        assert member.status_code == 200, member.text
        assert {row["id"] for row in _rows(member)} == open_rows
        everything = _export(client, setup["member_headers"], format=fmt)
        assert everything.status_code == 200, everything.text
        member_rows = _rows(everything)
        assert not walled & {row["id"] for row in member_rows}
        assert docket_id not in everything.text
        assert not any(row["action"] == "ip_docket.created" for row in member_rows)

        # An admin outside the wall still sees them.
        owner = _export(client, setup["owner_headers"], action=PROBE_ACTION, format=fmt)
        assert owner.status_code == 200, owner.text
        assert {row["id"] for row in _rows(owner)} == open_rows | walled
        owner_all = _export(client, setup["owner_headers"], format=fmt)
        assert any(
            row["action"] == "ip_docket.created" and row["target_id"] == docket_id
            for row in _rows(owner_all)
        )

    # The cap counts only rows the caller may see: 20 visible rows fit a cap of
    # 25 for the walled admin, so a 422 cannot reveal the 30 walled ones, while
    # the unwalled admin's 50 rows exceed it.
    monkeypatch.setattr(admin_routes, "AUDIT_EXPORT_MAX_ROWS", 25, raising=False)
    member = _export(client, setup["member_headers"], action=PROBE_ACTION)
    assert member.status_code == 200, member.text
    assert {row["id"] for row in _rows(member)} == open_rows
    owner = _export(client, setup["owner_headers"], action=PROBE_ACTION)
    assert owner.status_code == 422, owner.text
    assert owner.json()["type"] == "audit_export_row_cap_exceeded"

    # Tenant isolation still holds alongside the wall filter.
    tenant_b = _second_tenant(client)
    other = _export(
        client, auth_headers(str(tenant_b["access_token"])), action=PROBE_ACTION
    )
    assert other.status_code == 200, other.text
    assert other.content == b""
    other_all = _export(client, auth_headers(str(tenant_b["access_token"])))
    assert {row["company_id"] for row in _rows(other_all)} <= {tenant_b["company"]["id"]}
    assert docket_id not in other_all.text


def matter_audit_hides_walled_link_events(client: TestClient) -> None:
    setup = _walled_docket(client)
    docket = setup["docket"]
    client.cookies.clear()
    owner_token = setup["owner_headers"]["Authorization"].removeprefix("Bearer ")
    matter = _mk_matter(client, owner_token, "WALL-LINK-001")
    client.cookies.clear()
    linked = client.post(
        f"/api/ip/dockets/{docket['id']}/matter-links",
        headers=setup["owner_headers"],
        json={
            "matter_id": matter["id"],
            "relation_role": "advisory",
            "reason": "Advice on the walled mark.",
            "expected_docket_updated_at": docket["updated_at"],
        },
    )
    assert linked.status_code == 201, linked.text

    def link_events(headers: dict[str, str]) -> tuple[list[dict], str, str]:
        client.cookies.clear()
        listed = client.get(f"/api/matters/{matter['id']}/audit-events", headers=headers)
        assert listed.status_code == 200, listed.text
        client.cookies.clear()
        exported = client.get(
            f"/api/matters/{matter['id']}/audit-events/export",
            headers=headers,
            params={"format": "csv"},
        )
        assert exported.status_code == 200, exported.text
        return listed.json()["events"], exported.text, str(listed.json()["total"])

    # The member can see the Matter but is walled off the linked docket: the
    # link event names that docket, so it is hidden from list, count and export.
    events, exported, _ = link_events(setup["member_headers"])
    assert not any(row["action"] == "ip_matter_link.created" for row in events)
    assert not any(row.get("ip_docket_id") == docket["id"] for row in events)
    assert docket["id"] not in exported
    assert "ip_matter_link.created" not in exported

    events, exported, _ = link_events(setup["owner_headers"])
    assert any(
        row["action"] == "ip_matter_link.created" and row["ip_docket_id"] == docket["id"]
        for row in events
    )
    assert "ip_matter_link.created" in exported


def test_audit_export_hides_ip_events_behind_an_ethical_wall(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ethical_wall_hides_walled_ip_events(client, monkeypatch)


def test_matter_audit_hides_link_events_for_a_walled_docket(client: TestClient) -> None:
    matter_audit_hides_walled_link_events(client)


def test_audit_export_streams_in_bounded_batches(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    streams_in_bounded_batches(client, monkeypatch)


def test_audit_export_refuses_window_over_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuses_window_over_cap(client, monkeypatch)


def test_audit_export_real_cap_refuses_one_row_over(client: TestClient) -> None:
    real_cap_refuses_one_row_over(client)


def test_audit_export_aborts_when_window_grows_while_streaming(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    aborts_when_window_grows_while_streaming(client, monkeypatch)


def test_audit_export_cap_is_counted_per_tenant(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap_is_counted_per_tenant(client, monkeypatch)
