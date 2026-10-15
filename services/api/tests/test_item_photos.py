"""D62: the shelf photo is kept at inspection (in the background) and served as a signed crop of one item."""

import asyncio
import io
import threading
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lastcall_api.deps import _IP_REQUEST_HISTORY
from lastcall_api.item_photos import InMemoryPhotoStore, keep_shelf_photo, wait_for_shelf_photos
from lastcall_api.main import app
from lastcall_shared.item_photos import sign_item_photo_url
from lastcall_shared.models import BoundingBox, FreshnessResult, ItemAssessment, ObservedQuantity, QuantityEstimate
from lastcall_shared.store import InMemoryStore

KEY = "test-signing-key-12345-at-least-32-chars-long"
CODE = "test-judge-access-code"
PKT = ZoneInfo("Asia/Karachi")
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=PKT)


def _shelf_jpeg() -> bytes:
    """800x600, with a yellow 'banana' block in the top-left quarter."""
    img = Image.new("RGB", (800, 600), (40, 90, 40))
    img.paste((230, 200, 40), (80, 60, 400, 300))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _result(inspection_id: str) -> FreshnessResult:
    return FreshnessResult(
        mart_id="demo_mart",
        shelf_id="shelf_1",
        inspection_id=inspection_id,
        photo_uri="upload:sha256:test",
        taken_at=NOW,
        items=[
            ItemAssessment(
                item_key="banana_top_left",
                name="banana",
                position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.5, xmax=0.5),
                grid="top-left",
                stage="overripe",
                stage_level="mid",
                worst_stage="overripe",
                score=40.0,
                observed=ObservedQuantity(method="count", min=10, max=12),
                quantity=QuantityEstimate(unit="dozen", low=0.8, high=1.0),
                confidence=0.9,
                confidence_level="high",
            )
        ],
    )


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setenv("DEMO_ACCESS_CODE", CODE)
    _IP_REQUEST_HISTORY.clear()
    store, photos = InMemoryStore(), InMemoryPhotoStore()
    app.state.store = store
    app.state.photo_store = photos

    async def fake_inspect(contents, **kwargs):
        return _result("insp_photo_1")

    app.state.inspect_fn = fake_inspect
    yield store, photos
    del app.state.photo_store
    del app.state.inspect_fn


def _inspect(client: TestClient, photo: bytes):
    return client.post(
        "/demo/inspect",
        headers={"X-Demo-Access-Code": CODE},
        files={"photo": ("shelf.jpg", photo, "image/jpeg")},
        data={"shelf_id": "shelf_1"},
    )


def _inspect_and_keep(client: TestClient, photo: bytes):
    """Inspects, then waits (on the app's own event loop) for the background photo save to finish."""
    resp = _inspect(client, photo)
    client.portal.call(wait_for_shelf_photos)
    return resp


def _stored_flag(client: TestClient, store: InMemoryStore) -> bool:
    return client.portal.call(store.get_inspection, "insp_photo_1").photo_stored


def _path(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.path}?{parsed.query}"


