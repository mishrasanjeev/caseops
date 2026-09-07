from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import IpPatentPriorityDetail, IpRelationship, MatterAccessGrant
from caseops_api.db.session import get_session_factory
from tests.test_ip_document_workflow import _upload
from tests.test_ip_patent_applications import _closed, _correction, _create, _setup


def _fixture(client, *, child_kind="complete", parent_kind="complete"):
    bootstrap, headers, family, payload = _setup(client)
    records = []
    for name, kind in (("Parent application", parent_kind), ("Child application", child_kind)):
        request = deepcopy(payload)
        request["facts"].update(title=name, application_kind=kind)
        request["facts"]["identifiers"][0]["raw_value"] = str(uuid4())
        response = _create(client, headers, request)
        assert response.status_code == 201, response.text
        records.append(response.json())
    parent, child = records
    command = {
        "parent_application_id": parent["id"],
        "relation_kind": "priority",
        "priority_date": "2026-09-05",
        "expected_application_version": child["version"],
        "expected_parent_version": parent["version"],
        "expected_lifecycle_version": child["lifecycle_version"],
        "expected_parent_lifecycle_version": parent["lifecycle_version"],
        "expected_priority_sequence": 0,
        "source": payload["facts"]["source"],
        "reason": "Record the parent identified in the source evidence.",
    }
    return bootstrap, headers, family, parent, child, command


def _post(client, headers, application, payload, key=None):
    return client.post(
        f"/api/ip/patents/applications/{application['id']}/priorities",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json=payload,
    )


def _list(client, headers, application, **params):
    response = client.get(
        f"/api/ip/patents/applications/{application['id']}/priorities",
        headers=headers,
        params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "kind,child_kind,parent_kind",
    [
        ("priority", "complete", "complete"),
        ("divisional_parent", "divisional", "complete"),
        ("addition_parent", "patent_of_addition", "complete"),
        ("national_phase_parent", "national_phase", "pct_international"),
    ],
)
def test_priority_kinds_persist_exact_evidence_and_canonical_relationship(
    client, kind, child_kind, parent_kind
):
    _, headers, family, parent, child, payload = _fixture(
        client, child_kind=child_kind, parent_kind=parent_kind
    )
    payload["relation_kind"] = kind
    key = str(uuid4())
    response = _post(client, headers, child, payload, key)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["application_id"] == child["id"]
    assert saved["parent_application_id"] == parent["id"]
    assert (
        saved["source"] == payload["source"] and saved["priority_date"] == payload["priority_date"]
    )
    assert saved["is_current"] and not saved["withdrawn"] and saved["review_flags"] == []
    assert _post(client, headers, child, payload, key).json() == saved
    detail = client.get(
        f"/api/ip/patents/applications/{child['id']}/priorities/{saved['id']}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json() == saved
    assert _list(client, headers, child)["priorities"] == [saved]
    graph = client.get(f"/api/ip/patents/families/{family['id']}/graph", headers=headers)
    assert graph.status_code == 200, graph.text
    assert graph.json()["priorities"] == [saved]
    assert {row["id"] for row in graph.json()["applications"]} == {child["id"], parent["id"]}
    for record in (child, parent):
        assert (
            client.get(f"/api/ip/patents/applications/{record['id']}", headers=headers).json()
            == record
        )
    with get_session_factory()() as session:
        relation = session.get(IpRelationship, saved["canonical_relationship_id"])
        assert relation.source_docket_id == child["docket_id"]
        assert relation.target_docket_id == parent["docket_id"]
        assert relation.relationship_kind == kind and relation.source == "patent_priority"


def test_priority_correction_withdrawal_and_reentry_preserve_original_facts(client):
    _, headers, _, _, child, payload = _fixture(client)
    original = _post(client, headers, child, payload)
    assert original.status_code == 201, original.text
    first = original.json()
    current = {**payload, "expected_priority_sequence": first["sequence"]}
    assert _post(client, headers, child, current).status_code == 409
    corrected = _post(
        client,
        headers,
        child,
        {
            **current,
            "supersedes_priority_id": first["id"],
            "reason": "Correct the explanatory evidence transcription.",
        },
    )
    assert corrected.status_code == 201, corrected.text
    second = corrected.json()
    assert first["canonical_relationship_id"] == second["canonical_relationship_id"]
    assert second["supersedes_priority_id"] == first["id"]
    stale = _post(client, headers, child, {**current, "supersedes_priority_id": first["id"]})
    assert stale.status_code == 409, stale.text
    withdrawal = {
        **payload,
        "expected_priority_sequence": second["sequence"],
        "supersedes_priority_id": second["id"],
        "withdrawn": True,
    }
    invalid = _post(client, headers, child, {**withdrawal, "priority_date": "2026-09-04"})
    assert invalid.status_code == 422, invalid.text
    removed = _post(client, headers, child, withdrawal)
    assert removed.status_code == 201, removed.text
    third = removed.json()
    assert not third["is_current"] and third["withdrawn"]
    assert _list(client, headers, child)["priorities"] == []
    assert (
        _post(
            client,
            headers,
            child,
            {
                **withdrawal,
                "expected_priority_sequence": third["sequence"],
                "supersedes_priority_id": third["id"],
            },
        ).status_code
        == 409
    )
    reentry = _post(
        client, headers, child, {**payload, "expected_priority_sequence": third["sequence"]}
    )
    assert reentry.status_code == 201, reentry.text
    history = _list(client, headers, child, history=True)["priorities"]
    assert len(history) == 4 and history[-1] == {**first, "is_current": False}
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpRelationship)) == 1
        assert session.scalar(select(func.count()).select_from(IpPatentPriorityDetail)) == 4


