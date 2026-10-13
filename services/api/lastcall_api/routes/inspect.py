"""POST /demo/inspect: the Freshness Inspector on an uploaded shelf photo."""

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from lastcall_api.deps import (
    DEMO_MART_ID,
    check_ip_limit,
    consume_daily_cap,
    get_store,
    photo_store_for,
    require_access_code,
)
from lastcall_api.inspector.images import ImageError
from lastcall_api.inspector.inspector import InspectorError, inspect_photo
from lastcall_api.item_photos import save_shelf_photo
from lastcall_shared import ids
from lastcall_shared.clock import now_pkt
from lastcall_shared.config import get_settings
from lastcall_shared.store import CallStore

logger = logging.getLogger("lastcall_api.inspect")

ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
_INSPECT_SEMAPHORE = asyncio.Semaphore(2)  # at most two Gemini inspections at once per instance

router = APIRouter(dependencies=[Depends(require_access_code)])


@router.post("/demo/inspect")
async def demo_inspect(
    request: Request,
    photo: UploadFile = File(...),
    shelf_id: str = Form(""),
    bin_capacity_kg: float | None = Form(None),
    store: CallStore = Depends(get_store),
) -> dict:
    """Inspects a shelf photo for produce freshness."""
    if not ids.SHELF_ID.match(shelf_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid shelf_id: must match {ids.SHELF_ID.pattern}"
        )
    if bin_capacity_kg is not None and not (0 < bin_capacity_kg <= 500):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid bin_capacity_kg: must be > 0 and <= 500"
        )

    settings = get_settings()
    limit = settings.IP_RATE_LIMIT_PER_HOUR
    await check_ip_limit(
        request, "inspect", limit, detail=f"Hourly IP limit reached (max {limit} inspections per hour)"
    )

    if photo.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Please upload a JPEG or PNG photo"
        )
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    contents = await photo.read(max_bytes + 1)  # one byte more tells us it is too large
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image exceeds maximum upload size of {settings.MAX_UPLOAD_MB} MB",
        )

    now = now_pkt()
    await consume_daily_cap(
        store, f"inspect-{now:%Y-%m-%d}", settings.DEMO_DAILY_INSPECT_CAP, "Daily demo inspection cap reached"
    )

    previous = await store.get_latest_inspection(DEMO_MART_ID, shelf_id)
    inspect_fn = getattr(request.app.state, "inspect_fn", inspect_photo)
    try:
        async with _INSPECT_SEMAPHORE:
            result = await inspect_fn(
                contents,
                mart_id=DEMO_MART_ID,
                shelf_id=shelf_id,
                previous=previous,
                now=now,
                bin_capacity_kg=bin_capacity_kg,
                reading_cache=store,
            )
    except ImageError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not a readable image") from None
    except InspectorError as exc:
        logger.error("inspector_call_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Inspection failed, please try again"
        ) from exc

    # Keep the shelf photo so the agent can send the buyer an item photo (D62; best effort)
    if await save_shelf_photo(photo_store_for(request.app), result.inspection_id, contents):
        result = result.model_copy(update={"photo_stored": True})
    await store.save_inspection(result)
    return result.model_dump(mode="json")
