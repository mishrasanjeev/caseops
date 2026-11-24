"""The Matter court-filing bundle is capped at max_attachment_size_bytes.

The bundle zips the rendered PDFs plus every selected Matter exhibit. Exhibits
stop being read once their stored size passes the cap, the ZIP stops being
written at the cap, and the caller gets a typed 422 instead of a response of
unbounded size.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.db.models import MatterAttachment
from caseops_api.db.session import get_session_factory
from caseops_api.services.document_storage import resolve_storage_path
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_drafting_studio import (
    _create_draft,
    _create_matter,
    _generate,
    _seed_attachment,
    _seed_authority,
)


def _bundle_url(client: TestClient, code: str) -> tuple[str, str, str]:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, code)
    _seed_authority(neutral_citation="2024 SCC OnLine SC 2091")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])
    return f"/api/matters/{matter_id}/drafts/{draft['id']}/filing-bundle.zip", token, matter_id


def _exhibit(matter_id: str, name: str, payload: bytes) -> Path:
    attachment_id = _seed_attachment(matter_id, extracted_text="exhibit", original_filename=name)
    with get_session_factory()() as session:
        row = session.get(MatterAttachment, attachment_id)
        assert row is not None
        path = resolve_storage_path(row.storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _assert_too_large(response, max_bytes: int) -> None:  # noqa: ANN001
    assert response.status_code == 422, response.status_code
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["type"] == "matter_filing_bundle_too_large"
    assert problem["max_bundle_bytes"] == max_bytes
    assert "the limit for a single file" in problem["detail"]
    assert "Select fewer exhibits" in problem["detail"]


def test_matter_filing_bundle_cap_follows_the_attachment_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, token, matter_id = _bundle_url(client, "BUNDLE-CAP-1")
    _exhibit(matter_id, "exhibit-a.pdf", os.urandom(8 * 1024))
    baseline = client.get(url, headers=auth_headers(token))
    assert baseline.status_code == 200, baseline.text
    assert baseline.headers["x-caseops-exhibit-count"] == "1"
    size = len(baseline.content)

    # Rendered PDFs carry timestamps, so test a margin on each side.
    monkeypatch.setenv("CASEOPS_MAX_ATTACHMENT_SIZE_BYTES", str(size + 64 * 1024))
    get_settings.cache_clear()
    assert client.get(url, headers=auth_headers(token)).status_code == 200

    # Under the bundle size but above the exhibit: the ZIP build stops.
    monkeypatch.setenv("CASEOPS_MAX_ATTACHMENT_SIZE_BYTES", str(size - 1024))
    get_settings.cache_clear()
    _assert_too_large(client.get(url, headers=auth_headers(token)), size - 1024)


def test_matter_filing_bundle_stops_reading_exhibits_past_the_default_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, token, matter_id = _bundle_url(client, "BUNDLE-CAP-2")
    max_bytes = get_settings().max_attachment_size_bytes
    assert max_bytes == 25 * 1024 * 1024
    # Two incompressible 13 MiB exhibits: either fits alone, together they do not.
    first = _exhibit(matter_id, "exhibit-a.pdf", os.urandom(13 * 1024 * 1024))
    second = _exhibit(matter_id, "exhibit-b.pdf", os.urandom(13 * 1024 * 1024))

    reads: list[Path] = []
    original_read_bytes = Path.read_bytes

    def tracking_read_bytes(self: Path) -> bytes:
        if self in {first, second}:
            reads.append(self)
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", tracking_read_bytes)
    _assert_too_large(client.get(url, headers=auth_headers(token)), max_bytes)
    # The second exhibit was refused on its stored size, before being read.
    assert reads == [first]
