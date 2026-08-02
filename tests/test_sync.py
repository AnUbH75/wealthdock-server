"""Tests for the cross-device synchronization API."""

import datetime
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from wealthdock_server.db.base import Base
from wealthdock_server.db.session import get_db
from wealthdock_server.main import app

# Create in-memory SQLite engine and session factory for isolated testing
test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
async def setup_db() -> AsyncGenerator[None, None]:
    """Re-create the database tables before each test case."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency override to use the in-memory SQLite database session."""
    async with test_session_factory() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


async def test_initial_sync_and_push() -> None:
    """Verify clean pull on empty DB and basic push capabilities."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Pull with since=None and no changes
        res = await client.post("/api/v1/sync", json={"since": None, "changes": []})
        assert res.status_code == 200
        data = res.json()
        assert "sync_point" in data
        assert data["changes"] == []

        # 2. Push a new item
        t1 = datetime.datetime.now(datetime.UTC).isoformat()
        item = {
            "id": "uuid-1",
            "type": "account",
            "data": {"name": "Savings", "balance": 1000.5},
            "updated_at": t1,
            "deleted": False,
        }
        res = await client.post("/api/v1/sync", json={"since": None, "changes": [item]})
        assert res.status_code == 200
        data = res.json()
        assert len(data["changes"]) == 1
        assert data["changes"][0]["id"] == "uuid-1"


async def test_sync_conflict_resolution_lww() -> None:
    """Verify that concurrent edits resolve using Last-Write-Wins based on timestamps."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Setup: Push an item with timestamp T1
        t1 = datetime.datetime(2026, 8, 2, 12, 0, 0, tzinfo=datetime.UTC)
        item = {
            "id": "uuid-1",
            "type": "account",
            "data": {"name": "Savings", "balance": 100.0},
            "updated_at": t1.isoformat(),
            "deleted": False,
        }
        await client.post("/api/v1/sync", json={"since": None, "changes": [item]})

        # Scenario A: Push edit with older timestamp T0 (LWW rejects incoming)
        t0 = datetime.datetime(2026, 8, 2, 11, 0, 0, tzinfo=datetime.UTC)
        older_item = {
            "id": "uuid-1",
            "type": "account",
            "data": {"name": "Savings-Old", "balance": 50.0},
            "updated_at": t0.isoformat(),
            "deleted": False,
        }
        res = await client.post(
            "/api/v1/sync", json={"since": t0.isoformat(), "changes": [older_item]}
        )
        assert res.status_code == 200
        data = res.json()

        # The response must contain the newer server version since it wins conflict
        assert len(data["changes"]) == 1
        assert data["changes"][0]["id"] == "uuid-1"
        assert data["changes"][0]["data"] == {"name": "Savings", "balance": 100.0}

        # Scenario B: Push edit with newer timestamp T2 (LWW accepts incoming)
        t2 = datetime.datetime(2026, 8, 2, 13, 0, 0, tzinfo=datetime.UTC)
        newer_item = {
            "id": "uuid-1",
            "type": "account",
            "data": {"name": "Savings-New", "balance": 200.0},
            "updated_at": t2.isoformat(),
            "deleted": False,
        }
        res = await client.post(
            "/api/v1/sync", json={"since": t1.isoformat(), "changes": [newer_item]}
        )
        assert res.status_code == 200
        data = res.json()

        # The response must contain the updated newer version
        assert len(data["changes"]) == 1
        assert data["changes"][0]["data"] == {"name": "Savings-New", "balance": 200.0}


async def test_sync_since_filtering() -> None:
    """Verify that only updates modified after the client's last sync point are pulled."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Push two items at different times
        t1 = datetime.datetime(2026, 8, 2, 10, 0, 0, tzinfo=datetime.UTC)
        item1 = {
            "id": "uuid-1",
            "type": "account",
            "data": {"balance": 100},
            "updated_at": t1.isoformat(),
            "deleted": False,
        }
        t2 = datetime.datetime(2026, 8, 2, 11, 0, 0, tzinfo=datetime.UTC)
        item2 = {
            "id": "uuid-2",
            "type": "account",
            "data": {"balance": 200},
            "updated_at": t2.isoformat(),
            "deleted": False,
        }
        await client.post("/api/v1/sync", json={"changes": [item1, item2]})

        # Sync since t1 -> should return only item2 (since t2 > t1)
        res = await client.post("/api/v1/sync", json={"since": t1.isoformat(), "changes": []})
        assert res.status_code == 200
        data = res.json()
        assert len(data["changes"]) == 1
        assert data["changes"][0]["id"] == "uuid-2"
