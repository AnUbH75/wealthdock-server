from pydantic import BaseModel


class SyncPayload(BaseModel):
    """Schema representing the sync data payload."""

    payload: str
