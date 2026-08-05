"""API router for cross-device synchronization."""

import datetime
import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wealthdock_server.api.v1.dependencies import get_current_user
from wealthdock_server.db.models import SyncRecord, User
from wealthdock_server.db.session import get_db
from wealthdock_server.schemas.sync import SyncItemSchema, SyncRequest, SyncResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["sync"])

PAGE_LIMIT = 100
CLAMP_TOLERANCE_MINUTES = 5


async def process_changes(
    payload_changes: list[SyncItemSchema],
    current_user_id: Any,
    db: AsyncSession,
    server_sync_point: datetime.datetime,
) -> None:
    """Process incoming changes from the client using Last-Write-Wins (LWW) resolution.

    Ensures client-side clock skew is clamped, resolves tie-breaks, and saves records.
    """
    if not payload_changes:
        return

    # Fetch existing records in bulk to resolve N+1 queries
    ids = [change.id for change in payload_changes]
    stmt = select(SyncRecord).where(
        SyncRecord.user_id == current_user_id,
        SyncRecord.id.in_(ids),
    )
    result = await db.execute(stmt)
    existing = {record.id: record for record in result.scalars()}

    max_allowed_time = server_sync_point + datetime.timedelta(minutes=CLAMP_TOLERANCE_MINUTES)

    for change in payload_changes:
        # Normalize incoming client timestamp
        incoming_updated_at = change.updated_at
        if incoming_updated_at.tzinfo is None:
            incoming_updated_at = incoming_updated_at.replace(tzinfo=datetime.UTC)
        else:
            incoming_updated_at = incoming_updated_at.astimezone(datetime.UTC)

        # Clamp skewed clocks to server time + tolerance
        if incoming_updated_at > max_allowed_time:
            logger.warning(
                "Client sync record %s timestamp %s is too far in future. "
                "Clamping to server time %s.",
                change.id,
                incoming_updated_at,
                server_sync_point,
            )
            incoming_updated_at = server_sync_point

        db_record = existing.get(change.id)
        if db_record is None:
            new_record = SyncRecord(
                id=change.id,
                user_id=current_user_id,
                type=change.type,
                data=change.data,
                updated_at=incoming_updated_at,
                server_updated_at=server_sync_point,
                deleted=change.deleted,
            )
            db.add(new_record)
        else:
            db_updated_at = db_record.updated_at
            if db_updated_at.tzinfo is None:
                db_updated_at = db_updated_at.replace(tzinfo=datetime.UTC)
            else:
                db_updated_at = db_updated_at.astimezone(datetime.UTC)

            # Last-Write-Wins with tie-break on equality (incoming replaces stored)
            if incoming_updated_at >= db_updated_at:
                db_record.type = change.type
                db_record.data = change.data
                db_record.updated_at = incoming_updated_at
                db_record.deleted = change.deleted
                db_record.server_updated_at = server_sync_point


@router.post("", response_model=SyncResponse)
async def sync(
    payload: SyncRequest,
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> SyncResponse:
    """Sync changes from and to the client.

    Processes incoming local changes using a Last-Write-Wins (LWW) conflict
    resolution based on timestamps, commits them, and returns all records
    updated since the client's last sync point (`since`).
    """
    server_sync_point = datetime.datetime.now(datetime.UTC)

    # 1. Process client writes with concurrency/IntegrityError retry handling
    if payload.changes:
        try:
            await process_changes(payload.changes, current_user.id, db, server_sync_point)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            # Retry processing which refreshes existing maps and applies LWW correctly
            await process_changes(payload.changes, current_user.id, db, server_sync_point)
            await db.commit()

    # 2. Query changes to pull since client's last sync point
    if payload.since is not None:
        since_time = payload.since
        if since_time.tzinfo is None:
            since_time = since_time.replace(tzinfo=datetime.UTC)
        else:
            since_time = since_time.astimezone(datetime.UTC)

        stmt_pull = select(SyncRecord).where(
            SyncRecord.user_id == current_user.id,
            SyncRecord.server_updated_at > since_time,
        )
    else:
        stmt_pull = select(SyncRecord).where(SyncRecord.user_id == current_user.id)

    # Apply paging and sorting
    stmt_pull = stmt_pull.order_by(SyncRecord.server_updated_at.asc()).limit(PAGE_LIMIT)

    result_pull = await db.execute(stmt_pull)
    db_changes = result_pull.scalars().all()

    # If paging is active, adjust returned sync point to allow sequential sync catches
    if len(db_changes) == PAGE_LIMIT:
        last_item_time = db_changes[-1].server_updated_at
        if last_item_time.tzinfo is None:
            last_item_time = last_item_time.replace(tzinfo=datetime.UTC)
        server_sync_point = last_item_time

    # Format response changes
    changes_to_return: list[SyncItemSchema] = []
    for item in db_changes:
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
