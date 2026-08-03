"""Database models for wealthdock-server."""

import datetime
import uuid
from typing import Any

from sqlalchemy import Boolean, DateTime, String, TypeDecorator, Uuid, func, true
from sqlalchemy.orm import Mapped, mapped_column, validates

from wealthdock_server.db.base import Base


class TZDateTime(TypeDecorator[datetime.datetime]):
    """DateTime type that ensures timezone-awareness, even on SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime.datetime | None, _dialect: Any
    ) -> datetime.datetime | None:
        """Verify the datetime is timezone-aware and convert to UTC before binding."""
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("datetime must be timezone-aware")
            return value.astimezone(datetime.UTC)
        return value

    def process_result_value(
        self, value: datetime.datetime | None, _dialect: Any
    ) -> datetime.datetime | None:
        """Assure timezone-awareness on datetime retrieved from database."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value


def utcnow() -> datetime.datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.datetime.now(datetime.UTC)


class User(Base):
    """User database model for registration, auth, and session sync."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )

    @validates("email")
    def validate_email(self, _key: str, value: str) -> str:
        """Normalize the email address to lowercase and strip whitespaces."""
        if value is not None:
            return value.lower().strip()
        return value
