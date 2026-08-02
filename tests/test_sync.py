"""Unit tests for the SyncState database model."""

import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from wealthdock_server.db.base import Base
from wealthdock_server.db.models import SyncState, User


def test_sync_state_model_creation() -> None:
    """Verify SyncState model attributes, relationships, and persistence."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    # 1. Create a user and sync state
    with session_factory() as session:
        user = User(
            email="sync@example.com",
            hashed_password="hashed_secure_password",
        )
        session.add(user)
        session.commit()
        user_id = user.id

        sync_state = SyncState(
            user_id=user_id,
            payload='{"assets": []}',
        )
        session.add(sync_state)
        session.commit()

    # 2. Fetch and assert the created sync state record
    with session_factory() as session:
        queried = session.get(SyncState, user_id)
        assert queried is not None
        assert queried.user_id == user_id
        assert queried.payload == '{"assets": []}'
        assert isinstance(queried.updated_at, datetime.datetime)
