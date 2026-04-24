"""Per-tenant authority annotations (§4.2)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentType
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _seed_authority(title: str = "State of Delhi v Kumar") -> str:
    """Insert a standalone authority_document row for the test to annotate."""
    from datetime import date

    Session = get_session_factory()
    with Session() as session:
        doc = AuthorityDocument(
            source="indiakanoon",
            adapter_name="indiakanoon",
            court_name="Delhi High Court",
            forum_level="high_court",
            document_type=AuthorityDocumentType.JUDGMENT,
            title=title,
            neutral_citation="2024:DHC:1111",
            case_reference="BAIL APPLN. 99/2024",
            decision_date=date(2024, 6, 1),
            canonical_key=f"dh-{title}",
            summary="Sample bail order for annotation tests.",
            document_text="Full document text (elided).",
            extracted_char_count=40,
        )
        session.add(doc)
        session.commit()
        return doc.id


def test_tenant_can_create_list_update_archive_and_delete(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    auth_id = _seed_authority()

    # Create
    resp = client.post(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token),
        json={
            "kind": "note",
            "title": "Parity precedent",
            "body": "Cite alongside triple-test grounds.",
        },
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["kind"] == "note"
    assert created["is_archived"] is False

    # List — sees it
    resp = client.get(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert [a["id"] for a in resp.json()["annotations"]] == [created["id"]]

    # Update — change title + archive
    resp = client.patch(
        f"/api/authorities/annotations/{created['id']}",
        headers=auth_headers(token),
        json={"title": "Parity precedent (revised)", "is_archived": True},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["title"] == "Parity precedent (revised)"
    assert updated["is_archived"] is True

    # List (default) — archived is hidden
    resp = client.get(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token),
    )
    assert resp.json()["annotations"] == []

    # List (include_archived) — now visible
    resp = client.get(
        f"/api/authorities/documents/{auth_id}/annotations?include_archived=true",
        headers=auth_headers(token),
    )
    assert [a["id"] for a in resp.json()["annotations"]] == [created["id"]]

    # Delete
    resp = client.delete(
        f"/api/authorities/annotations/{created['id']}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 204

    # List — empty
    resp = client.get(
        f"/api/authorities/documents/{auth_id}/annotations?include_archived=true",
        headers=auth_headers(token),
    )
    assert resp.json()["annotations"] == []


def _bootstrap(client: TestClient, *, slug: str, email: str) -> dict:
    # EG-001 (2026-04-23) made cookies win over bearer headers in
    # ``get_current_context``. The Starlette TestClient persists cookies
    # across requests, which means a second bootstrap silently
    # overwrites the first tenant's cookie — and any later
    # ``Authorization: Bearer ...`` call would be misrouted to whichever
    # tenant happened to bootstrap last. Clear cookies before AND after
    # bootstrap so tenant-isolation tests rely on the bearer header alone.
    client.cookies.clear()
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": slug.title() + " LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Owner",
            "owner_email": email,
            "owner_password": "FoundersPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return resp.json()


def test_annotations_are_tenant_isolated(client: TestClient) -> None:
    auth_id = _seed_authority("Tenant Isolation v Leakage")

    boot_a = _bootstrap(client, slug="tenant-a", email="a@example.com")
    token_a = str(boot_a["access_token"])
    boot_b = _bootstrap(client, slug="tenant-b", email="b@example.com")
    token_b = str(boot_b["access_token"])

    # A creates an annotation
    resp = client.post(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token_a),
        json={"kind": "flag", "title": "Watchlist"},
    )
    assert resp.status_code == 201
    ann_id = resp.json()["id"]

    # B lists — sees nothing (A's annotation is private to A)
    resp = client.get(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 200
    assert resp.json()["annotations"] == []

    # B cannot update A's annotation
    resp = client.patch(
        f"/api/authorities/annotations/{ann_id}",
        headers=auth_headers(token_b),
        json={"title": "Hijacked"},
    )
    assert resp.status_code == 404

    # B cannot delete A's annotation
    resp = client.delete(
        f"/api/authorities/annotations/{ann_id}",
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 404

    # A's annotation still intact
    resp = client.get(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token_a),
    )
    kept = resp.json()["annotations"]
    assert [a["title"] for a in kept] == ["Watchlist"]


def test_duplicate_kind_plus_title_is_rejected_per_tenant(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    auth_id = _seed_authority("Dup Title v Unique Scope")

    payload = {"kind": "tag", "title": "Bail"}
    first = client.post(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token),
        json=payload,
    )
    assert first.status_code == 201

    second = client.post(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token),
        json=payload,
    )
    assert second.status_code == 409


def test_unknown_authority_returns_404(client: TestClient) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    resp = client.get(
        "/api/authorities/documents/00000000-0000-0000-0000-000000000000/annotations",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_saved_annotations_history_view_is_tenant_isolated(
    client: TestClient,
) -> None:
    """BUG-030: GET /api/authorities/annotations returns the calling
    tenant's annotations joined with authority preview, never another
    tenant's rows."""
    auth_a = _seed_authority("Saved-history A v Other")
    auth_b = _seed_authority("Saved-history B v Other")

    boot_a = _bootstrap(client, slug="saved-a", email="saved-a@example.com")
    token_a = str(boot_a["access_token"])
    boot_b = _bootstrap(client, slug="saved-b", email="saved-b@example.com")
    token_b = str(boot_b["access_token"])

    # A saves on both authorities, B saves on auth_b
    for auth_id, kind, title in [
        (auth_a, "note", "A on A"),
        (auth_b, "flag", "A on B"),
    ]:
        resp = client.post(
            f"/api/authorities/documents/{auth_id}/annotations",
            headers=auth_headers(token_a),
            json={"kind": kind, "title": title},
        )
        assert resp.status_code == 201, resp.text

    resp = client.post(
        f"/api/authorities/documents/{auth_b}/annotations",
        headers=auth_headers(token_b),
        json={"kind": "tag", "title": "B on B"},
    )
    assert resp.status_code == 201, resp.text

    # A sees both of A's saves, with embedded authority preview
    resp = client.get(
        "/api/authorities/annotations", headers=auth_headers(token_a)
    )
    assert resp.status_code == 200, resp.text
    rows_a = resp.json()["annotations"]
    titles_a = sorted(r["title"] for r in rows_a)
    assert titles_a == ["A on A", "A on B"]
    for r in rows_a:
        assert r["authority_court_name"] == "Delhi High Court"
        assert r["authority_forum_level"] == "high_court"
        assert r["authority_document_type"] == "judgment"
        assert r["authority_neutral_citation"] == "2024:DHC:1111"
        assert r["authority_decision_date"] == "2024-06-01"

    # B sees only B's save — no leakage of A's annotations
    resp = client.get(
        "/api/authorities/annotations", headers=auth_headers(token_b)
    )
    assert resp.status_code == 200
    rows_b = resp.json()["annotations"]
    assert [r["title"] for r in rows_b] == ["B on B"]


def test_saved_annotations_default_hides_archived_and_orders_newest_first(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    auth_id = _seed_authority("Order + archive v History")

    # Two saves; archive the older one
    first = client.post(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token),
        json={"kind": "note", "title": "Older"},
    )
    assert first.status_code == 201
    older_id = first.json()["id"]

    second = client.post(
        f"/api/authorities/documents/{auth_id}/annotations",
        headers=auth_headers(token),
        json={"kind": "flag", "title": "Newer"},
    )
    assert second.status_code == 201
    newer_id = second.json()["id"]

    archive = client.patch(
        f"/api/authorities/annotations/{older_id}",
        headers=auth_headers(token),
        json={"is_archived": True},
    )
    assert archive.status_code == 200

    # Default: archived hidden, newest-first
    resp = client.get(
        "/api/authorities/annotations", headers=auth_headers(token)
    )
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["annotations"]]
    assert ids == [newer_id]

    # include_archived=true brings the older one back, newest-first preserved
    resp = client.get(
        "/api/authorities/annotations?include_archived=true",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["annotations"]]
    assert ids == [newer_id, older_id]
