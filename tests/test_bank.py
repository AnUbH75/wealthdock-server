"""Tests for the external bank connections API and BankConnection model."""

import datetime
import uuid
from collections.abc import AsyncGenerator
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt  # type: ignore[import-untyped]
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from wealthdock_server.core.config import get_settings
from wealthdock_server.db.base import Base
from wealthdock_server.db.models import BankConnection, User
from wealthdock_server.db.session import get_db
from wealthdock_server.main import app

test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


def test_bank_connection_model_creation() -> None:
    """Verify BankConnection model attributes, relationships, and persistence."""
    engine = create_engine("sqlite:///", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        user = User(
            email="bank_model@example.com",
            hashed_password="hashed_secure_password",
        )
        session.add(user)
        session.commit()
        user_id = user.id

        connection = BankConnection(
            user_id=user_id,
            provider="plaid",
            item_id="item_12345",
            access_token="super_secret_access_token_123",
            status="active",
        )
        session.add(connection)
        session.commit()
        connection_id = connection.id

    with session_factory() as session:
        queried = session.get(BankConnection, connection_id)
        assert queried is not None
        assert queried.user_id == user_id
        assert queried.provider == "plaid"
        assert queried.item_id == "item_12345"
        assert queried.access_token == "super_secret_access_token_123"
        assert queried.status == "active"
        assert isinstance(queried.created_at, datetime.datetime)

        # Verify the access token is encrypted in the raw database
        result = session.execute(
            text("SELECT access_token FROM bank_connections WHERE item_id = :item_id"),
            {"item_id": "item_12345"},
        )
        raw_token = result.scalar()
        assert raw_token is not None
        assert raw_token != "super_secret_access_token_123"


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
async def test_unauthenticated_bank_endpoints_denied() -> None:
    """Verify that unauthenticated requests to bank connection routes are blocked."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # connections route
        res = await client.post("/api/v1/bank/connections", json={"provider": "plaid"})
        assert res.status_code == 401

        # exchange route
        res = await client.post(
            "/api/v1/bank/connections/exchange",
            json={"public_token": "pt_123", "provider": "plaid", "item_id": "it_123"},
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_create_link_token() -> None:
    """Verify link token creation for authenticated users."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/bank/connections",
            json={"provider": "gocardless"},
            headers=headers,
        )
        assert res.status_code == 201
        data = res.json()
        assert "link_token" in data
        assert data["provider"] == "gocardless"


@pytest.mark.asyncio
async def test_exchange_token() -> None:
    """Verify token exchange creates connection and returns metadata."""
    email = "user@example.com"
    await seed_user(email)
    token = create_token(email)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/bank/connections/exchange",
            json={"public_token": "pub_token_abc123", "provider": "plaid", "item_id": "item_xyz"},
            headers=headers,
        )
        assert res.status_code == 201
        data = res.json()
        assert "id" in data
        assert data["provider"] == "plaid"
        assert data["item_id"] == "item_xyz"
        assert data["status"] == "active"

        # Verify database connection state and encryption
        async with test_session_factory() as session:
            result = await session.execute(
                text("SELECT id, access_token FROM bank_connections WHERE item_id = 'item_xyz'")
            )
            row = result.fetchone()
            assert row is not None
            _, db_access_token = row
            assert db_access_token is not None
            assert not db_access_token.startswith("access_token_plaid_")


@pytest.mark.asyncio
async def test_receive_webhook_gocardless_valid() -> None:
    """Verify that a valid GoCardless signature is accepted."""
    import hashlib
    import hmac
    import json

    settings = get_settings()
    payload = {"webhook_type": "TRANSACTIONS", "item_id": "item_xyz"}
    body_bytes = json.dumps(payload).encode("utf-8")

    signature = hmac.new(
        settings.gocardless_webhook_secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    headers = {"Webhook-Signature": signature}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/bank/webhooks",
            content=body_bytes,
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json() == {"status": "received"}


@pytest.mark.asyncio
async def test_receive_webhook_plaid_valid() -> None:
    """Verify that a valid Plaid signature is accepted."""
    import hashlib
    import json

    from jose import jwt

    settings = get_settings()
    payload = {"webhook_type": "TRANSACTIONS", "item_id": "item_xyz"}
    body_bytes = json.dumps(payload).encode("utf-8")
    body_hash = hashlib.sha256(body_bytes).hexdigest()

    jwt_payload = {"request_body_sha256": body_hash}
    token = jwt.encode(jwt_payload, settings.plaid_webhook_secret, algorithm="HS256")

    headers = {"Plaid-Verification": token}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/bank/webhooks",
            content=body_bytes,
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json() == {"status": "received"}


@pytest.mark.asyncio
async def test_receive_webhook_invalid_signatures() -> None:
    """Verify that invalid signatures are rejected with 401 Unauthorized."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Missing signature
        res = await client.post(
            "/api/v1/bank/webhooks",
            json={"webhook_type": "TRANSACTIONS"},
        )
        assert res.status_code == 401
        assert "Missing webhook signature header" in res.json()["detail"]

        # 2. Invalid GoCardless signature
        res = await client.post(
            "/api/v1/bank/webhooks",
            json={"webhook_type": "TRANSACTIONS"},
            headers={"Webhook-Signature": "invalid-signature"},
        )
        assert res.status_code == 401
        assert "Invalid GoCardless webhook signature" in res.json()["detail"]

        # 3. Invalid Plaid signature (bad JWT)
        res = await client.post(
            "/api/v1/bank/webhooks",
            json={"webhook_type": "TRANSACTIONS"},
            headers={"Plaid-Verification": "invalid-jwt-token"},
        )
        assert res.status_code == 401
        assert "Invalid Plaid webhook signature" in res.json()["detail"]

        # 4. Plaid signature body hash mismatch
        from jose import jwt
        settings = get_settings()
        jwt_payload = {"request_body_sha256": "wrong-body-hash"}
        token = jwt.encode(jwt_payload, settings.plaid_webhook_secret, algorithm="HS256")
        res = await client.post(
            "/api/v1/bank/webhooks",
            content=b"some-payload",
            headers={"Plaid-Verification": token},
        )
        assert res.status_code == 401
        assert "Plaid webhook payload hash mismatch" in res.json()["detail"]