def test_priority_cycle_self_link_chronology_and_kind_rejection_are_atomic(client):
    _, headers, _, parent, child, payload = _fixture(client)
    for changes in [
        {"parent_application_id": child["id"]},
        {"priority_date": "2026-09-06"},
        {"relation_kind": "divisional_parent"},
        {"relation_kind": "addition_parent"},
        {"relation_kind": "national_phase_parent"},
    ]:
        rejected = _post(client, headers, child, {**payload, **changes})
        assert rejected.status_code == 422, rejected.text
    created = _post(client, headers, child, payload)
    assert created.status_code == 201, created.text
    cycle = _post(client, headers, parent, {**payload, "parent_application_id": child["id"]})
    assert cycle.status_code == 422 and "patent_priority_cycle" in cycle.text
    assert len(_list(client, headers, child)["priorities"]) == 1
    assert _list(client, headers, parent)["priorities"] == []


def test_priority_sources_stale_versions_and_direct_database_immutability(client):
    _, headers, _, _, child, payload = _fixture(client)
    for field in ("document_id", "document_version_id"):
        rejected = _post(
            client,
            headers,
            child,
            {**payload, "source": {**payload["source"], field: str(uuid4())}},
        )
        assert rejected.status_code == 404, rejected.text
    rejected = _post(
        client,
        headers,
        child,
        {**payload, "source": {**payload["source"], "content_sha256": "0" * 64}},
    )
    assert rejected.status_code == 409, rejected.text
    for field in (
        "expected_application_version",
        "expected_parent_version",
        "expected_lifecycle_version",
        "expected_parent_lifecycle_version",
        "expected_priority_sequence",
    ):
        rejected = _post(client, headers, child, {**payload, field: payload[field] + 1})
        assert rejected.status_code == 409, rejected.text
    response = _post(client, headers, child, payload)
    assert response.status_code == 201, response.text
    saved = response.json()
    with get_session_factory()() as session:
        for table, identity in (
            ("ip_patent_priority_details", saved["id"]),
            ("ip_relationships", saved["canonical_relationship_id"]),
        ):
            for statement in (
                f"UPDATE {table} SET company_id = company_id WHERE id = :id",
                f"DELETE FROM {table} WHERE id = :id",
            ):
                with pytest.raises(IntegrityError, match="append-only"):
                    session.execute(text(statement), {"id": identity})
                    session.commit()
                session.rollback()
    assert _list(client, headers, child)["priorities"] == [saved]


