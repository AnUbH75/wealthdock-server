"""Smoke tests for the FastAPI app."""

from httpx import ASGITransport, AsyncClient

from wealthdock_server.main import app


async def test_health_check() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
