"""Slice S2 (MOD-TS-017) — statutes read API tests.

Maps to FT-S2-1 .. FT-S2-7 in
``docs/PRD_STATUTE_MODEL_2026-04-25.md`` §6.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from caseops_api.db.models import (
    AuditEvent,
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityIngestionRun,
    Contract,
    ContractLegalReference,
    DocumentProcessingJob,
    LegalUpdateAlert,
    LegalUpdateSourceRecord,
    LegalUpdateWatchlist,
    Matter,
    MatterStatuteReference,
    ModelRun,
    NotificationDeliveryIntent,
    StatuteChangeEvent,
    StatuteSection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.seed_statutes import _seed
from caseops_api.services import legal_updates as legal_updates_service
from caseops_api.services.legal_update_sources import (
    PrsActsParliamentAdapter,
    sync_source,
    upsert_source_records,
)
from tests.test_auth_company import auth_headers, bootstrap_company

ADP18_AUTHORITY_RECORD_ID = "adp18-supreme-court-notification"
PRS_FIXTURE_HTML = """
<html>
  <body>
    <a href="/acts/parliament/negotiable-instruments-act-1881">
      The Negotiable Instruments Act, 1881
    </a>
    <a href="mailto:test@example.com">Contact</a>
  </body>
</html>
"""


def _bootstrap_with_seed(client: TestClient) -> str:
    """Bootstrap a company, seed the statutes catalog, return token."""
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as s:
        _seed(s)
    return token


def _bootstrap_second_company(client: TestClient, slug: str = "adp18-other") -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": f"owner@{slug}.example.com",
            "owner_password": "OtherPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_legal_update_authority() -> str:
    with get_session_factory()() as session:
        existing = session.scalar(
            select(AuthorityDocument).where(
                AuthorityDocument.canonical_key == ADP18_AUTHORITY_RECORD_ID
            )
        )
        if existing is not None:
            return existing.id
        document = AuthorityDocument(
            source="supreme_court_latest_orders",
            adapter_name="test-adp18",
            court_name="Supreme Court of India",
            forum_level="supreme_court",
            document_type="notice",
            title="Supreme Court registry notification on Section 138 procedure",
            case_reference="Notification No. ADP18/2026",
            bench_name=None,
            neutral_citation=None,
            decision_date=date(2026, 5, 20),
            canonical_key=ADP18_AUTHORITY_RECORD_ID,
            source_reference="https://www.sci.gov.in/adp18-notification",
            summary=(
                "Registry notification addressing Section 138 filing procedure "
                "for cheque dishonour matters."
            ),
            document_text="ADP18_FULL_TEXT_SENTINEL should never be returned",
            extracted_char_count=128,
            sections_cited_json=json.dumps(["Section 138"]),
        )
        session.add(document)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=document.id,
                chunk_index=0,
                content=(
                    "Section 138 registry notification metadata for "
                    "cheque dishonour filing review."
                ),
                token_count=12,
            )
        )
        session.commit()
        return document.id


def _create_legal_update_matter(
    client: TestClient,
    token: str,
    *,
    code: str,
) -> str:
    response = client.post(
        "/api/matters",
        headers=auth_headers(token),
        json={
            "matter_code": code,
            "title": f"Legal update matter {code}",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def test_ft_s2_1_list_statutes_returns_seeded_acts(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get("/api/statutes/", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    short_names = {a["short_name"] for a in body["statutes"]}
    assert {
        "BNSS", "BNS", "BSA", "CrPC", "IPC", "Constitution", "NI Act",
    } <= short_names
    assert body["total_section_count"] == 0
    assert body["total_catalog_section_count"] > 0
    # Catalog coverage is truthful: unreviewed seed text is not counted as verified.
    bnss = next(a for a in body["statutes"] if a["short_name"] == "BNSS")
    assert bnss["section_count"] == 0
    assert bnss["catalog_section_count"] >= 17


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
    assert nums == []
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
    assert body["section"]["source_action"]["target_type"] == "statute_section"
    assert body["section"]["source_action"]["target_id"] == body["section"]["id"]
    assert body["section"]["source_action"]["state"] == "missing"
    assert body["section"]["source_action"]["open_url"] is None
    assert body["section"]["section_text"] is None
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


def test_adp18_legal_update_watchlist_run_is_in_app_idempotent_and_bounded(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    authority_id = _seed_legal_update_authority()

    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Cheque dishonour updates",
            "statute_id": "ni-act-1881",
            "jurisdiction": "india",
            "statute_terms": ["Section 138"],
            "update_types": ["amendment", "notification"],
        },
    )
    assert create.status_code == 201, create.text
    watchlist = create.json()
    assert watchlist["source_key"] is None
    assert watchlist["update_types"] == ["amendment", "notification"]

    preview = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": True, "limit": 10},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["delivery_status"] == "in_app_only"
    assert preview_body["matched_count"] >= 1
    response_blob = json.dumps(preview_body)
    assert authority_id in response_blob
    assert "ADP18_FULL_TEXT_SENTINEL" not in response_blob
    assert "document_text" not in response_blob
    assert "source_payload" not in response_blob
    assert "storage_key" not in response_blob
    assert all(
        len(item.get("snippet") or "") <= 280 for item in preview_body["matches"]
    )
    assert all(
        item["source_key"] and item["source_category"] and item["provenance_status"]
        for item in preview_body["matches"]
    )

    run = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert run.status_code == 200, run.text
    assert run.json()["created_count"] >= 1

    rerun = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["created_count"] == 0

    listed = client.get(
        "/api/statutes/legal-updates",
        headers=auth_headers(token),
    )
    assert listed.status_code == 200, listed.text
    updates = listed.json()["updates"]
    assert updates
    assert "ADP18_FULL_TEXT_SENTINEL" not in json.dumps(updates)

    read = client.patch(
        f"/api/statutes/legal-updates/{updates[0]['id']}",
        headers=auth_headers(token),
        json={"action": "read"},
    )
    assert read.status_code == 200, read.text
    assert read.json()["is_read"] is True

    digest = client.get(
        "/api/statutes/legal-updates/digest-preview",
        headers=auth_headers(token),
    )
    assert digest.status_code == 200, digest.text
    assert digest.json()["delivery_status"] == "in_app_only"
    assert "provider-specific approval" in digest.json()["delivery_note"]

    with get_session_factory()() as session:
        assert session.scalar(select(AuthorityIngestionRun)) is None
        assert session.scalar(select(DocumentProcessingJob)) is None
        assert session.scalar(select(ModelRun)) is None
        assert (
            session.scalar(
                select(func.count()).select_from(LegalUpdateAlert).where(
                    LegalUpdateAlert.watchlist_id == watchlist["id"],
                    LegalUpdateAlert.company_id == watchlist["company_id"],
                )
            )
            == run.json()["created_count"]
        )
        audit_events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == watchlist["company_id"],
                    AuditEvent.action.in_(
                        [
                            "legal_update.watchlist_created",
                            "legal_update.watchlist_run",
                            "legal_update.alert_read",
                        ]
                    ),
                )
            )
        )
        assert len(audit_events) >= 3
        audit_blob = "\n".join(event.metadata_json or "" for event in audit_events)
        for forbidden in (
            "Section 138",
            "cheque dishonour",
            "ADP18_FULL_TEXT_SENTINEL",
            "snippet",
            "document_text",
            "source_payload",
            "storage_key",
        ):
            assert forbidden not in audit_blob


def test_adp18_watchlists_are_tenant_scoped_and_archived_rules_do_not_generate(
    client: TestClient,
) -> None:
    token_a = _bootstrap_with_seed(client)
    token_b = str(_bootstrap_second_company(client, "adp18-other-b")["access_token"])

    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token_a),
        json={
            "name": "Tenant A statutory updates",
            "statute_id": "crpc-1973",
            "statute_terms": ["Section 482"],
            "update_types": ["amendment"],
        },
    )
    assert create.status_code == 201, create.text
    watchlist_id = create.json()["id"]

    tenant_b_list = client.get(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token_b),
    )
    assert tenant_b_list.status_code == 200, tenant_b_list.text
    assert tenant_b_list.json()["watchlists"] == []

    tenant_b_run = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}/run",
        headers=auth_headers(token_b),
        json={"preview_only": False},
    )
    assert tenant_b_run.status_code == 404

    archive = client.patch(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}",
        headers=auth_headers(token_a),
        json={"is_archived": True},
    )
    assert archive.status_code == 200, archive.text
    assert archive.json()["is_archived"] is True

    archived_run = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}/run",
        headers=auth_headers(token_a),
        json={"preview_only": False},
    )
    assert archived_run.status_code == 200, archived_run.text
    assert archived_run.json()["matched_count"] == 0
    assert archived_run.json()["created_count"] == 0


def test_adp18_watchlist_rejects_unbounded_and_unknown_source_filters(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    unbounded = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={"name": "Unbounded"},
    )
    assert unbounded.status_code == 400
    assert "bounded filter" in unbounded.json()["detail"]

    unknown_source = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Unknown source",
            "source_key": "not-a-source",
            "update_types": ["notification"],
        },
    )
    assert unknown_source.status_code == 400
    assert "source registry" in unknown_source.json()["detail"]


def test_matter_scoped_legal_update_watchlist_rejects_disposed_mutations_but_keeps_history(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _bootstrap_with_seed(client)
    matter_id = _create_legal_update_matter(
        client,
        token,
        code="LEGAL-UPDATES-DISPOSED",
    )
    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Matter-scoped NI Act updates",
            "statute_id": "ni-act-1881",
            "statute_terms": ["Section 138"],
            "matter_id": matter_id,
            "update_types": ["amendment"],
        },
    )
    assert create.status_code == 201, create.text
    watchlist_id = str(create.json()["id"])

    initial_run = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert initial_run.status_code == 200, initial_run.text
    assert initial_run.json()["created_count"] >= 1

    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.status = "disposed"
        matter.is_active = False
        session.commit()
        baseline_alert_count = int(
            session.scalar(
                select(func.count()).select_from(LegalUpdateAlert).where(
                    LegalUpdateAlert.watchlist_id == watchlist_id
                )
            )
            or 0
        )
        baseline_intent_count = int(
            session.scalar(
                select(func.count()).select_from(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.matter_id == matter_id
                )
            )
            or 0
        )
        baseline_run_audit_count = int(
            session.scalar(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.action == "legal_update.watchlist_run",
                    AuditEvent.target_id == watchlist_id,
                )
            )
            or 0
        )

    match_calls = 0
    original_matches = legal_updates_service._matches_for_watchlist

    def counted_matches(session, *, rule):
        nonlocal match_calls
        match_calls += 1
        return original_matches(session, rule=rule)

    monkeypatch.setattr(
        legal_updates_service,
        "_matches_for_watchlist",
        counted_matches,
    )

    blocked_create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "No second disposed watchlist",
            "matter_id": matter_id,
            "statute_terms": ["Section 138"],
            "update_types": ["amendment"],
        },
    )
    blocked_update = client.patch(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}",
        headers=auth_headers(token),
        json={"name": "Must remain unchanged"},
    )
    blocked_run = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert [
        blocked_create.status_code,
        blocked_update.status_code,
        blocked_run.status_code,
    ] == [409, 409, 409]
    assert match_calls == 0

    watchlist_history = client.get(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
    )
    assert watchlist_history.status_code == 200, watchlist_history.text
    historical_watchlist = next(
        row
        for row in watchlist_history.json()["watchlists"]
        if row["id"] == watchlist_id
    )
    assert historical_watchlist["name"] == "Matter-scoped NI Act updates"

    alert_history = client.get(
        "/api/statutes/legal-updates",
        headers=auth_headers(token),
    )
    assert alert_history.status_code == 200, alert_history.text
    historical_alert = next(
        row
        for row in alert_history.json()["updates"]
        if row["watchlist_id"] == watchlist_id
    )
    mark_read = client.patch(
        f"/api/statutes/legal-updates/{historical_alert['id']}",
        headers=auth_headers(token),
        json={"action": "read"},
    )
    assert mark_read.status_code == 200, mark_read.text
    assert mark_read.json()["is_read"] is True

    def fixture_sync_source(session, **kwargs):
        return sync_source(session, html=PRS_FIXTURE_HTML, **kwargs)

    monkeypatch.setattr(
        "caseops_api.api.routes.statutes.sync_source",
        fixture_sync_source,
    )
    source_sync = client.post(
        "/api/statutes/legal-updates/sources/prs_acts_parliament/sync?limit=1",
        headers=auth_headers(token),
    )
    assert source_sync.status_code == 200, source_sync.text
    assert source_sync.json()["status"] == "failed"

    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(LegalUpdateWatchlist).where(
                    LegalUpdateWatchlist.matter_id == matter_id
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(LegalUpdateAlert).where(
                    LegalUpdateAlert.watchlist_id == watchlist_id
                )
            )
            == baseline_alert_count
        )
        assert (
            session.scalar(
                select(func.count()).select_from(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.matter_id == matter_id
                )
            )
            == baseline_intent_count
        )
        assert (
            session.scalar(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.action == "legal_update.watchlist_run",
                    AuditEvent.target_id == watchlist_id,
                )
            )
            == baseline_run_audit_count
        )


def test_matter_scoped_legal_update_watchlist_treats_inactive_active_row_as_terminal(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _bootstrap_with_seed(client)
    matter_id = _create_legal_update_matter(
        client,
        token,
        code="LEGAL-UPDATES-INACTIVE",
    )
    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Inactive-row watchlist",
            "matter_id": matter_id,
            "statute_terms": ["Section 138"],
            "update_types": ["amendment"],
        },
    )
    assert create.status_code == 201, create.text
    watchlist_id = str(create.json()["id"])

    with get_session_factory()() as session:
        # Reproduce a pre-constraint legacy inconsistency.  The current schema
        # rejects this state at the database boundary, but the service guard
        # must remain fail-closed while old/backfilled rows can still surface.
        session.execute(text("PRAGMA ignore_check_constraints = ON"))
        session.execute(
            text("UPDATE matters SET is_active = 0 WHERE id = :matter_id"),
            {"matter_id": matter_id},
        )
        session.execute(text("PRAGMA ignore_check_constraints = OFF"))
        session.commit()

    def matches_must_not_run(*_args, **_kwargs):
        raise AssertionError("inactive Matter reached legal-update matching")

    monkeypatch.setattr(
        legal_updates_service,
        "_matches_for_watchlist",
        matches_must_not_run,
    )
    blocked_create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "No inactive Matter watchlist",
            "matter_id": matter_id,
            "statute_terms": ["Section 138"],
            "update_types": ["amendment"],
        },
    )
    blocked_update = client.patch(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}",
        headers=auth_headers(token),
        json={"is_archived": True},
    )
    blocked_preview = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}/run",
        headers=auth_headers(token),
        json={"preview_only": True, "limit": 10},
    )
    assert [
        blocked_create.status_code,
        blocked_update.status_code,
        blocked_preview.status_code,
    ] == [409, 409, 409]

    historical_list = client.get(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
    )
    assert historical_list.status_code == 200, historical_list.text
    historical = next(
        row
        for row in historical_list.json()["watchlists"]
        if row["id"] == watchlist_id
    )
    assert historical["is_archived"] is False

    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(LegalUpdateWatchlist).where(
                    LegalUpdateWatchlist.matter_id == matter_id
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(LegalUpdateAlert).where(
                    LegalUpdateAlert.watchlist_id == watchlist_id
                )
            )
            == 0
        )


def test_matter_scoped_legal_update_run_rechecks_after_disposal_race(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _bootstrap_with_seed(client)
    matter_id = _create_legal_update_matter(
        client,
        token,
        code="LEGAL-UPDATES-RACE",
    )
    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Dispose during matching",
            "statute_id": "ni-act-1881",
            "statute_terms": ["Section 138"],
            "matter_id": matter_id,
            "update_types": ["amendment"],
        },
    )
    assert create.status_code == 201, create.text
    watchlist_id = str(create.json()["id"])
    original_matches = legal_updates_service._matches_for_watchlist
    disposal_interposed = False

    def matches_then_dispose(session, *, rule):
        nonlocal disposal_interposed
        matches = original_matches(session, rule=rule)
        if not disposal_interposed:
            with get_session_factory()() as disposal_session:
                matter = disposal_session.get(Matter, matter_id)
                assert matter is not None
                matter.status = "disposed"
                matter.is_active = False
                disposal_session.commit()
            disposal_interposed = True
        return matches

    monkeypatch.setattr(
        legal_updates_service,
        "_matches_for_watchlist",
        matches_then_dispose,
    )
    response = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert disposal_interposed is True
    assert response.status_code == 409, response.text
    assert "disposed" in response.text.lower()

    history = client.get(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
    )
    assert history.status_code == 200, history.text
    assert any(row["id"] == watchlist_id for row in history.json()["watchlists"])

    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        assert matter.status == "disposed"
        assert matter.is_active is False
        assert session.scalar(
            select(LegalUpdateAlert).where(
                LegalUpdateAlert.watchlist_id == watchlist_id
            )
        ) is None
        assert session.scalar(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.matter_id == matter_id
            )
        ) is None
        assert session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "legal_update.watchlist_run",
                AuditEvent.target_id == watchlist_id,
            )
        ) is None


def test_ai_enhancement_prs_parser_and_sync_are_idempotent(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    adapter = PrsActsParliamentAdapter(
        base_url="https://prsindia.org",
        html=PRS_FIXTURE_HTML,
    )
    parsed = adapter.fetch_records(limit=10)
    assert len(parsed) == 1
    assert parsed[0].source_key == "prs_acts_parliament"
    assert parsed[0].source_category == "prs_india"
    assert parsed[0].update_type == "act"
    assert parsed[0].act_year == 1881

    with get_session_factory()() as session:
        run = sync_source(session, html=PRS_FIXTURE_HTML)
        session.commit()
        assert run.status == "completed"
        assert run.fetched_count == 1
        assert run.created_count == 1
        assert run.changed_count == 0

        rerun = sync_source(session, html=PRS_FIXTURE_HTML)
        session.commit()
        assert rerun.status == "completed"
        assert rerun.created_count == 0
        assert rerun.changed_count == 0

        changed = replace(
            parsed[0],
            content_hash="0" * 64,
            raw_metadata={**parsed[0].raw_metadata, "test_revision": "changed"},
        )
        created_count, changed_count, _, changed_ids = upsert_source_records(
            session,
            [changed],
        )
        session.commit()
        assert created_count == 0
        assert changed_count == 1
        assert changed_ids

        dated_record = replace(
            parsed[0],
            source_record_key="dated-prs-record",
            title="The Dated Example Act, 2026",
            normalized_title="the dated example act 2026",
            source_url="https://prsindia.org/acts/parliament/dated-example-act",
            source_document_url=(
                "https://prsindia.org/acts/parliament/dated-example-act"
            ),
            published_date=date(2026, 5, 26),
            act_year=2026,
            content_hash="1" * 64,
            raw_metadata={
                **parsed[0].raw_metadata,
                "title": "The Dated Example Act, 2026",
            },
        )
        dated_created_count, _, dated_ids, _ = upsert_source_records(
            session,
            [dated_record],
        )
        session.commit()
        assert dated_created_count == 1
        assert dated_ids

    source_records = client.get(
        "/api/statutes/legal-updates/source-records",
        headers=auth_headers(token),
    )
    assert source_records.status_code == 200, source_records.text
    records = [
        record
        for record in source_records.json()["records"]
        if record["source_key"] == "prs_acts_parliament"
        and "Negotiable Instruments" in record["title"]
    ]
    assert records
    assert records[0]["source_key"] == "prs_acts_parliament"
    assert records[0]["summary_status"] in {"failed", "completed", "not_required"}
    assert records[0]["summary"]["review_framing"] == (
        "Source-backed summary for lawyer review."
    )

    filtered_records = client.get(
        (
            "/api/statutes/legal-updates/source-records"
            "?since_date=2026-05-01&until_date=2026-12-31"
        ),
        headers=auth_headers(token),
    )
    assert filtered_records.status_code == 200, filtered_records.text
    filtered_titles = {record["title"] for record in filtered_records.json()["records"]}
    assert "The Dated Example Act, 2026" in filtered_titles
    assert "The Negotiable Instruments Act, 1881" not in filtered_titles

    history = client.get(
        "/api/statutes/ni-act-1881/amendment-history",
        headers=auth_headers(token),
    )
    assert history.status_code == 200, history.text
    assert history.json()["events"]
    parsed_source_url = urlparse(history.json()["events"][0]["source_url"])
    assert parsed_source_url.scheme == "https"
    assert parsed_source_url.netloc == "prsindia.org"

    with get_session_factory()() as session:
        assert session.scalar(select(LegalUpdateSourceRecord)) is not None
        assert session.scalar(select(StatuteChangeEvent)) is not None


def test_ai_enhancement_source_sync_route_uses_configured_source(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _bootstrap_with_seed(client)

    def fixture_sync_source(session, **kwargs):
        return sync_source(session, html=PRS_FIXTURE_HTML, **kwargs)

    monkeypatch.setattr(
        "caseops_api.api.routes.statutes.sync_source",
        fixture_sync_source,
    )

    response = client.post(
        "/api/statutes/legal-updates/sources/prs_acts_parliament/sync?limit=1",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_key"] == "prs_acts_parliament"
    assert body["status"] == "completed"
    assert body["fetched_count"] == 1
    assert body["created_count"] == 1


def test_ai_enhancement_source_records_match_watchlists_and_enqueue_in_app_intents(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    with get_session_factory()() as session:
        run = sync_source(session, html=PRS_FIXTURE_HTML)
        session.commit()
        assert run.created_count == 1

    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "PRS NI Act updates",
            "source_key": "prs_acts_parliament",
            "source_category": "prs_india",
            "statute_terms": ["Negotiable Instruments"],
            "update_types": ["act"],
        },
    )
    assert create.status_code == 201, create.text
    watchlist = create.json()

    run_watchlist = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert run_watchlist.status_code == 200, run_watchlist.text
    body = run_watchlist.json()
    assert body["matched_count"] == 1
    assert body["created_count"] == 1
    assert body["matches"][0]["source_record_id"]
    assert body["matches"][0]["summary"]["review_framing"] == (
        "Source-backed summary for lawyer review."
    )

    rerun = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["created_count"] == 0

    listed = client.get(
        "/api/statutes/legal-updates",
        headers=auth_headers(token),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["updates"][0]["source_record_id"]
    assert listed.json()["updates"][0]["summary"]["review_framing"] == (
        "Source-backed summary for lawyer review."
    )

    with get_session_factory()() as session:
        alert_count = session.scalar(
            select(func.count()).select_from(LegalUpdateAlert).where(
                LegalUpdateAlert.watchlist_id == watchlist["id"]
            )
        )
        assert alert_count == 1
        intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.company_id == watchlist["company_id"],
                    NotificationDeliveryIntent.event_type
                    == "legal_update.watchlist_matched",
                )
            )
        )
        assert len(intents) == 1
        assert intents[0].channel == "in_app"
        assert intents[0].status == "queued"


def test_adp18_matter_and_contract_relevance_explanations_are_bounded(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    matter_resp = client.post(
        "/api/matters",
        headers=auth_headers(token),
        json={
            "matter_code": "ADP18-REL",
            "title": "Cheque dishonour petition",
            "practice_area": "Criminal",
            "forum_level": "high_court",
            "court_name": "High Court of Delhi",
            "forum_state": "Delhi",
            "status": "intake",
        },
    )
    assert matter_resp.status_code == 200, matter_resp.text
    matter_id = matter_resp.json()["id"]

    with get_session_factory()() as session:
        section = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "ni-act-1881",
                StatuteSection.section_number == "Section 138",
            )
        )
        assert section is not None
        matter_ref = MatterStatuteReference(
            matter_id=matter_id,
            section_id=section.id,
            relevance="cited",
        )
        company_id = matter_resp.json()["company_id"]
        contract = Contract(
            company_id=company_id,
            linked_matter_id=matter_id,
            title="Cheque supply agreement",
            contract_code="ADP18-CONTRACT",
            contract_type="commercial",
            jurisdiction="Delhi",
        )
        session.add_all([matter_ref, contract])
        session.flush()
        session.add(
            ContractLegalReference(
                company_id=company_id,
                contract_id=contract.id,
                act_name="Negotiable Instruments Act",
                section_label="Section 138",
                statute_id="ni-act-1881",
            )
        )
        session.commit()
        contract_id = contract.id

    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Matter linked NI Act updates",
            "statute_id": "ni-act-1881",
            "statute_terms": ["Section 138"],
            "matter_id": matter_id,
            "contract_id": contract_id,
            "update_types": ["amendment"],
        },
    )
    assert create.status_code == 201, create.text
    run = client.post(
        f"/api/statutes/legal-updates/watchlists/{create.json()['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": True, "limit": 5},
    )
    assert run.status_code == 200, run.text
    matches = run.json()["matches"]
    assert matches
    explanation_blob = " ".join(item["relevance_explanation"] for item in matches)
    assert "matter statute references matched watched section" in explanation_blob
    assert "contract legal references matched watched statute/Act" in explanation_blob
    assert "ADP18" not in explanation_blob
