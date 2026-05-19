"""Offline dry-run planner for exact-content corpus duplicate cleanup.

The planner consumes an explicit JSON metadata packet and emits a bounded JSON
plan. It intentionally has no database client, production connection handling,
or write-capable SQL generation. Production cleanup remains a separate,
approval-gated milestone.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APPROVED_EXACT_CONTENT_CANDIDATE_IDS = frozenset(
    {
        "f791ca94-9198-4448-a16c-81ec27ed8fc7",
        "8c8eafd3-b75e-4b24-993a-e68a483485bc",
        "200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8",
        "5b79de0a-5a2e-4354-8347-f5ecd94af211",
    }
)

QUARANTINED_SAME_REF_DIFFERENT_CONTENT_IDS = frozenset(
    {
        "2ef2d85e-306c-48e0-9582-ce269127e2c5",
        "ad5e99fd-d7e0-4663-abac-2ec02199fadd",
        "18687e36-79f0-4134-9f62-4828a30f0eb1",
        "763bf1be-6622-4b0f-892a-26ab9c458f5e",
        "6497a7ce-50e0-4484-8157-59108708cca8",
        "82f1ed37-f120-41cc-acb0-8f628b063e19",
        "463fc76b-5583-424a-a13b-64978d362553",
        "c22e0558-8fb2-42d7-9d4f-8f8a1e158463",
    }
)

REQUIRED_APPROVAL_GATES = (
    "legal_content",
    "database",
    "engineering",
    "product",
    "operations",
)

REQUIRED_DEPENDENCIES = (
    "authority_annotations.authority_document_id",
    "authority_citations.cited_authority_document_id",
    "authority_citations.source_authority_document_id",
    "authority_document_chunks.authority_document_id",
    "authority_statute_references.authority_id",
    "contract_legal_references.authority_id",
    "judge_authority_affinity.cited_authority_document_id",
    "judge_authority_affinity.sample_judgment_id",
    "judge_decision_index.authority_document_id",
    "judge_statute_focus.sample_judgment_id",
    "predictive_outcome_aggregate_snapshots.evidence_source_ids_json",
    "predictive_outcome_classifications.source_id",
    "predictive_signal_evidence.source_id",
)

FORBIDDEN_PAYLOAD_KEYS = {
    "document_text",
    "ocr_text",
    "full_judgment_text",
    "source_payload",
    "raw_payload",
    "payload_text",
    "tenant_data",
    "matter_data",
    "db_url",
    "database_url",
    "credentials",
    "password",
    "secret",
    "token",
}

MAX_METADATA_STRING_LENGTH = 500
MAX_BOUNDED_TITLE_LENGTH = 180


class PlannerInputError(ValueError):
    """Raised when offline metadata cannot safely produce a cleanup plan."""


@dataclass(frozen=True)
class CandidateRow:
    authority_document_id: str
    source: str
    source_reference: str
    review_role: str
    text_hash: str
    characters: int
    chunk_count: int
    embedded_chunk_count: int
    metadata_chunk_count: int
    structured_metadata_present: bool
    structured_metadata_version: int | None
    bounded_title: str
    updated_at: str
    dependency_counts: dict[str, int]

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], *, group_source: str, group_reference: str
    ) -> CandidateRow:
        row_id = _required_str(payload, "authority_document_id")
        source = _required_str(payload, "source")
        source_reference = _required_str(payload, "source_reference")
        if source != group_source or source_reference != group_reference:
            raise PlannerInputError(
                f"row {row_id} does not match its group source/source_reference"
            )

        title = _required_str(payload, "bounded_title")
        if len(title) > MAX_BOUNDED_TITLE_LENGTH:
            raise PlannerInputError(f"row {row_id} bounded_title is not bounded")

        dependency_counts = _dependency_counts(payload.get("dependency_counts"), row_id=row_id)

        version_value = payload.get("structured_metadata_version")
        if version_value is None:
            version = None
        elif isinstance(version_value, int):
            version = version_value
        else:
            raise PlannerInputError(
                f"row {row_id} structured_metadata_version must be an integer or null"
            )

        return cls(
            authority_document_id=row_id,
            source=source,
            source_reference=source_reference,
            review_role=_required_str(payload, "review_role"),
            text_hash=_required_str(payload, "text_hash"),
            characters=_required_int(payload, "characters"),
            chunk_count=_required_int(payload, "chunk_count"),
            embedded_chunk_count=_required_int(payload, "embedded_chunk_count"),
            metadata_chunk_count=_required_int(payload, "metadata_chunk_count"),
            structured_metadata_present=_required_bool(payload, "structured_metadata_present"),
            structured_metadata_version=version,
            bounded_title=title,
            updated_at=_required_str(payload, "updated_at"),
            dependency_counts=dependency_counts,
        )


def generate_cleanup_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate explicit offline metadata and return a non-executing plan."""

    _scan_forbidden_payload(payload)
    metadata = _metadata(payload)
    approved_ids = _approved_candidate_ids(payload)
    groups = _candidate_groups(payload)

    plan_groups: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_dependency_rows = 0
    nonzero_dependencies: set[str] = set()

    for group_payload in groups:
        group_source = _required_str(group_payload, "source")
        group_reference = _required_str(group_payload, "source_reference")
        group_type = _required_str(group_payload, "group_type")
        if group_type != "exact-content":
            raise PlannerInputError(
                f"{group_reference} is {group_type!r}; only exact-content groups are allowed"
            )

        row_payloads = _required_sequence(group_payload, "rows")
        rows = [
            CandidateRow.from_payload(
                row,
                group_source=group_source,
                group_reference=group_reference,
            )
            for row in row_payloads
        ]
        if len(rows) < 2:
            raise PlannerInputError(f"{group_reference} must include keeper and loser rows")

        row_ids = {row.authority_document_id for row in rows}
        if row_ids & QUARANTINED_SAME_REF_DIFFERENT_CONTENT_IDS:
            raise PlannerInputError(
                f"{group_reference} includes quarantined same-ref/different-content rows"
            )
        if not row_ids <= approved_ids:
            unknown = sorted(row_ids - approved_ids)
            raise PlannerInputError(
                f"{group_reference} includes unapproved candidate ids: {unknown}"
            )
        if seen_ids & row_ids:
            raise PlannerInputError(f"{group_reference} repeats candidate ids")
        seen_ids.update(row_ids)

        text_hashes = {row.text_hash for row in rows}
        if len(text_hashes) != 1:
            raise PlannerInputError(
                f"{group_reference} has different text hashes and remains quarantined"
            )

        keepers = [row for row in rows if row.review_role == "keeper candidate"]
        losers = [row for row in rows if row.review_role == "loser candidate"]
        if len(keepers) != 1:
            raise PlannerInputError(f"{group_reference} must have exactly one keeper candidate")
        if not losers:
            raise PlannerInputError(f"{group_reference} must have at least one loser candidate")

        keeper = keepers[0]
        dependency_plan = []
        for loser in losers:
            for dependency, row_count in loser.dependency_counts.items():
                if row_count <= 0:
                    continue
                nonzero_dependencies.add(dependency)
                total_dependency_rows += row_count
                dependency_plan.append(
                    {
                        "dependency": dependency,
                        "from_authority_document_id": loser.authority_document_id,
                        "to_authority_document_id": keeper.authority_document_id,
                        "row_count": row_count,
                        "future_action": "repoint_in_separate_approved_cleanup",
                    }
                )

        plan_groups.append(
            {
                "source": group_source,
                "source_reference": group_reference,
                "text_hash": rows[0].text_hash,
                "keeper_candidate_id": keeper.authority_document_id,
                "loser_candidate_ids": [row.authority_document_id for row in losers],
                "dependency_repoint_plan": dependency_plan,
                "future_loser_retirement_candidates": [
                    row.authority_document_id for row in losers
                ],
                "bounded_row_metadata": [_row_metadata(row) for row in rows],
                "preconditions": [
                    "same source and source_reference",
                    "single exact-content text hash",
                    "approved exact-content candidate ids only",
                    "complete dependency inventory supplied",
                    "approval, rollback, and audit metadata supplied",
                ],
            }
        )

    if seen_ids != APPROVED_EXACT_CONTENT_CANDIDATE_IDS:
        missing = sorted(APPROVED_EXACT_CONTENT_CANDIDATE_IDS - seen_ids)
        extra = sorted(seen_ids - APPROVED_EXACT_CONTENT_CANDIDATE_IDS)
        raise PlannerInputError(
            f"input must cover exactly the approved exact-content candidates; "
            f"missing={missing} extra={extra}"
        )

    return {
        "plan_type": "exact_content_duplicate_cleanup_dry_run",
        "cleanup_execution_supported": False,
        "cleanup_authorized": False,
        "production_connection_supported": False,
        "source_reports": metadata["source_reports"],
        "source_snapshot_timestamp": metadata["source_snapshot_timestamp"],
        "source_environment_label": metadata["source_environment_label"],
        "approval_gates": metadata["approval_gates"],
        "rollback_plan": metadata["rollback_plan"],
        "audit_plan": metadata["audit_plan"],
        "same_ref_different_content_quarantine": {
            "status": "excluded",
            "group_count": metadata["quarantined_group_count"],
            "row_count": metadata["quarantined_row_count"],
        },
        "totals": {
            "exact_content_groups": len(plan_groups),
            "keeper_candidates": len(plan_groups),
            "loser_candidates": sum(len(group["loser_candidate_ids"]) for group in plan_groups),
            "dependency_rows_for_future_repoint": total_dependency_rows,
            "nonzero_dependency_columns": sorted(nonzero_dependencies),
        },
        "groups": plan_groups,
        "non_execution_boundary": {
            "input_source": "explicit_offline_metadata_only",
            "write_sql_generated": False,
            "database_connection_generated": False,
            "requires_separate_cleanup_pr": True,
        },
    }


