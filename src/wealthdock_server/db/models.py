"""Database models for wealthdock-server."""

import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from wealthdock_server.db.base import Base


class SyncRecord(Base):
    """A single syncable record representing financial data/state.

    Uses a last-write-wins protocol via the `updated_at` timestamp.
    """

    __tablename__ = "sync_records"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
