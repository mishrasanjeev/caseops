"""Bound source snapshot history work under ordinary and adverse PostgreSQL plans."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import pytest
from sqlalchemy import Integer, delete, false, func, inspect, literal, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, defer, raiseload

from caseops_api.db.models import CompanyMembership, DocumentProcessingJob, utcnow
from caseops_api.services import document_jobs
from tests.test_document_processing_snapshots_20261018_postgres import (
    BATCH_SIZE,
    HISTORY_PER_SOURCE,
    TARGETS,
    _assert_scalar_read,
    _clone_sources,
    _is_read_only_select,
    _observe,
    _plan_nodes,
    _receipt,
    _save,
    _source,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_company,
    _seed_membership,
)
from tests.test_postgres_validation import (
    migration_pg_engine as _migration_pg_engine,
)

pytestmark = pytest.mark.postgres
PLANNER_FLAGS = ("enable_indexscan", "enable_indexonlyscan", "enable_bitmapscan")
# Four single-history passes: relation scan, sort, window output, rank filter.
HISTORY_OPERATOR_PASSES = 4
history_pg_engine = _migration_pg_engine


def _row_work(node):
    return (
        node.get("Actual Rows", 0)
        + node.get("Rows Removed by Filter", 0)
        + node.get("Rows Removed by Index Recheck", 0)
        + node.get("Rows Removed by Join Filter", 0)
    ) * node.get("Actual Loops", 1)


def _history_work(plan):
    all_nodes = list(_plan_nodes(plan))
    job_index_names, job_bitmap_nodes = set(), set()

    def bind_bitmap_descendants(node):
        if node["Node Type"] not in ("BitmapAnd", "BitmapOr", "Bitmap Index Scan"):
            return
        job_bitmap_nodes.add(id(node))
        if node["Node Type"] == "Bitmap Index Scan":
            assert node.get("Index Name"), "Job bitmap index must retain its index identity"
            job_index_names.add(node["Index Name"])
        for child in node.get("Plans", []):
            bind_bitmap_descendants(child)

    for node in all_nodes:
        if node.get("Relation Name") == "document_processing_jobs":
            if node.get("Index Name"):
                job_index_names.add(node["Index Name"])
            for child in node.get("Plans", []):
                bind_bitmap_descendants(child)
    producers = {
        node["Subplan Name"].removeprefix("CTE "): node
        for node in all_nodes
        if node.get("Subplan Name", "").startswith("CTE ")
    }

    def carries_history(node, seen=frozenset()):
        if (
            node.get("Relation Name") == "document_processing_jobs"
            or id(node) in job_bitmap_nodes
            or node.get("Index Name") in job_index_names
        ):
            return True
        reference = node.get("CTE Name")
        if reference is not None:
            assert reference in producers, f"Unresolved CTE history producer: {reference}"
        if reference in producers and reference not in seen:
            producer = producers[reference]
            if producer.get("Actual Rows", 0) > BATCH_SIZE and carries_history(
                producer, seen | {reference}
            ):
                return True
        return any(
            not child.get("Subplan Name", "").startswith("CTE ") and carries_history(child, seen)
            for child in node.get("Plans", [])
        )

    charged = []
    for offset, node in enumerate(all_nodes):
        relation = node.get("Relation Name") == "document_processing_jobs"
        per_loop = _row_work(node) / max(node.get("Actual Loops", 1), 1)
        if carries_history(node):
            charged.append(
                {
                    "node_offset": offset,
                    "node_type": node["Node Type"],
                    "relation": node.get("Relation Name"),
                    "index": node.get("Index Name"),
                    "job_bitmap_descendant": id(node) in job_bitmap_nodes,
                    "cte": node.get("CTE Name"),
                    "rows_per_loop": per_loop,
                    "loops": node.get("Actual Loops", 1),
                    "row_work": _row_work(node),
                    "raw_job_relation": relation,
                }
            )
    return {
        "job_rows": sum(row["row_work"] for row in charged if row["raw_job_relation"]),
        "total_history_rows": sum(row["row_work"] for row in charged),
        "job_index_names": sorted(job_index_names),
        "charged_nodes": charged,
    }


def _verify_oracles(retained_count):
    plain = select(literal(1).label("value"))
    readable = select(plain.cte("readable").c.value)
    erased = (
        delete(DocumentProcessingJob)
        .where(false())
        .returning(DocumentProcessingJob.id)
        .cte("erased")
    )
    nested_dml = select(literal(1)).add_cte(erased)
    materialized = select(
        plain.cte("materialized").prefix_with("MATERIALIZED", dialect="postgresql").c.value
    )
    for statement in (plain, readable, materialized):
        assert _is_read_only_select(statement.compile(dialect=postgresql.dialect()).statement)
    assert nested_dml.is_select
    assert not _is_read_only_select(nested_dml.compile(dialect=postgresql.dialect()).statement)
    assert not _is_read_only_select(delete(DocumentProcessingJob))
    assert not _is_read_only_select(text("WITH readable AS (SELECT 1) SELECT * FROM readable"))
    assert not _is_read_only_select(None)
    for sql in (
        "SELECT 1 AS id",
        "WITH erased AS (DELETE FROM offline_not_executed RETURNING id) SELECT id FROM erased",
    ):
        opaque = text(sql).columns(id=Integer)
        wrapped = select(opaque.cte("opaque").c.id)
        for statement in (opaque, wrapped):
            assert statement.is_select
            compiled = statement.compile(dialect=postgresql.dialect()).statement
            assert not _is_read_only_select(compiled)
    assert not _is_read_only_select(select(literal(1)).where(text("1 = 1")))

    class SnapshotCaptured(Exception):
        pass

    for target_type in ("matter_attachment", "contract_attachment", "ip_document_version"):
        captured = []

        def compile_only(statement, captured=captured):
            captured.append(statement)
            raise SnapshotCaptured

        # Build the real helper's AST without binding a database or executing SQL.
        with Session() as reader, patch.object(reader, "execute", side_effect=compile_only) as call:
            with pytest.raises(SnapshotCaptured):
                document_jobs.load_latest_processing_jobs(
                    reader,
                    company_id="00000000-0000-0000-0000-000000000001",
                    target_type=target_type,
                    attachment_ids=["00000000-0000-0000-0000-000000000002"],
                )
            assert reader.bind is None and call.call_count == 1
        assert len(captured) == 1
        compiled = captured[0].compile(dialect=postgresql.dialect())
        assert str(compiled).startswith("WITH ") and "AS MATERIALIZED" in str(compiled)
        assert _is_read_only_select(compiled.statement)

    scan = {
        "Node Type": "Seq Scan",
        "Relation Name": "document_processing_jobs",
        "Actual Rows": retained_count,
        "Actual Loops": 1,
    }
    sort = {
        "Node Type": "Sort",
        "Subplan Name": "CTE latest",
        "Actual Rows": retained_count,
        "Actual Loops": 1,
        "Plans": [scan],
    }
    reference = {
        "Node Type": "CTE Scan",
        "CTE Name": "latest",
        "Actual Rows": BATCH_SIZE,
        "Actual Loops": BATCH_SIZE,
    }
    safe = {
        "Node Type": "Nested Loop",
        "Actual Rows": BATCH_SIZE,
        "Actual Loops": 1,
        "Plans": [sort, reference],
    }
    bounded = _history_work(safe)
    assert bounded["job_rows"] == retained_count
    assert bounded["total_history_rows"] == 2 * retained_count + BATCH_SIZE**2 + BATCH_SIZE
    unsafe = deepcopy(safe)
    unsafe["Plans"][1]["Actual Rows"] = retained_count
    amplified = _history_work(unsafe)
    assert amplified["job_rows"] == retained_count
    assert amplified["total_history_rows"] == (BATCH_SIZE + 2) * retained_count + BATCH_SIZE
    assert amplified["total_history_rows"] > HISTORY_OPERATOR_PASSES * (
        retained_count + BATCH_SIZE * 4
    )
    reduced = deepcopy(safe)
    reduced["Plans"][0] = {
        "Node Type": "Subquery Scan",
        "Subplan Name": "CTE latest",
        "Actual Rows": BATCH_SIZE,
        "Rows Removed by Filter": retained_count - BATCH_SIZE,
        "Actual Loops": 1,
        "Plans": [dict(sort, **{"Subplan Name": ""})],
    }
    reduced["Rows Removed by Join Filter"] = BATCH_SIZE * (BATCH_SIZE - 1)
    # A reduced receipt set is bounded metadata; its producer's history stays charged.
    assert _history_work(reduced)["total_history_rows"] == 3 * retained_count
    bitmap = {
        "Node Type": "Sort",
        "Actual Rows": retained_count,
        "Actual Loops": 1,
        "Plans": [
            {
                "Node Type": "Bitmap Heap Scan",
                "Relation Name": "document_processing_jobs",
                "Actual Rows": retained_count,
                "Actual Loops": 1,
                "Plans": [
                    {
                        "Node Type": "BitmapAnd",
                        "Actual Rows": 0,
                        "Actual Loops": 1,
                        "Plans": [
                            {
                                "Node Type": "Bitmap Index Scan",
                                "Index Name": "synthetic_target_idx",
                                "Actual Rows": 2 * retained_count,
                                "Actual Loops": 1,
                            },
                            {
                                "Node Type": "Bitmap Index Scan",
                                "Index Name": "synthetic_company_idx",
                                "Actual Rows": retained_count + 2,
                                "Actual Loops": 1,
                            },
                        ],
                    }
                ],
            }
        ],
    }
    bitmap_work = _history_work(bitmap)
    assert bitmap_work["job_rows"] == retained_count
    assert bitmap_work["total_history_rows"] == 5 * retained_count + 2
    assert bitmap_work["total_history_rows"] > HISTORY_OPERATOR_PASSES * (
        retained_count + BATCH_SIZE * 4
    )
    assert (
        len(
            [row for row in bitmap_work["charged_nodes"] if row["node_type"] == "Bitmap Index Scan"]
        )
        == 2
    )
    unrelated = deepcopy(bitmap)
    unrelated["Plans"][0]["Relation Name"] = "unrelated_synthetic_records"
    assert _history_work(unrelated)["total_history_rows"] == 0


def _settings(session):
    names = (*PLANNER_FLAGS, "jit", "jit_above_cost", "statement_timeout", "lock_timeout")
    return {name: session.scalar(select(func.current_setting(name))) for name in names}


def _latest_shape(plan):
    nodes = list(_plan_nodes(plan))
    return {
        "materialized_producers": [
            {"rows": node.get("Actual Rows"), "loops": node.get("Actual Loops")}
            for node in nodes
            if node.get("Subplan Name") == "CTE latest_processing_receipts"
        ],
        "materialized_scans": [
            {"rows": node.get("Actual Rows"), "loops": node.get("Actual Loops")}
            for node in nodes
            if node.get("CTE Name") == "latest_processing_receipts"
        ],
        "rank_inputs": [
            child.get("Actual Rows", 0) * child.get("Actual Loops", 1)
            for node in nodes
            if node["Node Type"] == "WindowAgg"
            for child in node.get("Plans", [])
        ],
    }


def _seed_history(engine, target):
    with Session(engine) as check:
        assert check.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 0
    fixture = _source(engine, target)
    when = utcnow() + timedelta(days=1)
    with Session(engine) as seed:
        ids = [fixture.source, *_clone_sources(seed, fixture, BATCH_SIZE - 1)]
        receipts, expected = [], {}
        for source_id in ids:
            for index in range(HISTORY_PER_SOURCE):
                receipt = _receipt(
                    fixture, source_id, queued_at=when + timedelta(seconds=3 * index)
                )
                receipts.append(receipt)
            expected[source_id] = receipts[-1]["id"]
        foreign = _seed_company(seed)
        newer = when + timedelta(days=1)
        wrong_type = "matter_attachment" if target == "contract" else "contract_attachment"
        misleading = [
            _receipt(
                fixture,
                fixture.source,
                queued_at=newer,
                company_id=foreign,
                requested_by_membership_id=None,
            ),
            _receipt(fixture, fixture.source, queued_at=newer, target_type=wrong_type),
        ]
        seed.execute(DocumentProcessingJob.__table__.insert(), [*receipts, *misleading])
        seed.commit()
        retained_count = seed.scalar(
            select(func.count())
            .select_from(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.company_id == fixture.company,
                DocumentProcessingJob.target_type == fixture.target_type,
                DocumentProcessingJob.attachment_id.in_(ids),
            )
        )
        assert retained_count == BATCH_SIZE * HISTORY_PER_SOURCE + 1
        assert (
            seed.scalar(select(func.count()).select_from(DocumentProcessingJob))
            == retained_count + 2
        )
        assert (
            seed.scalar(
                select(func.count())
                .select_from(DocumentProcessingJob)
                .where(DocumentProcessingJob.id.in_([row["id"] for row in misleading]))
            )
            == 2
        )
    return fixture, ids, expected, retained_count


def _measure(engine, fixture, ids, profile, directory):
    directory.mkdir()
    with Session(engine) as reader:
        before = _settings(reader)
        if profile == "no-index-or-bitmap":
            for name in PLANNER_FLAGS:
                reader.execute(text(f"SET LOCAL {name} = off"))
        settings = _settings(reader)
        sources = reader.scalars(
            select(fixture.model)
            .where(fixture.model.id.in_(ids))
            .options(
                defer(fixture.model.extracted_text, raiseload=True),
                raiseload("*"),
            )
        ).all()
        assert len(sources) == BATCH_SIZE
        identities = set(reader.identity_map)
        with _observe(reader) as (statements, materialized):
            started = perf_counter()
            jobs = document_jobs.load_latest_processing_jobs(
                reader,
                company_id=fixture.company,
                target_type=fixture.target_type,
                attachment_ids=ids,
            )
            elapsed = perf_counter() - started
        _save(directory, "observed-sql.json", statements)
        assert len(statements) == 1, "Actual snapshot observer must fire exactly once"
        measured = statements[0]
        plan = (
            reader.connection()
            .exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + measured["statement"],
                measured["parameters"],
            )
            .scalar_one()
        )
        _save(directory, "plan.json", plan)
        summary = {
            "profile": profile,
            "settings_before": before,
            "settings_during": settings,
            "query_count": len(statements),
            "orm_loads": materialized,
            "call_seconds": elapsed,
            "sql_bytes": len(measured["statement"].encode()),
            "returned_ids": {source_id: job.id for source_id, job in jobs.items()},
            "returned_company_type_actor": {
                source_id: [job.company_id, job.target_type, job.requested_by_membership_id]
                for source_id, job in jobs.items()
            },
            "returned_receipt_state": {
                source_id: [
                    job.status,
                    job.processed_char_count,
                    job.error_message,
                    job.requested_by_name,
                ]
                for source_id, job in jobs.items()
            },
            "identity_map_unchanged": set(reader.identity_map) == identities,
            "source_bodies_unloaded": all(
                "extracted_text" in inspect(row).unloaded for row in sources
            ),
            "source_processing": [
                {
                    "status": row.processing_status,
                    "characters": row.extracted_char_count,
                    "ocr_quality": getattr(row, "ocr_quality_score", None),
                }
                for row in sources
            ],
            "work": _history_work(plan[0]["Plan"]),
            "latest_shape": _latest_shape(plan[0]["Plan"]),
            "root_rows": plan[0]["Plan"].get("Actual Rows"),
            "root_loops": plan[0]["Plan"].get("Actual Loops"),
            "execution_ms": plan[0]["Execution Time"],
            "planning_ms": plan[0]["Planning Time"],
            "buffers": plan[0]["Plan"].get("Shared Hit Blocks", 0)
            + plan[0]["Plan"].get("Shared Read Blocks", 0),
        }
        _save(directory, "measurement-summary.json", summary)
    with Session(engine) as restored:
        summary["settings_after_transaction_close"] = _settings(restored)
    _save(directory, "restoration.json", summary["settings_after_transaction_close"])
    return summary, statements, materialized


def _assert_profiles(measured, fixture, expected, retained_count):
    raw_bound = 2 * (retained_count + BATCH_SIZE * 4)
    total_bound = HISTORY_OPERATOR_PASSES * (retained_count + BATCH_SIZE * 4)
    for summary, statements, materialized in measured:
        _assert_scalar_read(statements, materialized)
        assert summary["returned_ids"] == expected
        assert all(
            row == [fixture.company, fixture.target_type, fixture.actor]
            for row in summary["returned_company_type_actor"].values()
        )
        assert summary["identity_map_unchanged"] and summary["source_bodies_unloaded"]
        assert all(
            row == {"status": "pending", "characters": 0, "ocr_quality": None}
            for row in summary["source_processing"]
        )
        assert summary["settings_after_transaction_close"] == summary["settings_before"]
        assert all(summary["settings_before"][name] == "on" for name in PLANNER_FLAGS)
        expected_settings = dict(summary["settings_before"])
        if summary["profile"] == "no-index-or-bitmap":
            expected_settings.update(dict.fromkeys(PLANNER_FLAGS, "off"))
        assert summary["settings_during"] == expected_settings
        assert summary["root_rows"] == BATCH_SIZE and summary["root_loops"] == 1
        assert 0 < summary["work"]["job_rows"] <= raw_bound, summary
        assert summary["work"]["total_history_rows"] <= total_bound, summary
        assert summary["buffers"] <= retained_count * 8 + BATCH_SIZE * 64, summary
        assert summary["sql_bytes"] <= 16_384, summary
        assert summary["call_seconds"] < 10 and summary["execution_ms"] < 10_000, summary
        shape = summary["latest_shape"]
        assert shape["materialized_producers"] == [{"rows": BATCH_SIZE, "loops": 1}], summary
        assert shape["materialized_scans"] and all(
            0 < row["rows"] <= BATCH_SIZE and row["loops"] >= 1
            for row in shape["materialized_scans"]
        ), summary
        assert shape["rank_inputs"] and 0 < sum(shape["rank_inputs"]) <= retained_count, summary


@pytest.mark.parametrize("target", TARGETS)
def test_batch_snapshot_history_work_is_bounded_under_adverse_planners(
    history_pg_engine,
    target,
    tmp_path,
    request,
    record_property,
):
    engine = history_pg_engine
    assert engine.dialect.name == "postgresql"
    fixture, ids, expected, retained_count = _seed_history(engine, target)
    _verify_oracles(retained_count)
    journal = os.environ.get("CASEOPS_TEST_RESULT_JOURNAL")
    key = sha256(request.node.nodeid.encode()).hexdigest()[:16]
    directory = (Path(journal).parent if journal else tmp_path) / "document-history-work"
    directory = directory / f"{target}-{key}"
    directory.mkdir(parents=True, exist_ok=False)
    raw_bound = 2 * (retained_count + BATCH_SIZE * 4)
    total_bound = HISTORY_OPERATOR_PASSES * (retained_count + BATCH_SIZE * 4)
    admission = {
        "target": target,
        "sources": BATCH_SIZE,
        "receipts_per_source": HISTORY_PER_SOURCE,
        "own_retained_receipts": retained_count,
        "foreign_or_wrong_type_controls": 2,
        "raw_job_bound_unchanged": raw_bound,
        "total_history_bound": total_bound,
        "total_budget_derivation": "Four single-history operators: scan/sort/window/rank-filter; "
        "same4-row/source slack as original bound. Loop-weighted history carriers all charged.",
        "independently_migrated_empty_test_database": True,
        "qualification": "Synthetic isolated16-source history, not production/global-history "
        "scale or HTTP latency proof.",
    }
    _save(directory, "admission-and-static-budgets.json", admission)
    measured = [
        _measure(engine, fixture, ids, profile, directory / profile)
        for profile in ("default", "no-index-or-bitmap")
    ]
    _save(directory, "all-profile-summaries.json", [row[0] for row in measured])
    record_property("document_history_work_artifact", str(directory))
    record_property("document_history_work_profiles", json.dumps([row[0] for row in measured]))
    # Keep both full plans even when the ordinary plan already violates a work bound.
    _assert_profiles(measured, fixture, expected, retained_count)


@pytest.mark.parametrize("target", TARGETS)
def test_foreign_same_id_history_is_filtered_before_rank_and_materialization(
    history_pg_engine,
    target,
    tmp_path,
    request,
    record_property,
):
    engine = history_pg_engine
    assert engine.dialect.name == "postgresql"
    fixture, ids, expected, retained_count = _seed_history(engine, target)
    _verify_oracles(retained_count)
    foreign_count = BATCH_SIZE * HISTORY_PER_SOURCE
    with Session(engine) as seed:
        foreign = _seed_company(seed)
        requester = _seed_membership(seed, foreign)
        member = seed.get(CompanyMembership, requester)
        member.user.full_name = "Foreign cohort requester must not leak"
        seed.flush()
        newer = utcnow() + timedelta(days=10)
        receipts = [
            _receipt(
                fixture,
                source_id,
                queued_at=newer + timedelta(seconds=3 * offset),
                company_id=foreign,
                requested_by_membership_id=requester,
                error_message="Foreign cohort receipt must not leak",
                processed_char_count=7,
            )
            for source_id in ids
            for offset in range(HISTORY_PER_SOURCE)
        ]
        seed.execute(DocumentProcessingJob.__table__.insert(), receipts)
        seed.commit()
        assert (
            seed.scalar(
                select(func.count())
                .select_from(DocumentProcessingJob)
                .where(
                    DocumentProcessingJob.company_id == foreign,
                    DocumentProcessingJob.target_type == fixture.target_type,
                    DocumentProcessingJob.attachment_id.in_(ids),
                )
            )
            == foreign_count
        )
        assert seed.scalar(select(func.count()).select_from(DocumentProcessingJob)) == (
            retained_count + 2 + foreign_count
        )
    journal = os.environ.get("CASEOPS_TEST_RESULT_JOURNAL")
    key = sha256(request.node.nodeid.encode()).hexdigest()[:16]
    directory = (Path(journal).parent if journal else tmp_path) / "document-history-work"
    directory = directory / f"{target}-foreign-{key}"
    directory.mkdir(parents=True, exist_ok=False)
    _save(
        directory,
        "admission-and-static-budgets.json",
        {
            "target": target,
            "sources": BATCH_SIZE,
            "own_retained_receipts": retained_count,
            "foreign_same_id_receipts": foreign_count,
            "other_foreign_or_wrong_type_controls": 2,
            "raw_job_bound_unchanged": 2 * (retained_count + BATCH_SIZE * 4),
            "total_history_bound_unchanged": HISTORY_OPERATOR_PASSES
            * (retained_count + BATCH_SIZE * 4),
            "rank_input_bound": retained_count,
            "materialized_latest_row_bound": BATCH_SIZE,
            "no_statistics_ANALYZE_JIT_timeout_or_production_planner_changes": True,
            "independently_migrated_empty_test_database": True,
            "qualification": (
                "One foreign 8192-receipt same-ID cohort, not unbounded global-history "
                "or production HTTP proof. A sequential scan may examine this cohort once, "
                "not rank it."
            ),
        },
    )
    measured = [
        _measure(engine, fixture, ids, profile, directory / profile)
        for profile in ("default", "no-index-or-bitmap")
    ]
    _save(directory, "all-profile-summaries.json", [row[0] for row in measured])
    record_property("document_history_work_artifact", str(directory))
    record_property("document_history_work_profiles", json.dumps([row[0] for row in measured]))
    _assert_profiles(measured, fixture, expected, retained_count)
    for summary, _, _ in measured:
        assert all(
            row[:3] == ["failed", 0, "Retained synthetic parser failure."]
            and row[3] != "Foreign cohort requester must not leak"
            for row in summary["returned_receipt_state"].values()
        ), summary