def _metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _required_mapping(payload, "plan_metadata")
    if bool(metadata.get("cleanup_authorized")):
        raise PlannerInputError("cleanup_authorized must be false for this planner")

    gates = _required_mapping(metadata, "approval_gates")
    missing_gates = [gate for gate in REQUIRED_APPROVAL_GATES if not gates.get(gate)]
    if missing_gates:
        raise PlannerInputError(f"missing approval gate metadata: {missing_gates}")

    source_reports = _required_sequence(metadata, "source_reports")
    if not source_reports:
        raise PlannerInputError("source_reports must not be empty")
    reports = []
    for index, report in enumerate(source_reports):
        if not isinstance(report, str) or not report:
            raise PlannerInputError(f"source_reports[{index}] must be a non-empty string")
        reports.append(report)

    return {
        "source_reports": reports,
        "source_snapshot_timestamp": _required_str(metadata, "source_snapshot_timestamp"),
        "source_environment_label": _required_str(metadata, "source_environment_label"),
        "approval_gates": {gate: str(gates[gate]) for gate in REQUIRED_APPROVAL_GATES},
        "rollback_plan": _required_str(metadata, "rollback_plan"),
        "audit_plan": _required_str(metadata, "audit_plan"),
        "quarantined_group_count": _required_int(metadata, "quarantined_group_count"),
        "quarantined_row_count": _required_int(metadata, "quarantined_row_count"),
    }


