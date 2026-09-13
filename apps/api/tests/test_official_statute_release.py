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
    "crpc-1973": 594,
    "ni-act-1881": 154,
    "limitation-1963": 31,
    "bsa-2023": 171,
    "arbitration-1996": 112,
    "bns-2023": 358,
    "bnss-2023": 591,
    "companies-2013": 480,
    "cpc-1908": 158,
    "hindu-marriage-1955": 35,
    "prevention-of-corruption-1988": 33,
    "rti-2005": 33,
    "gst-cgst-2017": 190,
    "transfer-of-property-1882": 136,
    "contract-1872": 192,
    "consumer-protection-2019": 107,
    "ndps-1985": 129,
    "iea-1872": 184,
    "specific-relief-1963": 47,
    "ipc-1860": 554,
}


@pytest.mark.parametrize(
    "label",
    ["[Repealed.]", "Repealed.]", "[Omitted.].", "[Repealed].", "[Repealed.] Enactments repealed"],
)
def test_publisher_omission_punctuation_cannot_enable_retired_text(label):
    assert release.is_omitted_arrangement(label)


@pytest.mark.parametrize(
    "label", ["Repeal and savings.", "Power to repeal rules.", "Enactments repealed."]
)
def test_repeal_power_is_not_itself_a_repealed_provision(label):
    assert not release.is_omitted_arrangement(label)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.indiacode.nic.in/indiacode/repealedfileopen?rfilename=A1872-1.pdf",
        "https://www.indiacode.nic.in/indiacode/bitstream/123456789/2065/1/aa2005.pdf",
    ],
)
def test_reviewed_official_download_contract_accepts_live_and_retained_editions(url):
    assert release._official_document_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.indiacode.nic.in/indiacode/repealedfileopen?rfilename=A1872-1.pdf",
        "https://example.com/indiacode/repealedfileopen?rfilename=A1872-1.pdf",
        "https://user:secret@www.indiacode.nic.in/indiacode/repealedfileopen?rfilename=A1872-1.pdf",
        "https://www.indiacode.nic.in/indiacode/repealedfileopen?rfilename=../A1872-1.pdf",
        "https://www.indiacode.nic.in/indiacode/repealedfileopen?rfilename=A1872-1.pdf&redirect=evil",
        "https://www.indiacode.nic.in/indiacode/repealedfileopen?rfilename=A1872-1.pdf&rfilename=A1860-45.pdf",
        "https://www.indiacode.nic.in/indiacode/bitstream/123456789/2065/1/aa2005.pdf?redirect=evil",
    ],
)
def test_download_contract_does_not_allow_arbitrary_query_or_publisher(url):
    assert not release._official_document_url(url)


