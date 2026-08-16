"""IPLF-039E per-path evidence: chain of title and related-right family (UJ-61).

Stable manifest test IDs:

* ``IPLF-UJ-61-NORMAL``   reconcile chain of title and related-right family
* ``IPLF-UJ-61-EXC-01``   executed-not-effective, unrecorded, partial, disputed
* ``IPLF-UJ-61-EXC-02``   family association alone never updates another recordal
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars


def _actor(client: TestClient):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    return auth_headers(token), token


def _docket(client, headers, *, matter_id, title):
    r = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": False,
            "particulars": _particulars(title.upper()),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _interest(client, headers, docket_id, **kw):
    body = {
        "interest_type": "ownership",
        "party_name": "Aster Holdings LLP",
        "effective_from": "2026-01-01",
        "evidence_reference": "attachment:deed-2026",
        "recordal_status": "not_required",
    }
    body.update(kw)
    return client.post(
        f"/api/ip/dockets/{docket_id}/title-interests", headers=headers, json=body
    )


def test_uj61_normal_reconcile_chain_of_title_and_family(client: TestClient) -> None:
    """IPLF-UJ-61-NORMAL — effective-dated interests form an ordered chain."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039E-UJ61")
    parent = _docket(client, headers, matter_id=matter["id"], title="Family Parent Mark")
    sibling = _docket(client, headers, matter_id=matter["id"], title="Family Sibling Mark")

    original = _interest(
        client,
        headers,
        parent["id"],
        party_name="Original Owner LLP",
        effective_from="2024-01-01",
        effective_until="2025-12-31",
    )
    assert original.status_code == 200, original.text

    # A later, non-overlapping assignment is a clean succession: no conflict.
    assigned = _interest(
        client,
        headers,
        parent["id"],
        interest_type="assignment",
        party_name="Aster Holdings LLP",
        effective_from="2026-01-01",
        recordal_status="pending",
        related_docket_id=sibling["id"],
    )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    interests = {i["party_name"]: i for i in body["title_interests"]}
    assert set(interests) == {"Original Owner LLP", "Aster Holdings LLP"}

    current = interests["Aster Holdings LLP"]
    assert current["interest_type"] == "assignment"
    assert current["effective_from"] == "2026-01-01"
    assert current["effective_until"] is None
    assert current["recordal_status"] == "pending"
    assert current["evidence_reference"] == "attachment:deed-2026"
    # Non-overlapping succession produces no conflict flag.
    assert current["conflict_flags_json"] == []
    # The family link is recorded on the interest, not by merging records.
    assert current["related_docket_id"] == sibling["id"]

    # A docket cannot be its own family relation.
    self_related = _interest(
        client, headers, parent["id"], related_docket_id=parent["id"]
    )
    assert self_related.status_code == 422, self_related.text


def test_uj61_exc01_overlapping_and_unrecorded_interests_are_flagged(
    client: TestClient,
) -> None:
    """IPLF-UJ-61-EXC-01 — competing and unrecorded title is surfaced, not merged."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039E-UJ61E1")
    docket = _docket(client, headers, matter_id=matter["id"], title="Disputed Title Mark")

    first = _interest(
        client,
        headers,
        docket["id"],
        interest_type="ownership",
        party_name="First Owner LLP",
        effective_from="2026-01-01",
    )
    assert first.status_code == 200, first.text
    assert first.json()["title_interests"][0]["conflict_flags_json"] == []

    # A second ownership over an overlapping period is competing title.
    competing = _interest(
        client,
        headers,
        docket["id"],
        interest_type="ownership",
        party_name="Second Owner LLP",
        effective_from="2026-06-01",
        evidence_reference="attachment:competing-deed",
    )
    assert competing.status_code == 200, competing.text
    rows = {i["party_name"]: i for i in competing.json()["title_interests"]}
    flags = rows["Second Owner LLP"]["conflict_flags_json"]
    assert flags, "an overlapping competing ownership must be flagged"
    assert any(f.startswith("competing_title:") for f in flags)

    # Executed but not yet recorded: the interest exists with a pending recordal
    # and is not silently treated as the registered position.
    licensed = _interest(
        client,
        headers,
        docket["id"],
        interest_type="licence",
        party_name="Licensee Ltd",
        effective_from="2026-03-01",
        recordal_status="pending",
        evidence_reference="attachment:licence-2026",
    )
    assert licensed.status_code == 200, licensed.text
    lic = {i["party_name"]: i for i in licensed.json()["title_interests"]}["Licensee Ltd"]
    assert lic["recordal_status"] == "pending"
    assert lic["conflict_flags_json"], "a licence over disputed ownership must be flagged"

    # A partial-period transfer keeps its own effective window rather than
    # overwriting the prior interest's dates.
    partial = _interest(
        client,
        headers,
        docket["id"],
        interest_type="assignment",
        party_name="Partial Assignee LLP",
        effective_from="2027-01-01",
        effective_until="2027-12-31",
        evidence_reference="attachment:partial-assignment",
    )
    assert partial.status_code == 200, partial.text
    final = {i["party_name"]: i for i in partial.json()["title_interests"]}
    assert final["Partial Assignee LLP"]["effective_until"] == "2027-12-31"
    assert final["First Owner LLP"]["effective_until"] is None


def test_uj61_exc02_family_association_never_updates_another_recordal(
    client: TestClient,
) -> None:
    """IPLF-UJ-61-EXC-02 — a related right's recordal is untouched by association."""

    headers, token = _actor(client)
    matter = _mk_matter(client, token, "IP-039E-UJ61E2")
    left = _docket(client, headers, matter_id=matter["id"], title="Family Left Mark")
    right = _docket(client, headers, matter_id=matter["id"], title="Family Right Mark")

    _interest(
        client,
        headers,
        right["id"],
        party_name="Family Owner LLP",
        recordal_status="not_required",
        evidence_reference="attachment:right-deed",
    )
    before = client.get(f"/api/ip/dockets/{right['id']}", headers=headers).json()
    before_rows = before["title_interests"]
    assert [r["recordal_status"] for r in before_rows] == ["not_required"]

    # Record a change on the left docket that names the right one as family.
    recorded = _interest(
        client,
        headers,
        left["id"],
        interest_type="assignment",
        party_name="Family Owner LLP",
        recordal_status="recorded",
        related_docket_id=right["id"],
        evidence_reference="attachment:left-assignment",
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["title_interests"][0]["recordal_status"] == "recorded"

    # The associated right is unchanged: same interests, same recordal status.
    after = client.get(f"/api/ip/dockets/{right['id']}", headers=headers).json()
    assert after["title_interests"] == before_rows
    assert [r["recordal_status"] for r in after["title_interests"]] == ["not_required"]
    # Association is one-directional evidence, not a shared record.
    assert all(r["related_docket_id"] is None for r in after["title_interests"])
