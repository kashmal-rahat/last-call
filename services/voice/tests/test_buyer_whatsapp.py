"""D62: the agent sends the buyer an item photo and the deal confirmation on WhatsApp."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

from lastcall_shared.item_photos import verify_item_photo_signature
from lastcall_shared.models import BoundingBox, FreshnessResult, ItemAssessment, ObservedQuantity, QuantityEstimate
from lastcall_shared.scenarios.loader import build_call
from lastcall_shared.store import InMemoryStore
from lastcall_voice.call_context import CallContext, register_context, unregister_context
from lastcall_voice.negotiator.buyer_messages import deal_confirmation_text
from lastcall_voice.negotiator.tools import confirm_deal, send_photo

PKT = ZoneInfo("Asia/Karachi")
NOW = datetime(2026, 10, 14, 14, 0, tzinfo=PKT)
KEY = "test-secret-key-12345-at-least-32-chars-long"


class FakeToolContext:
    def __init__(self, call_id: str):
        self.state = {"call_id": call_id}


@pytest.fixture(autouse=True)
def settings_env(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setenv("API_PUBLIC_URL", "https://api.example.com")
    yield


async def _call_with_context(*, photo_stored: bool):
    store = InMemoryStore()
    call, batch = build_call("easy_yes", now=NOW)
    await store.create_call(call, batch)
    await store.save_inspection(
        FreshnessResult(
            mart_id=call.mart_id,
            shelf_id="shelf_1",
            inspection_id=batch.inspection_id,
            photo_uri="upload:sha256:test",
            taken_at=NOW,
            photo_stored=photo_stored,
            items=[
                ItemAssessment(
                    item_key=batch.item_key,
                    name=call.brief.item,
                    position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.5, xmax=0.5),
                    grid="top-left",
                    stage="overripe",
                    stage_level="mid",
                    worst_stage="overripe",
                    score=40.0,
                    observed=ObservedQuantity(method="count", min=10, max=12),
                    quantity=QuantityEstimate(unit=call.brief.quantity_unit, low=1.0, high=1.5),
                    confidence=0.9,
                    confidence_level="high",
                )
            ],
        )
    )
    events: list[dict] = []

    async def notify(event: dict) -> None:
        events.append(event)

    ctx = CallContext(store=store, call_id=call.call_id, mode="voice", clock=lambda: NOW, notify=notify)
    register_context(ctx)
    return store, call, batch, events


async def test_send_photo_sends_a_signed_crop_of_this_item():
    store, call, batch, events = await _call_with_context(photo_stored=True)
    try:
        result = await send_photo(tool_context=FakeToolContext(call.call_id))
    finally:
        unregister_context(call.call_id)

    assert result["ok"] is True
    (event,) = events
    assert event["type"] == "whatsapp" and event["whatsapp"] == "photo"
    assert call.brief.item.capitalize() in event["text"]
    url = urlparse(event["media_url"])
    query = parse_qs(url.query)
    assert url.path == f"/demo/item-photos/{batch.inspection_id}/{batch.item_key}.jpg"
    assert verify_item_photo_signature(
        batch.inspection_id, batch.item_key, int(query["exp"][0]), query["sig"][0], key=KEY
    )
    (outbox,) = await store.get_outbox(call.call_id)
    assert outbox.kind == "photo" and outbox.status == "sent_in_call"


async def test_send_photo_is_honest_when_no_photo_was_kept():
    store, call, _, events = await _call_with_context(photo_stored=False)
    try:
        result = await send_photo(tool_context=FakeToolContext(call.call_id))
    finally:
        unregister_context(call.call_id)
    assert result["ok"] is False and "No photo" in result["message"]
    assert events == [] and await store.get_outbox(call.call_id) == []


async def test_confirm_deal_sends_the_whatsapp_confirmation():
    store, call, _, events = await _call_with_context(photo_stored=False)
    price = call.negotiation.ladder[0]
    call.negotiation.approved_prices = [price]
    await store.save_negotiation(call.call_id, call.negotiation)
    await store.lock_batch(call.batch_id, call.call_id, datetime.now(timezone.utc) + timedelta(minutes=10))
    pickup = (NOW + timedelta(hours=1)).isoformat()
    try:
        result = await confirm_deal(
            price_per_unit=price,
            quantity=call.brief.quantity,
            pickup_time_iso=pickup,
            buyer_confirmed=True,
            tool_context=FakeToolContext(call.call_id),
        )
    finally:
        unregister_context(call.call_id)

    assert result["ok"] is True, result
    (event,) = events
    assert event["whatsapp"] == "confirmation" and event["media_url"] is None
    assert event["text"].startswith(f"Deal confirmed · {call.brief.mart.name}")
    assert f"at Rs {price} / {call.brief.quantity_unit}" in event["text"]
    (outbox,) = await store.get_outbox(call.call_id)
    assert outbox.kind == "whatsapp_confirmation" and outbox.status == "sent_in_call"


def test_confirmation_text_uses_mart_time_and_totals():
    call, _ = build_call("easy_yes", now=NOW)
    pickup_utc = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)  # 18:00 in Lahore
    text = deal_confirmation_text(call, quantity=1.5, price_per_unit=105, pickup=pickup_utc, now=NOW)
    lines = text.split("\n")
    assert (
        lines[1] == f"1.5 {call.brief.quantity_unit} {call.brief.item} at Rs 105 / {call.brief.quantity_unit} (Rs 158)"
    )
    assert lines[2] == "Pickup: today, by 6 PM"
    assert lines[3] == f"Payment: {call.brief.payment_terms}"
    tomorrow = deal_confirmation_text(call, quantity=1, price_per_unit=105, pickup=NOW + timedelta(days=1), now=NOW)
    assert "Pickup: Thu 15 Oct, by 2 PM" in tomorrow


def test_donation_confirmation_has_no_price():
    call, _ = build_call("donation", now=NOW)
    text = deal_confirmation_text(call, quantity=3, price_per_unit=0, pickup=NOW + timedelta(hours=2), now=NOW)
    assert text.startswith("Donation confirmed") and "free of charge" in text
    assert "Rs" not in text and "Payment" not in text


async def test_photo_is_sent_once_per_call():
    store, call, _, events = await _call_with_context(photo_stored=True)
    try:
        first = await send_photo(tool_context=FakeToolContext(call.call_id))
        second = await send_photo(tool_context=FakeToolContext(call.call_id))
    finally:
        unregister_context(call.call_id)
    assert first["ok"] and second["ok"] and "already sent" in second["message"]
    assert len(events) == 1 and len(await store.get_outbox(call.call_id)) == 1