@pytest.mark.parametrize(
    "defect", ["outside", "unknown_parent", "missing_child", "self", "kind", "duplicate"]
)
def test_supplement_inventory_rejects_incomplete_or_foreign_lineage(defect):
    entries = [
        {
            "key": "schedule",
            "kind": "schedule",
            "section_number": "Schedule",
            "span_through_key": "form_1",
        },
        {"key": "form_1", "kind": "form", "section_number": "Form 1", "parent_key": "schedule"},
        {"key": "appendix", "kind": "appendix", "section_number": "Appendix"},
    ]
    if defect == "outside":
        entries[-1]["parent_key"] = "schedule"
    elif defect == "unknown_parent":
        entries[1]["parent_key"] = "different_schedule"
    elif defect == "missing_child":
        entries[0]["span_through_key"] = "missing_form"
    elif defect == "self":
        entries[0]["span_through_key"] = "schedule"
    elif defect == "kind":
        entries[1]["kind"] = "invented"
    else:
        entries.append(deepcopy(entries[1]))
    with pytest.raises(ValueError):
        release._supplement_inventory({"supplements": entries})


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
            "crpc-1973": 484,
            "ni-act-1881": 148,
            "limitation-1963": 32,
            "bsa-2023": 170,
            "arbitration-1996": 87,
            "bns-2023": 358,
            "bnss-2023": 531,
            "companies-2013": 470,
            "cpc-1908": 158,
            "hindu-marriage-1955": 30,
            "prevention-of-corruption-1988": 31,
            "rti-2005": 31,
            "gst-cgst-2017": 174,
            "transfer-of-property-1882": 137,
            "contract-1872": 266,
            "consumer-protection-2019": 107,
            "ndps-1985": 83,
            "iea-1872": 167,
            "specific-relief-1963": 44,
            "ipc-1860": 511,
        }[act_id]
        assert {f"Section {number}" for number in range(1, last + 1)} <= numbers
        previous = None
        for row in rows:
            policy = row["source_policy"]
            fragments = policy["body_fragments"]
            parent_number = policy.get("parent_provision")
            local_previous = None
            if parent_number:
                parent = sources[act_id, parent_number]
                parent_fragments = parent["source_policy"]["body_fragments"]
                assert row["section_text"] in parent["section_text"]
                assert (fragments[0]["page"], fragments[0]["first_line"]) >= (
                    parent_fragments[0]["page"],
                    parent_fragments[0]["first_line"],
                )
                assert (fragments[-1]["page"], fragments[-1]["end_line"]) <= (
                    parent_fragments[-1]["page"],
                    parent_fragments[-1]["end_line"],
                )
            assert fragments[0]["page"] == policy["official_pdf_page"]
            assert fragments[-1]["page"] == policy["official_pdf_end_page"]
            parts = row["section_text"].split("\n\n")
            assert len(parts) == len(fragments)
            for fragment, part in zip(fragments, parts, strict=True):
                assert hashlib.sha256(part.encode()).hexdigest() == fragment["text_sha256"]
                if fragment.get("region") == "publisher_notes":
                    evidence = document["omission_evidence"][
                        row["section_number"].removeprefix("Section ")
                    ]
                    assert row["verification_status"] == "retired"
                    assert part == evidence["text"]
                    assert fragment["page"] == evidence["page"]
                    assert fragment["first_line"] == evidence["first_line"]
                    assert fragment["end_line"] == evidence["end_line"]
                    continue
                start = fragment["page"], fragment["first_line"]
                end = fragment["page"], fragment["end_line"]
                assert start < end
                prior = local_previous if parent_number else previous
                if prior:
                    assert start >= prior
                    if start[0] == prior[0]:
                        assert start == prior
                local_previous = end
                if not parent_number:
                    previous = end
            assert row["source_url"].endswith(f"#page={fragments[0]['page']}")
            assert len(row["section_text"]) > 20
            assert row["effective_from"] is None  # No invented blanket commencement.
    bns_106 = sources["bns-2023", "Section 106"]
    assert "excludes section 106(2)" in bns_106["editorial_notes"]
    assert "#page=16" in bns_106["editorial_notes"]
    last_bns = sources["bns-2023", "Section 358"]
    assert last_bns["source_policy"]["official_pdf_end_page"] == 111
    assert "(4) The mention of particular matters" in last_bns["section_text"]
    assert "STATEMENT OF OBJECTS AND REASONS" not in last_bns["section_text"]


def test_bsa_complete_schedule_and_final_section_are_separate_source_units():
    documents, sources = release.load_release_bundle()
    section = sources["bsa-2023", "Section 170"]
    schedule = sources["bsa-2023", "Schedule"]
    assert "THE SCHEDULE" not in section["section_text"]
    assert schedule["section_text"].startswith("THE SCHEDULE\n")
    assert "PART A" in schedule["section_text"] and "PART B" in schedule["section_text"]
    assert "STATEMENT OF OBJECTS AND REASONS" not in schedule["section_text"]
    assert schedule["source_policy"]["provision_kind"] == "schedule"
    assert schedule["source_policy"]["official_pdf_page"] == 52
    assert schedule["source_policy"]["official_pdf_end_page"] == 53
    assert schedule["verification_status"] == "verified_official"
    assert documents["bsa-2023"]["act_url"].endswith("20063?view_type=browse")


def test_crpc_inherited_admission_retains_forms_and_withholds_unreconciled_tables():
    documents, sources = release.load_release_bundle()
    assert documents["crpc-1973"]["act_url"] == documents["crpc-1973"]["source_url"]
    parent = sources["crpc-1973", "Second Schedule"]
    assert len(parent["source_policy"]["contains_provisions"]) == 57
    assert parent["source_policy"]["official_pdf_end_page"] == 260
    assert "APPENDIX" not in parent["section_text"]
    final = sources["crpc-1973", "Second Schedule Form 56"]
    assert final["section_text"] in parent["section_text"]
    assert sources["crpc-1973", "Section 482"]["verification_status"] == "verified_official"
    assert sources["crpc-1973", "First Schedule"]["verification_status"] == "quarantined"
    for document in documents.values():
        for item in document.get("supplements", []):
            reason = document.get("blocked_supplements", {}).get(item["key"])
            if reason:
                row = sources[document["statute_id"], item["section_number"]]
                assert row["verification_status"] == "quarantined"
                assert row["quarantine_reason"] == reason
                assert row["section_text"]


