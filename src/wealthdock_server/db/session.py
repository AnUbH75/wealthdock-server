"""Async SQLAlchemy engine/session setup and FastAPI dependency."""

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from wealthdock_server.core.config import get_settings

# Global fallback engine for non-app contexts (like CLI/scripts/testing fallback)
_global_engine = None


def _get_global_session_factory() -> async_sessionmaker[AsyncSession]:
    global _global_engine
    if _global_engine is None:
        _global_engine = create_async_engine(get_settings().database_url, echo=False)
    return async_sessionmaker(_global_engine, expire_on_commit=False)


async def get_db(request: Request = None) -> AsyncGenerator[AsyncSession, None]:  # type: ignore[assignment]
    """Yield a request-scoped async database session."""
    if request is not None and hasattr(request.app.state, "db_session_factory"):
        session_factory = request.app.state.db_session_factory
    else:
        session_factory = _get_global_session_factory()

    async with session_factory() as session:
        yield session
