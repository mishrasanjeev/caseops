"""The IP pleading filing bundle is capped at max_attachment_size_bytes.

The ZIP is built in memory from the rendered DOCX and two JSON manifests. The
cap is enforced on the bytes written while the archive is built, so an
oversized member stops the build and the caller gets a typed 422 instead of a
response of unbounded size.
"""

from __future__ import annotations

import io
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.services import ip_draft_exports
from tests.test_auth_company import auth_headers
from tests.test_ip_opposition_opponent_workflow import _fixture
from tests.test_ip_pleading_drafting import _base, _generate_grounded_notice


def _finalized_bundle_url(client: TestClient) -> tuple[str, dict[str, str]]:
    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    base = _base(docket, proceeding)
    draft = _generate_grounded_notice(
        client, bootstrap=bootstrap, docket=docket, proceeding=proceeding
    )
    for action in ("submit", "approve", "finalize"):
        response = client.post(
            f"{base}/drafts/{draft['id']}/{action}",
            headers=headers,
            json={"notes": f"Human-controlled {action}."},
        )
        assert response.status_code == 200, response.text
    return f"{base}/drafts/{draft['id']}/filing-bundle.zip", headers


def _assert_too_large(response, max_bytes: int) -> None:  # noqa: ANN001
    assert response.status_code == 422, response.status_code
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["type"] == "ip_filing_bundle_too_large"
    assert problem["max_bundle_bytes"] == max_bytes
    assert "the limit for a single file" in problem["detail"]
    assert "Download the DOCX instead" in problem["detail"]


def test_filing_bundle_cap_follows_the_attachment_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, headers = _finalized_bundle_url(client)
    baseline = client.get(url, headers=headers)
    assert baseline.status_code == 200, baseline.text
    size = len(baseline.content)
    with zipfile.ZipFile(io.BytesIO(baseline.content)) as archive:
        assert "internal/generation-manifest.json" in archive.namelist()

    # Each render embeds a fresh DOCX timestamp, so the size moves by a few
    # bytes between calls; test a clear margin on each side of the limit.
    monkeypatch.setenv("CASEOPS_MAX_ATTACHMENT_SIZE_BYTES", str(size + 1024))
    get_settings.cache_clear()
    under_limit = client.get(url, headers=headers)
    assert under_limit.status_code == 200, under_limit.text

    monkeypatch.setenv("CASEOPS_MAX_ATTACHMENT_SIZE_BYTES", str(size - 1024))
    get_settings.cache_clear()
    _assert_too_large(client.get(url, headers=headers), size - 1024)


def test_filing_bundle_over_default_cap_stops_while_building(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, headers = _finalized_bundle_url(client)
    max_bytes = get_settings().max_attachment_size_bytes
    assert max_bytes == 25 * 1024 * 1024
    # Incompressible, so deflate cannot bring it back under the cap.
    oversized_docx = os.urandom(max_bytes + 1024)
    monkeypatch.setattr(
        ip_draft_exports,
        "render_ip_version_docx",
        lambda *args, **kwargs: (oversized_docx, "oversized.docx"),
    )
    written: list[str] = []
    original_writestr = zipfile.ZipFile.writestr

    def tracking_writestr(self, zinfo_or_arcname, data, *args, **kwargs):  # noqa: ANN001
        written.append(str(getattr(zinfo_or_arcname, "filename", zinfo_or_arcname)))
        return original_writestr(self, zinfo_or_arcname, data, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", tracking_writestr)

    _assert_too_large(client.get(url, headers=headers), max_bytes)
    # The oversized first member aborted the build; nothing after it was added.
    assert written == ["filed-document/oversized.docx"]
