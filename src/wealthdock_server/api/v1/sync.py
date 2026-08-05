"""API router for synchronization endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wealthdock_server.api.deps import get_current_user
from wealthdock_server.db.models import SyncState, User
from wealthdock_server.db.session import get_db
from wealthdock_server.schemas.sync import DEFAULT_SYNC_PAYLOAD, SyncPayload

router = APIRouter()


@router.get("", response_model=SyncPayload)
async def get_sync_state(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncPayload:
    """Retrieve the user's synced assets and configurations."""
    result = await db.execute(select(SyncState).where(SyncState.user_id == current_user.id))
    sync_state = result.scalar_one_or_none()
    if not sync_state:
        return SyncPayload(payload=DEFAULT_SYNC_PAYLOAD, version=0)
    return SyncPayload(payload=sync_state.payload, version=sync_state.version)


@router.post("", response_model=SyncPayload)
async def update_sync_state(
    payload_in: SyncPayload,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncPayload:
    """Update/synchronize user's assets and configurations using optimistic lock."""
    result = await db.execute(
        select(SyncState).where(SyncState.user_id == current_user.id).with_for_update()
    )
    sync_state = result.scalar_one_or_none()

    if not sync_state:
        if payload_in.version != 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "State conflict: version mismatch. No existing state found, expected version 0."
                ),
            )
        sync_state = SyncState(user_id=current_user.id, payload=payload_in.payload, version=1)
        db.add(sync_state)
        try:
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="State conflict: concurrent modification during initialization.",
            ) from e
    else:
        if sync_state.version != payload_in.version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="State conflict: version mismatch. Please fetch the latest state and merge.",
            )
        sync_state.payload = payload_in.payload
        sync_state.version += 1
        await db.commit()

    await db.refresh(sync_state)
    return SyncPayload(payload=sync_state.payload, version=sync_state.version)
