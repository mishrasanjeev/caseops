"""Wall directory search (adjacent path of Nov 24 workbook rows 4-5).

The directory returns the 500 most recent walls and the admin screen filtered
only those, so an older wall could not be found and the "already walled"
check could miss it. `q` and `matter_id` now narrow on the server. They must
never widen what the reader may see: a walled admin still cannot find walls on
the Matter they are walled from, by code, title or person.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ethical_walls import _create_matter, _invite_member


def _directory(client: TestClient, token: str, **params: str) -> dict:
    response = client.get(
        "/api/matters/ethical-walls", headers=auth_headers(token), params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def _wall(client: TestClient, token: str, matter_id: str, membership_id: str) -> None:
    response = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(token),
        json={"excluded_membership_id": membership_id, "reason": "Screened."},
    )
    assert response.status_code == 200, response.text


def test_search_and_matter_filter_narrow_on_the_server(client: TestClient) -> None:
    owner_token = str(bootstrap_company(client)["access_token"])
    first = _create_matter(client, owner_token, "WALL-SRCH-1")
    second = _create_matter(client, owner_token, "WALL-SRCH-2")
    divya, _ = _invite_member(client, owner_token, "divya.iyer@asterlegal.in")
    chetan, _ = _invite_member(client, owner_token, "chetan.rao@asterlegal.in")
    _wall(client, owner_token, first, divya)
    _wall(client, owner_token, second, chetan)

    by_person = _directory(client, owner_token, q="divya.iyer")
    assert [(r["matter_id"], r["excluded_membership_id"]) for r in by_person["walls"]] == [
        (first, divya)
    ]
    by_code = _directory(client, owner_token, q="srch-2")
    assert [r["excluded_membership_id"] for r in by_code["walls"]] == [chetan]
    by_matter = _directory(client, owner_token, matter_id=first)
    assert [r["excluded_membership_id"] for r in by_matter["walls"]] == [divya]
    assert _directory(client, owner_token, q="nobody-matches")["walls"] == []
    assert len(_directory(client, owner_token)["walls"]) == 2


def test_search_never_reveals_walls_on_a_matter_the_admin_is_walled_from(
    client: TestClient,
) -> None:
    owner_token = str(bootstrap_company(client)["access_token"])
    hidden = _create_matter(client, owner_token, "WALL-HIDDEN")
    admin_id, admin_token = _invite_member(
        client, owner_token, "walled.admin@asterlegal.in", role="admin"
    )
    other_id, _ = _invite_member(client, owner_token, "other.person@asterlegal.in")
    _wall(client, owner_token, hidden, admin_id)
    _wall(client, owner_token, hidden, other_id)

    for params in (
        {"q": "WALL-HIDDEN"},
        {"q": "other.person"},
        {"q": "ACL test"},
        {"matter_id": hidden},
    ):
        body = _directory(client, admin_token, **params)
        assert body["walls"] == [], params
        assert "WALL-HIDDEN" not in str(body)


def test_narrowed_reads_are_audited_without_the_search_text(client: TestClient) -> None:
    import json

    from sqlalchemy import select

    from caseops_api.db.models import AuditEvent
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    matter = _create_matter(client, owner_token, "WALL-AUDIT")
    _directory(client, owner_token, q="private needle", matter_id=matter)
    with get_session_factory()() as session:
        rows = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "matter.ethical_walls_viewed")
            )
        )
    metadata = [json.loads(row.metadata_json or "{}") for row in rows]
    narrowed = [m for m in metadata if m.get("searched")]
    assert narrowed and narrowed[-1]["matter_id"] == matter
    assert "private needle" not in json.dumps(metadata)
