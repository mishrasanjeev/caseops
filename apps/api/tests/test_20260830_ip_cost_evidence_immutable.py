"""Migration proof for the IPLF-039F immutable cost-evidence boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260830_0002"
MIGRATION_HEAD = "20260830_0003"
TRIGGERS = {
    "trg_ip_cost_items_evidence_immutable",
    "trg_ip_cost_items_evidence_retained",
}


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Config]:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-cost-evidence.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return database_url, config


def _insert_matterless_cost(connection) -> None:  # type: ignore[no-untyped-def]
    # The trigger is the subject of this migration-level test.  Parent rows are
    # intentionally unnecessary, so disable SQLite FKs for the synthetic row.
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    connection.execute(
        text(
            "INSERT INTO ip_cost_items ("
            "id, company_id, docket_id, matter_id, category, description, "
            "amount_minor, currency, billable, cost_nature, rate_confidential, "
            "evidence_reference, reconciliation_status, created_at"
            ") VALUES ("
            "'cost-039f', 'company-039f', 'docket-039f', NULL, 'official_fee', "
            "'Official filing fee paid before a Matter existed', 900000, 'INR', "
            "0, 'actual', 0, 'receipt:registry-fee-unbilled-2026', "
            "'nonbillable', CURRENT_TIMESTAMP)"
        )
    )


def test_cost_evidence_guard_allows_only_reconciliation_projection_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch)
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            triggers = set(
                connection.scalars(
                    text(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                        "AND tbl_name = 'ip_cost_items'"
                    )
                )
            )
            assert TRIGGERS.issubset(triggers)
            _insert_matterless_cost(connection)

            # Reconciliation is a derived projection and remains refreshable.
            connection.execute(
                text(
                    "UPDATE ip_cost_items SET reconciliation_status = 'nonbillable', "
                    "canonical_amount_minor = NULL, "
                    "reconciliation_difference_minor = NULL, "
                    "reconciled_at = CURRENT_TIMESTAMP "
                    "WHERE id = 'cost-039f'"
                )
            )

        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="IP cost evidence is immutable"
        ):
            connection.execute(
                text(
                    "UPDATE ip_cost_items SET amount_minor = 1 "
                    "WHERE id = 'cost-039f'"
                )
            )

        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="IP cost evidence is immutable"
        ):
            connection.execute(
                text(
                    "UPDATE ip_cost_items SET matter_id = 'matter-later', "
                    "billable = 1 WHERE id = 'cost-039f'"
                )
            )

        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="IP cost evidence is retained"
        ):
            connection.execute(text("DELETE FROM ip_cost_items WHERE id = 'cost-039f'"))

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT matter_id, billable, amount_minor, evidence_reference, "
                    "reconciliation_status FROM ip_cost_items WHERE id = 'cost-039f'"
                )
            ).one()
            assert tuple(row) == (
                None,
                False,
                900000,
                "receipt:registry-fee-unbilled-2026",
                "nonbillable",
            )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            triggers = set(
                connection.scalars(
                    text(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                        "AND tbl_name = 'ip_cost_items'"
                    )
                )
            )
        assert TRIGGERS.isdisjoint(triggers)
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
