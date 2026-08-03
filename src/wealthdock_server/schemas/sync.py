"""Pydantic schemas for synchronization endpoints."""

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

DEFAULT_EMPTY_PAYLOAD: dict[str, list[Any]] = {
    "assets": [],
    "budgets": [],
    "transactions": [],
}
DEFAULT_SYNC_PAYLOAD = json.dumps(DEFAULT_EMPTY_PAYLOAD)


class SyncPayload(BaseModel):
    """Schema representing the sync data payload."""

    payload: str = Field(
        ...,
        max_length=100000,
        description="JSON-encoded string representing sync state.",
    )
    version: int = Field(
        ...,
        description="Monotonically increasing version for optimistic concurrency.",
    )

    @field_validator("payload")
    @classmethod
    def validate_json_payload(cls, v: str) -> str:
        """Verify that payload is a valid JSON string."""
        try:
            json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError("Payload must be a valid JSON-encoded string.") from e
        return v
