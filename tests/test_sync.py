"""Tests for the cross-device synchronization API and SyncState model."""

import datetime
import gzip
import json
import uuid
from collections.abc import AsyncGenerator
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt  # type: ignore[import-untyped]
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from wealthdock_server.core.config import get_settings
from wealthdock_server.db.base import Base
from wealthdock_server.db.models import SyncState, User
from wealthdock_server.db.session import get_db
from wealthdock_server.main import app

# Create in-memory SQLite engine and session factory for isolated testing
test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


def test_sync_state_model_creation() -> None:
    """Verify SyncState model attributes, relationships, and persistence."""
    engine = create_engine("sqlite:///", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    # 1. Create a user and sync state
    with session_factory() as session:
        user = User(
            email="sync_model@example.com",
            hashed_password="hashed_secure_password",
        )
        session.add(user)
        session.commit()
        user_id = user.id

        sync_state = SyncState(
            user_id=user_id,
            payload={"assets": []},
            version=1,
        )
        session.add(sync_state)
        session.commit()

    # 2. Fetch and assert the created sync state record
    with session_factory() as session:
        queried = session.get(SyncState, user_id)
        assert queried is not None
        assert queried.user_id == user_id
        assert queried.payload == {"assets": []}
        assert queried.version == 1
        assert isinstance(queried.updated_at, datetime.datetime)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency override to use the in-memory SQLite database session."""
    async with test_session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def setup_db() -> AsyncGenerator[None, None]:
    """Re-create the database tables before each test case and manage overrides."""
    app.dependency_overrides[get_db] = override_get_db
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.clear()


def create_token(email: str) -> str:
    """Generate a JWT test token."""
    settings = get_settings()
    payload = {
        "sub": email,
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=30),
    }
    return cast(
        str,
        jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm),
    )


async def seed_user(email: str) -> uuid.UUID:
    """Helper to seed a user in the test database and return its ID."""
    async with test_session_factory() as session:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=email,
            hashed_password="hashedpassword",
        )
        session.add(user)
        await session.commit()
        return user_id


@pytest.mark.asyncio
async def test_unauthenticated_sync_denied() -> None:
    """Verify that unauthenticated requests to the sync endpoint are blocked."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/sync", json={"since": None, "changes": []})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_initial_sync_and_push() -> None:
    """Verify clean pull on empty DB and basic push capabilities for authenticated user."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Pull with since=None and no changes
        res = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": []},
            headers=headers,
        )
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
        res = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item]},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["changes"]) == 1
        assert data["changes"][0]["id"] == "uuid-1"


@pytest.mark.asyncio
async def test_user_data_isolation() -> None:
    """Verify that user A cannot see or modify user B's synced records."""
    # Seed two separate users
    await seed_user("userA@example.com")
    await seed_user("userB@example.com")
    token_a = create_token("userA@example.com")
    token_b = create_token("userB@example.com")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User A pushes a record
        t1 = datetime.datetime.now(datetime.UTC).isoformat()
        item = {
            "id": "record-1",
            "type": "account",
            "data": {"name": "User A Account"},
            "updated_at": t1,
            "deleted": False,
        }
        res = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item]},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res.status_code == 200

        # User B pulls, should NOT see User A's record
        res_pull = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": []},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert res_pull.status_code == 200
        data_pull = res_pull.json()
        assert len(data_pull["changes"]) == 0

        # User B attempts to push to User A's record ID
        item_skewed = {
            "id": "record-1",
            "type": "account",
            "data": {"name": "Hijacked"},
            "updated_at": t1,
            "deleted": False,
        }
        res_hijack = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item_skewed]},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert res_hijack.status_code == 200

        # Verify that User A's record is unchanged and not hijacked
        res_verify = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": []},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        data_verify = res_verify.json()
        assert len(data_verify["changes"]) == 1
        assert data_verify["changes"][0]["data"] == {"name": "User A Account"}


@pytest.mark.asyncio
async def test_sync_conflict_resolution_lww() -> None:
    """Verify that concurrent edits resolve using Last-Write-Wins based on timestamps."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

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
        await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item]},
            headers=headers,
        )

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
            "/api/v1/sync",
            json={"since": t0.isoformat(), "changes": [older_item]},
            headers=headers,
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
            "/api/v1/sync",
            json={"since": t1.isoformat(), "changes": [newer_item]},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()

        # The response must contain the updated newer version
        assert len(data["changes"]) == 1
        assert data["changes"][0]["data"] == {
            "name": "Savings-New",
            "balance": 200.0,
        }


@pytest.mark.asyncio
async def test_sync_since_filtering_on_server_time() -> None:
    """Verify that filtering runs on server_updated_at rather than client updated_at."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Push item 1 with client timestamp = Monday
        t_monday = datetime.datetime(2026, 8, 3, 10, 0, 0, tzinfo=datetime.UTC)
        item1 = {
            "id": "uuid-1",
            "type": "account",
            "data": {"balance": 100},
            "updated_at": t_monday.isoformat(),
            "deleted": False,
        }
        res1 = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item1]},
            headers=headers,
        )
        assert res1.status_code == 200
        sync_point_after_1 = res1.json()["sync_point"]

        # Push item 2 with client timestamp = Sunday (e.g. offline change)
        t_sunday = datetime.datetime(2026, 8, 2, 10, 0, 0, tzinfo=datetime.UTC)
        item2 = {
            "id": "uuid-2",
            "type": "account",
            "data": {"balance": 200},
            "updated_at": t_sunday.isoformat(),
            "deleted": False,
        }
        res2 = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item2]},
            headers=headers,
        )
        assert res2.status_code == 200

        # Pull changes since sync_point_after_1. Even though item2 has an older
        # client updated_at, it was written later, so server_updated_at >
        # sync_point_after_1 is true.
        res_pull = await client.post(
            "/api/v1/sync",
            json={"since": sync_point_after_1, "changes": []},
            headers=headers,
        )
        assert res_pull.status_code == 200
        changes = res_pull.json()["changes"]
        assert len(changes) == 1
        assert changes[0]["id"] == "uuid-2"


