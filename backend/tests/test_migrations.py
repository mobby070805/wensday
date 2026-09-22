"""Alembic migrations: `alembic upgrade head` must produce exactly the schema the ORM models
describe, downgrade must actually work, and the migration DDL must compile for PostgreSQL with
no live server (offline SQL emission) — the same three things an operator needs to trust before
running migrations against a production database.

Each test shells out to the real `alembic` CLI (not the internal Python API) against a scratch
SQLite file, because that is exactly the command `docs/deployment.md` tells operators to run —
these tests are that instruction, executed.
"""
from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db import Database
from app.models import Base, User

pytestmark = pytest.mark.timeout(60)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _run(*args: str, db_url: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {"WENSDAY_DATABASE_URL": db_url, "WENSDAY_JWT_SECRET": "x" * 40, **(extra_env or {})}
    import os

    full_env = {**os.environ, **env}
    return subprocess.run(
        [PYTHON, "-m", "alembic", *args], cwd=BACKEND_ROOT, env=full_env,
        capture_output=True, text=True, timeout=45,
    )


def _sqlite_url(tmp_path: Path, name: str = "db.sqlite3") -> tuple[str, Path]:
    f = tmp_path / name
    return f"sqlite+aiosqlite:///{f.as_posix()}", f


def _sync_reflect(sqlite_file: Path) -> dict:
    """Reflect the actual on-disk schema (sync engine — reflection doesn't need async)."""
    engine = create_engine(f"sqlite:///{sqlite_file.as_posix()}")
    insp = inspect(engine)
    schema = {}
    for table in insp.get_table_names():
        cols = {c["name"]: (str(c["type"]), c["nullable"]) for c in insp.get_columns(table)}
        idx = {i["name"] for i in insp.get_indexes(table)}
        schema[table] = {"columns": cols, "indexes": idx}
    engine.dispose()
    return schema


# ------------------------------------------------------------------ upgrade produces the real schema
def test_alembic_upgrade_head_matches_the_orm_models(tmp_path):
    migrated_url, migrated_file = _sqlite_url(tmp_path, "migrated.sqlite3")
    r = _run("upgrade", "head", db_url=migrated_url)
    assert r.returncode == 0, r.stdout + r.stderr
    migrated_schema = _sync_reflect(migrated_file)

    declarative_url, declarative_file = _sqlite_url(tmp_path, "declarative.sqlite3")
    engine = create_engine(declarative_url.replace("sqlite+aiosqlite", "sqlite"))
    Base.metadata.create_all(engine)
    engine.dispose()
    declarative_schema = _sync_reflect(declarative_file)

    # every table and column the ORM declares must exist with the same nullability;
    # alembic_version is the one legitimate extra table on the migrated side.
    assert set(migrated_schema) - {"alembic_version"} == set(declarative_schema)
    for table, expected in declarative_schema.items():
        assert migrated_schema[table]["columns"] == expected["columns"], table
        assert migrated_schema[table]["indexes"] == expected["indexes"], table


def test_alembic_current_reports_the_head_revision_after_upgrade(tmp_path):
    url, _ = _sqlite_url(tmp_path)
    _run("upgrade", "head", db_url=url)
    heads = _run("heads", db_url=url)
    current = _run("current", db_url=url)
    assert heads.returncode == current.returncode == 0
    head_rev = heads.stdout.strip().split()[0]
    assert head_rev in current.stdout


# ------------------------------------------------------------------ downgrade actually works
def test_alembic_downgrade_to_base_then_upgrade_again_round_trips(tmp_path):
    url, f = _sqlite_url(tmp_path)
    up1 = _run("upgrade", "head", db_url=url)
    assert up1.returncode == 0, up1.stdout + up1.stderr
    assert set(_sync_reflect(f)) - {"alembic_version"}  # something was actually created

    down = _run("downgrade", "base", db_url=url)
    assert down.returncode == 0, down.stdout + down.stderr
    after_down = _sync_reflect(f)
    assert set(after_down) - {"alembic_version"} == set()  # every app table is gone

    up2 = _run("upgrade", "head", db_url=url)
    assert up2.returncode == 0, up2.stdout + up2.stderr
    assert "users" in _sync_reflect(f)  # rebuilt cleanly a second time


def test_running_upgrade_head_twice_is_a_safe_no_op(tmp_path):
    """Idempotence: re-running the deploy step (e.g. a retried CI job) must not fail or double-apply."""
    url, _ = _sqlite_url(tmp_path)
    first = _run("upgrade", "head", db_url=url)
    second = _run("upgrade", "head", db_url=url)
    assert first.returncode == 0 and second.returncode == 0, second.stdout + second.stderr


# ------------------------------------------------------------------ app-level: create_all defers to Alembic
async def test_create_all_populates_a_fresh_dev_database():
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    async with db.session() as s:
        s.add(User(email="a@x.com"))
        await s.commit()  # would raise if the table didn't exist
    await db.dispose()


async def test_create_all_defers_to_a_migration_managed_database(tmp_path):
    """If WENSDAY_AUTO_CREATE_TABLES=true is left on by mistake against a database that Alembic
    already owns (alembic_version present), create_all must not run — it would silently mask a
    genuinely missing migration for any table added to app/models.py after the last revision."""
    f = tmp_path / "migrated.sqlite3"
    db = Database(f"sqlite+aiosqlite:///{f.as_posix()}")
    async with db.engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))

    await db.create_all()  # must be a no-op

    async with db.engine.begin() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert tables == ["alembic_version"]  # none of the ORM's tables were created
    await db.dispose()


