"""API router for cross-device synchronization."""

import datetime
import gzip
import io
import json
import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.routing import APIRoute
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wealthdock_server.api.v1.dependencies import get_current_user
from wealthdock_server.db.models import SyncRecord, SyncState, User
from wealthdock_server.db.session import get_db
from wealthdock_server.schemas.sync import (
    DEFAULT_SYNC_PAYLOAD,
    SyncItemSchema,
    SyncPayload,
    SyncRequest,
    SyncResponse,
)

logger = logging.getLogger(__name__)


class GzipRequest(Request):
    """Request class that decompresses gzip payloads if the Content-Encoding is set to gzip."""

    async def body(self) -> bytes:
        """Decompress and retrieve the HTTP request body if it is gzip encoded."""
        if not hasattr(self, "_body"):
            body = await super().body()
            if "gzip" in self.headers.getlist("Content-Encoding"):
                max_size = 10 * 1024 * 1024  # 10 MB limit
                try:
                    with gzip.GzipFile(fileobj=io.BytesIO(body)) as f:
                        chunks = []
                        total_size = 0
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            total_size += len(chunk)
                            if total_size > max_size:
                                raise HTTPException(
                                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                    detail="Decompressed payload size exceeds maximum limit",
                                )
                            chunks.append(chunk)
                        body = b"".join(chunks)
                except HTTPException:
                    raise
                except (OSError, EOFError) as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid gzip payload",
                    ) from e
            self._body = body
        return self._body


class GzipRoute(APIRoute):
    """Route class that uses GzipRequest to handle gzipped request bodies."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        """Wrap the route handler to use GzipRequest for incoming request decoding."""
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            request = GzipRequest(request.scope, request.receive)
            return await original_route_handler(request)

        return custom_route_handler


router = APIRouter(prefix="/sync", tags=["sync"], route_class=GzipRoute)

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

    if db.bind is not None and db.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert  # type: ignore[assignment]

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

        stmt = insert(SyncRecord).values(
            id=change.id,
            user_id=current_user_id,
            type=change.type,
            data=change.data,
            updated_at=incoming_updated_at,
            server_updated_at=server_sync_point,
            deleted=change.deleted,
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=["id", "user_id"],
            set_={
                "type": stmt.excluded.type,
                "data": stmt.excluded.data,
                "updated_at": stmt.excluded.updated_at,
                "server_updated_at": stmt.excluded.server_updated_at,
                "deleted": stmt.excluded.deleted,
            },
            where=(stmt.excluded.updated_at >= SyncRecord.updated_at),
        )

        await db.execute(stmt)


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
    return SyncPayload(payload=json.dumps(sync_state.payload), version=sync_state.version)


@router.post("", response_model=None)
async def sync(
    payload_in: dict[str, Any],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Synchronize user data supporting whole-state and per-record sync."""
    if "payload" in payload_in and "version" in payload_in:
        sync_payload = SyncPayload.model_validate(payload_in)
        result = await db.execute(
            select(SyncState).where(SyncState.user_id == current_user.id).with_for_update()
        )
        sync_state = result.scalar_one_or_none()

        if not sync_state:
            if sync_payload.version != 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="State conflict: version mismatch. No state found, expected version 0.",
                )
            sync_state = SyncState(
                user_id=current_user.id, payload=json.loads(sync_payload.payload), version=1
            )
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
            if sync_state.version != sync_payload.version:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="State conflict: version mismatch. Please fetch latest state and merge.",
                )
            sync_state.payload = json.loads(sync_payload.payload)
            sync_state.version += 1
            await db.commit()

        await db.refresh(sync_state)
        return SyncPayload(payload=json.dumps(sync_state.payload), version=sync_state.version)

    # Per-record LWW sync
    sync_req = SyncRequest.model_validate(payload_in)
    server_sync_point = datetime.datetime.now(datetime.UTC)

    if sync_req.changes:
        try:
            await process_changes(sync_req.changes, current_user.id, db, server_sync_point)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            db.expire_all()
            await process_changes(sync_req.changes, current_user.id, db, server_sync_point)
            await db.commit()

    if sync_req.since is not None:
        since_time = sync_req.since
        if since_time.tzinfo is None:
            since_time = since_time.replace(tzinfo=datetime.UTC)
        else:
            since_time = since_time.astimezone(datetime.UTC)

        if sync_req.last_seen_id is not None:
            filter_cond = or_(
                SyncRecord.server_updated_at > since_time,
                and_(
                    SyncRecord.server_updated_at == since_time,
                    SyncRecord.id > sync_req.last_seen_id,
                ),
            )
        else:
            filter_cond = SyncRecord.server_updated_at > since_time

        stmt_pull = select(SyncRecord).where(
            SyncRecord.user_id == current_user.id,
            filter_cond,
        )
    else:
        stmt_pull = select(SyncRecord).where(SyncRecord.user_id == current_user.id)

    stmt_pull = stmt_pull.order_by(SyncRecord.server_updated_at.asc(), SyncRecord.id.asc()).limit(
        PAGE_LIMIT
    )

    result_pull = await db.execute(stmt_pull)
    db_changes = result_pull.scalars().all()

    last_seen_id = None
    if len(db_changes) == PAGE_LIMIT:
        last_item = db_changes[-1]
        last_item_time = last_item.server_updated_at
        if last_item_time.tzinfo is None:
            last_item_time = last_item_time.replace(tzinfo=datetime.UTC)
        server_sync_point = last_item_time
        last_seen_id = last_item.id

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

    return SyncResponse(
        sync_point=server_sync_point,
        last_seen_id=last_seen_id,
        changes=changes_to_return,
    )
