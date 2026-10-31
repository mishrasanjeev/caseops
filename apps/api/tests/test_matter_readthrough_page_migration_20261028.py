"""Literal0007→0008 source compatibility, distinct from current-head refusal.

Retained historical Table objects perform all rolling writes. No provider,
manual projection refresh or new-column writer supplies the serving result.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    HearingPack,
    HearingPackItem,
    MatterHearing,
    PredictiveOutcomeClassification,
    Recommendation,
    RecommendationDecision,
    RecommendationOption,
    User,
)
from caseops_api.services import matter_readthrough as reads
from caseops_api.services.session_context import SessionContext
from tests.test_counsel_page_migration_20261027 import _catalog, _rows, _seed
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as forbid_unadmitted_network,
)
from tests.test_matter_task_queue_migration_20261028 import _artifact
from tests.test_platform_console_migration import fresh_engine, migration_config
from tests.test_postgres_validation import _seed_matter

PREVIOUS = "20261027_0007"
NAMED_HEAD = "20261027_0008"
DIALECTS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
STAMP = datetime(2026, 10, 28, 7, 11, 13, 123456, tzinfo=UTC)
FAMILIES = {
    "recommendations": "matter_recommendation_read_pages",
    "recommendation_options": "matter_option_read_pages",
    "recommendation_decisions": "matter_decision_read_pages",
    "hearing_packs": "matter_hearing_pack_read_pages",
    "hearing_pack_items": "matter_pack_item_read_pages",
}
NEW_TABLES = set(FAMILIES.values()) | {"matter_readthrough_dirty"}
LAYOUTS = {
    "recommendations": ("chron", "id"),
    "recommendation_options": ("rank",),
    "recommendation_decisions": ("chron",),
    "hearing_packs": ("latest", "id"),
    "hearing_pack_items": ("rank",),
}
OUTBOXES = (
    "audit_events",
    "domain_outbox_events",
    "in_app_notifications",
    "notification_delivery_intents",
    "notification_delivery_events",
)


def identity(number):
    return str(UUID(int=0x800000 + number))


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def reflected(engine, name):
    return Table(name, MetaData(), autoload_with=engine)


def seed_old(engine):
    scope, _ = _seed(engine, count=1)
    wide = "Retained original 資料 é\n" * 90000
    with Session(engine) as session:
        session.get(CompanyMembership, scope["member"]).role = "owner"
        other = _seed_matter(session, scope["company"])
        hearing = MatterHearing(
            id=identity(9000),
            company_id=scope["company"],
            matter_id=scope["matter"],
            hearing_on=STAMP.date(),
            forum_name="Retained fixture forum",
            purpose="Retained source only",
            status="scheduled",
            created_at=STAMP,
            reminder_policy_json={"channels": [], "critical": False},
        )
        session.add(hearing)
        # These historical models deliberately share scalar IDs rather than
        # an ORM relationship; establish the actual referenced row first.
        session.flush()
        for n in reversed(range(27)):
            created = STAMP + timedelta(microseconds=n % 3)
            session.add(
                Recommendation(
                    id=identity(n),
                    company_id=scope["company"],
                    matter_id=scope["matter"],
                    type="authority",
                    title=f"Retained recommendation {n}",
                    rationale=wide if n == 0 else f"Original rationale {n}",
                    assumptions_json='["Original assumption"]',
                    missing_facts_json="[]",
                    retrieved_authorities_json="[]",
                    confidence="low",
                    status="proposed",
                    review_required=True,
                    created_at=created,
                    updated_at=created,
                )
            )
            session.add(
                HearingPack(
                    id=identity(3000 + n),
                    matter_id=scope["matter"],
                    hearing_id=hearing.id,
                    status="draft",
                    review_required=True,
                    summary=wide if n == 0 else f"Original pack {n}",
                    generated_at=created,
                    reviewed_at=None,
                )
            )
        session.flush()
        # An explicitly synthetic retained legacy category, not a claim of a
        # legally valid classification or eligibility for public aggregation.
        session.add(
            PredictiveOutcomeClassification(
                id=identity(9500),
                source_type="recommendation",
                source_id=identity(0),
                source_hash=hashlib.sha256(wide.encode("utf-8")).hexdigest(),
                company_id=scope["company"],
                matter_id=scope["matter"],
                classification_label="unverified_fixture",
                signal_type="retained_migration_fixture",
                rationale_snippet="Original private classification remains retained",
                status="unverified_fixture",
                method="deterministic",
                created_at=STAMP,
                updated_at=STAMP,
            )
        )
        for n in reversed(range(27)):
            session.add(
                RecommendationOption(
                    id=identity(1000 + n),
                    recommendation_id=identity(0),
                    rank=n % 3 - 1,
                    label=f"Original option {n}",
                    confidence="low",
                    rationale=wide if n == 0 else f"Original option body {n}",
                    supporting_citations_json='["Opaque stored source"]',
                    risk_notes=None,
                )
            )
            session.add(
                RecommendationDecision(
                    id=identity(2000 + n),
                    recommendation_id=identity(0),
                    decision="deferred",
                    actor_membership_id=None,
                    selected_option_index=None,
                    notes=None if n == 0 else f"Original decision {n}",
                    created_at=STAMP + timedelta(microseconds=n % 3),
                )
            )
            session.add(
                HearingPackItem(
                    id=identity(4000 + n),
                    pack_id=identity(3000),
                    rank=n % 3 - 1,
                    item_type="chronology",
                    title=f"Original item {n}",
                    body=wide if n == 0 else f"Original item body {n}",
                    source_ref=None if n == 0 else "opaque:retained/source",
                    created_at=STAMP,
                )
            )
        session.commit()
    old = {name: reflected(engine, name) for name in FAMILIES}
    with engine.connect() as connection:
        rows = {
            name: {row["id"]: dict(row) for row in connection.execute(select(table)).mappings()}
            for name, table in old.items()
        }
    return {**scope, "other_matter": other, "hearing": identity(9000)}, old, rows, wide


def context(session, scope):
    member = session.get(CompanyMembership, scope["member"])
    return SessionContext(
        company=session.get(Company, scope["company"]),
        membership=member,
        user=session.get(User, member.user_id),
    )


def source_scope(rows, source, row, scope):
    if source == "recommendations":
        return row["company_id"], row["matter_id"]
    if source in {"recommendation_options", "recommendation_decisions"}:
        parent = rows["recommendations"][row["recommendation_id"]]
        return parent["company_id"], parent["matter_id"]
    if source == "hearing_packs":
        return scope["company"], row["matter_id"]
    parent = rows["hearing_packs"][row["pack_id"]]
    return scope["company"], parent["matter_id"]


def parent_key(source, layout, row):
    if source in {"recommendation_options", "recommendation_decisions"}:
        return row["recommendation_id"]
    if source == "hearing_pack_items":
        return row["pack_id"]
    if source == "hearing_packs" and layout == "latest":
        return row["hearing_id"] or ""
    return ""


def ordered(source, layout, rows):
    key = (
        "id"
        if layout == "id"
        else "rank"
        if layout == "rank"
        else ("generated_at" if source == "hearing_packs" else "created_at")
    )
    return sorted(
        rows, key=lambda row: (row[key], row["id"]), reverse=layout in {"chron", "latest"}
    )


def require_physical(engine, scope, rows):
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM matter_readthrough_dirty")) == 0
        for source, name in FAMILIES.items():
            table = reflected(engine, name)
            pages = list(connection.execute(select(table)).mappings())
            if engine.dialect.name == "sqlite":
                assert pages == []
                continue
            for layout in LAYOUTS[source]:
                groups = {}
                for row in rows[source].values():
                    company, matter = source_scope(rows, source, row, scope)
                    groups.setdefault(
                        (company, matter, parent_key(source, layout, row)), []
                    ).append(row)
                actual_groups = {
                    (page["company_id"], page["matter_id"], page["parent_key"])
                    for page in pages
                    if page["layout"] == layout
                }
                assert actual_groups == set(groups)
                for group, members in groups.items():
                    expected = ordered(source, layout, members)
                    selected = sorted(
                        (
                            p
                            for p in pages
                            if p["layout"] == layout
                            and (p["company_id"], p["matter_id"], p["parent_key"]) == group
                        ),
                        key=lambda p: p["page_number"],
                    )
                    chunks = [expected[n : n + 25] for n in range(0, len(expected), 25)]
                    assert [p["page_number"] for p in selected] == list(range(len(chunks)))
                    assert [p["record_count"] for p in selected] == [len(chunk) for chunk in chunks]
                    assert [[entry["id"] for entry in p["payload"]] for p in selected] == [
                        [row["id"] for row in chunk] for chunk in chunks
                    ]
                    for page, chunk in zip(selected, chunks, strict=True):
                        assert page["last_id"] == chunk[-1]["id"]
                        assert all(
                            entry["__company_id"] == group[0] and entry["__matter_id"] == group[1]
                            for entry in page["payload"]
                        )
                        if layout == "rank":
                            assert page["last_rank"] == chunk[-1]["rank"]
                        if layout in {"chron", "latest"}:
                            key = "generated_at" if layout == "latest" else "created_at"
                            assert utc(page["last_stamp"]) == utc(chunk[-1][key])
                        for entry, original in zip(page["payload"], chunk, strict=True):
                            # Independent literals cover every wide source family and
                            # nullable source notes/references without parsing JSON text.
                            for field, cap in (
                                ("rationale", 16384),
                                ("summary", 16384),
                                ("body", 16384),
                                ("notes", 16384),
                                ("source_ref", 500),
                            ):
                                if field not in entry:
                                    continue
                                raw = original[field]
                                assert entry[field] == (raw[: cap + 1] if raw is not None else None)
                                assert entry[field + "_source_bytes"] == (
                                    len(raw.encode("utf-8")) if raw is not None else None
                                )


def require_reads(engine, scope, rows):
    observed = []
    with Session(engine) as session:
        actor = context(session, scope)
        matter = scope["matter"]
        specs = [
            ("recommendations", "chron", reads.list_recommendations, {}),
            (
                "recommendation_options",
                "rank",
                reads.list_options,
                {"recommendation_id": identity(0)},
            ),
            (
                "recommendation_decisions",
                "chron",
                reads.list_decisions,
                {"recommendation_id": identity(0)},
            ),
            ("hearing_pack_items", "rank", reads.list_pack_items, {"pack_id": identity(3000)}),
        ]
        for source, layout, read, extra in specs:
            expected = ordered(source, layout, list(rows[source].values()))
            default = read(session, context=actor, matter_id=matter, **extra)
            assert default.limit == 25
            assert [row.id for row in default.items] == [row["id"] for row in expected[:25]]
            assert default.next_cursor is not None
            observed.append(
                {
                    "source": source,
                    "limit": "omitted_default_25",
                    "ids": [row.id for row in default.items],
                }
            )
            for limit in (7, 25):
                cursor = None
                found = []
                seen = set()
                for _ in range(8):
                    page = read(
                        session,
                        context=actor,
                        matter_id=matter,
                        limit=limit,
                        cursor=cursor,
                        **extra,
                    )
                    found.extend(page.items)
                    observed.append(
                        {"source": source, "limit": limit, "ids": [r.id for r in page.items]}
                    )
                    if page.next_cursor is None:
                        break
                    assert page.next_cursor not in seen
                    seen.add(page.next_cursor)
                    cursor = page.next_cursor
                else:
                    raise AssertionError("Complete retained inventory did not terminate")
                assert [row.id for row in found] == [row["id"] for row in expected]
                assert len(found) == len({row.id for row in found})
                scalar_fields = {
                    "recommendations": ("type", "title", "confidence", "status", "review_required"),
                    "recommendation_options": ("label", "confidence", "rationale", "risk_notes"),
                    "recommendation_decisions": (
                        "decision",
                        "notes",
                        "actor_membership_id",
                        "selected_option_index",
                    ),
                    "hearing_pack_items": ("item_type", "title", "body", "source_ref"),
                }[source]
                for actual, original in zip(found, expected, strict=True):
                    wide = (
                        any(
                            isinstance(original.get(field), str) and len(original[field]) > 16384
                            for field in ("rationale", "body", "notes")
                        )
                        and source != "recommendations"
                    )
                    assert actual.read_state == ("unsupported_size" if wide else "available")
                    if wide:
                        assert actual.record is None
                    else:
                        for field in scalar_fields:
                            assert getattr(actual.record, field) == original[field]
        detail = reads.get_recommendation(
            session, context=actor, matter_id=matter, recommendation_id=identity(0)
        )
        pack = reads.get_pack(session, context=actor, matter_id=matter, pack_id=identity(3000))
        latest = reads.get_latest_pack(
            session, context=actor, matter_id=matter, hearing_id=scope["hearing"]
        )
        assert detail.read_state == pack.read_state == "unsupported_size"
        assert detail.record is pack.record is None
        assert (
            latest.id
            == ordered("hearing_packs", "latest", list(rows["hearing_packs"].values()))[0]["id"]
        )
        assert latest.record.summary == rows["hearing_packs"][latest.id]["summary"]
    return observed


@pytest.mark.parametrize("kind", DIALECTS)
def test_named_0007_to_0008_backfill_old_column_crud_and_restart_preserve_every_source(
    kind,
    tmp_path,
    monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        assert NEW_TABLES.isdisjoint(inspect(engine).get_table_names())
        scope, old, rows, wide = seed_old(engine)
        old_names = sorted(set(inspect(engine).get_table_names()) - {"alembic_version"})
        before = _rows(engine, old_names)
        outboxes = _rows(engine, OUTBOXES)
        assert before["predictive_outcome_classifications"]
        original = _artifact(tmp_path / "0007-all-source-and-receipts.json", before)
        assert original["bytes"] > 1024**2 and all(outboxes.values())
        command.upgrade(config, NAMED_HEAD)
        assert set(inspect(engine).get_table_names()) == set(old_names) | NEW_TABLES | {
            "alembic_version"
        }
        preserved = _artifact(
            tmp_path / "0008-original-source-and-receipts.json", _rows(engine, old_names)
        )
        assert preserved["sha256"] == original["sha256"]
        require_physical(engine, scope, rows)
        observations = require_reads(engine, scope, rows)
        for number, (source, table) in enumerate(old.items()):
            example = dict(next(iter(rows[source].values())))
            new = {**example, "id": identity(10000 + number)}
            for field in ("rationale", "summary", "body", "notes"):
                if field in new:
                    new[field] = "Old writer committed after migration"
            with engine.begin() as connection:
                statement = table.insert().values(**new).returning(table.c.id)
                acknowledged_id = connection.execute(statement).scalar_one()
                assert acknowledged_id == new["id"]
            rows[source][new["id"]] = new
            require_physical(engine, scope, rows)
            observations += require_reads(engine, scope, rows)
            if source == "hearing_packs":
                with Session(engine) as session:
                    direct = reads.get_pack(
                        session,
                        context=context(session, scope),
                        matter_id=scope["matter"],
                        pack_id=new["id"],
                    )
                    assert direct.read_state == "available"
                    assert direct.record.summary == new["summary"]
            changes = {
                field: "Updated old source after migration"
                for field in ("title", "label", "notes")
                if field in new
            }
            if not changes:
                changes = {"summary": "Updated old source after migration"}
            with engine.begin() as connection:
                statement = (
                    table.update()
                    .where(table.c.id == new["id"])
                    .values(**changes)
                    .returning(table.c.id)
                )
                acknowledged_id = connection.execute(statement).scalar_one()
                assert acknowledged_id == new["id"]
            rows[source][new["id"]].update(changes)
            require_physical(engine, scope, rows)
            observations += require_reads(engine, scope, rows)
            if source == "hearing_packs":
                with Session(engine) as session:
                    direct = reads.get_pack(
                        session,
                        context=context(session, scope),
                        matter_id=scope["matter"],
                        pack_id=new["id"],
                    )
                    assert direct.read_state == "available"
                    assert direct.record.summary == changes["summary"]
            with engine.begin() as connection:
                statement = table.delete().where(table.c.id == new["id"]).returning(table.c.id)
                acknowledged_id = connection.execute(statement).scalar_one()
                assert acknowledged_id == new["id"]
            del rows[source][new["id"]]
            require_physical(engine, scope, rows)
            observations += require_reads(engine, scope, rows)
        assert _rows(engine, OUTBOXES) == outboxes
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(old["recommendations"].c.rationale).where(
                        old["recommendations"].c.id == identity(0)
                    )
                )
                == wide
            )
        engine.dispose()
        observations += require_reads(engine, scope, rows)
        require_physical(engine, scope, rows)
        names = sorted(inspect(engine).get_table_names())
        before_refusal = _rows(engine, names), _catalog(engine)
        failure = None
        try:
            command.downgrade(config, PREVIOUS)
        except RuntimeError as error:
            failure = str(error)
        assert (
            failure
            == "Matter retained-read projection is restore-forward; restore the reviewed backup."
        )
        assert (_rows(engine, names), _catalog(engine)) == before_refusal
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == NAMED_HEAD
        observations += require_reads(engine, scope, rows)
        _artifact(
            tmp_path / "complete-named-read-journey.json",
            {
                "dialect": kind,
                "previous": PREVIOUS,
                "namedHead": NAMED_HEAD,
                "oldSourceRows": 135,
                "oldColumnAcknowledgedWrites": {"insert": 5, "update": 5, "delete": 5},
                "observations": observations,
                "sourceOutboxBytesUnchanged": True,
            },
        )


@pytest.mark.parametrize("kind", DIALECTS)
def test_actual_current_head_restore_refusal_preserves_rows_classifications_catalog_and_revision(
    kind,
    tmp_path,
    monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        current = ScriptDirectory.from_config(config).get_current_head()
        assert current == "20261029_0002"
        # SQLite refuses the non-immediate destination at the new seek index.
        # PostgreSQL reaches the Matter guard inside its rollback transaction.
        expected_refusal = (
            "SQLite seek index downgrade requires exact immediate parent."
            if engine.dialect.name == "sqlite"
            else "Matter retained-read projection is restore-forward; restore the reviewed backup."
        )
        command.upgrade(config, "head")
        scope, _, rows, _ = seed_old(engine)
        require_physical(engine, scope, rows)
        names = sorted(inspect(engine).get_table_names())
        before_rows, before_catalog = _rows(engine, names), _catalog(engine)
        assert before_rows["predictive_outcome_classifications"]
        before = _artifact(tmp_path / "current-before-refusal-all-rows.json", before_rows)
        _artifact(tmp_path / "current-before-refusal-catalog.json", before_catalog)
        refusal = None
        try:
            command.downgrade(config, PREVIOUS)
        except RuntimeError as error:
            refusal = str(error)
        assert refusal == expected_refusal
        after_rows, after_catalog = _rows(engine, names), _catalog(engine)
        after = _artifact(tmp_path / "current-after-refusal-all-rows.json", after_rows)
        _artifact(tmp_path / "current-after-refusal-catalog.json", after_catalog)
        assert before_rows == after_rows and before_catalog == after_catalog
        assert before["sha256"] == after["sha256"]
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == current
        require_physical(engine, scope, rows)
        require_reads(engine, scope, rows)
