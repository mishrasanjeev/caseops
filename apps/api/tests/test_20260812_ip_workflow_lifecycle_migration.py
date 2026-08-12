from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache, get_engine

PREVIOUS_HEAD = "20260812_0001"
MIGRATION_HEAD = "20260812_0002"
WORKFLOW_TABLES = {"ip_workflow_definitions", "ip_workflow_versions"}
PROVENANCE_TABLES = {
    "matter_tasks",
    "matter_hearings",
    "hearing_reminders",
    "matter_next_hearing_suggestions",
    "matter_deadlines",
    "notification_delivery_intents",
    "calendar_event_syncs",
}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(
                connection.scalar(text("SELECT version_num FROM alembic_version"))
            )
    finally:
        engine.dispose()


def _seed_company_and_docket(connection) -> tuple[str, str]:
    company_id = str(uuid4())
    docket_id = str(uuid4())
    now = datetime.now(UTC)
    connection.execute(
        text(
            "INSERT INTO companies "
            "(id, name, slug, company_type, tenant_key, is_active, timezone, created_at) "
            "VALUES (:id, 'Workflow fixture', :slug, 'law_firm', :tenant_key, "
            "true, 'Asia/Kolkata', :created_at)"
        ),
        {
            "id": company_id,
            "slug": f"workflow-{company_id[:8]}",
            "tenant_key": company_id,
            "created_at": now,
        },
    )
    connection.execute(
        text(
            "INSERT INTO ip_docket_records "
            "(id, company_id, record_type, title, status, is_active, "
            "lifecycle_version, archived_by_matter_disposal, restricted, "
            "access_policy_version, current_version, created_at, updated_at) "
            "VALUES (:id, :company_id, 'trademark', 'Legacy unpinned docket', "
            "'draft', true, 0, false, false, 0, 1, :created_at, :created_at)"
        ),
        {"id": docket_id, "company_id": company_id, "created_at": now},
    )
    return company_id, docket_id


def _insert_candidate_workflow(connection, company_id: str) -> tuple[str, str]:
    definition_id = str(uuid4())
    version_id = str(uuid4())
    connection.execute(
        text(
            "INSERT INTO ip_workflow_definitions "
            "(id, company_id, key, name, initial_state) "
            "VALUES (:id, :company_id, 'trademark-standard', "
            "'Trademark standard', 'draft')"
        ),
        {"id": definition_id, "company_id": company_id},
    )
    connection.execute(
        text(
            "INSERT INTO ip_workflow_versions "
            "(id, company_id, definition_id, version, status, schema_version, "
            "transition_table_json, fixture_set_json, source_hash, content_hash, "
            "engine_compatibility) VALUES "
            "(:id, :company_id, :definition_id, 1, 'candidate', 1, '{}', '[]', "
            ":source_hash, :content_hash, 'caseops-ip-workflow-v1')"
        ),
        {
            "id": version_id,
            "company_id": company_id,
            "definition_id": definition_id,
            "source_hash": "a" * 64,
            "content_hash": "b" * 64,
        },
    )
    return definition_id, version_id


