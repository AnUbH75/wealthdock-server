"""Smoke tests for the FastAPI app."""

from collections.abc import Generator
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from wealthdock_server.db import session as db_session
from wealthdock_server.db.session import (
    dispose_global_engine,
    get_db,
    get_standalone_session,
)
from wealthdock_server.main import app, create_app


@pytest.fixture
def restore_global_engine() -> Generator[None, None, None]:
    """Fixture that saves and restores db_session global engine/factory state."""
    old_engine = db_session._global_engine
    old_factory = db_session._global_session_factory
    try:
        yield
    finally:
        db_session._global_engine = old_engine
        db_session._global_session_factory = old_factory


async def test_health_check() -> None:
    """Verify health check endpoint returns 200 ok."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_lifespan_disposes_engine() -> None:
    """Verify that database engine is created on startup and disposed on shutdown."""
    test_app = create_app()

    with patch.object(AsyncEngine, "dispose", new_callable=AsyncMock) as mock_dispose:
        with TestClient(test_app):
            # Verify db_engine is set during startup
            assert hasattr(test_app.state, "db_engine")
            assert hasattr(test_app.state, "db_session_factory")

        # Verify engine.dispose was called when TestClient context exited
        mock_dispose.assert_awaited_once()


async def test_get_db_from_request_state() -> None:
    """Verify get_db uses request-scoped session factory and raises if missing."""
    # 1. Test get_db with request object having the session factory
    mock_request = MagicMock()
    mock_request.app.state.db_session_factory = MagicMock(return_value=AsyncMock())

    generator = get_db(mock_request)
    session = await generator.__anext__()
    assert session is not None
    mock_request.app.state.db_session_factory.assert_called_once()

    # Clean up generator
    with suppress(StopAsyncIteration):
        await generator.__anext__()

    # 2. Test get_db raises RuntimeError when session factory is missing
    mock_bad_request = MagicMock(spec=[])
    bad_generator = get_db(mock_bad_request)
    with pytest.raises(RuntimeError, match="Database session factory is not initialized"):
        await bad_generator.__anext__()


@pytest.mark.asyncio
async def test_global_engine_memoization_and_disposal(restore_global_engine: None) -> None:
    """Verify memoization and disposal of the global fallback engine."""
    with patch("wealthdock_server.db.session.create_async_engine") as mock_create_engine:
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        db_session._global_engine = None
        db_session._global_session_factory = None

        factory1 = db_session._get_global_session_factory()
        factory2 = db_session._get_global_session_factory()

        assert factory1 is factory2
        mock_create_engine.assert_called_once()

        await dispose_global_engine()
        mock_engine.dispose.assert_awaited_once()
        assert db_session._global_engine is None
        assert db_session._global_session_factory is None


@pytest.mark.asyncio
async def test_get_standalone_session() -> None:
    """Verify standalone session context manager creates session and disposes engine on exit."""
    with patch("wealthdock_server.db.session.create_async_engine") as mock_create_engine:
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_engine.dispose = AsyncMock()
        mock_create_engine.return_value = mock_engine

        with patch("wealthdock_server.db.session.async_sessionmaker") as mock_session_maker:
            mock_session = AsyncMock()
            mock_factory = MagicMock(
                return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session))
            )
            mock_session_maker.return_value = mock_factory

            async with get_standalone_session() as session:
                assert session is not None

            mock_engine.dispose.assert_awaited_once()


def test_get_db_fastapi_dependency_injection() -> None:
    """Verify get_db works through FastAPI dependency resolution machinery."""
    test_app = create_app()
            fallback_generator = get_db(None)  # type: ignore[arg-type]
            await fallback_generator.__anext__()

    @test_app.get("/test-db-route")
    async def test_route(db: AsyncSession = Depends(get_db)) -> dict[str, str]:  # noqa: B008
        assert db is not None
        return {"status": "ok"}

    with TestClient(test_app) as client:
        res = client.get("/test-db-route")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