def test_additional_editions_reconcile_schedules_and_inserted_provisions():
    _documents, sources = release.load_release_bundle()
    schedule = sources["limitation-1963", "Schedule"]
    assert schedule["source_policy"]["official_pdf_page"] == 12
    assert schedule["source_policy"]["official_pdf_end_page"] == 24
    assert "Description of suit" in schedule["section_text"]
    assert "Period of limitation" in schedule["section_text"]
    assert "137. Any other application" in schedule["section_text"]
    assert "THE SCHEDULE" not in sources["limitation-1963", "Section 32"]["section_text"]
    for number in ("138", "142A", "143A", "148"):
        row = sources["ni-act-1881", f"Section {number}"]
        assert row["verification_status"] == "verified_official"
    retired_schedule = sources["ni-act-1881", "Schedule"]
    assert retired_schedule["verification_status"] == "retired"
    assert retired_schedule["legal_status"] == "repealed"
    assert "1891" in retired_schedule["section_text"]
    assert "SCHEDULE" not in sources["ni-act-1881", "Section 148"]["section_text"]


def test_bnss_every_form_is_complete_and_retained_in_the_complete_second_schedule():
    documents, sources = release.load_release_bundle()
    parent = sources["bnss-2023", "Second Schedule"]
    forms = parent["source_policy"]["contains_provisions"]
    assert forms == [f"Second Schedule - Form {number}" for number in range(1, 59)]
    assert parent["source_policy"]["official_pdf_page"] == 222
    assert parent["source_policy"]["official_pdf_end_page"] == 281
    for number in forms:
        form = sources["bnss-2023", number]
        assert form["section_text"] in parent["section_text"]
        assert form["source_policy"]["parent_provision"] == "Second Schedule"
        assert form["source_policy"]["provision_kind"] == "form"
        assert form["verification_status"] == "verified_official"
    first = sources["bnss-2023", "First Schedule"]
    assert "CLASSIFICATION OF OFFENCES" in first["section_text"]
    assert first["source_policy"]["official_pdf_end_page"] == 221
    assert "FORM No. 1" not in sources["bnss-2023", "Section 1"]["section_text"]
    assert "STATEMENT OF OBJECTS AND REASONS" not in parent["section_text"]
    assert documents["bnss-2023"]["non_provision_pages"][-1]["pages"] == [282, 282]


def test_contract_malformed_repeal_marker_and_complete_label_are_preserved():
    _, sources = release.load_release_bundle()
    retired = sources["contract-1872", "Section 90"]
    assert retired["source_policy"]["arrangement_label"] == "Repealed.]."
    assert retired["verification_status"] == "retired"
    assert retired["legal_status"] == "repealed"
    assert "[Delivery how made.]" in retired["section_text"]
    section = sources["contract-1872", "Section 1"]
    assert "Extent." in section["section_label"]
    assert "Commencement." in section["section_label"]
    assert "Saving" in section["section_label"]
    assert "This Act may be called the Indian Contract Act, 1872" in section["section_text"]


def test_arbitration_all_schedules_and_appendix_are_distinct_complete_sources():
    _, sources = release.load_release_bundle()
    names = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth"]
    for name in names:
        row = sources["arbitration-1996", f"{name} Schedule"]
        assert row["source_policy"]["provision_kind"] == "schedule"
        assert "STATEMENT OF OBJECTS AND REASONS" not in row["section_text"]
    assert sources["arbitration-1996", "Eighth Schedule"]["verification_status"] == "retired"
    assert sources["arbitration-1996", "Appendix"]["source_policy"]["official_pdf_end_page"] == 53


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
        "schedule_kind",
        "schedule_heading",
        "schedule_page",
        "historical_scope",
        "table_cell",
        "table_missing",
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
    elif defect == "historical_scope":
        historical = next(
            row
            for row in rows
            if row["statute_id"] == "ipc-1860" and row["verification_status"] == "verified_official"
        )
        historical["source_policy"]["edition_scope"] = True
    elif defect.startswith("table_"):
        schedule = next(
            row
            for row in rows
            if row["statute_id"] == "ndps-1985" and row["section_number"] == "Schedule"
        )
        if defect == "table_missing":
            schedule["source_policy"]["structured_tables"] = []
        else:
            schedule["source_policy"]["structured_tables"][0]["rows"][0]["cells"][1] = (
                "Synthetic changed cell"
            )
    elif defect.startswith("schedule_"):
        schedule = next(
            row
            for row in rows
            if row["statute_id"] == "bsa-2023" and row["section_number"] == "Schedule"
        )
        if defect == "schedule_kind":
            schedule["source_policy"]["provision_kind"] = "section"
        elif defect == "schedule_page":
            schedule["source_policy"]["official_pdf_page"] = 51
            schedule["source_url"] = schedule["source_url"].replace("#page=52", "#page=51")
        else:
            schedule["section_text"] = "Wrong schedule\n" + schedule["section_text"]
            schedule["source_sha256"] = hashlib.sha256(
                schedule["section_text"].encode()
            ).hexdigest()
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
            if row.section_number in documents[row.statute_id].get(
                "retained_legacy_placeholders", []
            ):
                assert (row.statute_id, row.section_number) not in sources
                assert row.section_text is None
                assert row.verification_status == "unverified"
                assert not _is_selectable_statute_section(row)
                continue
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
            if row.section_number in documents[row.statute_id].get(
                "retained_legacy_placeholders", []
            ):
                assert row.section_text is None
                assert row.verification_status == "unverified"
                continue
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
        assert listed[act_id]["catalog_section_count"] == release.EXPECTED_COUNTS[act_id] + len(
            documents[act_id].get("retained_legacy_placeholders", [])
        )
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
    bootstrap = bootstrap_company(client)
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
        other.verified_by_membership_id = str(bootstrap["membership"]["id"])
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


