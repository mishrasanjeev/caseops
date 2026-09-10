"""BUG010/011: actual release seed, source tables and saved references on PostgreSQL."""

# Ruff treats imported pytest fixtures as ordinary shadowed parameters.
# ruff: noqa: F811

from urllib.parse import quote

import pytest
from sqlalchemy import select

from caseops_api.api.routes.statutes import (
    _is_selectable_statute_section,
    _selectable_statute_section_sql,
)
from caseops_api.db.models import StatuteSection
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.official_statute_release import load_release_bundle
from caseops_api.scripts.seed_statutes import _seed
from tests.fixtures_postgres_client import (  # noqa: F401
    http_pg_engine,
    isolated_postgres_client,
    migrated_http_template,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_official_statute_release import (
    test_complete_release_seed_details_history_and_idempotence as assert_release_seed,
)
from tests.test_statute_selection_parity import (
    test_empty_provenance_cannot_inflate_catalogue_or_allow_attachment as assert_selection_parity,
)

pytestmark = pytest.mark.postgres


def test_empty_provenance_catalogue_write_parity_on_postgres(isolated_postgres_client):
    assert_selection_parity(isolated_postgres_client)


def test_complete_release_inventory_and_idempotence_on_postgres(isolated_postgres_client):
    assert_release_seed(isolated_postgres_client)


def test_real_schedule_and_historical_provisions_attach_and_reload_on_postgres(
    isolated_postgres_client,
):
    client = isolated_postgres_client
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    with get_session_factory()() as session:
        _seed(session)
    _, sources = load_release_bundle()
    matter_response = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Catalogue PostgreSQL source acceptance",
            "matter_code": "CAT-PG-0909",
            "practice_area": "Civil",
            "forum_level": "high_court",
        },
    )
    assert matter_response.status_code == 200, matter_response.text
    matter_id = matter_response.json()["id"]
    for act, number in [
        ("ndps-1985", "Schedule"),
        ("specific-relief-1963", "Schedule"),
        ("ipc-1860", "Section 302"),
        ("iea-1872", "Section 65B"),
        ("crpc-1973", "Section 482"),
    ]:
        source = sources[act, number]
        url = f"/api/statutes/{act}/sections/{quote(number)}"
        detail = client.get(url, headers=headers)
        assert detail.status_code == 200, detail.text
        record = detail.json()["section"]
        assert record["section_text"] == source["section_text"]
        assert record["structured_tables"] == source["source_policy"].get("structured_tables", [])
        response = client.post(
            f"/api/matters/{matter_id}/statute-references",
            headers=headers,
            json={"section_id": record["id"], "relevance": "cited"},
        )
        assert response.status_code == 201, response.text
        saved = client.get(f"/api/matters/{matter_id}/statute-references", headers=headers)
        assert saved.status_code == 200, saved.text
        assert any(row["section_id"] == record["id"] for row in saved.json()["references"])
        assert client.get(url, headers=headers).json()["section"] == record

    section_id = record["id"]
    for legal_status, verification, scope in [
        ("repealed", "verified_official", None),
        ("repealed", "verified_official", True),
        ("repealed", "verified_official", "invented"),
        ("draft", "verified_official", "historical_repealed_law"),
        ("advisory", "verified_official", "historical_repealed_law"),
        ("repealed", "verified_licensed", "historical_repealed_law"),
        ("repealed", "retired", "historical_repealed_law"),
        ("repealed", "quarantined", "historical_repealed_law"),
        ("repealed", "unverified", "historical_repealed_law"),
    ]:
        with get_session_factory()() as session:
            row = session.get(StatuteSection, section_id)
            row.legal_status = legal_status
            row.verification_status = verification
            row.source_policy_json = {**row.source_policy_json, "edition_scope": scope}
            session.commit()
            assert not _is_selectable_statute_section(row)
            assert (
                session.scalar(
                    select(StatuteSection.id).where(
                        StatuteSection.id == section_id, _selectable_statute_section_sql()
                    )
                )
                is None
            )
        rejected = client.post(
            f"/api/matters/{matter_id}/statute-references",
            headers=headers,
            json={"section_id": section_id, "relevance": "context"},
        )
        assert rejected.status_code == 409, rejected.text
    saved = client.get(f"/api/matters/{matter_id}/statute-references", headers=headers)
    assert len(saved.json()["references"]) == 5
