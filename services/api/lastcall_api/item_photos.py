"""Item photos for buyers (D62).

When a buyer doubts the quality, the agent sends a photo of just that item. The api keeps
each inspected shelf photo (the normalised JPEG the Inspector already makes: no EXIF, long
side <= 1600 px) until the bucket deletes it after a day, and crops the item on request using
the Inspector's box.

- Storage: a private Cloud Storage bucket with a 1-day delete rule (Terraform). Nothing is
  public; links are signed with APP_SIGNING_KEY (`lastcall_shared.item_photos`).
- Saving is best effort and doesn't hold up the inspection (D72): the photo is made small while
  the request runs (CPU work, which Cloud Run only gives during a request), then uploaded in the
  background (network work, 10 s seen on Cloud Run), and nothing needs it until a call. When it is
  kept, the inspection is marked `photo_stored`, which the agent checks before offering a photo;
  if anything fails, the agent simply says no photo is available.
"""

import asyncio
import logging
import time
from functools import lru_cache
from typing import Callable, Protocol

from fastapi import APIRouter, HTTPException, Query, Response, status

from lastcall_api.inspector.images import ImageError, crop_group, prepare_image
from lastcall_shared import ids
from lastcall_shared.config import get_settings
from lastcall_shared.item_photos import verify_item_photo_signature
from lastcall_shared.models import BoundingBox
from lastcall_shared.store import CallStore

logger = logging.getLogger("lastcall_api.item_photos")


class PhotoStore(Protocol):
    async def put_shelf_photo(self, inspection_id: str, jpeg: bytes) -> None: ...
    async def get_shelf_photo(self, inspection_id: str) -> bytes | None: ...


UPLOAD_TIMEOUT_S = 15  # one attempt at a ~300 KB JPEG
UPLOAD_RETRY_BUDGET_S = 30  # all attempts together


