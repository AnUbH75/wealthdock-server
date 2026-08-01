"""Async SQLAlchemy engine/session setup and FastAPI dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from wealthdock_server.core.config import get_settings

engine = create_async_engine(get_settings().database_url, echo=False)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield a request-scoped async database session."""
    async with async_session_factory() as session:
        yield session
