"""Async SQLAlchemy engine and session management."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


class Database:
    """Owns the async engine and session factory for the application's lifetime."""

    def __init__(self, url: str, *, pool_size: int = 10, max_overflow: int = 10) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        """Build a database from application settings."""
        return cls(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )

    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session; roll back on error so connections are never left dirty."""
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        """Close all pooled connections."""
        await self.engine.dispose()
