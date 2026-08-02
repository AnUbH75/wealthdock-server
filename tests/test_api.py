from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from wealthdock_server.db.base import Base
from wealthdock_server.db.session import get_db
from wealthdock_server.main import app

# In-memory SQLite async database for testing
DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        yield session


# Override the get_db dependency
app.dependency_overrides[get_db] = override_get_db


@pytest.mark.asyncio
async def test_auth_and_sync_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register a user
        reg_response = await client.post(
            "/api/v1/auth/register",
            json={"email": "api@example.com", "password": "secure_password"},
        )
        assert reg_response.status_code == 201
        data = reg_response.json()
        assert "access_token" in data
        assert data["email"] == "api@example.com"
        token = data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Login
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "api@example.com", "password": "secure_password"},
        )
        assert login_response.status_code == 200
        assert "access_token" in login_response.json()

        # 3. Get sync state (should be default empty structure)
        get_response = await client.get("/api/v1/sync", headers=headers)
        assert get_response.status_code == 200
        assert "payload" in get_response.json()
        assert "assets" in get_response.json()["payload"]

        # 4. Update sync state
        payload_data = '{"assets":[{"id":"1","name":"Test Savings","type":"bank","value":5000}]}'
        update_response = await client.post(
            "/api/v1/sync",
            headers=headers,
            json={"payload": payload_data},
        )
        assert update_response.status_code == 200
        assert update_response.json()["payload"] == payload_data

        # 5. Fetch updated state
        get_updated = await client.get("/api/v1/sync", headers=headers)
        assert get_updated.status_code == 200
        assert get_updated.json()["payload"] == payload_data
