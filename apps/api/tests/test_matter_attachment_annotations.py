"""Sprint Q10 — tests for matter attachment annotations."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import Matter, MatterAttachment
from caseops_api.db.session import get_session_factory


def _bootstrap(client: TestClient) -> tuple[str, dict[str, str]]:
    from tests.test_auth_company import auth_headers, bootstrap_company

    boot = bootstrap_company(client)
    return str(boot["access_token"]), auth_headers(str(boot["access_token"]))


def _create_matter(client: TestClient, headers: dict[str, str], code: str) -> str:
    resp = client.post(
        "/api/matters",
        json={
            "matter_code": code,
            "title": f"Q10 annotation matter {code}",
            "practice_area": "Civil / Contract",
            "forum_level": "high_court",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _seed_attachment(matter_id: str) -> str:
    """Insert a minimal MatterAttachment directly — the web-side upload
    flow is its own test surface; for annotation tests we just need a
    valid attachment row to hang annotations on."""
    factory = get_session_factory()
    with factory() as session:
        matter = session.scalar(select(Matter).where(Matter.id == matter_id))
        assert matter is not None
        attachment = MatterAttachment(
            matter_id=matter_id,
            original_filename="q10-fixture.pdf",
            content_type="application/pdf",
            storage_key=f"test/{uuid.uuid4()}.pdf",
            size_bytes=1024,
            sha256_hex="0" * 64,
            processing_status="processed",
        )
        session.add(attachment)
        session.commit()
        return attachment.id


def test_list_annotations_empty_on_fresh_attachment(client: TestClient) -> None:
    _, headers = _bootstrap(client)
    matter_id = _create_matter(client, headers, "Q10-001")
    attachment_id = _seed_attachment(matter_id)

    resp = client.get(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"annotations": []}


def test_create_annotation_round_trips(client: TestClient) -> None:
    _, headers = _bootstrap(client)
    matter_id = _create_matter(client, headers, "Q10-002")
    attachment_id = _seed_attachment(matter_id)

    create = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        json={
            "kind": "highlight",
            "page": 3,
            "bbox": [10.0, 20.0, 200.0, 40.0],
            "quoted_text": "The triple test is satisfied.",
            "body": "Cite Satender Kumar Antil on parity.",
            "color": "#ffeb3b",
        },
        headers=headers,
    )
    assert create.status_code == 200, create.text
    body = create.json()
    assert body["kind"] == "highlight"
    assert body["page"] == 3
    assert body["bbox"] == [10.0, 20.0, 200.0, 40.0]
    assert body["quoted_text"].startswith("The triple test")
    assert body["matter_attachment_id"] == attachment_id

    listed = client.get(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        headers=headers,
    )
    assert listed.status_code == 200
    items = listed.json()["annotations"]
    assert len(items) == 1
    assert items[0]["id"] == body["id"]


def test_create_annotation_rejects_bad_bbox(client: TestClient) -> None:
    _, headers = _bootstrap(client)
    matter_id = _create_matter(client, headers, "Q10-003")
    attachment_id = _seed_attachment(matter_id)

    resp = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        json={"kind": "highlight", "page": 1, "bbox": [1.0, 2.0]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_create_annotation_rejects_non_positive_page(client: TestClient) -> None:
    _, headers = _bootstrap(client)
    matter_id = _create_matter(client, headers, "Q10-004")
    attachment_id = _seed_attachment(matter_id)

    resp = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        json={"kind": "note", "page": 0},
        headers=headers,
    )
    assert resp.status_code == 422


def test_archive_annotation_removes_from_list(client: TestClient) -> None:
    _, headers = _bootstrap(client)
    matter_id = _create_matter(client, headers, "Q10-005")
    attachment_id = _seed_attachment(matter_id)

    created = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        json={"kind": "note", "page": 1, "body": "to-archive"},
        headers=headers,
    )
    aid = created.json()["id"]

    del_resp = client.delete(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations/{aid}",
        headers=headers,
    )
    assert del_resp.status_code == 204

    listed = client.get(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        headers=headers,
    )
    assert listed.json() == {"annotations": []}


def test_cross_tenant_attachment_is_404(client: TestClient) -> None:
    """Tenant A's attachment must not be reachable from Tenant B."""
    _, headers_a = _bootstrap(client)
    matter_id = _create_matter(client, headers_a, "Q10-ISO")
    attachment_id = _seed_attachment(matter_id)

    # Tenant B bootstraps.
    b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B LLP",
            "company_slug": "tenant-b-q10",
            "company_type": "law_firm",
            "owner_full_name": "Tenant B Owner",
            "owner_email": "b@q10.example",
            "owner_password": "TenantB-Strong!234",
        },
    )
    assert b.status_code == 200
    headers_b = {"Authorization": f"Bearer {b.json()['access_token']}"}

    resp = client.get(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        headers=headers_b,
    )
    assert resp.status_code == 404


def test_kind_validation(client: TestClient) -> None:
    _, headers = _bootstrap(client)
    matter_id = _create_matter(client, headers, "Q10-006")
    attachment_id = _seed_attachment(matter_id)

    resp = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/annotations",
        json={"kind": "invalid_kind", "page": 1},
        headers=headers,
    )
    # Either pydantic 422 (Literal rejected) or service-level 422 —
    # both signal the client mis-picked a kind.
    assert resp.status_code == 422
