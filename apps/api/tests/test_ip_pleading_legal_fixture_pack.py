from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from caseops_api.services.drafting_targets import TRADEMARK_PLEADING_TEMPLATES
from caseops_api.services.ip_draft_validation import validate_ip_context_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_PATH = (
    REPO_ROOT
    / "docs"
    / "ip-implementation"
    / "fixtures"
    / "m4"
    / "IPLF-047"
    / "trademark-pleading-fixtures-v1.json"
)
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_ip_pleading_legal_fixtures.py"
SPEC = importlib.util.spec_from_file_location("ip_pleading_legal_fixtures", SCRIPT_PATH)
assert SPEC and SPEC.loader
ip_pleading_legal_fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip_pleading_legal_fixtures)


def _pack() -> dict:
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def _fixture(fixture_id: str) -> dict:
    return next(row for row in _pack()["fixtures"] if row["id"] == fixture_id)


def test_candidate_pack_is_structurally_valid_but_not_authoritative() -> None:
    pack = _pack()

    assert ip_pleading_legal_fixtures.validate_pack(pack) == []
    errors = ip_pleading_legal_fixtures.validate_pack(pack, require_approved=True)

    assert errors
    assert "pack is not approved" in errors
    assert sum("is not approved" in error for error in errors) == len(pack["fixtures"]) + 1
    assert pack["authoritative_activation_allowed"] is False
    assert all(row["expected_legal_outcome"] is None for row in pack["fixtures"])


def test_candidate_pack_hashes_detect_content_and_approval_tampering() -> None:
    pack = _pack()
    tampered = copy.deepcopy(pack)
    tampered["fixtures"][0]["synthetic_inputs"]["mark"] = "TAMPERED MARK"

    errors = ip_pleading_legal_fixtures.validate_pack(tampered)

    assert "fixtures[0].content_sha256 does not match canonical content" in errors
    assert "content_sha256 does not match canonical pack content" in errors

    forged = copy.deepcopy(pack)
    forged["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "reviewer-1",
            "legal_approved_by": "lawyer-1",
            "approved_at": "2026-08-24T04:00:00+05:30",
            "source_review_completed_at": "2026-08-24T03:59:00+05:30",
            "approved_content_sha256": "0" * 64,
        }
    )
    forged_errors = ip_pleading_legal_fixtures.validate_pack(forged)
    assert "pack.approval hash does not match immutable content" in forged_errors


def test_exact_hash_approved_pack_can_pass_authoritative_gate() -> None:
    pack = copy.deepcopy(_pack())
    pack["legal_content_status"] = "approved"
    pack["authoritative_activation_allowed"] = True
    for source in pack["official_sources"]:
        source["review_status"] = "lawyer_reviewed"
    for fixture in pack["fixtures"]:
        fixture["legal_content_status"] = "approved"
        fixture["expected_legal_outcome"] = {
            "reviewed_result": "Qualified legal SME supplied expectation"
        }
        fixture["content_sha256"] = ip_pleading_legal_fixtures.fixture_content_sha256(
            fixture
        )
        fixture["approval"].update(
            {
                "status": "approved",
                "reviewed_by": "independent-reviewer",
                "legal_approved_by": "qualified-legal-sme",
                "approved_at": "2026-08-24T04:00:00+05:30",
                "source_review_completed_at": "2026-08-24T03:59:00+05:30",
                "approved_content_sha256": fixture["content_sha256"],
            }
        )
    pack["content_sha256"] = ip_pleading_legal_fixtures.pack_content_sha256(pack)
    pack["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "independent-reviewer",
            "legal_approved_by": "qualified-legal-sme",
            "approved_at": "2026-08-24T04:00:00+05:30",
            "source_review_completed_at": "2026-08-24T03:59:00+05:30",
            "approved_content_sha256": pack["content_sha256"],
        }
    )

    assert ip_pleading_legal_fixtures.validate_pack(pack, require_approved=True) == []


def test_candidate_date_conflict_fixture_uses_canonical_validator() -> None:
    fixture = _fixture("IP-PLEADING-GOLDEN-003")
    context = fixture["synthetic_inputs"]["context_manifest"]

    findings = validate_ip_context_manifest(
        context,
        template_key=fixture["scope"]["template_keys"][0],
    )
    blocker_codes = {row.code for row in findings if row.severity == "blocker"}
    warning_codes = {row.code for row in findings if row.severity == "warning"}

    assert blocker_codes == set(fixture["expected_software_behavior"]["blocker_codes"])
    assert warning_codes == set(fixture["expected_software_behavior"]["warning_codes"])


def test_candidate_template_matrix_matches_canonical_catalog() -> None:
    fixture = _fixture("IP-PLEADING-GOLDEN-006")
    expected_matrix = fixture["synthetic_inputs"]["expected_matrix"]

    assert set(TRADEMARK_PLEADING_TEMPLATES) == set(expected_matrix)
    for key, expected in expected_matrix.items():
        template = TRADEMARK_PLEADING_TEMPLATES[key]
        assert sorted(template.sides) == expected["sides"]
        assert sorted(template.stages) == expected["stages"]
        assert template.jurisdictions == frozenset({fixture["scope"]["jurisdiction"]})
        assert template.format_profile == fixture["expected_software_behavior"][
            "format_profile"
        ]
