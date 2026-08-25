import datetime
import hashlib
import hmac
import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from wealthdock_server.api.deps import get_current_user
from wealthdock_server.core.config import get_settings
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
    request: Request,
) -> Any:
    """Public webhook receiver endpoint for aggregators to push updates.

    Verifies the webhook signature header from Plaid or GoCardless.
    """
    body = await request.body()
    settings = get_settings()

    plaid_verification = request.headers.get("Plaid-Verification")
    gocardless_signature = request.headers.get("Webhook-Signature")

    if not plaid_verification and not gocardless_signature:
        logger.warning("Rejecting webhook: Missing signature header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature header",
        )

    if gocardless_signature:
        # Verify GoCardless signature using HMAC-SHA256
        secret = settings.gocardless_webhook_secret
        computed = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, gocardless_signature):
            logger.warning("Rejecting webhook: Invalid GoCardless signature")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid GoCardless webhook signature",
            )
        logger.info("GoCardless webhook signature verified successfully")

    elif plaid_verification:
        # Verify Plaid webhook signature
        # Plaid's signature is a JWT. We decode and verify it using settings.plaid_webhook_secret.
        try:
            payload = jwt.decode(
                plaid_verification,
                settings.plaid_webhook_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            # Verify body hash
            body_hash = hashlib.sha256(body).hexdigest()
            if payload.get("request_body_sha256") != body_hash:
                logger.warning("Rejecting webhook: Plaid body hash mismatch")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Plaid webhook payload hash mismatch",
                )
        except Exception as e:
            logger.warning("Rejecting webhook: Invalid Plaid signature: %s", e)
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid Plaid webhook signature: {e!s}",
            ) from e
        logger.info("Plaid webhook signature verified successfully")

    try:
        payload_data = json.loads(body) if body else {}
    except ValueError:
        payload_data = {}

    logger.info("Received authenticated bank webhook payload: %s", payload_data)
    return {"status": "received"}