class GcsPhotoStore:
    """Shelf photos in a private bucket (`shelf/{inspection_id}.jpg`); the bucket's lifecycle rule deletes them."""

    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage  # imported here so tests and local runs need no GCS client

        self._bucket = storage.Client().bucket(bucket_name)

    @staticmethod
    def _object_name(inspection_id: str) -> str:
        return f"shelf/{inspection_id}.jpg"

    async def put_shelf_photo(self, inspection_id: str, jpeg: bytes) -> None:
        from google.cloud.storage.retry import DEFAULT_RETRY

        blob = self._bucket.blob(self._object_name(inspection_id))
        # Bounded, unlike the client's defaults (60 s per attempt, retries for 120 s): a stuck upload
        # would hold one of the two upload slots and a worker thread
        await asyncio.to_thread(
            blob.upload_from_string,
            jpeg,
            content_type="image/jpeg",
            timeout=UPLOAD_TIMEOUT_S,
            retry=DEFAULT_RETRY.with_timeout(UPLOAD_RETRY_BUDGET_S),
        )

    async def get_shelf_photo(self, inspection_id: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        blob = self._bucket.blob(self._object_name(inspection_id))
        try:
            return await asyncio.to_thread(blob.download_as_bytes)
        except NotFound:
            return None


class InMemoryPhotoStore:
    def __init__(self) -> None:
        self.photos: dict[str, bytes] = {}

    async def put_shelf_photo(self, inspection_id: str, jpeg: bytes) -> None:
        self.photos[inspection_id] = jpeg

    async def get_shelf_photo(self, inspection_id: str) -> bytes | None:
        return self.photos.get(inspection_id)


@lru_cache
def default_photo_store() -> PhotoStore | None:
    """One storage client per process; None when no bucket is configured (no photos)."""
    bucket = get_settings().SHELF_PHOTO_BUCKET
    return GcsPhotoStore(bucket) if bucket else None


# Uploads in progress. asyncio keeps only weak references to tasks, so they are held here until done.
# At most two run at once: each holds a worker thread for the storage client, which a slow upload
# would otherwise let pile up.
_SHELF_PHOTO_UPLOADS: set[asyncio.Task[None]] = set()
_UPLOAD_SLOTS = asyncio.Semaphore(2)


async def keep_shelf_photo(photo_store: PhotoStore | None, store: CallStore, inspection_id: str, upload: bytes) -> None:
    """Keeps the shelf photo for the agent (D62) without making the judge wait for the upload (D72).

    Makes the 1600 px JPEG now, while the request has the CPU, then uploads it and marks the inspection
    `photo_stored` in the background. Call it after the inspection is saved, so the mark always finds it.
    Never raises. No photo store (local runs, tests without one): nothing to do.
    """
    if photo_store is None:
        return
    try:
        # Only the 1600 px JPEG is kept, so decode at reduced size (a phone photo would need ~200 MB in full)
        prepared = await asyncio.to_thread(prepare_image, upload, decode_max_side=1600)
    except Exception as exc:
        _not_kept("shelf_photo_not_saved", inspection_id, exc)
        return
    task = asyncio.create_task(_upload_and_mark(photo_store, store, inspection_id, prepared.jpeg))
    _SHELF_PHOTO_UPLOADS.add(task)
    task.add_done_callback(_SHELF_PHOTO_UPLOADS.discard)


async def _upload_and_mark(photo_store: PhotoStore, store: CallStore, inspection_id: str, jpeg: bytes) -> None:
    async with _UPLOAD_SLOTS:
        started = time.monotonic()
        try:
            await photo_store.put_shelf_photo(inspection_id, jpeg)
        except Exception as exc:
            _not_kept("shelf_photo_not_saved", inspection_id, exc)
            return
        try:
            await store.mark_photo_stored(inspection_id)
        except Exception as exc:
            _not_kept("shelf_photo_not_marked", inspection_id, exc)
            return
        logger.info(
            "shelf_photo_kept",
            extra={"inspection_id": inspection_id, "latency_ms": round((time.monotonic() - started) * 1000)},
        )


def _not_kept(event: str, inspection_id: str, exc: Exception) -> None:
    # The inspection stays photo_stored=False, so the agent says no photo is available
    logger.warning(event, extra={"inspection_id": inspection_id, "error_class": type(exc).__name__})


async def wait_for_shelf_photos(timeout: float | None = None) -> None:
    """Waits for the uploads in progress: at shutdown (bounded, so a stuck one can't hold it up) and in tests."""
    if _SHELF_PHOTO_UPLOADS:
        await asyncio.wait(set(_SHELF_PHOTO_UPLOADS), timeout=timeout)


def crop_item(shelf_jpeg: bytes, position: BoundingBox) -> bytes:
    """The item's box from the Inspector (0–1 scale), with a margin, as a JPEG."""
    prepared = prepare_image(shelf_jpeg)
    box = [round(v * 1000) for v in (position.ymin, position.xmin, position.ymax, position.xmax)]
    return crop_group(prepared.full, box)


def build_router(
    *,
    get_store: Callable[[], CallStore],
    get_photo_store: Callable[[], PhotoStore | None],
) -> APIRouter:
    router = APIRouter(tags=["item-photos"])

    @router.get("/demo/item-photos/{inspection_id}/{item_key}.jpg")
    async def item_photo(
        inspection_id: str,
        item_key: str,
        exp: int = Query(...),
        sig: str = Query(..., max_length=64),
    ) -> Response:
        """A signed, time-limited crop of one item. Fetched by the page and by Twilio (WhatsApp)."""
        if not (ids.INSPECTION_ID.match(inspection_id) and ids.ITEM_KEY.match(item_key)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
        key = get_settings().APP_SIGNING_KEY.get_secret_value()
        if not verify_item_photo_signature(inspection_id, item_key, exp, sig, key=key):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Link is invalid or expired")

        photo_store = get_photo_store()
        inspection = await get_store().get_inspection(inspection_id)
        item = next((i for i in inspection.items if i.item_key == item_key), None) if inspection else None
        shelf_jpeg = await photo_store.get_shelf_photo(inspection_id) if (photo_store and item) else None
        if item is None or shelf_jpeg is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not available")

        try:
            jpeg = await asyncio.to_thread(crop_item, shelf_jpeg, item.position)
        except ImageError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not available") from None
        return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    return router