def test_ip_workflow_expand_is_inert_and_empty_rollback_is_rehearsable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-workflow.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    engine = get_engine(database_url)
    with engine.begin() as connection:
        company_id, docket_id = _seed_company_and_docket(connection)
        linked_task_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO matter_tasks "
                "(id, company_id, ip_docket_id, title, status, priority, "
                "created_at, updated_at) VALUES "
                "(:id, :company_id, :docket_id, 'Existing live IP task', "
                "'todo', 'medium', :created_at, :created_at)"
            ),
            {
                "id": linked_task_id,
                "company_id": company_id,
                "docket_id": docket_id,
                "created_at": datetime.now(UTC),
            },
        )
    engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    # Use the application engine so SQLite enforces composite foreign keys in
    # the same fail-closed way as PostgreSQL.
    engine = get_engine(database_url)
    inspector = inspect(engine)
    assert WORKFLOW_TABLES <= set(inspector.get_table_names())
    for table_name in PROVENANCE_TABLES:
        columns = {row["name"] for row in inspector.get_columns(table_name)}
        assert {
            "neutralized_by_ip_lifecycle_event_id",
            "neutralized_by_ip_lifecycle_version",
            "neutralized_at",
        } <= columns
        target_column = (
            "neutralized_ip_docket_id"
            if table_name == "calendar_event_syncs"
            else "ip_docket_id"
        )
        foreign_keys = {
            tuple(row["constrained_columns"]): (
                row["referred_table"],
                tuple(row["referred_columns"]),
            )
            for row in inspector.get_foreign_keys(table_name)
        }
        assert foreign_keys[
            (
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                target_column,
                "neutralized_by_ip_lifecycle_version",
            )
        ] == (
            "ip_docket_events",
            ("id", "company_id", "docket_id", "resulting_lifecycle_version"),
        )
        checks = {
            row["name"] for row in inspector.get_check_constraints(table_name)
        }
        assert any(name.endswith("_ip_lifecycle_terminal_state") for name in checks)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM ip_workflow_definitions")) == 0
        assert connection.scalar(text("SELECT count(*) FROM ip_workflow_versions")) == 0
        assert connection.execute(
            text(
                "SELECT workflow_definition_id, workflow_version_id, "
                "workflow_version_number FROM ip_docket_records WHERE id = :id"
            ),
            {"id": docket_id},
        ).one() == (None, None, None)
        assert connection.execute(
            text(
                "SELECT ip_docket_id, neutralized_by_ip_lifecycle_event_id, "
                "neutralized_by_ip_lifecycle_version, neutralized_at "
                "FROM matter_tasks WHERE id = :id"
            ),
            {"id": linked_task_id},
        ).one() == (docket_id, None, None, None)
    engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == PREVIOUS_HEAD
    downgraded_engine = create_engine(database_url, future=True)
    try:
        assert WORKFLOW_TABLES.isdisjoint(
            set(inspect(downgraded_engine).get_table_names())
        )
    finally:
        downgraded_engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD

    get_settings.cache_clear()
    clear_engine_cache()


def test_ip_workflow_evidence_blocks_destructive_downgrade_and_pins_are_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-workflow-populated.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)
    command.upgrade(config, MIGRATION_HEAD)

    # Use the application engine so SQLite enforces the composite pin FK.
    engine = get_engine(database_url)
    with engine.begin() as connection:
        company_id, docket_id = _seed_company_and_docket(connection)
        definition_id, version_id = _insert_candidate_workflow(connection, company_id)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ip_docket_records SET workflow_definition_id = :definition_id "
                    "WHERE id = :docket_id"
                ),
                {"definition_id": definition_id, "docket_id": docket_id},
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ip_docket_records SET "
                    "workflow_definition_id = :definition_id, "
                    "workflow_version_id = :version_id, "
                    "workflow_version_number = 1 WHERE id = :docket_id"
                ),
                {
                    "definition_id": definition_id,
                    "version_id": str(uuid4()),
                    "docket_id": docket_id,
                },
            )

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ip_docket_records SET workflow_definition_id = :definition_id, "
                "workflow_version_id = :version_id, workflow_version_number = 1 "
                "WHERE id = :docket_id"
            ),
            {
                "definition_id": definition_id,
                "version_id": version_id,
                "docket_id": docket_id,
            },
        )

    engine.dispose()
    with pytest.raises(RuntimeError, match="roll application code forward"):
        command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()


def test_published_workflow_contract_cannot_be_rewritten_or_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-workflow-immutable.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)
    command.upgrade(config, MIGRATION_HEAD)

    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        company_id, _ = _seed_company_and_docket(connection)
        _, version_id = _insert_candidate_workflow(connection, company_id)
        empty_definition_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO ip_workflow_definitions "
                "(id, company_id, key, name, initial_state) VALUES "
                "(:id, :company_id, 'empty-retained', 'Empty retained', 'draft')"
            ),
            {"id": empty_definition_id, "company_id": company_id},
        )
        connection.execute(
            text(
                "UPDATE ip_workflow_versions SET transition_table_json = :contract "
                "WHERE id = :id"
            ),
            {"id": version_id, "contract": '{"commands": []}'},
        )

    # Candidate content remains editable while it is being prepared. Once it
    # leaves candidate, the database itself rejects contract rewrites.
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ip_workflow_versions SET status = 'disabled', "
                "retired_at = :retired_at WHERE id = :id"
            ),
            {"id": version_id, "retired_at": datetime.now(UTC)},
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ip_workflow_versions SET transition_table_json = '{}' "
                    "WHERE id = :id"
                ),
                {"id": version_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ip_workflow_versions SET status = 'candidate', "
                    "retired_at = NULL WHERE id = :id"
                ),
                {"id": version_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ip_workflow_versions WHERE id = :id"),
                {"id": version_id},
            )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ip_workflow_definitions SET retired_at = :retired_at "
                "WHERE id = :id"
            ),
            {"id": empty_definition_id, "retired_at": datetime.now(UTC)},
        )
        connection.execute(
            text(
                "UPDATE ip_workflow_definitions SET name = 'Renamed retained', "
                "description = 'Display metadata remains mutable' WHERE id = :id"
            ),
            {"id": empty_definition_id},
        )
    for column_name, replacement in (
        ("key", "rewritten-retained"),
        ("initial_state", "rewritten"),
    ):
        with pytest.raises(IntegrityError, match="definition identity is immutable"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f"UPDATE ip_workflow_definitions SET {column_name} = :replacement "
                        "WHERE id = :id"
                    ),
                    {"id": empty_definition_id, "replacement": replacement},
                )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ip_workflow_definitions WHERE id = :id"),
                {"id": empty_definition_id},
            )
    engine.dispose()
    get_settings.cache_clear()
    clear_engine_cache()


