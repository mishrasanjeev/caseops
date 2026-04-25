"""Slice S2 (MOD-TS-017) — statutes read API tests.

Maps to FT-S2-1 .. FT-S2-7 in
``docs/PRD_STATUTE_MODEL_2026-04-25.md`` §6.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.scripts.seed_statutes import _seed
from tests.test_auth_company import auth_headers, bootstrap_company


def _bootstrap_with_seed(client: TestClient) -> str:
    """Bootstrap a company, seed the statutes catalog, return token."""
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as s:
        _seed(s)
    return token


def test_ft_s2_1_list_statutes_returns_seeded_acts(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get("/api/statutes/", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    short_names = {a["short_name"] for a in body["statutes"]}
    assert {
        "BNSS", "BNS", "BSA", "CrPC", "IPC", "Constitution", "NI Act",
    } <= short_names
    assert body["total_section_count"] > 0
    # Each item has its denormalised section_count.
    bnss = next(a for a in body["statutes"] if a["short_name"] == "BNSS")
    assert bnss["section_count"] >= 17  # we seeded 17 BNSS sections


def test_ft_s2_2_list_statutes_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/statutes/")
    assert resp.status_code == 401
    assert resp.json()["type"] == "missing_bearer_token"


def test_ft_s2_3_get_statute_returns_metadata(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get("/api/statutes/bnss-2023", headers=auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["short_name"] == "BNSS"
    assert body["enacted_year"] == 2023
    assert "indiacode" in body["source_url"]


def test_ft_s2_4_get_statute_404_unknown_id(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get(
        "/api/statutes/does-not-exist", headers=auth_headers(token),
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_ft_s2_5_list_sections_returns_ordered_rows(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get(
        "/api/statutes/crpc-1973/sections", headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["statute"]["short_name"] == "CrPC"
    nums = [s["section_number"] for s in body["sections"]]
    assert "Section 482" in nums
    assert "Section 41A" in nums
    assert "Section 438" in nums  # Sushila Aggarwal anticipatory bail
    # Ordinals are monotonic (seed loader sets them by JSON position).
    ordinals = [s["ordinal"] for s in body["sections"]]
    assert ordinals == sorted(ordinals)


def test_ft_s2_6_get_section_detail_returns_section_url_fallback(
    client: TestClient,
) -> None:
    """Section URL falls back to parent act's source_url when not
    explicitly set in the seed (verified from S1; this is a route-
    level smoke too)."""
    token = _bootstrap_with_seed(client)
    resp = client.get(
        "/api/statutes/ipc-1860/sections/Section 302",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["section"]["section_number"] == "Section 302"
    assert body["section"]["section_label"] == "Punishment for murder"
    assert body["section"]["section_url"]
    assert "indiacode" in body["section"]["section_url"]
    # No parent or children for this section in v1 seed.
    assert body["parent_section"] is None
    assert body["child_sections"] == []


def test_ft_s2_7_get_section_404_unknown_section_number(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get(
        "/api/statutes/ipc-1860/sections/Section 99999",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"].lower()
    assert "section 99999" in detail
    assert "ipc" in detail
