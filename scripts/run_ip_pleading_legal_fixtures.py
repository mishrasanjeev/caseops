#!/usr/bin/env python3
"""Validate the IPLF-047 trademark pleading legal-fixture pack.

The committed pack contains synthetic candidate fixtures. Structural validation
is suitable for CI; ``--require-approved`` is the fail-closed activation gate
and cannot pass until qualified human reviewers approve the exact content hash.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    REPO_ROOT
    / "docs"
    / "ip-implementation"
    / "fixtures"
    / "m4"
    / "IPLF-047"
    / "trademark-pleading-fixtures-v1.json"
)
SCHEMA_VERSION = "caseops.ip-pleading-legal-fixtures/v1"
REQUIRED_REQUIREMENTS = {f"IP-DRAFT-{number:02d}" for number in range(1, 11)}
REQUIRED_JOURNEY_PATHS = {
    "UJ-24-NORMAL",
    "UJ-24-EXC-01",
    "UJ-24-EXC-02",
    "UJ-24-EXC-03",
}
REQUIRED_CATEGORIES = {"positive", "negative", "boundary"}
REQUIRED_TEMPLATES = {
    "trademark_opposition_notice",
    "trademark_counterstatement",
    "trademark_opponent_evidence",
    "trademark_applicant_evidence",
    "trademark_reply_evidence",
}
ALLOWED_APPROVAL_STATUSES = {"pending_lawyer_review", "approved", "retired"}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
HTTPS_RE = re.compile(r"^https://", re.IGNORECASE)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _fixture_content(fixture: dict[str, Any]) -> dict[str, Any]:
    content = copy.deepcopy(fixture)
    content.pop("content_sha256", None)
    content.pop("approval", None)
    return content


def fixture_content_sha256(fixture: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_fixture_content(fixture)).encode()).hexdigest()


def _pack_content(pack: dict[str, Any]) -> dict[str, Any]:
    content = copy.deepcopy(pack)
    content.pop("content_sha256", None)
    content.pop("approval", None)
    fixtures = content.get("fixtures")
    if isinstance(fixtures, list):
        content["fixtures"] = [_fixture_content(row) for row in fixtures]
    return content


def pack_content_sha256(pack: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_pack_content(pack)).encode()).hexdigest()


def _validate_approval(
    approval: object,
    *,
    content_hash: str,
    path: str,
    require_approved: bool,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(approval, dict):
        return [f"{path}.approval must be an object"]
    status = approval.get("status")
    if status not in ALLOWED_APPROVAL_STATUSES:
        errors.append(f"{path}.approval.status is invalid")
        return errors
    if require_approved and status != "approved":
        errors.append(f"{path} is not approved")
    if status != "approved":
        if approval.get("approved_content_sha256") is not None:
            errors.append(f"{path} pending/retired approval cannot carry an approved hash")
        return errors

    approved_hash = approval.get("approved_content_sha256")
    if approved_hash != content_hash:
        errors.append(f"{path}.approval hash does not match immutable content")
    proposer = str(approval.get("proposed_by") or "").strip()
    reviewer = str(approval.get("reviewed_by") or "").strip()
    legal_approver = str(approval.get("legal_approved_by") or "").strip()
    if not all((proposer, reviewer, legal_approver)):
        errors.append(f"{path}.approval requires proposer, reviewer, and legal approver")
    if len({proposer, reviewer, legal_approver}) != 3:
        errors.append(f"{path}.approval actors must be three distinct identities")
    if not approval.get("approved_at"):
        errors.append(f"{path}.approval.approved_at is required")
    if not approval.get("source_review_completed_at"):
        errors.append(f"{path}.approval.source_review_completed_at is required")
    return errors


def _validate_test_ref(reference: object, *, path: str) -> list[str]:
    if not isinstance(reference, str) or "::" not in reference:
        return [f"{path} must be a pytest node reference"]
    file_ref, test_name = reference.split("::", 1)
    test_path = REPO_ROOT / file_ref
    if not test_path.is_file():
        return [f"{path} points to missing file {file_ref}"]
    if not re.fullmatch(r"test_[a-zA-Z0-9_]+", test_name):
        return [f"{path} has an invalid pytest test name"]
    if f"def {test_name}(" not in test_path.read_text(encoding="utf-8"):
        return [f"{path} points to missing test {test_name}"]
    return []


def validate_pack(pack: object, *, require_approved: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(pack, dict):
        return ["Fixture pack must be a JSON object"]
    if pack.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if not re.fullmatch(r"IPLF-047-[A-Z0-9-]+", str(pack.get("pack_id") or "")):
        errors.append("pack_id must be an IPLF-047 identifier")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(pack.get("version") or "")):
        errors.append("version must use semantic versioning")
    if pack.get("authoritative_activation_allowed") is not False:
        errors.append("committed candidate pack must deny authoritative activation")

    sources = pack.get("official_sources")
    if not isinstance(sources, list) or not sources:
        errors.append("official_sources must be a non-empty list")
        sources = []
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        path = f"official_sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{path} must be an object")
            continue
        source_id = str(source.get("id") or "")
        if not source_id or source_id in source_ids:
            errors.append(f"{path}.id must be non-empty and unique")
        source_ids.add(source_id)
        if not HTTPS_RE.match(str(source.get("url") or "")):
            errors.append(f"{path}.url must use HTTPS")
        if not SHA256_RE.fullmatch(str(source.get("sha256") or "")):
            errors.append(f"{path}.sha256 must be an exact SHA-256")
        if not source.get("retrieved_at"):
            errors.append(f"{path}.retrieved_at is required")

    fixtures = pack.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        errors.append("fixtures must be a non-empty list")
        fixtures = []
    fixture_ids: set[str] = set()
    categories: set[str] = set()
    requirements: set[str] = set()
    journey_paths: set[str] = set()
    templates: set[str] = set()
    all_test_refs: list[tuple[str, str]] = []
    approved_count = 0
    for index, fixture in enumerate(fixtures):
        path = f"fixtures[{index}]"
        if not isinstance(fixture, dict):
            errors.append(f"{path} must be an object")
            continue
        fixture_id = str(fixture.get("id") or "")
        if not re.fullmatch(r"IP-PLEADING-GOLDEN-\d{3}", fixture_id):
            errors.append(f"{path}.id must match IP-PLEADING-GOLDEN-NNN")
        if fixture_id in fixture_ids:
            errors.append(f"{path}.id must be unique")
        fixture_ids.add(fixture_id)
        category = str(fixture.get("category") or "")
        if category not in REQUIRED_CATEGORIES:
            errors.append(f"{path}.category is invalid")
        categories.add(category)
        if fixture.get("data_classification") != "synthetic_anonymized":
            errors.append(f"{path} must remain synthetic_anonymized")
        if fixture.get("legal_content_status") != "candidate_unapproved":
            errors.append(f"{path} must remain candidate_unapproved in source control")

        scope = fixture.get("scope")
        if not isinstance(scope, dict):
            errors.append(f"{path}.scope must be an object")
            scope = {}
        if scope.get("jurisdiction") != "IN":
            errors.append(f"{path}.scope.jurisdiction must be IN")
        template_keys = scope.get("template_keys")
        if not isinstance(template_keys, list) or not template_keys:
            errors.append(f"{path}.scope.template_keys must be non-empty")
            template_keys = []
        templates.update(str(value) for value in template_keys)

        fixture_requirements = set(fixture.get("requirement_ids") or [])
        unknown_requirements = fixture_requirements - REQUIRED_REQUIREMENTS
        if unknown_requirements:
            errors.append(f"{path} has unknown requirements {sorted(unknown_requirements)}")
        requirements.update(fixture_requirements)
        fixture_paths = set(fixture.get("journey_path_ids") or [])
        unknown_paths = fixture_paths - REQUIRED_JOURNEY_PATHS
        if unknown_paths:
            errors.append(f"{path} has unknown journey paths {sorted(unknown_paths)}")
        journey_paths.update(fixture_paths)

        source_refs = fixture.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            errors.append(f"{path}.source_refs must be non-empty")
            source_refs = []
        missing_sources = set(source_refs) - source_ids
        if missing_sources:
            errors.append(f"{path} references unknown sources {sorted(missing_sources)}")

        expected = fixture.get("expected_software_behavior")
        if not isinstance(expected, dict) or not expected:
            errors.append(f"{path}.expected_software_behavior must be non-empty")
        if fixture.get("expected_legal_outcome") is not None:
            errors.append(f"{path}.expected_legal_outcome must stay null before SME approval")

        calculated_hash = fixture_content_sha256(fixture)
        if fixture.get("content_sha256") != calculated_hash:
            errors.append(f"{path}.content_sha256 does not match canonical content")
        errors.extend(
            _validate_approval(
                fixture.get("approval"),
                content_hash=calculated_hash,
                path=path,
                require_approved=require_approved,
            )
        )
        approval = fixture.get("approval")
        if isinstance(approval, dict) and approval.get("status") == "approved":
            approved_count += 1

        test_refs = fixture.get("automation_test_refs")
        if not isinstance(test_refs, list) or not test_refs:
            errors.append(f"{path}.automation_test_refs must be non-empty")
            test_refs = []
        for ref_index, reference in enumerate(test_refs):
            ref_path = f"{path}.automation_test_refs[{ref_index}]"
            errors.extend(_validate_test_ref(reference, path=ref_path))
            if isinstance(reference, str):
                all_test_refs.append((fixture_id, reference))

    if categories != REQUIRED_CATEGORIES:
        errors.append(f"fixture categories must cover {sorted(REQUIRED_CATEGORIES)}")
    if requirements != REQUIRED_REQUIREMENTS:
        errors.append(f"fixture requirements must cover {sorted(REQUIRED_REQUIREMENTS)}")
    if journey_paths != REQUIRED_JOURNEY_PATHS:
        errors.append(f"fixture journey paths must cover {sorted(REQUIRED_JOURNEY_PATHS)}")
    if templates != REQUIRED_TEMPLATES:
        errors.append(f"fixture templates must cover {sorted(REQUIRED_TEMPLATES)}")
    if len({reference for _, reference in all_test_refs}) < 7:
        errors.append("automation must reference at least seven distinct canonical tests")

    calculated_pack_hash = pack_content_sha256(pack)
    if pack.get("content_sha256") != calculated_pack_hash:
        errors.append("content_sha256 does not match canonical pack content")
    errors.extend(
        _validate_approval(
            pack.get("approval"),
            content_hash=calculated_pack_hash,
            path="pack",
            require_approved=require_approved,
        )
    )
    if require_approved and approved_count != len(fixtures):
        errors.append(f"only {approved_count}/{len(fixtures)} fixtures are approved")
    return errors


def load_pack(path: Path = DEFAULT_FIXTURES) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Fixture pack must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate IPLF-047 trademark pleading legal fixtures."
    )
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--require-approved", action="store_true")
    parser.add_argument("--print-hashes", action="store_true")
    args = parser.parse_args()
    pack = load_pack(args.fixtures)
    errors = validate_pack(pack, require_approved=args.require_approved)
    output: dict[str, Any] = {
        "result": "pass" if not errors else "fail",
        "pack_id": pack.get("pack_id"),
        "version": pack.get("version"),
        "fixture_count": len(pack.get("fixtures") or []),
        "approved_count": sum(
            isinstance(row, dict)
            and isinstance(row.get("approval"), dict)
            and row["approval"].get("status") == "approved"
            for row in pack.get("fixtures") or []
        ),
        "authoritative_ready": not validate_pack(pack, require_approved=True),
        "errors": errors,
    }
    if args.print_hashes:
        output["content_sha256"] = pack_content_sha256(pack)
        output["fixture_hashes"] = {
            row["id"]: fixture_content_sha256(row)
            for row in pack.get("fixtures") or []
            if isinstance(row, dict) and row.get("id")
        }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
