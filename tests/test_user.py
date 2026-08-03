"""Unit tests for the User database model."""

import datetime
import gc
import uuid
from collections.abc import Generator
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from wealthdock_server.core.config import get_settings
from wealthdock_server.db.models import User


@pytest.fixture
def db_session_factory() -> Generator[sessionmaker[Session], None, None]:
    """Run migrations on a temporary SQLite database and yield session factory."""
    db_file = "test_user_temp.db"
    db_path = Path(db_file)
    db_url_async = f"sqlite+aiosqlite:///{db_file}"
    db_url_sync = f"sqlite:///{db_file}"

    # Remove any existing temp database file
    with suppress(OSError):
        db_path.unlink(missing_ok=True)

    # Set DATABASE_URL env var for Alembic env.py to connect to
    import os

    os.environ["DATABASE_URL"] = db_url_async
    get_settings.cache_clear()

    # Run upgrade head to test the migrations execution
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    # Setup database connection and session maker
    engine = create_engine(db_url_sync, echo=False)
    session_factory = sessionmaker(bind=engine)

    yield session_factory

    # Teardown: close connections, run downgrade, and delete the temp db file
    engine.dispose()
    command.downgrade(alembic_cfg, "base")

    # Reset cache and env var
    os.environ.pop("DATABASE_URL", None)
    get_settings.cache_clear()

    # Clean up file
    gc.collect()
    with suppress(OSError):
        db_path.unlink(missing_ok=True)


def test_user_model_creation(db_session_factory: Any) -> None:
    """Verify User model attributes, defaults, and persistence using alembic migrations."""
    # 1. Create a new user record
    with db_session_factory() as session:
        user = User(
            email="Test@Example.com",  # Mixed casing to test normalization
            hashed_password="hashed_secure_password",
        )
        session.add(user)
        session.commit()
        user_id = user.id

        assert isinstance(user_id, uuid.UUID)
        assert user.is_active is True
        assert isinstance(user.created_at, datetime.datetime)
        assert user.created_at.tzinfo is not None  # Assert timezone-aware
        assert isinstance(user.updated_at, datetime.datetime)
        assert user.updated_at.tzinfo is not None  # Assert timezone-aware

    # 2. Fetch and assert the created record fields
    with db_session_factory() as session:
        queried = session.get(User, user_id)
        assert queried is not None
        assert queried.email == "test@example.com"  # Normalized to lowercase
        assert queried.hashed_password == "hashed_secure_password"
        assert queried.is_active is True
        assert queried.created_at.tzinfo is not None
        assert queried.updated_at.tzinfo is not None


def test_user_email_unique_and_normalized(db_session_factory: Any) -> None:
    """Verify email uniqueness constraints and case normalization logic."""
    # Create first user
    with db_session_factory() as session:
        user1 = User(email="test@example.com", hashed_password="pw")
        session.add(user1)
        session.commit()

    # Try creating second user with the same email
    with db_session_factory() as session:
        user2 = User(email="test@example.com", hashed_password="pw")
        session.add(user2)
        with pytest.raises(IntegrityError):
            session.commit()

    # Try creating second user with different casing but same email address
    with db_session_factory() as session:
        user3 = User(email="TEST@EXAMPLE.COM", hashed_password="pw")
        session.add(user3)
        with pytest.raises(IntegrityError):
            session.commit()