def test_workflow_actor_reference_delete_preserves_immutable_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-workflow-actor.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)
    command.upgrade(config, MIGRATION_HEAD)

    # The application engine enables SQLite foreign-key enforcement just as
    # production PostgreSQL does natively.
    engine = get_engine(database_url)
    with engine.begin() as connection:
        company_id, _ = _seed_company_and_docket(connection)
        _, version_id = _insert_candidate_workflow(connection, company_id)
        user_id = str(uuid4())
        membership_id = str(uuid4())
        now = datetime.now(UTC)
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, full_name, password_hash, is_active, created_at) "
                "VALUES (:id, :email, 'Workflow proposer', 'not-used', true, :now)"
            ),
            {
                "id": user_id,
                "email": f"workflow-{user_id[:8]}@example.com",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO company_memberships "
                "(id, company_id, user_id, role, is_active, created_at) "
                "VALUES (:id, :company_id, :user_id, 'member', true, :now)"
            ),
            {
                "id": membership_id,
                "company_id": company_id,
                "user_id": user_id,
                "now": now,
            },
        )
        connection.execute(
            text(
                "UPDATE ip_workflow_versions SET "
                "proposed_by_membership_id = :membership_id, "
                "proposed_by_membership_company_id = :company_id, "
                "proposer_membership_id_snapshot = :membership_id, "
                "proposer_user_id_snapshot = :user_id, "
                "proposer_label_snapshot = 'Workflow proposer', "
                "proposer_authority_snapshot_json = :authority "
                "WHERE id = :version_id"
            ),
            {
                "membership_id": membership_id,
                "company_id": company_id,
                "user_id": user_id,
                "authority": '{"capabilities": ["ip:approve"]}',
                "version_id": version_id,
            },
        )
        connection.execute(
            text(
                "UPDATE ip_workflow_versions SET status = 'disabled', "
                "retired_at = :retired_at WHERE id = :version_id"
            ),
            {"retired_at": datetime.now(UTC), "version_id": version_id},
        )
        connection.execute(
            text("DELETE FROM company_memberships WHERE id = :id"),
            {"id": membership_id},
        )
        row = connection.execute(
            text(
                "SELECT proposed_by_membership_id, "
                "proposed_by_membership_company_id, "
                "proposer_membership_id_snapshot, proposer_user_id_snapshot, "
                "proposer_label_snapshot, status FROM ip_workflow_versions WHERE id = :id"
            ),
            {"id": version_id},
        ).one()
        assert row == (
            None,
            None,
            membership_id,
            user_id,
            "Workflow proposer",
            "disabled",
        )

    engine.dispose()
    get_settings.cache_clear()
    clear_engine_cache()


