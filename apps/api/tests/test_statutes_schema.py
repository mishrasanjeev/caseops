"""Slice S1 (MOD-TS-017) — schema + seed tests for the Statute model.

Maps to FT-S1-1 .. FT-S1-5 in
``docs/PRD_STATUTE_MODEL_2026-04-25.md`` §6.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuthorityStatuteReference,
    MatterStatuteReference,
    Statute,
    StatuteSection,
)
from caseops_api.scripts.seed_statutes import _seed
from tests.test_auth_company import bootstrap_company


def test_ft_s1_1_seed_inserts_7_acts(client: TestClient) -> None:
    """Seed loader inserts the 7 v1 central acts: BNSS, BNS, BSA,
    CrPC, IPC, Constitution, NI Act."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        s_ins, s_upd, sec_ins, sec_upd = _seed(s)
        ids = {row.id for row in s.scalars(select(Statute)).all()}
    assert s_ins == 7
    assert {
        "constitution-india", "bnss-2023", "bns-2023", "bsa-2023",
        "crpc-1973", "ipc-1860", "ni-act-1881",
    } <= ids
    assert sec_ins > 0


def test_ft_s1_2_seed_is_idempotent(client: TestClient) -> None:
    """Re-running the seed inserts 0 acts and 0 sections; updates
    them in place."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        _seed(s)
    with get_session_factory()() as s:
        s_ins, s_upd, sec_ins, sec_upd = _seed(s)
    assert s_ins == 0
    assert sec_ins == 0
    assert s_upd == 7


def test_ft_s1_3_unique_constraint_on_section_per_statute(
    client: TestClient,
) -> None:
    """Inserting two rows with the same (statute_id, section_number)
    raises an integrity error — uq_statute_sections_unique."""
    from sqlalchemy.exc import IntegrityError

    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        s.add(
            Statute(
                id="test-act", short_name="TEST",
                long_name="Test Act for unique-constraint test",
                enacted_year=2026, jurisdiction="india", is_active=True,
            ),
        )
        s.commit()
        s.add(
            StatuteSection(
                statute_id="test-act", section_number="1",
                section_label="First section", ordinal=1, is_active=True,
            ),
        )
        s.commit()
        s.add(
            StatuteSection(
                statute_id="test-act", section_number="1",
                section_label="Duplicate", ordinal=2, is_active=True,
            ),
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_ft_s1_4_section_url_falls_back_to_act_url(
    client: TestClient,
) -> None:
    """When a section doesn't ship its own section_url, the seed
    falls back to the parent act's source_url so every UI render
    has a clickable verify link."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        _seed(s)
        # CrPC s.482 doesn't carry an explicit section_url in the
        # seed JSON; it should inherit the parent act's source_url.
        row = s.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "crpc-1973",
                StatuteSection.section_number == "Section 482",
            )
        )
        assert row is not None
        assert row.section_url is not None
        assert "indiacode" in row.section_url


def test_ft_s1_5_fk_constraints_declared_correctly(
    client: TestClient,
) -> None:
    """ORM-level FK declarations are correct: StatuteSection.statute_id
    cascades on Statute delete (Postgres enforces; SQLite tests skip
    runtime cascade per pragma not enabled). MatterStatuteReference
    and AuthorityStatuteReference reference tables exist + are
    queryable. Postgres CI's test_postgres_validation.py asserts
    runtime cascade behavior."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        # All four tables exist and are queryable (no error means
        # the migration ran cleanly).
        assert s.scalar(select(Statute).limit(1)) is None or True
        assert s.scalar(select(StatuteSection).limit(1)) is None or True
        assert s.scalar(select(MatterStatuteReference).limit(1)) is None or True
        assert s.scalar(select(AuthorityStatuteReference).limit(1)) is None or True

    # FK declarations on the ORM model match the migration.
    fk_section_to_statute = next(
        fk for fk in StatuteSection.__table__.foreign_keys
        if fk.column.table.name == "statutes"
    )
    assert fk_section_to_statute.ondelete == "CASCADE"
    fk_matter_ref_to_section = next(
        fk for fk in MatterStatuteReference.__table__.foreign_keys
        if fk.column.table.name == "statute_sections"
    )
    assert fk_matter_ref_to_section.ondelete == "RESTRICT"
    fk_authority_ref_to_section = next(
        fk for fk in AuthorityStatuteReference.__table__.foreign_keys
        if fk.column.table.name == "statute_sections"
    )
    assert fk_authority_ref_to_section.ondelete == "RESTRICT"