def test_priority_closed_historical_parent_is_read_only_but_new_link_and_closed_child_are_rejected(
    client,
):
    _, headers, _, parent, child, payload = _fixture(client)
    response = _post(client, headers, child, payload)
    assert response.status_code == 201, response.text
    saved = response.json()
    _closed(client, headers, parent["docket_id"])
    current = {
        **payload,
        "expected_parent_lifecycle_version": 1,
        "expected_priority_sequence": saved["sequence"],
    }
    new_link = _post(client, headers, child, {**current, "priority_date": "2026-09-04"})
    assert new_link.status_code == 404, new_link.text
    correction = _post(client, headers, child, {**current, "supersedes_priority_id": saved["id"]})
    assert correction.status_code == 201, correction.text
    assert (
        client.get(f"/api/ip/patents/applications/{parent['id']}", headers=headers).json()[
            "is_active"
        ]
        is False
    )
    _closed(client, headers, child["docket_id"])
    denied = _post(
        client,
        headers,
        child,
        {
            **current,
            "expected_lifecycle_version": 1,
            "expected_priority_sequence": correction.json()["sequence"],
            "supersedes_priority_id": correction.json()["id"],
            "withdrawn": True,
        },
    )
    assert denied.status_code == 404, denied.text
    assert len(_list(client, headers, child, history=True)["priorities"]) == 2


def test_application_correction_revalidates_incoming_and_outgoing_priority_facts(client):
    _, headers, _, parent, child, payload = _fixture(client, child_kind="divisional")
    response = _post(client, headers, child, {**payload, "relation_kind": "divisional_parent"})
    assert response.status_code == 201, response.text
    for record, changes in (
        (child, {"application_kind": "complete"}),
        (parent, {"filing_date": "2026-09-06"}),
    ):
        rejected = client.post(
            f"/api/ip/patents/applications/{record['id']}/corrections",
            headers=headers,
            json=_correction(record, **changes),
        )
        assert rejected.status_code == 422, rejected.text
        assert (
            client.get(f"/api/ip/patents/applications/{record['id']}", headers=headers).json()
            == record
        )
    allowed = client.post(
        f"/api/ip/patents/applications/{parent['id']}/corrections",
        headers=headers,
        json=_correction(parent, title="Corrected parent title"),
    )
    assert allowed.status_code == 200, allowed.text
    retained = _list(client, headers, child)["priorities"][0]
    assert (
        retained["parent_version"] == 1
        and retained["current_parent_title"] == "Corrected parent title"
    )


def test_priority_office_labels_are_review_flags_not_invented_office_identity_rules(client):
    _, headers, _, parent, child, payload = _fixture(client, child_kind="divisional")
    changed = client.post(
        f"/api/ip/patents/applications/{parent['id']}/corrections",
        headers=headers,
        json=_correction(
            parent, office="Historical Delhi office", jurisdiction="US", filing_date=None
        ),
    )
    assert changed.status_code == 200, changed.text
    response = _post(
        client,
        headers,
        child,
        {**payload, "relation_kind": "divisional_parent", "expected_parent_version": 2},
    )
    assert response.status_code == 201, response.text
    assert set(response.json()["review_flags"]) == {
        "office_names_differ",
        "jurisdictions_differ",
        "filing_dates_incomplete",
    }


def test_priority_and_graph_pages_are_bounded_and_reject_changed_snapshots(client):
    _, headers, family, _, child, payload = _fixture(client)
    for sequence in range(4):
        response = _post(
            client,
            headers,
            child,
            {
                **payload,
                "priority_date": f"2026-09-0{sequence + 1}",
                "expected_priority_sequence": sequence,
            },
        )
        assert response.status_code == 201, response.text
    first = _list(client, headers, child, limit=2)
    assert [row["sequence"] for row in first["priorities"]] == [4, 3]
    second = _list(
        client, headers, child, limit=2, cursor=first["next_cursor"], snapshot_sequence=4
    )
    assert [row["sequence"] for row in second["priorities"]] == [2, 1] and second[
        "next_cursor"
    ] is None
    base = f"/api/ip/patents/families/{family['id']}/graph"
    graph = client.get(base, headers=headers, params={"application_limit": 1, "priority_limit": 2})
    assert graph.status_code == 200, graph.text
    page = graph.json()
    assert len(page["applications"]) == 1 and len(page["priorities"]) == 2
    assert page["has_more_applications"] and page["has_more_relationships"]
    continuation = {
        "application_limit": 1,
        "priority_limit": 2,
        "applications_cursor": page["applications_next_cursor"],
        "priorities_cursor": page["priorities_next_cursor"],
    }
    tail = client.get(base, headers=headers, params=continuation)
    assert tail.status_code == 200, tail.text
    assert not tail.json()["has_more_applications"] and not tail.json()["has_more_relationships"]
    assert page["applications"][0]["id"] != tail.json()["applications"][0]["id"]
    created = _post(client, headers, child, {**payload, "expected_priority_sequence": 4})
    assert created.status_code == 201, created.text
    assert client.get(base, headers=headers, params=continuation).status_code == 409
    assert (
        client.get(
            f"/api/ip/patents/applications/{child['id']}/priorities",
            headers=headers,
            params={"cursor": 3, "snapshot_sequence": 4},
        ).status_code
        == 409
    )
    for cursor in ("bad", "4:0", "2:4", "-1:2", "4:3:2"):
        assert (
            client.get(base, headers=headers, params={"priorities_cursor": cursor}).status_code
            == 422
        )