def test_lifecycle_provenance_rejects_cross_docket_version_and_open_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-provenance.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)
    command.upgrade(config, MIGRATION_HEAD)

    engine = get_engine(database_url)
    with engine.begin() as connection:
        company_id, first_docket_id = _seed_company_and_docket(connection)
        second_docket_id = str(uuid4())
        now = datetime.now(UTC)
        connection.execute(
            text(
                "INSERT INTO ip_docket_records "
                "(id, company_id, record_type, title, status, is_active, "
                "lifecycle_version, archived_by_matter_disposal, restricted, "
                "access_policy_version, current_version, created_at, updated_at) "
                "VALUES (:id, :company_id, 'trademark', 'Second docket', 'draft', "
                "true, 0, false, false, 0, 1, :now, :now)"
            ),
            {"id": second_docket_id, "company_id": company_id, "now": now},
        )
        user_id = str(uuid4())
        membership_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, full_name, password_hash, is_active, created_at) "
                "VALUES (:id, :email, 'Lifecycle actor', 'not-used', true, :now)"
            ),
            {
                "id": user_id,
                "email": f"lifecycle-{user_id[:8]}@example.com",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO company_memberships "
                "(id, company_id, user_id, role, is_active, created_at) "
                "VALUES (:id, :company_id, :user_id, 'member', true, :now)"
            ),
            {
                "id": membership_id,
                "company_id": company_id,
                "user_id": user_id,
                "now": now,
            },
        )
        event_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO ip_docket_events "
                "(id, company_id, docket_id, sequence, event_kind, source, "
                "effective_at, entered_at, responsible_membership_id, "
                "entered_by_membership_id, evidence_refs_json, document_refs_json, "
                "resulting_deadline_refs_json, candidate_status, payload_json, "
                "resulting_lifecycle_version, created_at) VALUES "
                "(:id, :company_id, :docket_id, 1, 'lifecycle_transition', "
                "'system', :now, :now, :membership_id, :membership_id, '[]', '[]', "
                "'[]', 'confirmed', '{}', 1, :now)"
            ),
            {
                "id": event_id,
                "company_id": company_id,
                "docket_id": first_docket_id,
                "membership_id": membership_id,
                "now": now,
            },
        )

    def insert_versioned_event(*, event_kind: str, candidate_status: str) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ip_docket_events "
                    "(id, company_id, docket_id, sequence, event_kind, source, "
                    "effective_at, entered_at, responsible_membership_id, "
                    "entered_by_membership_id, evidence_refs_json, document_refs_json, "
                    "resulting_deadline_refs_json, candidate_status, payload_json, "
                    "resulting_lifecycle_version, created_at) VALUES "
                    "(:id, :company_id, :docket_id, 2, :event_kind, 'system', "
                    ":now, :now, :membership_id, :membership_id, '[]', '[]', '[]', "
                    ":candidate_status, '{}', 2, :now)"
                ),
                {
                    "id": str(uuid4()),
                    "company_id": company_id,
                    "docket_id": first_docket_id,
                    "event_kind": event_kind,
                    "candidate_status": candidate_status,
                    "membership_id": membership_id,
                    "now": datetime.now(UTC),
                },
            )

    with pytest.raises(IntegrityError):
        insert_versioned_event(event_kind="manual_note", candidate_status="confirmed")
    with pytest.raises(IntegrityError):
        insert_versioned_event(
            event_kind="lifecycle_transition", candidate_status="candidate"
        )

    def insert_task(*, docket_id: str, version: int, status: str) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO matter_tasks "
                    "(id, company_id, ip_docket_id, title, status, priority, "
                    "cancelled_by_matter_disposal, neutralized_by_ip_lifecycle_event_id, "
                    "neutralized_by_ip_lifecycle_version, neutralized_at, "
                    "created_at, updated_at) VALUES "
                    "(:id, :company_id, :docket_id, 'Lifecycle child', :status, "
                    "'medium', false, :event_id, :version, :now, :now, :now)"
                ),
                {
                    "id": str(uuid4()),
                    "company_id": company_id,
                    "docket_id": docket_id,
                    "status": status,
                    "event_id": event_id,
                    "version": version,
                    "now": datetime.now(UTC),
                },
            )

    with pytest.raises(IntegrityError):
        insert_task(docket_id=second_docket_id, version=1, status="cancelled")
    with pytest.raises(IntegrityError):
        insert_task(docket_id=first_docket_id, version=2, status="cancelled")
    with pytest.raises(IntegrityError):
        insert_task(docket_id=first_docket_id, version=1, status="todo")
    insert_task(docket_id=first_docket_id, version=1, status="cancelled")

    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM matter_tasks "
                "WHERE neutralized_by_ip_lifecycle_event_id = :event_id"
            ),
            {"event_id": event_id},
        ) == 1
    engine.dispose()
    get_settings.cache_clear()
    clear_engine_cache()
