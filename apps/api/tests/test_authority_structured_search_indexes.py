from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy.dialects import postgresql

from caseops_api.services.authorities import _authority_mode_filter_clause


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260811_0005_authority_structured_search_trigrams.py"
    )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_structured_search_migration_builds_all_indexes_concurrently() -> None:
    module = _load_migration_module()
    definitions = module.AUTHORITY_STRUCTURED_SEARCH_TRIGRAM_INDEXES

    assert module.down_revision == "20260811_0004"
    assert {name for name, _ in definitions} == {
        "ix_authority_documents_citation_trgm",
        "ix_authority_documents_party_trgm",
        "ix_authority_documents_name_prefilter_trgm",
        "ix_authority_documents_court_name_trgm",
        "ix_authority_documents_judge_trgm",
        "ix_authority_documents_act_section_trgm",
    }
    for name, ddl in definitions:
        assert f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name}" in ddl
        assert "USING gin" in ddl
        assert "gin_trgm_ops" in ddl
    assert all("summary" not in ddl for _, ddl in definitions)
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "indisvalid" in source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in source


def test_structured_mode_clauses_match_indexed_expressions() -> None:
    expected_fragments = {
        "exact_citation": ("case_reference", "neutral_citation"),
        "party": ("parties_json", "title"),
        "court": ("court_name",),
        "judge": ("bench_name", "judges_json"),
        "act_section": ("sections_cited_json", "title"),
    }

    for mode, fields in expected_fragments.items():
        clause = _authority_mode_filter_clause(mode, "Needle")
        assert clause is not None
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).casefold()
        for field in fields:
            assert field in sql
        assert "summary" not in sql
