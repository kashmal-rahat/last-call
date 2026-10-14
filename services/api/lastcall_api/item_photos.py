"""Item photos for buyers (D62).

When a buyer doubts the quality, the agent sends a photo of just that item. The api keeps
each inspected shelf photo (the normalised JPEG the Inspector already makes: no EXIF, long
side <= 1600 px) for one day, and crops the item on request using the Inspector's box.

- Storage: a private Cloud Storage bucket with a 1-day delete rule (Terraform). Nothing is
  public; links are signed with APP_SIGNING_KEY (`lastcall_shared.item_photos`).
- Saving is best effort: if it fails, the inspection still succeeds and the agent simply
  says no photo is available.
"""

import asyncio
import logging
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


class GcsPhotoStore:
    """Shelf photos in a private bucket (`shelf/{inspection_id}.jpg`); the bucket's lifecycle rule deletes them."""

    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage  # imported here so tests and local runs need no GCS client

        self._bucket = storage.Client().bucket(bucket_name)

    @staticmethod
    def _object_name(inspection_id: str) -> str:
        return f"shelf/{inspection_id}.jpg"

    async def put_shelf_photo(self, inspection_id: str, jpeg: bytes) -> None:
        blob = self._bucket.blob(self._object_name(inspection_id))
        await asyncio.to_thread(blob.upload_from_string, jpeg, content_type="image/jpeg")

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


async def save_shelf_photo(photo_store: PhotoStore | None, inspection_id: str, upload: bytes) -> bool:
    """Keeps the normalised shelf photo for the agent. Returns whether it was saved; never raises."""
    if photo_store is None:
        return False
    try:
        # Only the 1600 px JPEG is kept, so decode at reduced size (a phone photo would need ~200 MB in full)
        prepared = await asyncio.to_thread(prepare_image, upload, decode_max_side=1600)
        await photo_store.put_shelf_photo(inspection_id, prepared.jpeg)
        return True
    except Exception as exc:
        logger.warning(
            "shelf_photo_not_saved", extra={"inspection_id": inspection_id, "error_class": type(exc).__name__}
        )
        return False


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