def test_priority_revoked_application_source_fails_closed_without_server_error(client):
    bootstrap, headers, family, _, child, payload = _fixture(client)
    response = _post(client, headers, child, payload)
    assert response.status_code == 201, response.text
    with get_session_factory()() as session:
        grants = list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.company_id == bootstrap["company"]["id"],
                    MatterAccessGrant.ip_docket_id == family["docket_id"],
                )
            )
        )
        assert grants
        for grant in grants:
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    denied = client.get(f"/api/ip/patents/applications/{child['id']}/priorities", headers=headers)
    assert denied.status_code == 404, denied.text


def test_cross_family_priority_does_not_move_or_merge_applications(client):
    _, headers, family, _, child, payload = _fixture(client)
    response = client.post(
        "/api/ip/patents/families",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**family["facts"], "title": "Separate priority family"},
    )
    assert response.status_code == 201, response.text
    other = response.json()
    facts = deepcopy(child["facts"])
    facts["title"] = "Cross-family parent"
    facts["identifiers"][0]["raw_value"] = str(uuid4())
    response = _create(
        client,
        headers,
        {
            "family_id": other["id"],
            "expected_family_version": 1,
            "expected_family_lifecycle_version": 0,
            "facts": facts,
        },
    )
    assert response.status_code == 201, response.text
    parent = response.json()
    recorded = _post(client, headers, child, {**payload, "parent_application_id": parent["id"]})
    assert recorded.status_code == 201, recorded.text
    for current_family in (family, other):
        graph = client.get(
            f"/api/ip/patents/families/{current_family['id']}/graph",
            headers=headers,
            params={"application_limit": 1},
        )
        assert graph.status_code == 200, graph.text
        assert graph.json()["priorities"] == [recorded.json()]
        assert all(row["family_id"] == current_family["id"] for row in graph.json()["applications"])
        assert (
            client.get(f"/api/ip/patents/families/{current_family['id']}", headers=headers).json()
            == current_family
        )
    for application in (child, parent):
        assert (
            client.get(f"/api/ip/patents/applications/{application['id']}", headers=headers).json()
            == application
        )


def test_priority_routes_do_not_disclose_other_tenant_links_or_grant_parent_access(client):
    bootstrap, headers, family, parent, child, payload = _fixture(client)
    created = _post(client, headers, child, payload)
    assert created.status_code == 201, created.text
    client.cookies.clear()
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Separate Priority Firm",
            "company_slug": "separate-priority-firm",
            "company_type": "law_firm",
            "owner_full_name": "Separate Owner",
            "owner_email": "owner@separate-priority.example.com",
            "owner_password": "SeparateTest123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    client.cookies.clear()
    base = f"/api/ip/patents/applications/{child['id']}/priorities"
    for url in (
        base,
        f"{base}/{created.json()['id']}",
        f"/api/ip/patents/families/{family['id']}/graph",
    ):
        assert client.get(url, headers=other_headers).status_code == 404
    assert _post(client, other_headers, child, payload).status_code == 404
    with get_session_factory()() as session:
        grants = list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.company_id == bootstrap["company"]["id"],
                    MatterAccessGrant.ip_docket_id == parent["docket_id"],
                )
            )
        )
        assert grants
        for grant in grants:
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert client.get(base, headers=headers).status_code == 404
    graph = client.get(f"/api/ip/patents/families/{family['id']}/graph", headers=headers)
    assert graph.status_code == 200, graph.text
    assert graph.json()["priorities"] == []
    assert (
        _post(
            client,
            headers,
            child,
            {
                **payload,
                "expected_priority_sequence": 1,
                "supersedes_priority_id": created.json()["id"],
            },
        ).status_code
        == 404
    )


