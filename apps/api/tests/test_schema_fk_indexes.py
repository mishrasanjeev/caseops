from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.session import get_engine


def test_foreign_key_columns_have_leading_index_or_migration_coverage(client: TestClient) -> None:
    # Inspect actual migrated FK prefixes with the release-health rule, not each
    # component column in isolation or a declaration of an index that may be absent.
    with get_engine().connect() as connection:
        gaps = database_foreign_key_gaps(inspect(connection))
    assert not gaps, f"Migrated foreign keys lack complete leading index coverage: {gaps}"


def test_fk_inventory_detects_a_missing_patent_source_composite_index(client: TestClient) -> None:
    with get_engine().begin() as connection:
        connection.execute(text("DROP INDEX ix_patent_family_versions_company_document"))
        gaps = database_foreign_key_gaps(
            inspect(connection),
            table_names=["ip_patent_family_versions"],
        )
        assert any(
            gap.constraint_name == "fk_patent_family_version_document_company"
            and set(gap.columns)
            == {
                "source_document_version_id",
                "company_id",
                "source_document_id",
            }
            for gap in gaps
        ), gaps
