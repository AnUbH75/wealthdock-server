"""Database models for wealthdock-server."""

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, validates

from wealthdock_server.db.base import Base


def utcnow() -> datetime.datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.datetime.now(datetime.UTC)


class User(Base):
    """User database model for registration, auth, and session sync."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    @validates("email")
    def validate_email(self, _key: str, value: str) -> str:
        """Normalize the email address to lowercase and strip whitespaces."""
        if value is not None:
            return value.lower().strip()
        return value


class SyncState(Base):
    """Stores sync payloads for a user to keep multiple devices consistent."""

    __tablename__ = "sync_states"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    payload: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
