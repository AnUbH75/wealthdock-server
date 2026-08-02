"""Pydantic schemas for the cross-device sync API."""

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SyncItemSchema(BaseModel):
    """Schema representing a single syncable item."""

    id: str = Field(..., description="Unique client-generated ID (typically UUID).")
    type: str = Field(..., description="Type of the record (e.g. 'account', 'transaction').")
    data: dict[str, Any] = Field(..., description="Arbitrary JSON data payload.")
    updated_at: datetime.datetime = Field(
        ..., description="Timestamp indicating when the client last modified the item."
    )
    deleted: bool = Field(False, description="Flag indicating if the item has been soft-deleted.")

    model_config = ConfigDict(from_attributes=True)


class SyncRequest(BaseModel):
    """Schema for incoming sync requests."""

    since: datetime.datetime | None = Field(
        None, description="The client's last sync point. Returns changes modified after this."
    )
    changes: list[SyncItemSchema] = Field(
        default_factory=list, description="A list of locally changed items to upload."
    )


class SyncResponse(BaseModel):
    """Schema for outgoing sync responses."""

    sync_point: datetime.datetime = Field(
        ..., description="The server's current timestamp to use as 'since' in the next sync."
    )
    changes: list[SyncItemSchema] = Field(
        ..., description="A list of items modified since the client's last sync point."
    )
