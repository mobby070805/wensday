"""Alembic environment.

The database URL and the table metadata both come from the app itself (`app.config.Settings`,
`app.models.Base`) rather than being duplicated in `alembic.ini` — there is exactly one source of
truth for "what does the schema look like" and "where is the database", both already used by the
app at runtime. Run every command from `backend/`:

    alembic upgrade head                              # apply pending migrations
    alembic revision --autogenerate -m "add X"         # after changing app/models.py
    alembic upgrade head --sql                         # emit SQL without connecting (any dialect)
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Single source of truth: the app's own settings, not a second copy in alembic.ini.
# `alembic -x db_url=...` lets ops target a different database for one invocation if ever needed.
_url = context.get_x_argument(as_dictionary=True).get("db_url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))


def run_migrations_offline() -> None:
    """Emit SQL without connecting to a database — used to verify migrations compile for a given
    dialect (e.g. PostgreSQL) with no live server available: `alembic upgrade head --sql`."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
