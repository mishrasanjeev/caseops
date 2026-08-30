from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from caseops_api.core.settings import get_settings
from caseops_api.db import models
from caseops_api.db.base import Base
from caseops_api.db.connection_safety import migration_connect_args

if models.__name__ != "caseops_api.db.models":
    raise RuntimeError("caseops_api.db.models did not import correctly")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # The application engine has always carried these server-side budgets.
    # Alembic previously did not, so a schema change blocked by a live
    # transaction could wait for the complete migration-job timeout.  Apply
    # the same fail-closed limits before the first migration statement.
    connect_args = migration_connect_args(
        settings.database_url,
        connect_timeout_seconds=settings.db_connect_timeout_seconds,
        statement_timeout_ms=settings.db_statement_timeout_ms,
        lock_timeout_ms=settings.db_lock_timeout_ms,
        idle_transaction_timeout_ms=settings.db_idle_transaction_timeout_ms,
    )
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
