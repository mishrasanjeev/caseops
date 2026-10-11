"""Release integration must contain both queue and financial schema protocols."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_financial_migration_follows_all_document_execution_protocols():
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "alembic"))
    directory = ScriptDirectory.from_config(config)

    lineage = {
        revision.revision
        for revision in directory.walk_revisions(base="base", head="20261011_0001")
    }

    assert {
        "20261010_0001",
        "20261010_0002",
        "20261010_0003",
        "20261010_0004",
    } <= lineage
