"""Async engine creation, session factory, and database initialization."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from baloo.db.models import Base

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None


def get_engine(database_url: str):
    """Create or return the async engine singleton."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(database_url, echo=False)
    return _engine


def get_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Create or return the async session factory singleton."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine(database_url)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def init_db(database_url: str) -> None:
    """Initialize the database: create tables if they don't exist."""
    engine = get_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")


async def close_db() -> None:
    """Dispose of the engine connection pool."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection closed")


def reset_engine() -> None:
    """Reset engine and session factory singletons (for testing)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