# ------------------------------------------------------------------ PostgreSQL compatibility
def test_migration_sql_compiles_for_postgresql_with_no_live_server(tmp_path):
    """Offline SQL emission: Alembic renders the migration's DDL for a chosen dialect without
    ever opening a connection. This proves the *migration*, not just SQLAlchemy's CreateTable,
    is valid PostgreSQL — no live server is available in this environment to test against."""
    r = _run("upgrade", "head", "--sql", db_url="postgresql://wensday:wensday@localhost/wensday")
    assert r.returncode == 0, r.stdout + r.stderr
    sql = r.stdout
    assert "CREATE TABLE" in sql and "users" in sql
    assert "CREATE TABLE alembic_version" in sql or "alembic_version" in sql
    # a handful of PostgreSQL-specific renderings that would look different (or fail) on SQLite
    assert "VARCHAR(320)" in sql or "VARCHAR (320)" in sql  # String(320) -> VARCHAR, not TEXT
    assert "REFERENCES" in sql  # foreign keys render as real constraints, not SQLite's inline form


def test_migration_sql_is_deterministic_across_runs():
    """Same inputs, same SQL — a prerequisite for trusting `--sql` output in a review/approval
    workflow (e.g. a DBA reviewing the exact DDL before it runs against production)."""
    a = _run("upgrade", "head", "--sql", db_url="postgresql://wensday:wensday@localhost/wensday")
    b = _run("upgrade", "head", "--sql", db_url="postgresql://wensday:wensday@localhost/wensday")
    assert a.returncode == b.returncode == 0
    assert a.stdout == b.stdout


# ------------------------------------------------------------------ no drift between models and migration
def test_autogenerate_detects_no_further_changes_against_head():
    """If this fails, app/models.py has drifted from the committed migration — the two most
    common causes are a model changed without a new revision, or a revision edited by hand
    after models moved on. Uses a unique scratch dir so it never collides with `versions/`."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        tmp_db = Path(d) / f"drift-{uuid.uuid4().hex}.sqlite3"
        url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
        _run("upgrade", "head", db_url=url)
        r = _run("check", db_url=url)
        assert r.returncode == 0, "app/models.py has changes not captured by a migration:\n" + r.stdout + r.stderr
