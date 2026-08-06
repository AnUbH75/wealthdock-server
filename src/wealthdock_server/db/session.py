"""Async SQLAlchemy engine/session setup and FastAPI dependency."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wealthdock_server.core.config import get_settings

# Global engine and session factory for non-app contexts (CLI, standalone scripts)
_global_engine: AsyncEngine | None = None
_global_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_global_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return memoized global session factory for standalone/non-app contexts."""
    global _global_engine, _global_session_factory
    if _global_session_factory is None:
        _global_engine = create_async_engine(get_settings().database_url, echo=False)
        _global_session_factory = async_sessionmaker(_global_engine, expire_on_commit=False)
    return _global_session_factory


async def dispose_global_engine() -> None:
    """Dispose of the global database engine if initialized."""
    global _global_engine, _global_session_factory
    if _global_engine is not None:
        await _global_engine.dispose()
        _global_engine = None
        _global_session_factory = None
async def get_db(request: Request = None) -> AsyncGenerator[AsyncSession, None]:  # type: ignore[assignment]
    """Yield a request-scoped async database session."""
    if request is not None and hasattr(request.app.state, "db_session_factory"):
        session_factory = request.app.state.db_session_factory
    else:
        session_factory = _get_global_session_factory()


@asynccontextmanager
async def get_standalone_session() -> AsyncIterator[AsyncSession]:
    """Async context manager to yield a database session for CLI tools and scripts.

    Creates a dedicated database engine and session factory, disposing of the
    engine on exit.
    """
    engine = create_async_engine(get_settings().database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async database session from app state."""
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    factory = getattr(state, "db_session_factory", None)
    if factory is None:
        raise RuntimeError("Database session factory is not initialized on app.state.")

    async with factory() as session:
        yield session