def test_seed_reconciles_stale_release_manifest_rows_without_a_human_reviewer(client):
    bootstrap_company(client)
    _, sources = release.load_release_bundle()
    with get_session_factory()() as session:
        _seed(session)
        row = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "bnss-2023",
                StatuteSection.section_number == "Section 191",
            )
        )
        expected = sources["bnss-2023", "Section 191"]
        row.section_label = str(expected["section_label"])[:-12]
        row.section_text = "Stale first-release text"
        row.source_sha256 = hashlib.sha256(row.section_text.encode()).hexdigest()
        row.verified_by_membership_id = None
        session.commit()

        _seed(session)
        session.expire_all()
        session.refresh(row)
        assert row.section_label == expected["section_label"]
        assert row.section_text == expected["section_text"]
        assert row.source_sha256 == expected["source_sha256"]
        assert row.source_version == 2
        assert session.scalar(
            select(func.count()).select_from(StatuteSourceVersion).where(
                StatuteSourceVersion.section_id == row.id,
            )
        ) == 2


def test_seed_reconciles_only_legacy_ai_quarantine_with_official_release(client):
    bootstrap_company(client)
    documents, sources = release.load_release_bundle()
    with get_session_factory()() as session:
        _seed(session)
        row = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "ipc-1860",
                StatuteSection.section_number == "Section 74",
            )
        )
        assert row is not None
        row.verification_status = "quarantined"
        row.quarantine_reason = "AI-generated legal text is not authoritative"
        row.section_text_source = "haiku_generated"
        row.section_text = "Legacy generated text that must not be served."
        row.source_sha256 = hashlib.sha256(row.section_text.encode()).hexdigest()
        row.is_provisional = True
        session.commit()

        _seed(session)
        session.expire_all()
        session.refresh(row)
        expected = sources["ipc-1860", "Section 74"]
        assert row.verification_status == "verified_official"
        assert row.section_text == expected["section_text"]
        assert row.source_sha256 == expected["source_sha256"]
        assert row.section_text_source == "official_release_manifest"
        assert row.quarantine_reason is None
        assert row.quarantined_at is None
        assert row.verified_at is not None
        assert row.section_url == expected["source_url"]
        assert row.statute_id in documents


@pytest.mark.parametrize("defect", ["unknown", "changed_text", "missing"])
def test_legacy_placeholder_exception_never_admits_unreconciled_source_rows(
    tmp_path, monkeypatch, defect
):
    from caseops_api.scripts import seed_statutes

    seeds = json.loads(seed_statutes.SEED_PATH.read_text(encoding="utf-8"))
    act = next(row for row in seeds if row["id"] == "ndps-1985")
    placeholder = next(row for row in act["sections"] if row["section_number"] == "Section 89")
    if defect == "unknown":
        placeholder["section_number"] = "Section 90"
    elif defect == "changed_text":
        placeholder["section_text"] = "Synthetic nonempty fixture, not statutory text."
    else:
        act["sections"].remove(placeholder)
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps(seeds), encoding="utf-8")
    monkeypatch.setattr(seed_statutes, "SEED_PATH", path)
    with pytest.raises(ValueError, match="orphan a seeded provision identity"):
        _seed(None)  # Rejection must precede every database write.
