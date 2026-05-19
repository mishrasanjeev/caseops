from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("corpus_duplicate_cleanup_planner.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("corpus_duplicate_cleanup_planner", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["corpus_duplicate_cleanup_planner"] = module
    spec.loader.exec_module(module)
    return module


def _dependency_counts(chunk_count: int) -> dict[str, int]:
    return {
        "authority_annotations.authority_document_id": 0,
        "authority_citations.cited_authority_document_id": 0,
        "authority_citations.source_authority_document_id": 0,
        "authority_document_chunks.authority_document_id": chunk_count,
        "authority_statute_references.authority_id": 0,
        "contract_legal_references.authority_id": 0,
        "judge_authority_affinity.cited_authority_document_id": 0,
        "judge_authority_affinity.sample_judgment_id": 0,
        "judge_decision_index.authority_document_id": 0,
        "judge_statute_focus.sample_judgment_id": 0,
        "predictive_outcome_aggregate_snapshots.evidence_source_ids_json": 0,
        "predictive_outcome_classifications.source_id": 0,
        "predictive_signal_evidence.source_id": 0,
    }


def _row(
    *,
    row_id: str,
    source_reference: str,
    role: str,
    text_hash: str,
    characters: int,
    chunks: int,
    title: str,
) -> dict[str, object]:
    return {
        "authority_document_id": row_id,
        "source": "ecourts-hc",
        "source_reference": source_reference,
        "review_role": role,
        "text_hash": text_hash,
        "characters": characters,
        "chunk_count": chunks,
        "embedded_chunk_count": chunks,
        "metadata_chunk_count": 1 if chunks == 2 else 0,
        "structured_metadata_present": chunks == 2,
        "structured_metadata_version": 1 if chunks == 2 else None,
        "bounded_title": title,
        "updated_at": "2026-05-18T16:47:49Z",
        "dependency_counts": _dependency_counts(chunks),
    }


def _valid_payload() -> dict[str, object]:
    return {
        "plan_metadata": {
            "source_reports": [
                "docs/runbooks/corpus-duplicate-readonly-audit-2026-05-18.md",
                "docs/runbooks/corpus-duplicate-metadata-extract-2026-05-18.md",
                "docs/runbooks/corpus-duplicate-exact-content-cleanup-approval-packet-2026-05-18.md",
                "docs/runbooks/corpus-duplicate-cleanup-no-execution-approval-checklist-2026-05-18.md",
            ],
            "source_snapshot_timestamp": "2026-05-18T16:47:49.328883Z",
            "source_environment_label": "production-primary-readonly-transaction",
            "cleanup_authorized": False,
            "approval_gates": {
                "legal_content": "required",
                "database": "required",
                "engineering": "required",
                "product": "required",
                "operations": "required",
            },
            "rollback_plan": (
                "Separate approved cleanup PR must include restore or row replay plan."
            ),
            "audit_plan": "Separate approved cleanup PR must capture pre and post bounded counts.",
            "quarantined_group_count": 4,
            "quarantined_row_count": 8,
        },
        "approved_exact_content_candidate_ids": [
            "f791ca94-9198-4448-a16c-81ec27ed8fc7",
            "8c8eafd3-b75e-4b24-993a-e68a483485bc",
            "200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8",
            "5b79de0a-5a2e-4354-8347-f5ecd94af211",
        ],
        "groups": [
            {
                "group_type": "exact-content",
                "source": "ecourts-hc",
                "source_reference": "DLHC010128692024_1_2024-12-23.pdf",
                "rows": [
                    _row(
                        row_id="f791ca94-9198-4448-a16c-81ec27ed8fc7",
                        source_reference="DLHC010128692024_1_2024-12-23.pdf",
                        role="keeper candidate",
                        text_hash="7343caaca1dca196a527c67174b89520",
                        characters=301860,
                        chunks=138,
                        title="CONT.CAS(C) 647/2024",
                    ),
                    _row(
                        row_id="8c8eafd3-b75e-4b24-993a-e68a483485bc",
                        source_reference="DLHC010128692024_1_2024-12-23.pdf",
                        role="loser candidate",
                        text_hash="7343caaca1dca196a527c67174b89520",
                        characters=301860,
                        chunks=138,
                        title="CONT.CAS(C) 647/2024",
                    ),
                ],
            },
            {
                "group_type": "exact-content",
                "source": "ecourts-hc",
                "source_reference": "DLHC010253692023_1_2025-01-13.pdf",
                "rows": [
                    _row(
                        row_id="200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8",
                        source_reference="DLHC010253692023_1_2025-01-13.pdf",
                        role="keeper candidate",
                        text_hash="c36ce20558296cc83b64171f0a55ec28",
                        characters=2272,
                        chunks=2,
                        title="CRL.REV.P. 714/2023",
                    ),
                    _row(
                        row_id="5b79de0a-5a2e-4354-8347-f5ecd94af211",
                        source_reference="DLHC010253692023_1_2025-01-13.pdf",
                        role="loser candidate",
                        text_hash="c36ce20558296cc83b64171f0a55ec28",
                        characters=2272,
                        chunks=2,
                        title="Kapil Bhati v. Jyoti Choudhary & Anr.",
                    ),
                ],
            },
        ],
    }


def test_exact_content_loser_to_keeper_plan_generated_from_fixture_metadata():
    module = _load_module()

    plan = module.generate_cleanup_plan(_valid_payload())

    assert plan["cleanup_execution_supported"] is False
    assert plan["cleanup_authorized"] is False
    assert plan["production_connection_supported"] is False
    assert plan["totals"]["exact_content_groups"] == 2
    assert plan["totals"]["loser_candidates"] == 2
    assert plan["totals"]["dependency_rows_for_future_repoint"] == 140
    assert [group["keeper_candidate_id"] for group in plan["groups"]] == [
        "f791ca94-9198-4448-a16c-81ec27ed8fc7",
        "200decb6-2ae1-4ba9-93ea-2c9c9ca8a5f8",
    ]
    assert plan["groups"][0]["loser_candidate_ids"] == [
        "8c8eafd3-b75e-4b24-993a-e68a483485bc"
    ]
    assert plan["groups"][1]["loser_candidate_ids"] == [
        "5b79de0a-5a2e-4354-8347-f5ecd94af211"
    ]


def test_same_ref_different_content_input_rejected():
    module = _load_module()
    payload = _valid_payload()
    payload["groups"][0]["rows"][1]["text_hash"] = "differenthash00000000000000000000"

    with pytest.raises(module.PlannerInputError, match="different text hashes"):
        module.generate_cleanup_plan(payload)


def test_missing_dependency_inventory_rejected():
    module = _load_module()
    payload = _valid_payload()
    del payload["groups"][1]["rows"][1]["dependency_counts"][
        "authority_document_chunks.authority_document_id"
    ]

    with pytest.raises(module.PlannerInputError, match="missing dependency counts"):
        module.generate_cleanup_plan(payload)


def test_unknown_candidate_id_rejected():
    module = _load_module()
    payload = _valid_payload()
    payload["groups"][0]["rows"][1]["authority_document_id"] = (
        "11111111-1111-4111-8111-111111111111"
    )

    with pytest.raises(module.PlannerInputError, match="unapproved candidate ids"):
        module.generate_cleanup_plan(payload)


def test_source_reference_mismatch_rejected():
    module = _load_module()
    payload = _valid_payload()
    payload["groups"][0]["rows"][1]["source_reference"] = (
        "DLHC010253692023_1_2025-01-13.pdf"
    )

    with pytest.raises(module.PlannerInputError, match="does not match its group"):
        module.generate_cleanup_plan(payload)


def test_non_exact_content_classification_rejected():
    module = _load_module()
    payload = _valid_payload()
    payload["groups"][0]["group_type"] = "same-ref/different-content"

    with pytest.raises(module.PlannerInputError, match="only exact-content groups are allowed"):
        module.generate_cleanup_plan(payload)


def test_missing_approval_metadata_rejected():
    module = _load_module()
    payload = _valid_payload()
    del payload["plan_metadata"]["approval_gates"]["database"]

    with pytest.raises(module.PlannerInputError, match="missing approval gate metadata"):
        module.generate_cleanup_plan(payload)


def test_full_text_payload_keys_rejected_for_bounded_output_only():
    module = _load_module()
    payload = _valid_payload()
    payload["groups"][0]["rows"][0]["document_text"] = "not allowed"

    with pytest.raises(module.PlannerInputError, match="forbidden payload key"):
        module.generate_cleanup_plan(payload)


def test_no_sql_write_statements_emitted():
    module = _load_module()

    plan = module.generate_cleanup_plan(_valid_payload())
    rendered = json.dumps(plan, sort_keys=True)
    write_verbs = [
        "INS" + "ERT",
        "UP" + "DATE",
        "DEL" + "ETE",
        "MER" + "GE",
        "AL" + "TER",
        "CREATE" + r"\s+INDEX",
        "DR" + "OP",
        "TRUN" + "CATE",
        "VAC" + "UUM",
        "REIN" + "DEX",
        "GRA" + "NT",
        "REV" + "OKE",
        "CA" + "LL",
        "D" + "O",
        "CO" + "PY",
    ]

    assert not re.search(r"\b(" + "|".join(write_verbs) + r")\b", rendered, re.IGNORECASE)


def test_no_production_connection_or_default_credentials_used():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "psycopg" not in source
    assert "sqlalchemy" not in source
    assert "CASEOPS_" + "DATABASE" + "_URL" not in source
    assert "DATABASE" + "_URL" not in source
    assert "gcloud" not in source
    assert "connect(" not in source
