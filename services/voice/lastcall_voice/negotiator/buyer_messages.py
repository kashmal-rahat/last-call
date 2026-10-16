"""What the agent sends the buyer on WhatsApp during a call (D62).

Tools build channel-neutral `whatsapp` events and hand them to `CallContext.notify`.
The transport decides how they reach the person playing the buyer: the browser page
shows them as WhatsApp messages; the phone bridge also sends a real WhatsApp message.
"""

import math
from datetime import datetime
from typing import Any, Literal

from lastcall_shared.clock import clock_words, day_words
from lastcall_shared.config import get_settings
from lastcall_shared.item_photos import sign_item_photo_url
from lastcall_shared.models import CallRecord
from lastcall_shared.store import CallStore

WhatsAppKind = Literal["photo", "confirmation"]


def whatsapp_event(kind: WhatsAppKind, text: str, media_url: str | None = None) -> dict[str, Any]:
    return {"type": "whatsapp", "whatsapp": kind, "text": text, "media_url": media_url}


async def item_photo_url(store: CallStore, call: CallRecord) -> str | None:
    """A signed link to a crop of this call's item, or None if no photo was kept."""
    settings = get_settings()
    if not settings.API_PUBLIC_URL:
        return None
    batch = await store.get_batch(call.batch_id)
    inspection = await store.get_inspection(batch.inspection_id) if batch else None
    if inspection is None or not inspection.photo_stored:
        return None
    if not any(item.item_key == batch.item_key for item in inspection.items):
        return None
    return sign_item_photo_url(
        settings.API_PUBLIC_URL,
        inspection.inspection_id,
        batch.item_key,
        key=settings.APP_SIGNING_KEY.get_secret_value(),
    )


def photo_caption(call: CallRecord) -> str:
    return f"{call.brief.item.capitalize()} · {call.brief.condition} · {call.brief.mart.name}"


def deal_confirmation_text(
    call: CallRecord, *, quantity: float, price_per_unit: int, pickup: datetime, now: datetime
) -> str:
    """The WhatsApp confirmation a buyer gets once the deal is agreed."""
    brief = call.brief
    mart_tz = brief.pickup_deadline.tzinfo  # the mart's local time
    pickup, now = pickup.astimezone(mart_tz), now.astimezone(mart_tz)
    goods = f"{quantity:g} {brief.quantity_unit} {brief.item}"
    pickup_line = f"Pickup: {day_words(pickup, now)}, by {clock_words(pickup)}"

    if brief.deal_type == "donation":
        lines = [f"Donation confirmed · {brief.mart.name}", f"{goods}, free of charge", pickup_line]
    else:
        total = math.ceil(quantity * price_per_unit)
        lines = [
            f"Deal confirmed · {brief.mart.name}",
            f"{goods} at Rs {price_per_unit} / {brief.quantity_unit} (Rs {total:,})",
            pickup_line,
            f"Payment: {brief.payment_terms}",
        ]
    lines.append(f"Address: {brief.mart.location}")
    return "\n".join(lines)
