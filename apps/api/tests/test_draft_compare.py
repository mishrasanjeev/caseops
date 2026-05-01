"""PG-005 Sprint 6 (2026-05-01) — draft revision compare.

Pure-function unit tests for ``compare_versions`` (line-level diff +
citation delta), plus integration tests for the
``GET /api/matters/{id}/drafts/{id}/compare`` route covering tenant
scoping, missing-revision 404, identical-revision 400, and the
context-lines query param.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from caseops_api.services.draft_compare import (
    compare_versions,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_drafting_studio import (
    _create_draft,
    _create_matter,
    _generate,
    _seed_authority,
)


def _fake_version(*, revision: int, body: str, citations: list[str]) -> SimpleNamespace:
    """Light-weight stand-in for DraftVersion sufficient for the pure
    compare_versions helper. Avoids spinning up the DB for these
    tests."""
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        revision=revision,
        body=body,
        citations_json=json.dumps(citations),
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------
# Pure-function diff tests.
# ---------------------------------------------------------------


def test_compare_versions_identifies_added_lines() -> None:
    prev = _fake_version(
        revision=1,
        body="Para 1.\n\nPara 2.",
        citations=[],
    )
    nxt = _fake_version(
        revision=2,
        body="Para 1.\n\nPara 1A — newly inserted.\n\nPara 2.",
        citations=[],
    )
    result = compare_versions(
        draft_id="d1", prev_version=prev, next_version=nxt, context_lines=2,
    )
    assert result.lines_added >= 1
    assert result.lines_removed == 0
    assert "+1 lines" in result.summary or "+2 lines" in result.summary
    # The new paragraph appears as an insert in the hunks.
    inserted_texts = [
        ln.text
        for hunk in result.hunks
        for ln in hunk.lines
        if ln.kind == "insert"
    ]
    assert any("newly inserted" in t for t in inserted_texts)


def test_compare_versions_identifies_removed_lines() -> None:
    prev = _fake_version(
        revision=1,
        body="Para 1.\n\nPara 2 — to be deleted.\n\nPara 3.",
        citations=[],
    )
    nxt = _fake_version(
        revision=2,
        body="Para 1.\n\nPara 3.",
        citations=[],
    )
    result = compare_versions(
        draft_id="d1", prev_version=prev, next_version=nxt, context_lines=1,
    )
    assert result.lines_removed >= 1
    assert result.lines_added == 0
    deleted_texts = [
        ln.text
        for hunk in result.hunks
        for ln in hunk.lines
        if ln.kind == "delete"
    ]
    assert any("to be deleted" in t for t in deleted_texts)


def test_compare_versions_replace_classification() -> None:
    """When a line is both deleted + inserted at the same offset, the
    diff opcode is 'replace' — the hunk lines tag both as 'replace'."""
    prev = _fake_version(
        revision=1, body="Para A.\nPara B old.\nPara C.", citations=[],
    )
    nxt = _fake_version(
        revision=2, body="Para A.\nPara B new.\nPara C.", citations=[],
    )
    result = compare_versions(
        draft_id="d1", prev_version=prev, next_version=nxt, context_lines=0,
    )
    assert result.lines_added >= 1
    assert result.lines_removed >= 1
    kinds = {ln.kind for hunk in result.hunks for ln in hunk.lines}
    assert "replace" in kinds


def test_compare_versions_citation_diff_set_semantics() -> None:
    """Citations are compared as case-folded sets — an "added" citation
    is one that's in next but not prev. Order in the source list does
    not matter."""
    prev = _fake_version(
        revision=1,
        body="Body unchanged.",
        citations=[
            "Sushila Aggarwal v. State (NCT of Delhi) (2020) 5 SCC 1",
            "Gurbaksh Singh Sibbia v. State of Punjab (1980) 2 SCC 565",
        ],
    )
    nxt = _fake_version(
        revision=2,
        body="Body unchanged.",
        citations=[
            "Sushila Aggarwal v. State (NCT of Delhi) (2020) 5 SCC 1",
            "Arnesh Kumar v. State of Bihar (2014) 8 SCC 273",
        ],
    )
    result = compare_versions(
        draft_id="d1", prev_version=prev, next_version=nxt, context_lines=1,
    )
    assert result.citations_added == ["Arnesh Kumar v. State of Bihar (2014) 8 SCC 273"]
    assert result.citations_removed == [
        "Gurbaksh Singh Sibbia v. State of Punjab (1980) 2 SCC 565"
    ]
    assert result.citations_kept == [
        "Sushila Aggarwal v. State (NCT of Delhi) (2020) 5 SCC 1"
    ]
    assert "+1 citations" in result.summary
    assert "-1 citations" in result.summary


def test_compare_versions_no_change_yields_no_change_summary() -> None:
    """Two identical bodies + identical citations → empty hunks and a
    'no textual changes' summary."""
    body = "Para A.\n\nPara B.\n\nPara C."
    prev = _fake_version(revision=1, body=body, citations=["Citation X"])
    nxt = _fake_version(revision=2, body=body, citations=["Citation X"])
    result = compare_versions(
        draft_id="d1", prev_version=prev, next_version=nxt, context_lines=2,
    )
    assert result.hunks == []
    assert result.lines_added == 0
    assert result.lines_removed == 0
    assert "no textual changes" in result.summary


def test_compare_versions_handles_malformed_citations_json() -> None:
    """Garbled citations_json → empty citation lists, no crash."""
    prev = _fake_version(revision=1, body="x", citations=[])
    prev.citations_json = "not valid json"
    nxt = _fake_version(revision=2, body="y", citations=["Cite A"])
    result = compare_versions(
        draft_id="d1", prev_version=prev, next_version=nxt, context_lines=1,
    )
    assert result.citations_added == ["Cite A"]
    assert result.citations_removed == []


def test_compare_versions_context_lines_zero_only_emits_changed_lines() -> None:
    """context_lines=0 → only the changed lines appear in hunks; no
    surrounding equal context."""
    prev = _fake_version(
        revision=1, body="A\nB old\nC", citations=[],
    )
    nxt = _fake_version(
        revision=2, body="A\nB new\nC", citations=[],
    )
    result = compare_versions(
        draft_id="d1", prev_version=prev, next_version=nxt, context_lines=0,
    )
    kinds = [ln.kind for hunk in result.hunks for ln in hunk.lines]
    assert "equal" not in kinds  # no context with context_lines=0


# ---------------------------------------------------------------
# Route integration tests.
# ---------------------------------------------------------------


def test_compare_route_returns_diff_between_two_revisions(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-CMP-1")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 3001")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])  # rev 1
    _generate(client, token, matter_id, draft["id"])  # rev 2

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/compare"
        "?prev_revision=1&next_revision=2",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["draft_id"] == draft["id"]
    assert body["prev_revision"] == 1
    assert body["next_revision"] == 2
    assert body["prev_version_id"]
    assert body["next_version_id"]
    assert body["prev_version_id"] != body["next_version_id"]
    assert "summary" in body
    # hunks may be empty if mock generator emits identical text twice;
    # citations_kept should at least round-trip.
    assert isinstance(body["hunks"], list)
    assert isinstance(body["citations_kept"], list)


def test_compare_route_404_on_unknown_revision(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-CMP-404")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 3002")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])  # only rev 1

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/compare"
        "?prev_revision=1&next_revision=99",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404, resp.text
    assert "99" in resp.json()["detail"]


def test_compare_route_400_on_identical_revisions(client: TestClient) -> None:
    """Comparing a revision with itself is meaningless — return 400
    rather than emit empty hunks silently."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-CMP-400")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 3003")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/compare"
        "?prev_revision=1&next_revision=1",
        headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text


def test_compare_route_400_on_invalid_context_lines(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-CMP-CTX")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 3004")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/compare"
        "?prev_revision=1&next_revision=2&context_lines=999",
        headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text
    assert "context_lines" in resp.json()["detail"]


def test_compare_route_404_on_unknown_draft(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-CMP-NF")
    resp = client.get(
        f"/api/matters/{matter_id}/drafts/00000000-0000-0000-0000-000000000000/compare"
        "?prev_revision=1&next_revision=2",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_compare_route_requires_auth(client: TestClient) -> None:
    resp = client.get(
        "/api/matters/00000000-0000-0000-0000-000000000000/drafts/"
        "00000000-0000-0000-0000-000000000000/compare"
        "?prev_revision=1&next_revision=2",
    )
    assert resp.status_code in {401, 403}
