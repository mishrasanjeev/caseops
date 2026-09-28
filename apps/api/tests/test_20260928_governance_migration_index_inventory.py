"""Exact migration index inventory for the data-governance map (2026-09-28).

The inventory used a regex over raw migration text. When a migration built an
index name from a constant, the optional ``IF NOT EXISTS`` group backtracked
and the keyword ``IF`` was recorded as a name (15 captures), a comment
contributed the word ``leaves``, and every such index was missing, so its
removal or drift could not change the fingerprint. The inventory now parses
each migration, resolves names from literals and constants, and fails closed
on any declaration it cannot name.
"""

from __future__ import annotations

import copy
import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "ip_data_governance_map", REPO_ROOT / "scripts" / "ip_data_governance_map.py"
)
assert SPEC is not None and SPEC.loader is not None
governance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(governance)

KEYWORDS = {"CONCURRENTLY", "EXISTS", "IF", "INDEX", "NOT", "ON", "ONLY", "UNIQUE", "USING"}

# The regexes the inventory used before 2026-09-28, kept to prove no name is lost.
OLD_DIRECT = re.compile(
    r"(?:op|batch_op)\.create_index\(\s*(?:op\.f\()?['\"]([^'\"]+)['\"]", re.MULTILINE
)
OLD_RAW = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+CONCURRENTLY)?"
    r"(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z0-9_]+)",
    re.IGNORECASE,
)


def test_real_inventory_has_no_keywords_or_prose() -> None:
    names = governance._migration_index_names()
    assert names == sorted(set(names))
    assert not {name.upper() for name in names} & KEYWORDS
    assert "leaves" not in names
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in names), [
        name for name in names if not re.fullmatch(r"[a-z][a-z0-9_]*", name)
    ]


def test_real_inventory_names_indexes_the_regex_could_not_see() -> None:
    names = set(governance._migration_index_names())
    assert {
        # Module constants inside f-strings.
        "ix_authority_documents_decision_updated",
        "ix_assistant_sessions_company_creator_title",
        "uq_ip_party_owner",
        "uq_ip_relationship_patent_owner",
        "ix_tracking_operation_recovery",
        # Loops over constant sequences, including a local f-string name.
        "ix_matters_temporary_e_case_number_trgm",
        "ix_matters_case_number_trgm",
        "ix_matters_cnr_number_trgm",
        "ix_matters_filing_number_trgm",
        "ix_matters_company_created_id",
        # Names split across adjacent string literals.
        "ix_authority_documents_citation_trgm",
        "ix_authority_documents_party_trgm",
        "ix_authority_documents_name_prefilter_trgm",
        "ix_authority_documents_court_name_trgm",
        "ix_authority_documents_judge_trgm",
        "ix_authority_documents_act_section_trgm",
        # Reviewed helper and database-derived migrations.
        "ix_matters_court_id",
        "ix_billing_coupon_redemptions_redeemed_by_membership_id",
        "ix_ip_docket_records_company_active_updated",
        "ix_ip_matter_links_docket_id",
        # Literal DDL.
        "ix_authority_documents_neutral_citation",
        "ix_authority_document_chunks_embedding_hnsw",
    } <= names


