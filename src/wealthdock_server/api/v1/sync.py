from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wealthdock_server.api.deps import get_current_user
from wealthdock_server.db.models import SyncState, User
from wealthdock_server.db.session import get_db
from wealthdock_server.schemas.sync import SyncPayload

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
        return SyncPayload(payload='{"assets":[],"budgets":[],"transactions":[]}')
    return SyncPayload(payload=sync_state.payload)


@router.post("", response_model=SyncPayload)
async def update_sync_state(
    payload_in: SyncPayload,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncPayload:
    """Update/synchronize user's assets and configurations (last-write-wins)."""
    result = await db.execute(select(SyncState).where(SyncState.user_id == current_user.id))
    sync_state = result.scalar_one_or_none()

    if not sync_state:
        sync_state = SyncState(user_id=current_user.id, payload=payload_in.payload)
        db.add(sync_state)
    else:
        sync_state.payload = payload_in.payload

    await db.commit()
    await db.refresh(sync_state)
    return SyncPayload(payload=sync_state.payload)
