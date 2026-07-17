import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load the same config.yaml the running service uses (respects SOAR_CONFIG) so
# migrations never drift from the app's own database.url / table_prefix.
from orchestrator.config import load_config  # noqa: E402
from orchestrator.db.base import configure_table_prefix  # noqa: E402

_soar_config = load_config(os.environ.get("SOAR_CONFIG", "config.yaml"))
configure_table_prefix(_soar_config.database.table_prefix)

# Table prefix must be applied before these are imported — __tablename__ is fixed
# at class-definition time (see orchestrator/db/base.py::configure_table_prefix).
from orchestrator.auth import models as _auth_models  # noqa: E402,F401
from orchestrator.db.base import Base  # noqa: E402
from orchestrator.store import models as _store_models  # noqa: E402,F401

config.set_main_option("sqlalchemy.url", _soar_config.database.url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