def _approved_candidate_ids(payload: Mapping[str, Any]) -> frozenset[str]:
    values = _required_sequence(payload, "approved_exact_content_candidate_ids")
    candidate_ids = frozenset(
        _coerce_str(value, "approved_exact_content_candidate_ids") for value in values
    )
    if candidate_ids != APPROVED_EXACT_CONTENT_CANDIDATE_IDS:
        missing = sorted(APPROVED_EXACT_CONTENT_CANDIDATE_IDS - candidate_ids)
        extra = sorted(candidate_ids - APPROVED_EXACT_CONTENT_CANDIDATE_IDS)
        raise PlannerInputError(
            f"approved_exact_content_candidate_ids must match source evidence; "
            f"missing={missing} extra={extra}"
        )
    return candidate_ids


def _candidate_groups(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    groups = _required_sequence(payload, "groups")
    result = []
    for index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            raise PlannerInputError(f"groups[{index}] must be an object")
        result.append(group)
    return result


def _row_metadata(row: CandidateRow) -> dict[str, Any]:
    return {
        "authority_document_id": row.authority_document_id,
        "review_role": row.review_role,
        "characters": row.characters,
        "chunk_count": row.chunk_count,
        "embedded_chunk_count": row.embedded_chunk_count,
        "metadata_chunk_count": row.metadata_chunk_count,
        "structured_metadata_present": row.structured_metadata_present,
        "structured_metadata_version": row.structured_metadata_version,
        "bounded_title": row.bounded_title,
        "updated_at": row.updated_at,
        "dependency_counts": row.dependency_counts,
    }


def _dependency_counts(value: Any, *, row_id: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise PlannerInputError(f"row {row_id} missing dependency inventory")

    missing = [dependency for dependency in REQUIRED_DEPENDENCIES if dependency not in value]
    if missing:
        raise PlannerInputError(f"row {row_id} missing dependency counts: {missing}")

    counts: dict[str, int] = {}
    for dependency in REQUIRED_DEPENDENCIES:
        raw_count = value[dependency]
        if not isinstance(raw_count, int) or raw_count < 0:
            raise PlannerInputError(
                f"row {row_id} dependency {dependency} must be a non-negative integer"
            )
        counts[dependency] = raw_count
    return counts


def _scan_forbidden_payload(value: Any, *, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_lower in FORBIDDEN_PAYLOAD_KEYS:
                raise PlannerInputError(f"forbidden payload key at {path}.{key_text}")
            _scan_forbidden_payload(item, path=f"{path}.{key_text}")
    elif isinstance(value, str):
        if len(value) > MAX_METADATA_STRING_LENGTH:
            raise PlannerInputError(f"oversized metadata string at {path}")
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        for index, item in enumerate(value):
            _scan_forbidden_payload(item, path=f"{path}[{index}]")


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise PlannerInputError(f"{key} must be an object")
    return value


def _required_sequence(payload: Mapping[str, Any], key: str) -> Sequence[Any]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, bytes | bytearray | str):
        raise PlannerInputError(f"{key} must be a list")
    return value


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return _coerce_str(value, key)


def _coerce_str(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise PlannerInputError(f"{key} must be a non-empty string")
    if len(value) > MAX_METADATA_STRING_LENGTH:
        raise PlannerInputError(f"{key} is oversized")
    return value


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value < 0:
        raise PlannerInputError(f"{key} must be a non-negative integer")
    return value


def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise PlannerInputError(f"{key} must be a boolean")
    return value


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="corpus-duplicate-cleanup-planner",
        description="Generate a non-executing exact-content duplicate cleanup dry-run plan.",
    )
    parser.add_argument("--input", required=True, help="Path to explicit offline metadata JSON.")
    parser.add_argument("--output", help="Optional path for the generated JSON plan.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        input_path = Path(args.input)
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise PlannerInputError("input JSON must be an object")
        plan = generate_cleanup_plan(payload)
    except (json.JSONDecodeError, OSError, PlannerInputError) as exc:
        print(f"planner rejected input: {exc}", file=sys.stderr)
        return 2

    output = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
