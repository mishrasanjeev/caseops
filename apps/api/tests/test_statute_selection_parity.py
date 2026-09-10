"""RAM10-STATUTES / BUG013: usable inventories and direct writes agree."""

from datetime import UTC, datetime

from sqlalchemy import select

from caseops_api.api.routes.statutes import (
    _is_selectable_statute_section,
    _selectable_statute_section_sql,
)
from caseops_api.db.models import Statute, StatuteSection
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.official_statute_release import load_release_bundle
from caseops_api.scripts.seed_statutes import _apply_verified_release_source
from tests.test_auth_company import auth_headers, bootstrap_company


def test_empty_provenance_cannot_inflate_catalogue_or_allow_attachment(client):
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    _, sources = load_release_bundle()
    source = sources["bsa-2023", "Section 63"]
    with get_session_factory()() as session:
        session.add(Statute(
            id="bsa-2023", short_name="BSA", long_name="Bharatiya Sakshya Adhiniyam, 2023",
        ))
        session.flush()
        row = StatuteSection(statute_id="bsa-2023", section_number="Section 63", ordinal=1)
        assert _apply_verified_release_source(row, source, now=datetime.now(UTC))
        session.add(row)
        session.commit()
        section_id = row.id
    matter = client.post("/api/matters/", headers=headers, json={
        "title": "September 10 statutory reference parity", "matter_code": "RAM10-PARITY",
        "practice_area": "Civil", "forum_level": "high_court",
    })
    assert matter.status_code == 200, matter.text
    references_url = f"/api/matters/{matter.json()['id']}/statute-references"

    def counts(expected):
        catalog = client.get("/api/statutes/", headers=headers)
        assert catalog.status_code == 200, catalog.text
        record = next(item for item in catalog.json()["statutes"] if item["id"] == "bsa-2023")
        assert record["section_count"] == expected
        assert record["catalog_section_count"] == 1
        sections = client.get("/api/statutes/bsa-2023/sections", headers=headers)
        assert sections.status_code == 200, sections.text
        assert sections.json()["verified_section_count"] == expected
        assert len(sections.json()["sections"]) == expected

    counts(1)
    attached = client.post(
        references_url, headers=headers, json={"section_id": section_id, "relevance": "cited"},
    )
    assert attached.status_code == 201, attached.text
    saved = client.get(references_url, headers=headers)
    assert saved.json()["references"][0]["section_id"] == section_id

    defects = [(field, value) for field in (
        "section_text", "source_sha256", "source_publisher", "issuing_body", "exact_source_version",
    ) for value in ("", None)]
    defects += [("verification_status", "unverified"), ("verification_status", "quarantined"),
                ("verification_status", "retired"), ("source_locator_type", "act_landing_page"),
                ("link_health_status", "broken"), ("section_text_fetched_at", None)]
    for field, value in defects:
        with get_session_factory()() as session:
            row = session.get(StatuteSection, section_id)
            prior = getattr(row, field)
            setattr(row, field, value)
            session.commit()
            assert not _is_selectable_statute_section(row), (field, value)
            assert session.scalar(select(StatuteSection.id).where(
                StatuteSection.id == section_id, _selectable_statute_section_sql(),
            )) is None, (field, value)
        counts(0)
        denied = client.post(
            references_url, headers=headers,
            json={"section_id": section_id, "relevance": "context"},
        )
        assert denied.status_code == 409, (field, value, denied.text)
        assert len(client.get(references_url, headers=headers).json()["references"]) == 1
        with get_session_factory()() as session:
            setattr(session.get(StatuteSection, section_id), field, prior)
            session.commit()
    counts(1)
