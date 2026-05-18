"""Async engine creation, session factory, and database initialization."""

import logging
from pathlib import Path

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


def _run_alembic_migrations(database_url: str) -> bool:
    """Run Alembic migrations synchronously.

    Uses a sync connection to avoid nested-async-loop issues when
    called from within an already-running event loop.

    If the database was previously managed by ``create_all`` (no
    ``alembic_version`` table), we stamp the baseline revision
    before running ``upgrade head``.

    Returns True if migrations ran, False otherwise.
    """
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        logger.warning("Alembic not installed, skipping migrations")
        return False

    project_root = Path(__file__).resolve().parent.parent.parent
    alembic_ini = project_root / "alembic.ini"

    if not alembic_ini.exists():
        logger.warning("alembic.ini not found at %s, skipping migrations", alembic_ini)
        return False

    # Convert async URL to sync for Alembic
    # e.g. postgresql+asyncpg:// -> postgresql://
    sync_url = database_url.replace("+asyncpg", "").replace("+aiosqlite", "")

    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
    # Point script_location to absolute path so it works from any cwd
    alembic_cfg.set_main_option(
        "script_location", str(project_root / "baloo" / "db" / "migrations")
    )

    # If the DB already has tables but no alembic_version table,
    # stamp the initial migration so Alembic doesn't try to re-create.
    try:
        import sqlalchemy

        sync_engine = sqlalchemy.create_engine(sync_url)
        inspector = sqlalchemy.inspect(sync_engine)
        tables = inspector.get_table_names()
        sync_engine.dispose()

        if "reviews" in tables and "alembic_version" not in tables:
            logger.info(
                "Existing DB without alembic_version detected, " "stamping baseline revision 001"
            )
            command.stamp(alembic_cfg, "001")
    except Exception as e:
        logger.warning("Could not inspect DB for stamping: %s", e)

    command.upgrade(alembic_cfg, "head")
    return True


async def init_db(database_url: str) -> None:
    """Initialize the database by running Alembic migrations.

    Runs ``alembic upgrade head`` so that every deployment
    automatically applies pending schema changes.
    Falls back to ``create_all`` only if Alembic is unavailable.
    """
    engine = get_engine(database_url)

    if _run_alembic_migrations(database_url):
        logger.info("Database migrations applied (alembic upgrade head)")
    else:
        logger.warning("Falling back to create_all (no migrations)")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized via create_all")

    # Clean up old execution logs
    from baloo.config.settings import get_settings

    settings = get_settings()
    if settings.log_retention_days > 0:
        await _cleanup_old_logs(engine, settings.log_retention_days)


async def _cleanup_old_logs(engine, retention_days: int) -> None:
    """Delete review_logs older than retention_days, scoped to current installation."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete

    from baloo.config.settings import get_settings
    from baloo.db.models import ReviewLog

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    installation_id = get_settings().installation_id
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                stmt = delete(ReviewLog).where(ReviewLog.created_at < cutoff)
                if installation_id:
                    stmt = stmt.where(ReviewLog.installation_id == installation_id)
                else:
                    stmt = stmt.where(ReviewLog.installation_id.is_(None))
                result = await session.execute(stmt)
                deleted = result.rowcount
                if deleted:
                    logger.info(
                        "Cleaned up %d review log entries older than %d days",
                        deleted,
                        retention_days,
                    )
    except Exception as exc:
        # Table may not exist yet on first run
        logger.debug("Log cleanup skipped: %s", exc)


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
