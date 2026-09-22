from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

log = logging.getLogger("wensday.db")


class Database:
    """Owns the engine + session factory. One per app instance (tests build their own)."""

    def __init__(self, url: str):
        kwargs: dict = {}
        if url.startswith("sqlite") and ":memory:" in url:
            # a single shared connection so every session sees the same in-memory DB
            kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        """Dev/test convenience only. A database with an `alembic_version` table is managed by
        migrations (`alembic upgrade head`); `create_all` only ever *adds* missing tables and
        never alters existing ones, so running it there wouldn't corrupt anything, but it would
        mask a genuinely missing migration (a table alembic doesn't know about yet would silently
        appear via create_all instead of failing loudly). If `WENSDAY_AUTO_CREATE_TABLES=true` is
        left on by mistake in a migrated environment, skip it rather than paper over that."""
        from .models import Base

        async with self.engine.begin() as conn:
            if await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("alembic_version")):
                log.info("database is migration-managed (alembic_version present); skipping create_all")
                return
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self.sessionmaker()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database = request.app.state.db
    async with db.session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
