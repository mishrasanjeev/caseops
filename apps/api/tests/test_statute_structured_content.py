"""CAT-STRUCT-01..06: exact source cells, withheld content and bounded DTOs."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from caseops_api.api.routes.statutes import StatuteSectionRecord
from caseops_api.schemas.statute_content import StatuteTable
from caseops_api.scripts.official_statute_release import load_release_bundle


def table_fixture():
    cells = ["1", "Test fixture", "First line\nSecond line"]
    return {
        "title": "Synthetic table contract fixture",
        "columns": ["Number", "Name", "Detail"],
        "physical_row_count": 2,
        "rows": [
            {
                "serial": "1",
                "cells": cells,
                "sha256": hashlib.sha256(
                    json.dumps(cells, ensure_ascii=False).encode()
                ).hexdigest(),
                "fragments": [
                    {
                        "page": 1,
                        "bbox": [10, 20, 200, 80],
                        "cells": ["1", "Test fixture", "First line"],
                    },
                    {"page": 2, "bbox": [10, 20, 200, 40], "cells": ["", "", "Second line"]},
                ],
            }
        ],
    }


def test_structured_table_preserves_cells_and_split_page_provenance():
    source = table_fixture()
    validated = StatuteTable.model_validate(source)
    assert validated.model_dump(mode="json") == source


@pytest.mark.parametrize(
    "defect", ["hash", "fragment", "column", "duplicate", "physical_count", "bounds", "unknown"]
)
def test_structured_table_rejects_each_kind_of_changed_source_evidence(defect):
    table = table_fixture()
    if defect == "hash":
        table["rows"][0]["cells"][2] = "Changed"
    elif defect == "fragment":
        table["rows"][0]["fragments"][1]["cells"][2] = "Changed"
    elif defect == "column":
        table["columns"].pop()
    elif defect == "duplicate":
        table["rows"].append(deepcopy(table["rows"][0]))
    elif defect == "physical_count":
        table["physical_row_count"] = 1
    elif defect == "bounds":
        table["rows"][0]["fragments"][0]["bbox"] = [200, 20, 10, 80]
    else:
        table["rows"][0]["inferred_name"] = "Not source evidence"
    with pytest.raises(ValidationError):
        StatuteTable.model_validate(table)


@pytest.mark.parametrize("status", ["unverified", "quarantined", "retired", "verified_official"])
def test_public_dto_never_exposes_unverified_structured_content(status):
    source = table_fixture()
    record = StatuteSectionRecord(
        id="synthetic-section",
        statute_id="synthetic-statute",
        section_number="Schedule",
        section_label="Test table",
        section_text="Synthetic test text",
        verification_status=status,
        source_sha256="a" * 64,
        source_publisher="Test publisher",
        issuing_body="Test issuing body",
        source_retrieved_at=datetime.now(UTC),
        exact_source_version="Synthetic fixture v1",
        source_locator_type="section_deep_link",
        link_health_status="available",
        section_url="https://www.indiacode.nic.in/indiacode/bitstream/123456789/1791/5/a1985-61.pdf#page=46",
        source_policy_json={"structured_tables": [source]},
        parent_section_id=None,
        ordinal=1,
    )
    response = record.model_dump(mode="json")
    assert "source_policy_json" not in response
    assert response["structured_tables"] == ([source] if status == "verified_official" else [])
    assert (response["section_text"] is not None) == (status == "verified_official")


def test_real_ndps_and_specific_relief_tables_reconcile_every_physical_cell():
    _documents, sources = load_release_bundle()
    for act, logical, physical in [("ndps-1985", 162, 164), ("specific-relief-1963", 5, 5)]:
        table = StatuteTable.model_validate(
            sources[act, "Schedule"]["source_policy"]["structured_tables"][0]
        )
        assert len(table.rows) == logical
        assert table.physical_row_count == physical
    table = sources["ndps-1985", "Schedule"]["source_policy"]["structured_tables"][0]
    assert [
        (row["serial"], [f["page"] for f in row["fragments"]])
        for row in table["rows"]
        if len(row["fragments"]) > 1
    ] == [
        ("110C", [51, 52]),
        ("110ZS", [53, 54]),
    ]
    for number in ("43", "44"):
        row = sources["specific-relief-1963", f"Section {number}"]
        assert row["verification_status"] == "retired"
        assert row["source_policy"]["body_fragments"][0]["region"] == "publisher_notes"
        assert row["section_text"].startswith("2. Sections 43 and 44 rep.")


def test_complete_historical_source_is_distinct_from_an_omitted_provision():
    _documents, sources = load_release_bundle()
    for act, number in [("ipc-1860", "302"), ("iea-1872", "65B")]:
        row = sources[act, f"Section {number}"]
        assert row["verification_status"] == "verified_official"
        assert row["legal_status"] == "repealed"
        assert row["source_policy"]["edition_scope"] == "historical_repealed_law"
        assert "relevant" in row["editorial_notes"]
    assert sources["iea-1872", "Section 2"]["verification_status"] == "retired"


def test_separate_ip_act_pack_is_not_catalogue_or_domain_activation():
    from caseops_api.scripts.official_statute_release import DATA

    manifest = json.loads((DATA / "verified_ip_statute_documents.json").read_text())
    rows = json.loads((DATA / "verified_ip_statute_sources.json").read_text())
    raw = (DATA / "verified_ip_statute_sources.json").read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == (DATA / "verified_ip_statute_sources.sha256").read_text().strip()
    )
    assert manifest["activation_status"] == "not_activated"
    assert len(rows) == 329
    assert sum(row["verification_status"] == "verified_official" for row in rows) == 305
    assert sum(row["verification_status"] == "retired" for row in rows) == 24
    _, admitted = load_release_bundle()
    assert not set(row["statute_id"] for row in rows) & set(act for act, _ in admitted)