def test_priority_parent_source_revocation_does_not_turn_an_accessible_child_into_a_500(client):
    bootstrap, headers, family, parent, child, payload = _fixture(client)
    key = str(uuid4())
    created = _post(client, headers, child, payload, key)
    assert created.status_code == 201, created.text
    separate = client.post(
        "/api/ip/patents/families",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**family["facts"], "title": "Separate source access boundary"},
    )
    assert separate.status_code == 201, separate.text
    private_family = separate.json()
    document = _upload(
        client,
        headers,
        filename="parent-only-source.txt",
        content=b"Parent source facts. " * 30,
        docket_id=private_family["docket_id"],
        confidentiality="restricted",
    )["document"]
    source = {
        "kind": "document_version",
        "document_id": document["id"],
        "document_version_id": document["versions"][0]["id"],
        "content_sha256": document["versions"][0]["sha256_hex"],
    }
    corrected = client.post(
        f"/api/ip/patents/applications/{parent['id']}/corrections",
        headers=headers,
        json=_correction(parent, source=source),
    )
    assert corrected.status_code == 200, corrected.text
    with get_session_factory()() as session:
        grants = list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.company_id == bootstrap["company"]["id"],
                    MatterAccessGrant.ip_docket_id == private_family["docket_id"],
                )
            )
        )
        assert grants
        for grant in grants:
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert (
        client.get(f"/api/ip/patents/applications/{child['id']}", headers=headers).json() == child
    )
    assert (
        client.get(f"/api/ip/patents/applications/{parent['id']}", headers=headers).status_code
        == 404
    )
    priorities = client.get(
        f"/api/ip/patents/applications/{child['id']}/priorities", headers=headers
    )
    assert priorities.status_code == 404 and "patent_priority_target_unavailable" in priorities.text
    assert _post(client, headers, child, payload, key).status_code == 404


def test_priority_new_source_and_parent_kind_date_corrections_preserve_every_predecessor(client):
    _, headers, family, _, child, payload = _fixture(client, child_kind="divisional")
    first = _post(client, headers, child, payload)
    assert first.status_code == 201, first.text
    records = [first.json()]
    document = _upload(
        client,
        headers,
        filename="corrected-priority.txt",
        content=b"Corrected priority evidence. " * 30,
        docket_id=family["docket_id"],
        confidentiality="restricted",
    )["document"]
    source = {
        "kind": "document_version",
        "document_id": document["id"],
        "document_version_id": document["versions"][0]["id"],
        "content_sha256": document["versions"][0]["sha256_hex"],
    }
    facts = {
        **child["facts"],
        "title": "Corrected parent",
        "application_kind": "complete",
        "filing_date": "2026-09-03",
        "identifiers": [],
        "source_pending_identifier_allocation": True,
    }
    new_parent = _create(
        client,
        headers,
        {
            "family_id": family["id"],
            "expected_family_version": 1,
            "expected_family_lifecycle_version": 0,
            "facts": facts,
        },
    )
    assert new_parent.status_code == 201, new_parent.text
    current = payload
    for changes in (
        {"source": source},
        {"relation_kind": "divisional_parent"},
        {"priority_date": "2026-09-04"},
        {"parent_application_id": new_parent.json()["id"]},
    ):
        current = {
            **current,
            **changes,
            "expected_priority_sequence": records[-1]["sequence"],
            "supersedes_priority_id": records[-1]["id"],
        }
        response = _post(client, headers, child, current)
        assert response.status_code == 201, response.text
        records.append(response.json())
    assert records[0]["canonical_relationship_id"] == records[1]["canonical_relationship_id"]
    assert records[0]["source"] == payload["source"] and records[1]["source"] == source
    assert len({row["canonical_relationship_id"] for row in records}) == 4
    history = _list(client, headers, child, history=True)["priorities"]
    assert history == [
        {**row, "is_current": index == len(records) - 1}
        for index, row in reversed(list(enumerate(records)))
    ]
    assert _list(client, headers, child)["priorities"] == [records[-1]]
