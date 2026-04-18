"""Pass 1 regression coverage — three deeper fail-opens the Codex
critical review + the follow-up audit identified.

1. Recommendation generation must raise 503 when authority retrieval
   itself errors, not mask the outage as an empty retrieval and then
   serve a confident refusal to the caller.
2. Draft DOCX export must not release a zero-verified-citation draft
   into the world unless the reviewing partner has explicitly
   approved or finalised it.
3. Hearing pack generation must drop any ``authority_card`` whose
   ``source_ref`` does not match a real authority — the model can't
   invent citations here either.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str = "PASS1-001") -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Pass-1 test — {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
            "description": "Seeded for Pass-1 regression tests.",
            "court_name": "Delhi High Court",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


# ---------------------------------------------------------------------------
# 1. Recommendation retrieval outage → 503, not a silent empty result.
# ---------------------------------------------------------------------------


def test_recommendation_fails_503_when_authority_retrieval_crashes(
    client: TestClient, monkeypatch
) -> None:
    from caseops_api.services import recommendations as rec_mod

    def _blowup(*args, **kwargs):
        raise RuntimeError("embedding provider exploded")

    # Patch the underlying catalog search that the retrieval helper
    # calls; this simulates e.g. an embedding-provider outage.
    monkeypatch.setattr(
        rec_mod, "search_authority_catalog", _blowup
    )

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "PASS1-REC-CRASH")
    resp = client.post(
        f"/api/matters/{matter_id}/recommendations",
        headers=auth_headers(token),
        json={"type": "authority"},
    )
    assert resp.status_code == 503, resp.text
    assert "retrieval" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 2. DOCX export refuses when verified_citation_count == 0 and the
#    draft has not been approved.
# ---------------------------------------------------------------------------


def test_docx_export_refuses_draft_with_zero_verified_citations(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "PASS1-EXP-ZERO")

    # Create + generate a draft via the mock LLM. The mock emits a
    # draft that cites authorities the catalog does not hold, so
    # verified_citation_count lands at 0.
    draft = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Bail application", "draft_type": "other"},
    ).json()
    draft_id = draft["id"]
    gen = client.post(
        f"/api/matters/{matter_id}/drafts/{draft_id}/generate",
        headers=auth_headers(token),
        json={"focus_note": "BNSS s.483 regular bail."},
    )
    assert gen.status_code == 200, gen.text
    assert gen.json()["versions"][-1]["verified_citation_count"] == 0

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft_id}/export.docx",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "verified" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3. Hearing pack drops authority_cards whose source_ref does not
#    exist in authority_documents.
# ---------------------------------------------------------------------------


def test_hearing_pack_drops_unverified_authority_cards(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "PASS1-HP")
    hearing = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": "2026-05-12",
            "forum_name": "Delhi High Court",
            "purpose": "Directions",
            "status": "scheduled",
        },
    )
    hearing_id = hearing.json()["id"]

    resp = client.post(
        f"/api/matters/{matter_id}/hearings/{hearing_id}/pack",
        headers=auth_headers(token),
        json={},
    )
    assert resp.status_code == 200, resp.text
    pack = resp.json()

    # The mock provider emits exactly one authority_card with
    # source_ref="MOCK-AUTH-1". That id is not in authority_documents,
    # so the verifier must drop it from the persisted pack.
    kinds = {item["item_type"] for item in pack["items"]}
    assert "authority_card" not in kinds, (
        "Unverified authority_card survived the verifier — fail-open regression."
    )
    # Other item types are matter-derived and should still land.
    assert {"chronology", "last_order", "issue"} <= kinds