def test_real_inventory_keeps_every_name_the_old_scanner_found() -> None:
    old: set[str] = set()
    for path in sorted(governance.MIGRATION_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        old.update(OLD_DIRECT.findall(source))
        old.update(OLD_RAW.findall(source))
    assert {"IF", "leaves"} <= old
    assert old - {"IF", "leaves"} <= set(governance._migration_index_names())


FIXTURES = {
    "0001_literal.py": '''
"""Mentions CREATE INDEX CONCURRENTLY leaves an invalid index in prose."""
from alembic import op


def upgrade():
    # An interrupted CREATE INDEX CONCURRENTLY leaves an invalid index.
    """A bare string: CREATE INDEX IF NOT EXISTS prose_only ON t (a)."""
    op.execute("CREATE INDEX ix_literal ON t (a)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS " "ix_adjacent ON t (a)")
    op.execute('CREATE UNIQUE INDEX "ix_quoted" ON t (a)')
''',
    "0002_constants.py": '''
from alembic import op

_NAME = "ix_constant"
_TABLE = "t"
_DDL = (
    "CREATE INDEX IF NOT EXISTS "
    f"{_NAME} ON {_TABLE} (a)"
)


def upgrade():
    op.execute(_DDL)
    op.execute(f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_NAME}_unique ON {_TABLE} (a)")
''',
    "0003_loops.py": '''
from alembic import op

_COLUMNS = ("alpha", "beta")
_PAIRS = (("ix_pair_one", "t"), ("ix_pair_two", "u"))


def upgrade():
    for column in _COLUMNS:
        name = f"ix_loop_{column}"
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON t ({column})")
    for name, table in _PAIRS:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} (a)")
''',
    "0004_create_index.py": '''
from alembic import op

_BATCH_NAME = "ix_batch_constant"


def upgrade():
    op.create_index("ix_op_literal", "t", ["a"])
    op.create_index(op.f("ix_op_f"), "t", ["a"])
    op.create_index(index_name="ix_keyword", table_name="t", columns=["a"])
    with op.batch_alter_table("t") as batch_op:
        batch_op.create_index(_BATCH_NAME, ["a"])
''',
    "0005_helpers.py": '''
import sqlalchemy as sa
from alembic import op

_TABLES = {"alpha": ("a", "b"), "beta": ("c",)}
_GENERATED = tuple(f"ix_gen_{column}" for column in ("x", "y", "z") if column != "y")


def _index_name(table, column):
    return f"ix_{table}_{column}"


def _create(table, column, *extra, unique=False):
    op.create_index(_index_name(table, column), table, [column], unique=unique)


def _create_table(table_name, *columns, suffix):
    op.create_index(f"ix_{table_name}_{suffix}", table_name, ["id"])


def upgrade():
    for table, columns in _TABLES.items():
        for column in columns:
            _create(table, column)
    _create_table("gamma", sa.Column("id"), sa.Column("x"), suffix="company_id")
    for column, column_type in (("typed", sa.String(80)), ("other", sa.Integer())):
        op.create_index(op.f(f"ix_typed_{column}"), "t", [column])
    for suffix in ("company_id", "status"):
        name = "ix_conditional_company" if suffix == "company_id" else f"ix_conditional_{suffix}"
        op.create_index(name, "t", [suffix])
    for name in _GENERATED:
        op.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON t (a)')
''',
}

EXPECTED = {
    "ix_literal",
    "ix_adjacent",
    "ix_quoted",
    "ix_constant",
    "ix_constant_unique",
    "ix_loop_alpha",
    "ix_loop_beta",
    "ix_pair_one",
    "ix_pair_two",
    "ix_op_literal",
    "ix_op_f",
    "ix_keyword",
    "ix_batch_constant",
    # Helpers inlined at their call sites, dict items, partial tuples,
    # conditional names and a generator-built constant.
    "ix_alpha_a",
    "ix_alpha_b",
    "ix_beta_c",
    "ix_gamma_company_id",
    "ix_typed_typed",
    "ix_typed_other",
    "ix_conditional_company",
    "ix_conditional_status",
    "ix_gen_x",
    "ix_gen_z",
}


def _migrations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> Path:
    directory = tmp_path / "versions"
    directory.mkdir()
    for name, source in files.items():
        (directory / name).write_text(source.lstrip("\n"), encoding="utf-8")
    monkeypatch.setattr(governance, "MIGRATION_DIR", directory)
    return directory


def test_fixture_declarations_resolve_exactly(tmp_path: Path, monkeypatch) -> None:
    _migrations(tmp_path, monkeypatch, FIXTURES)
    assert set(governance._migration_index_names()) == EXPECTED


@pytest.mark.parametrize(
    ("source", "line"),
    [
        # A helper parameter is not a known constant.
        (
            'from alembic import op\n\n\ndef _create(name):\n'
            '    op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON t (a)")\n',
            5,
        ),
        # A parameter shadows the module constant of the same name.
        (
            'from alembic import op\n_NAME = "ix_module"\n\n\ndef _create(_NAME):\n'
            '    op.execute(f"CREATE INDEX {_NAME} ON t (a)")\n',
            6,
        ),
        # PostgreSQL would invent the name of an unnamed index.
        ('from alembic import op\nop.execute("CREATE INDEX ON t (a)")\n', 2),
        # str.format hides the name from static reading.
        (
            'from alembic import op\nNAME = "ix_x"\n'
            'op.execute("CREATE INDEX {} ON t (a)".format(NAME))\n',
            3,
        ),
        # A computed create_index name.
        ('from alembic import op\nop.create_index(make_name(), "t", ["a"])\n', 2),
        # A loop over a value that is not a constant sequence.
        (
            'from alembic import op\n\n\ndef upgrade(names):\n    for name in names:\n'
            '        op.execute(f"CREATE INDEX {name} ON t (a)")\n',
            6,
        ),
        # A helper called with a value only known at run time.
        (
            'from alembic import op\n\n\ndef _create(table):\n'
            '    op.create_index(f"ix_{table}_id", table, ["id"])\n\n\n'
            'def upgrade():\n    for table in op.get_bind().info:\n        _create(table)\n',
            5,
        ),
        # A helper whose parameters arrive through an unknown mapping.
        (
            'from alembic import op\n\n\ndef _create(table):\n'
            '    op.create_index(f"ix_{table}_id", table, ["id"])\n\n\n'
            'def upgrade(options):\n    _create(**options)\n',
            5,
        ),
    ],
)
def test_undeterminable_declarations_fail_closed(
    tmp_path: Path, monkeypatch, source: str, line: int
) -> None:
    _migrations(tmp_path, monkeypatch, {**FIXTURES, "0009_dynamic.py": source})
    with pytest.raises(governance.MigrationIndexInventoryError) as refusal:
        governance._migration_index_names()
    assert f"0009_dynamic.py:{line}:" in str(refusal.value)


def test_validate_reports_an_unnamed_declaration_instead_of_crashing(
    tmp_path: Path, monkeypatch
) -> None:
    data = copy.deepcopy(governance._load(governance.MAP_PATH))
    _migrations(
        tmp_path,
        monkeypatch,
        {"0001_unnamed.py": 'from alembic import op\nop.execute("CREATE INDEX ON t (a)")\n'},
    )
    errors = governance.validate(data, check_generated_view=False)
    assert any(
        "migration index inventory" in error and "0001_unnamed.py:2:" in error for error in errors
    ), errors
