"""Smoke tests for the FastAPI app."""

from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from wealthdock_server.db.session import get_db
from wealthdock_server.main import app, create_app


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
    """Verify get_db uses request-scoped session factory or global fallback."""
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

    # 2. Test get_db fallback without request (global fallback)
    with patch("wealthdock_server.db.session.create_async_engine") as mock_create_engine:
        mock_session_maker = MagicMock(return_value=AsyncMock())
        patch_path = "wealthdock_server.db.session.async_sessionmaker"
        with patch(patch_path, return_value=mock_session_maker):
            # Reset global engine to force recreation
            from wealthdock_server.db import session as db_session

            db_session._global_engine = None

            fallback_generator = get_db(None)  # type: ignore[arg-type]
            await fallback_generator.__anext__()

            mock_create_engine.assert_called_once()
            mock_session_maker.assert_called_once()

            # Clean up fallback generator
            with suppress(StopAsyncIteration):
                await fallback_generator.__anext__()
