from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.db.base import Base

_engine = None
_session_factory = None


def init_engine(database_url: str, pool_size: int = 10, max_overflow: int = 20) -> None:
    global _engine, _session_factory
    kwargs: dict = {}
    # SQLite doesn't support pool_size/max_overflow
    if not database_url.startswith("sqlite"):
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = max_overflow
    _engine = create_async_engine(database_url, **kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables (dev/test). Production uses Alembic migrations."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session_factory() -> async_sessionmaker:
    return _session_factory


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session
