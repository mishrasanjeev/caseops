"""BUG-010 / RAM05-STATUTES / FT-S1..S4: real edition completeness, not a sample seed."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import pytest
from sqlalchemy import func, select

from caseops_api.api.routes.statutes import StatuteSectionRecord, _is_selectable_statute_section
from caseops_api.db.models import Statute, StatuteSection, StatuteSourceVersion
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import official_statute_release as release
from caseops_api.scripts.seed_statutes import _seed
from tests.test_auth_company import auth_headers, bootstrap_company

VERIFIED = {
    "arbitration-1996": 104,
    "bns-2023": 358,
    "bnss-2023": 531,
    "companies-2013": 480,
    "cpc-1908": 158,
}


def test_official_documents_and_every_provision_have_complete_pinned_evidence():
    documents, sources = release.load_release_bundle()
    root = Path(__file__).resolve().parents[3] / "tests/fixtures/statutes/official"
    for act_id, document in documents.items():
        assert (
            hashlib.sha256((root / document["file"]).read_bytes()).hexdigest() == document["sha256"]
        )
        for evidence in document.get("treatment_evidence", {}).values():
            assert (
                hashlib.sha256((root / evidence["file"]).read_bytes()).hexdigest()
                == evidence["sha256"]
            )
        rows = [row for (act, _), row in sources.items() if act == act_id]
        assert len(rows) == release.EXPECTED_COUNTS[act_id]
        assert (
            sum(row["verification_status"] == "verified_official" for row in rows)
            == VERIFIED[act_id]
        )
        numbers = {row["section_number"] for row in rows}
        last = {
            "arbitration-1996": 87,
            "bns-2023": 358,
            "bnss-2023": 531,
            "companies-2013": 470,
            "cpc-1908": 158,
        }[act_id]
        assert {f"Section {number}" for number in range(1, last + 1)} <= numbers
        previous = None
        for row in rows:
            policy = row["source_policy"]
            fragments = policy["body_fragments"]
            assert fragments[0]["page"] == policy["official_pdf_page"]
            assert fragments[-1]["page"] == policy["official_pdf_end_page"]
            parts = row["section_text"].split("\n\n")
            assert len(parts) == len(fragments)
            for fragment, part in zip(fragments, parts, strict=True):
                assert hashlib.sha256(part.encode()).hexdigest() == fragment["text_sha256"]
                start = fragment["page"], fragment["first_line"]
                end = fragment["page"], fragment["end_line"]
                assert start < end
                if previous:
                    assert start >= previous
                    if start[0] == previous[0]:
                        assert start == previous
                previous = end
            assert row["source_url"].endswith(f"#page={fragments[0]['page']}")
            assert len(row["section_text"]) > 20
            assert row["effective_from"] is None  # No invented blanket commencement.
    bns_106 = sources["bns-2023", "Section 106"]
    assert "excludes section 106(2)" in bns_106["editorial_notes"]
    assert "#page=16" in bns_106["editorial_notes"]


@pytest.mark.parametrize(
    "defect",
    [
        "checksum",
        "missing",
        "duplicate",
        "wrong_act_url",
        "wrong_document",
        "text",
        "unsafe_enabled",
        "repealed_enabled",
        "retrieved_at",
        "wrong_version",
        "wrong_page",
    ],
)
def test_release_admission_rejects_tampered_or_incomplete_evidence(tmp_path, monkeypatch, defect):
    rows = json.loads(release.BUNDLE_PATH.read_text(encoding="utf-8"))
    if defect == "missing":
        rows.pop()
    elif defect == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif defect == "wrong_act_url":
        rows[0]["source_url"] = rows[110]["source_url"]
    elif defect == "wrong_document":
        rows[0]["source_document_sha256"] = "0" * 64
    elif defect == "text":
        rows[0]["section_text"] = "An invented legal rule."
    elif defect == "unsafe_enabled":
        next(row for row in rows if row["verification_status"] == "quarantined")[
            "verification_status"
        ] = "verified_official"
    elif defect == "repealed_enabled":
        next(row for row in rows if row["verification_status"] == "retired")[
            "verification_status"
        ] = "verified_official"
    elif defect == "retrieved_at":
        rows[0]["source_retrieved_at"] = "2099-01-01T00:00:00+00:00"
    elif defect == "wrong_version":
        rows[0]["exact_source_version"] = "Current law"
    elif defect == "wrong_page":
        rows[0]["source_policy"]["official_pdf_page"] = 1
    raw = json.dumps(rows)
    bundle = tmp_path / "bundle.json"
    checksum = tmp_path / "bundle.sha256"
    bundle.write_text(raw, encoding="utf-8")
    checksum.write_text(
        "0" * 64 if defect == "checksum" else hashlib.sha256(raw.encode()).hexdigest()
    )
    monkeypatch.setattr(release, "BUNDLE_PATH", bundle)
    monkeypatch.setattr(release, "CHECKSUM_PATH", checksum)
    with pytest.raises(ValueError):
        release.load_release_bundle()


def test_complete_release_seed_details_history_and_idempotence(client):
    token = str(bootstrap_company(client)["access_token"])
    documents, sources = release.load_release_bundle()
    with get_session_factory()() as session:
        _seed(session)
        rows = session.scalars(
            select(StatuteSection).where(StatuteSection.statute_id.in_(documents))
        ).all()
        before = {}
        counts = Counter()
        for row in rows:
            source = sources[row.statute_id, row.section_number]
            assert row.section_text == source["section_text"]
            assert row.source_sha256 == source["source_sha256"]
            assert row.section_url == source["source_url"]
            assert row.editorial_notes == source["editorial_notes"]
            assert row.verification_status == source["verification_status"]
            record = StatuteSectionRecord.model_validate(row)
            if source["verification_status"] == "verified_official":
                assert record.section_text == source["section_text"]
                assert _is_selectable_statute_section(row)
                counts[row.statute_id] += 1
            else:
                assert record.section_text is None
                assert not _is_selectable_statute_section(row)
            before[row.id] = (
                row.source_sha256,
                row.source_version,
                row.link_last_checked_at,
                row.verified_at,
                row.source_policy_json,
            )
        assert dict(counts) == VERIFIED
        history = session.scalars(select(StatuteSourceVersion)).all()
        history_before = {
            row.id: (row.section_id, row.proposed_source_version, row.candidate_sha256, row.status)
            for row in history
        }
        assert len(history_before) == len(sources) + 1  # Retain Article 14's existing owner.
        assert _seed(session)[::2] == (0, 0)
        session.expire_all()
        for row in session.scalars(
            select(StatuteSection).where(StatuteSection.statute_id.in_(documents))
        ):
            assert before[row.id] == (
                row.source_sha256,
                row.source_version,
                row.link_last_checked_at,
                row.verified_at,
                row.source_policy_json,
            )
        assert history_before == {
            row.id: (row.section_id, row.proposed_source_version, row.candidate_sha256, row.status)
            for row in session.scalars(select(StatuteSourceVersion))
        }
    headers = auth_headers(token)
    catalog = client.get("/api/statutes", headers=headers)
    assert catalog.status_code == 200, catalog.text
    listed = {row["id"]: row for row in catalog.json()["statutes"]}
    for act_id, expected in VERIFIED.items():
        assert listed[act_id]["section_count"] == expected
        assert listed[act_id]["catalog_section_count"] == release.EXPECTED_COUNTS[act_id]
        response = client.get(f"/api/statutes/{act_id}/sections", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data["sections"]) == expected
        assert data["statute"]["source_url"] == documents[act_id]["act_url"]
        for row in (
            data["sections"][0],
            data["sections"][len(data["sections"]) // 2],
            data["sections"][-1],
        ):
            response = client.get(
                f"/api/statutes/{act_id}/sections/{quote(row['section_number'])}", headers=headers
            )
            assert response.status_code == 200, response.text
            assert (
                response.json()["section"]["section_text"]
                == sources[act_id, row["section_number"]]["section_text"]
            )


def test_seed_preserves_reviewed_labels_and_pending_history_when_upgrading_legacy_rows(client):
    bootstrap_company(client)
    with get_session_factory()() as session:
        _seed(session)
        first = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "bnss-2023",
                StatuteSection.section_number == "Section 41",
            )
        )
        assert "Arrest by Magistrate" in first.section_text
        assert "Notice of appearance" not in first.section_label
        original = session.scalar(
            select(StatuteSourceVersion).where(StatuteSourceVersion.section_id == first.id)
        )
        pending = StatuteSourceVersion(
            **{
                column.name: getattr(original, column.name)
                for column in StatuteSourceVersion.__table__.columns
                if column.name not in {"id", "proposed_source_version", "status"}
            },
            proposed_source_version=2,
            status="pending",
        )
        session.add(pending)
        first.verification_status = "unverified"
        first.section_text = "Old incorrect catalog description"
        first.source_sha256 = None
        other = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "bns-2023",
                StatuteSection.section_number == "Section 63",
            )
        )
        other.section_label = "Independently reviewed label"
        other.exact_source_version = "Independent reviewed source version"
        session.commit()
        pending_id = pending.id
        _seed(session)
        session.expire_all()
        assert first.source_version == 3
        assert "Arrest by Magistrate" in first.section_text
        assert session.get(StatuteSourceVersion, pending_id).status == "pending"
        assert (
            session.scalar(
                select(func.count())
                .select_from(StatuteSourceVersion)
                .where(
                    StatuteSourceVersion.section_id == first.id,
                )
            )
            == 3
        )
        assert other.section_label == "Independently reviewed label"
        assert other.exact_source_version == "Independent reviewed source version"
        assert session.get(Statute, "bnss-2023").source_url.endswith("20099?view_type=browse")
