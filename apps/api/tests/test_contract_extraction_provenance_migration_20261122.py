"""Cross-dialect retained and rolling old-shape contract extraction records."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, inspect, select, text

from alembic import command
from caseops_api.db.models import CompanyMembership, Contract, NotificationPhoneContact, User
from caseops_api.db.session import CaseOpsSession
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company

PREVIOUS = "20261122_0003"
REVISION = "20261122_0631"
CONTENT = {
    "contract_clauses": "notes",
    "contract_obligations": "description",
}
STAMP = datetime(2026, 11, 22, tzinfo=UTC)
PREFIX = "[auto] Same bytes could come from a human or an older model."


def _columns(schema):
    return {
        name: [
            {**column, "type": str(column["type"])}
            for column in schema.get_columns(name)
        ]
        for name in CONTENT
    }


def _snapshot(engine, tables):
    with engine.connect() as connection:
        return {
            name: connection.execute(select(table).order_by(table.c.title)).all()
            for name, table in tables.items()
        }


@pytest.mark.parametrize("kind", KINDS)
def test_extraction_provenance_preserves_ambiguous_rows_and_accepts_old_writes(
    kind, tmp_path, monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        with CaseOpsSession(bind=engine) as session:
            if engine.dialect.name == "sqlite":
                session.serialize_sqlite_writer()
            company_id = _seed_company(session)
            contract = Contract(
                id=str(uuid4()), company_id=company_id, title="Retained contract",
                contract_code="RET-631", contract_type="services",
            )
            contract_id = contract.id
            membership = CompanyMembership(
                id=str(uuid4()), company_id=company_id, role="member",
                user=User(
                    email="phone-retention@example.test", full_name="Synthetic member",
                    password_hash="disabled-test-credential",
                ),
            )
            session.add_all([contract, membership])
            session.flush()
            session.add(NotificationPhoneContact(
                company_id=company_id, membership_id=membership.id, phone_number="+12025550117",
                verified_at=STAMP, whatsapp_consent_at=STAMP, whatsapp_opted_out_at=STAMP,
                consent_text_version="v1", opt_out_source="webhook",
            ))
            session.commit()

        phone = Table("notification_phone_contacts", MetaData(), autoload_with=engine)
        version = text("SELECT version_num FROM alembic_version")
        phone_select = select(phone)
        with engine.connect() as connection:
            [phone_before] = connection.execute(phone_select).all()
        phone_indexes = inspect(engine).get_indexes(phone.name)
        assert phone_before.whatsapp_opted_out_at is not None
        with pytest.raises(RuntimeError) as phone_refused:
            command.downgrade(config, "20261122_0002")
        assert str(phone_refused.value) == (
            "Phone consent and opt-out evidence is retained; restore-forward only."
        )
        with engine.connect() as connection:
            assert connection.scalar(version) == PREVIOUS
            assert connection.execute(phone_select).all() == [phone_before]
        assert inspect(engine).get_indexes(phone.name) == phone_indexes

        old_tables = {name: Table(name, MetaData(), autoload_with=engine) for name in CONTENT}

        def insert_old(name, title):
            fields = {
                "id": str(uuid4()), "contract_id": contract_id,
                "title": title, "created_at": STAMP, CONTENT[name]: PREFIX,
            }
            if name == "contract_clauses":
                fields.update(clause_type="payment", clause_text="Pay the agreed sum.",
                              risk_level="medium")
            else:
                fields.update(status="completed", priority="medium", completed_at=STAMP)
            with engine.begin() as connection:
                connection.execute(old_tables[name].insert().values(**fields))

        for name in CONTENT:
            assert "extracted_by_ai" not in old_tables[name].c
            insert_old(name, "Retained before migration")
        old_rows = _snapshot(engine, old_tables)
        command.upgrade(config, REVISION)
        assert _snapshot(engine, old_tables) == old_rows

        for name in CONTENT:
            insert_old(name, "Admitted by rolling old writer")
        new_tables = {name: Table(name, MetaData(), autoload_with=engine) for name in CONTENT}
        schema = inspect(engine)
        before = _snapshot(engine, new_tables)
        columns = _columns(schema)
        indexes = {name: schema.get_indexes(name) for name in CONTENT}
        for name, content in CONTENT.items():
            assert [row.title for row in before[name]] == [
                "Admitted by rolling old writer", "Retained before migration",
            ]
            assert [(row._mapping[content], row.extracted_by_ai) for row in before[name]] == [
                (PREFIX, False), (PREFIX, False),
            ]

        with pytest.raises(RuntimeError) as error:
            command.downgrade(config, PREVIOUS)
        assert str(error.value) == (
            "Contract extraction provenance is restore-forward. Restore the reviewed backup."
        )
        assert _snapshot(engine, new_tables) == before
        current = inspect(engine)
        assert _columns(current) == columns
        assert {name: current.get_indexes(name) for name in CONTENT} == indexes
        with engine.connect() as connection:
            assert connection.scalar(version) == REVISION
            assert connection.execute(phone_select).all() == [phone_before]
        assert inspect(engine).get_indexes(phone.name) == phone_indexes