@pytest.mark.asyncio
async def test_soft_deletion() -> None:
    """Verify that soft-deleted items are stored and returned as tombstones."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Push active item
        t1 = datetime.datetime.now(datetime.UTC).isoformat()
        item = {
            "id": "del-1",
            "type": "account",
            "data": {"balance": 100},
            "updated_at": t1,
            "deleted": False,
        }
        await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item]},
            headers=headers,
        )

        # Push tombstone with newer timestamp
        t2 = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)).isoformat()
        deleted_item = {
            "id": "del-1",
            "type": "account",
            "data": {"balance": 100},
            "updated_at": t2,
            "deleted": True,
        }
        await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [deleted_item]},
            headers=headers,
        )

        # Pull and assert tombstone is returned
        res = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": []},
            headers=headers,
        )
        assert res.status_code == 200
        changes = res.json()["changes"]
        assert len(changes) == 1
        assert changes[0]["deleted"] is True


@pytest.mark.asyncio
async def test_timestamp_clamping() -> None:
    """Verify client timestamps far in the future are clamped to server time."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        future_time = datetime.datetime(2099, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
        item = {
            "id": "clamp-1",
            "type": "account",
            "data": {},
            "updated_at": future_time.isoformat(),
            "deleted": False,
        }
        res = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item]},
            headers=headers,
        )
        assert res.status_code == 200
        sync_point = res.json()["sync_point"]

        # Pull and verify that the updated_at was clamped and doesn't remain 2099
        res_pull = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": []},
            headers=headers,
        )
        changes = res_pull.json()["changes"]
        assert len(changes) == 1
        # The stored updated_at should be <= the returned sync_point
        assert datetime.datetime.fromisoformat(
            changes[0]["updated_at"]
        ) <= datetime.datetime.fromisoformat(sync_point)


@pytest.mark.asyncio
async def test_sync_keyset_pagination() -> None:
    """Verify keyset pagination works correctly for records with identical server_updated_at."""
    from unittest.mock import patch

    import wealthdock_server.api.v1.sync

    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    base_time = datetime.datetime.now(datetime.UTC)
    t1 = (base_time - datetime.timedelta(hours=3)).isoformat()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Upload 3 records in a single request. They will have the exact same server_updated_at.
        changes_in = [
            {"id": "item-a", "type": "asset", "data": {}, "updated_at": t1, "deleted": False},
            {"id": "item-b", "type": "asset", "data": {}, "updated_at": t1, "deleted": False},
            {"id": "item-c", "type": "asset", "data": {}, "updated_at": t1, "deleted": False},
        ]
        res = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": changes_in},
            headers=headers,
        )
        assert res.status_code == 200

        # 2. Pull with PAGE_LIMIT overridden to 2
        with patch.object(wealthdock_server.api.v1.sync, "PAGE_LIMIT", 2):
            res_page1 = await client.post(
                "/api/v1/sync",
                json={"since": None, "changes": []},
                headers=headers,
            )
            assert res_page1.status_code == 200
            data1 = res_page1.json()
            assert len(data1["changes"]) == 2
            # Keyset pagination should sort by ID, so item-a and item-b should be returned
            ids1 = [c["id"] for c in data1["changes"]]
            assert ids1 == ["item-a", "item-b"]
            assert data1["last_seen_id"] == "item-b"

            # 3. Pull page 2 using the composite cursor (sync_point + last_seen_id)
            res_page2 = await client.post(
                "/api/v1/sync",
                json={
                    "since": data1["sync_point"],
                    "last_seen_id": data1["last_seen_id"],
                    "changes": [],
                },
                headers=headers,
            )
            assert res_page2.status_code == 200
            data2 = res_page2.json()
            assert len(data2["changes"]) == 1
            assert data2["changes"][0]["id"] == "item-c"
            assert data2["last_seen_id"] is None


