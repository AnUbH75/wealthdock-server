"""API router for cross-device synchronization."""

import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wealthdock_server.db.models import SyncRecord
from wealthdock_server.db.session import get_db
from wealthdock_server.schemas.sync import SyncItemSchema, SyncRequest, SyncResponse

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("", response_model=SyncResponse)
async def sync(
    payload: SyncRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> SyncResponse:
    """Sync changes from and to the client.

    Processes incoming local changes using a Last-Write-Wins (LWW) conflict
    resolution based on timestamps, commits them, and returns all records
    updated since the client's last sync point (`since`).
    """
    # 1. Capture the server sync point timestamp
    server_sync_point = datetime.datetime.now(datetime.UTC)

    # 2. Process incoming client changes
    for change in payload.changes:
        stmt = select(SyncRecord).where(SyncRecord.id == change.id)
        result = await db.execute(stmt)
        db_record = result.scalar_one_or_none()

        # Normalize incoming timestamp to UTC timezone-aware
        incoming_updated_at = change.updated_at
        if incoming_updated_at.tzinfo is None:
            incoming_updated_at = incoming_updated_at.replace(tzinfo=datetime.UTC)
        else:
            incoming_updated_at = incoming_updated_at.astimezone(datetime.UTC)

        if db_record is None:
            # Insert new record
            new_record = SyncRecord(
                id=change.id,
                type=change.type,
                data=change.data,
                updated_at=incoming_updated_at,
                deleted=change.deleted,
            )
            db.add(new_record)
        else:
            # Normalize database timestamp to UTC timezone-aware
            db_updated_at = db_record.updated_at
            if db_updated_at.tzinfo is None:
                db_updated_at = db_updated_at.replace(tzinfo=datetime.UTC)
            else:
                db_updated_at = db_updated_at.astimezone(datetime.UTC)

            # Last-Write-Wins check
            if incoming_updated_at > db_updated_at:
                db_record.type = change.type
                db_record.data = change.data
                db_record.updated_at = incoming_updated_at
                db_record.deleted = change.deleted

    # Commit changes
    await db.commit()

    # 3. Query all changes since the client's last sync point
    if payload.since is not None:
        since_time = payload.since
        if since_time.tzinfo is None:
            since_time = since_time.replace(tzinfo=datetime.UTC)
        else:
            since_time = since_time.astimezone(datetime.UTC)

        stmt_pull = select(SyncRecord).where(SyncRecord.updated_at > since_time)
    else:
        stmt_pull = select(SyncRecord)

    result_pull = await db.execute(stmt_pull)
    db_changes = result_pull.scalars().all()

    # Format response changes
    changes_to_return: list[SyncItemSchema] = []
    for item in db_changes:
        # Ensure database datetimes returned are timezone-aware
        item_updated_at = item.updated_at
        if item_updated_at.tzinfo is None:
            item_updated_at = item_updated_at.replace(tzinfo=datetime.UTC)

        changes_to_return.append(
            SyncItemSchema(
                id=item.id,
                type=item.type,
                data=item.data,
                updated_at=item_updated_at,
                deleted=item.deleted,
            )
        )

    return SyncResponse(sync_point=server_sync_point, changes=changes_to_return)