def test_inspection_keeps_the_photo_and_serves_a_signed_item_crop(setup):
    store, photos = setup
    with TestClient(app) as client:
        resp = _inspect_and_keep(client, _shelf_jpeg())
        # Answered before the photo was kept; the inspection is marked once it is
        assert resp.status_code == 200 and resp.json()["photo_stored"] is False
        assert "insp_photo_1" in photos.photos
        assert _stored_flag(client, store) is True

        url = sign_item_photo_url("https://api.example.com", "insp_photo_1", "banana_top_left", key=KEY)
        photo = client.get(_path(url))
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    crop = Image.open(io.BytesIO(photo.content))
    assert crop.width < 800 and crop.height < 600  # a crop, not the shelf
    r, g, b = crop.convert("RGB").getpixel((crop.width // 2, crop.height // 2))
    assert r > 180 and g > 150 and b < 100  # the yellow item is in the middle


@pytest.mark.parametrize(
    "case, expected",
    [("bad_signature", 403), ("expired", 403), ("other_item", 404), ("bad_item_key", 404)],
)
def test_photo_link_refusals(setup, case, expected):
    item = "banana_top_left"
    url = sign_item_photo_url("https://api.example.com", "insp_photo_1", item, key=KEY)
    if case == "bad_signature":
        url = url.replace("sig=", "sig=x")
    elif case == "expired":
        url = sign_item_photo_url("https://api.example.com", "insp_photo_1", item, key=KEY, now=0)
    elif case == "other_item":
        url = sign_item_photo_url("https://api.example.com", "insp_photo_1", "apple_center", key=KEY)
    elif case == "bad_item_key":
        url = sign_item_photo_url("https://api.example.com", "insp_photo_1", "Bad.Key", key=KEY)
    with TestClient(app) as client:
        _inspect_and_keep(client, _shelf_jpeg())
        assert client.get(_path(url)).status_code == expected


def test_inspection_still_works_when_the_photo_cannot_be_kept(setup):
    store, photos = setup
    with TestClient(app) as client:
        resp = _inspect_and_keep(client, b"not-a-real-jpeg")  # the fake inspector accepts it; the photo step can't
        assert resp.status_code == 200 and resp.json()["photo_stored"] is False
        assert photos.photos == {}
        assert _stored_flag(client, store) is False
        url = sign_item_photo_url("https://api.example.com", "insp_photo_1", "banana_top_left", key=KEY)
        assert client.get(_path(url)).status_code == 404


class _SlowPhotoStore(InMemoryPhotoStore):
    """An upload that waits until the test releases it, like the 10 s Cloud Storage stalls seen live."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    async def put_shelf_photo(self, inspection_id: str, jpeg: bytes) -> None:
        await asyncio.to_thread(self.release.wait, 5)
        await super().put_shelf_photo(inspection_id, jpeg)


def test_the_inspection_is_answered_without_waiting_for_the_photo_upload(setup):
    store, _ = setup
    slow = _SlowPhotoStore()
    app.state.photo_store = slow
    with TestClient(app) as client:
        resp = _inspect(client, _shelf_jpeg())  # returns while the upload is still held
        assert resp.status_code == 200 and resp.json()["photo_stored"] is False
        assert slow.photos == {} and _stored_flag(client, store) is False

        slow.release.set()
        client.portal.call(wait_for_shelf_photos)
        assert "insp_photo_1" in slow.photos and _stored_flag(client, store) is True


@pytest.mark.asyncio
async def test_keep_shelf_photo_never_raises_when_the_mark_fails():
    class NoInspectionStore(InMemoryStore):
        async def mark_photo_stored(self, inspection_id: str) -> None:
            raise LookupError(inspection_id)  # e.g. Firestore NotFound

    photos = InMemoryPhotoStore()
    await keep_shelf_photo(photos, NoInspectionStore(), "insp_photo_1", _shelf_jpeg())
    await wait_for_shelf_photos()
    assert "insp_photo_1" in photos.photos  # kept; the agent just won't offer it


@pytest.mark.asyncio
async def test_the_photo_is_made_small_before_the_answer_and_only_uploaded_in_the_background():
    """The decode needs CPU, which Cloud Run gives only during a request, so it is done before returning."""
    slow = _SlowPhotoStore()
    store = InMemoryStore()
    await store.save_inspection(_result("insp_photo_1"))
    await keep_shelf_photo(slow, store, "insp_photo_1", _shelf_jpeg())  # returns with the upload held
    assert slow.photos == {}

    slow.release.set()
    await wait_for_shelf_photos()
    kept = Image.open(io.BytesIO(slow.photos["insp_photo_1"]))
    assert max(kept.size) <= 1600 and (await store.get_inspection("insp_photo_1")).photo_stored is True


@pytest.mark.asyncio
async def test_waiting_for_uploads_is_bounded():
    """At shutdown the app waits for uploads, but a stuck one can't hold it past the limit."""
    slow = _SlowPhotoStore()
    await keep_shelf_photo(slow, InMemoryStore(), "insp_photo_1", _shelf_jpeg())
    started = asyncio.get_running_loop().time()
    await wait_for_shelf_photos(timeout=0.2)
    assert asyncio.get_running_loop().time() - started < 1 and slow.photos == {}
    slow.release.set()
    await wait_for_shelf_photos()
