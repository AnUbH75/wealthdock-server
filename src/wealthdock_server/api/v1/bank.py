"""API router for external bank connections and webhooks."""

import datetime
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from wealthdock_server.api.deps import get_current_user
from wealthdock_server.db.models import BankConnection, User
from wealthdock_server.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bank", tags=["bank"])


class BankConnectionCreate(BaseModel):
    """Schema for creating a bank connection link token."""

    provider: str = Field(..., description="The bank aggregator provider (e.g., plaid, gocardless)")


class LinkTokenResponse(BaseModel):
    """Schema for link token response."""

    link_token: str
    provider: str


class TokenExchangeRequest(BaseModel):
    """Schema for exchanging public token for access token."""

    public_token: str
    provider: str
    item_id: str


class BankConnectionResponse(BaseModel):
    """Schema for returning bank connection metadata."""

    id: uuid.UUID
    provider: str
    item_id: str
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/connections", response_model=LinkTokenResponse, status_code=status.HTTP_201_CREATED)
async def create_link_token(
    request: BankConnectionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
) -> Any:
    """Create a link token or initiate a bank authentication session."""
    logger.info("Creating link token for user: %s, provider: %s", current_user.id, request.provider)
    mock_token = f"link_token_{request.provider}_{uuid.uuid4().hex}"
    return LinkTokenResponse(link_token=mock_token, provider=request.provider)


@router.post(
    "/connections/exchange",
    response_model=BankConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def exchange_token(
    request: TokenExchangeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Exchange a temporary public token for a permanent access token and save connection."""
    logger.info(
        "Exchanging public token for user: %s, provider: %s",
        current_user.id,
        request.provider,
    )

    mock_access_token = f"access_token_{request.provider}_{uuid.uuid4().hex}"

    connection = BankConnection(
        user_id=current_user.id,
        provider=request.provider,
        item_id=request.item_id,
        access_token=mock_access_token,
        status="active",
    )

    db.add(connection)
    await db.commit()
    await db.refresh(connection)

    return connection


@router.post("/webhooks", status_code=status.HTTP_200_OK)
async def receive_webhook(
    payload: dict[str, Any],
) -> Any:
    """Public webhook receiver endpoint for aggregators to push updates."""
    logger.info("Received bank webhook payload: %s", payload)
    return {"status": "received"}