@pytest.mark.asyncio
async def test_sync_database_upsert_lww() -> None:
    """Verify that database-level upserts resolve conflicts correctly using LWW."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    base_time = datetime.datetime.now(datetime.UTC)
    t1 = (base_time - datetime.timedelta(hours=3)).isoformat()
    t2 = (base_time - datetime.timedelta(hours=2)).isoformat()
    t3 = (base_time - datetime.timedelta(hours=4)).isoformat()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Insert record initially
        item1 = {
            "id": "upsert-1",
            "type": "asset",
            "data": {"value": 10},
            "updated_at": t1,
            "deleted": False,
        }
        res1 = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item1]},
            headers=headers,
        )
        assert res1.status_code == 200

        # 2. Update with newer timestamp (should succeed)
        item2 = {
            "id": "upsert-1",
            "type": "asset",
            "data": {"value": 20},
            "updated_at": t2,
            "deleted": False,
        }
        res2 = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item2]},
            headers=headers,
        )
        assert res2.status_code == 200

        # 3. Pull changes and verify value is updated to 20
        res_pull1 = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": []},
            headers=headers,
        )
        changes = res_pull1.json()["changes"]
        assert len(changes) == 1
        assert changes[0]["data"] == {"value": 20}

        # 4. Attempt update with older timestamp (should NOT update)
        item3 = {
            "id": "upsert-1",
            "type": "asset",
            "data": {"value": 5},
            "updated_at": t3,
            "deleted": False,
        }
        res3 = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": [item3]},
            headers=headers,
        )
        assert res3.status_code == 200

        # 5. Pull changes and verify value remains 20 (LWW)
        res_pull2 = await client.post(
            "/api/v1/sync",
            json={"since": None, "changes": []},
            headers=headers,
        )
        changes2 = res_pull2.json()["changes"]
        assert len(changes2) == 1
        assert changes2[0]["data"] == {"value": 20}


@pytest.mark.asyncio
async def test_sync_gzip_request_decompression() -> None:
    """Verify that gzip-compressed sync request payloads are decompressed correctly."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)

    # 1. Send small payload compressed with gzip
    small_data = {"payload": json.dumps({"assets": [{"id": "1", "value": 100}]}), "version": 0}
    compressed_small = gzip.compress(json.dumps(small_data).encode("utf-8"))

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Encoding": "gzip",
        "Content-Type": "application/json",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/sync", content=compressed_small, headers=headers)
        assert res.status_code == 200
        response_json = res.json()
        assert response_json["version"] == 1
        assert json.loads(response_json["payload"]) == {"assets": [{"id": "1", "value": 100}]}

    # 2. Send large payload compressed with gzip
    large_assets = [{"id": str(i), "value": float(i * 100)} for i in range(100)]
    large_data = {"payload": json.dumps({"assets": large_assets}), "version": 1}
    compressed_large = gzip.compress(json.dumps(large_data).encode("utf-8"))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/sync", content=compressed_large, headers=headers)
        assert res.status_code == 200
        response_json = res.json()
        assert response_json["version"] == 2
        assert json.loads(response_json["payload"]) == {"assets": large_assets}


@pytest.mark.asyncio
async def test_sync_gzip_response_compression() -> None:
    """Verify that sync responses are compressed with gzip when client requests it."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "gzip",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Trigger sync to store a large payload in DB
        large_assets = [{"id": str(i), "value": float(i * 100)} for i in range(100)]
        post_data = {"payload": json.dumps({"assets": large_assets}), "version": 0}
        post_res = await client.post("/api/v1/sync", json=post_data, headers=headers)
        assert post_res.status_code == 200

        # The POST response should be gzipped since the payload exceeds 1000 bytes
        assert post_res.headers.get("content-encoding") == "gzip"
        res_json = post_res.json()
        assert res_json["version"] == 1
        assert json.loads(res_json["payload"]) == {"assets": large_assets}

        # 2. Get sync state with Accept-Encoding: gzip
        get_res = await client.get("/api/v1/sync", headers=headers)
        assert get_res.status_code == 200
        assert get_res.headers.get("content-encoding") == "gzip"
        get_json = get_res.json()
        assert get_json["version"] == 1
        assert json.loads(get_json["payload"]) == {"assets": large_assets}


@pytest.mark.asyncio
async def test_sync_gzip_decompression_limit() -> None:
    """Verify that gzip-compressed sync request payloads exceeding the limit are rejected with 413."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)

    # 10MB + 1 byte of data
    huge_data = b"a" * (10 * 1024 * 1024 + 1)
    compressed_huge = gzip.compress(huge_data)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Encoding": "gzip",
        "Content-Type": "application/json",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/sync", content=compressed_huge, headers=headers)
        assert res.status_code == 413
        assert "exceeds maximum limit" in res.json()["detail"]


@pytest.mark.asyncio
async def test_sync_gzip_decompression_invalid() -> None:
    """Verify that invalid/malformed gzip payloads are rejected with 400 Bad Request."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Encoding": "gzip",
        "Content-Type": "application/json",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/sync", content=b"invalid-gzip-payload", headers=headers)
        assert res.status_code == 400
        assert "Invalid gzip payload" in res.json()["detail"]
