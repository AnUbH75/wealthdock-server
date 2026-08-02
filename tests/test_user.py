"""Unit tests for the User database model."""

import datetime
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from wealthdock_server.db.base import Base
from wealthdock_server.db.models import User


def test_user_model_creation() -> None:
    """Verify User model attributes, defaults, and persistence."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    # 1. Create a new user record
    with session_factory() as session:
        user = User(
            email="test@example.com",
            hashed_password="hashed_secure_password",
        )
        session.add(user)
        session.commit()
        user_id = user.id

        assert isinstance(user_id, uuid.UUID)
        assert user.is_active is True
        assert isinstance(user.created_at, datetime.datetime)
        assert isinstance(user.updated_at, datetime.datetime)

    # 2. Fetch and assert the created record fields
    with session_factory() as session:
        queried = session.get(User, user_id)
        assert queried is not None
        assert queried.email == "test@example.com"
        assert queried.hashed_password == "hashed_secure_password"
        assert queried.is_active is True
