"""BLOCKING tool declarations and handlers for the Negotiator Agent."""

import logging
from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from lastcall_shared.models import DealRecord, OutboxMessage, StaffTask
from lastcall_voice.call_context import CallContext, get_context
from lastcall_voice.negotiator.buyer_messages import (
    deal_confirmation_text,
    item_photo_url,
    photo_caption,
    whatsapp_event,
)
from lastcall_voice.negotiator.deals import validate_deal_terms
from lastcall_voice.negotiator.pricing import verify_offer as verify_offer_logic
from lastcall_voice.negotiator.prompt import time_words

PKT = ZoneInfo("Asia/Karachi")
logger = logging.getLogger("lastcall_voice.tools")


async def _notify_buyer(ctx: CallContext, event: dict[str, Any]) -> bool:
    """Hands a WhatsApp event to the call's transport (D62). Never fails the tool."""
    if ctx.notify is None:
        return False
    try:
        await ctx.notify(event)
        return True
    except Exception as exc:
        logger.warning("notify_buyer_failed", extra={"call_id": ctx.call_id, "error_class": type(exc).__name__})
        return False


async def verify_offer(
    buyer_offer_per_unit: int | None = None,
    buyer_asks_lower: bool = False,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Evaluates the buyer's offer or provides a quote against the negotiated price ladder.

    Args:
        buyer_offer_per_unit: The price per unit offered by the buyer in PKR, or None to repeat or ask for a lower price.
        buyer_asks_lower: Set to True only when the buyer asks for a lower price without naming a number. To repeat a price, leave False.
    """
    call_id = tool_context.state.get("call_id") if tool_context else None
    ctx = get_context(call_id) if call_id else None
    if not ctx:
        return {"error": "Active call context not found"}

    call = await ctx.store.get_call(call_id)
    if not call:
        return {"error": f"Call record {call_id} not found"}

    decision = verify_offer_logic(
        state=call.negotiation,
        policy=call.policy,
        deal_type=call.brief.deal_type,
        buyer_offer=buyer_offer_per_unit,
        unit=call.brief.opening_price_unit,
        buyer_asks_lower=buyer_asks_lower,
    )
    await ctx.store.save_negotiation(call_id, call.negotiation)
    ctx.negotiation = call.negotiation

    return {
        "decision": decision.decision,
        "price_per_unit": decision.price_per_unit,
        "unit": decision.unit,
        "offer_band": decision.offer_band,
    }


async def confirm_deal(
    price_per_unit: int,
    quantity: float,
    pickup_time_iso: str,
    buyer_confirmed: bool,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Records an agreed deal after clear confirmation from the buyer on all terms.

    Args:
        price_per_unit: Agreed price per unit in PKR (must be 0 for donation).
        quantity: Agreed quantity in the brief's unit.
        pickup_time_iso: Pickup time in ISO format with timezone offset (e.g. 2026-10-07T16:00:00+05:00).
        buyer_confirmed: True only if the buyer explicitly agreed to the repeated terms.
    """
    call_id = tool_context.state.get("call_id") if tool_context else None
    ctx = get_context(call_id) if call_id else None
    if not ctx:
        return {"ok": False, "reasons": ["Active call context not found"]}

    if ctx.outcome_set:
        return {"ok": False, "reason": "outcome already recorded", "reasons": ["outcome already recorded"]}

    call = await ctx.store.get_call(call_id)
    batch = await ctx.store.get_batch(call.batch_id)
    now = ctx.clock() if ctx.clock else datetime.now(PKT)

    # 1. Parse ISO time without rewrites or defaults (C0)
    if not pickup_time_iso or not isinstance(pickup_time_iso, str):
        return {
            "ok": False,
            "reasons": ["Pickup time is missing or invalid. Please ask the buyer for the pickup time again."],
        }
    try:
        pickup_dt = datetime.fromisoformat(pickup_time_iso)
    except Exception:
        return {
            "ok": False,
            "reasons": ["Unparseable pickup time format. Please ask the buyer for the pickup time again."],
        }

    if pickup_dt.tzinfo is None:
        return {
            "ok": False,
            "reasons": ["Pickup time must include timezone. Please ask the buyer for the pickup time again."],
        }

    if pickup_dt <= now:
        return {
            "ok": False,
            "reasons": ["Pickup time cannot be in the past. Please ask the buyer for the pickup time again."],
        }

    if pickup_dt > call.brief.pickup_deadline:
        return {
            "ok": False,
            "reasons": [
                f"Pickup time ({pickup_dt.isoformat()}) exceeds pickup deadline ({call.brief.pickup_deadline.isoformat()}). Please ask the buyer for the pickup time again."
            ],
        }

    # 2. Check quantity vs remaining stock (C0)
    if quantity > batch.remaining_quantity:
        rem_q = int(batch.remaining_quantity) if batch.remaining_quantity.is_integer() else batch.remaining_quantity
        unit_str = call.brief.quantity_unit
        return {
            "ok": False,
            "reasons": [f"Only {rem_q} {unit_str} is available"],
            "available_quantity": batch.remaining_quantity,
        }

    # 3. Validate deal terms
    reasons = validate_deal_terms(
        state=call.negotiation,
        brief=call.brief,
        batch=batch,
        price=price_per_unit,
        quantity=quantity,
        pickup_time=pickup_dt,
        buyer_confirmed=buyer_confirmed,
        now=now,
    )
    if reasons:
        return {"ok": False, "reasons": reasons}

    # 4. Create deal and execute transaction
    deal = DealRecord(
        mart_id=call.mart_id,
        call_id=call_id,
        batch_id=batch.batch_id,
        buyer_id=call.brief.buyer.buyer_id,
        deal_type=call.brief.deal_type,
        price_per_unit=price_per_unit,
        unit=call.brief.quantity_unit,
        quantity=quantity,
        pickup_time=pickup_dt,
        pickup_deadline=call.brief.pickup_deadline,
        payment_terms=call.brief.payment_terms,
        status="agreed",
        created_at=now,
    )
    ok, err = await ctx.store.save_deal_tx(call_id, deal, quantity)
    if not ok:
        return {"ok": False, "reasons": [err or "Failed to lock and save deal transaction."]}

    # 5. WhatsApp confirmation to the buyer (D62), recorded in the outbox
    confirmation = deal_confirmation_text(call, quantity=quantity, price_per_unit=price_per_unit, pickup=pickup_dt, now=now)
    delivered = await _notify_buyer(ctx, whatsapp_event("confirmation", confirmation))
    msg = OutboxMessage(
        mart_id=call.mart_id,
        kind="whatsapp_confirmation",
        call_id=call_id,
        to_buyer_id=call.brief.buyer.buyer_id,
        payload={
            "item": call.brief.item,
            "quantity": quantity,
            "unit": call.brief.quantity_unit,
            "price_per_unit": price_per_unit,
            "pickup_time": pickup_dt.isoformat(),
            "text": confirmation,
        },
        status="sent_in_call" if delivered else "stub_not_sent",
    )
    await ctx.store.add_outbox(msg)

    ctx.closing = True
    ctx.outcome_set = True
    ctx.outcome = "deal" if quantity >= call.brief.quantity else "partial_deal"
    ctx.agreed_price_per_unit = price_per_unit
    ctx.agreed_quantity = quantity
    ctx.agreed_quantity_unit = call.brief.quantity_unit
    ctx.pickup_time = pickup_dt
    return {"ok": True, "deal_id": deal.call_id}


async def schedule_callback(
    when_iso: str,
    note: str,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Schedules a callback when the buyer requests to be called at a later time.

    Args:
        when_iso: Desired callback time in ISO format with timezone offset (e.g. 2026-10-08T11:00:00+05:00). Must be strictly in the future.
        note: Note explaining the reason for callback.
    """
    call_id = tool_context.state.get("call_id") if tool_context else None
    ctx = get_context(call_id) if call_id else None
    if not ctx:
        return {"ok": False, "reason": "Active call context not found"}

    if ctx.outcome_set:
        return {"ok": False, "reason": "Outcome already recorded for this call."}

    now = ctx.clock() if ctx.clock else datetime.now(PKT)
    try:
        if len(when_iso.strip()) <= 8 and ":" in when_iso:
            # Time only string like "11:00" or "11:00:00"
            t_part = time.fromisoformat(when_iso.strip())
            cb_dt = datetime.combine(now.date(), t_part, tzinfo=PKT)
            if cb_dt <= now:
                cb_dt += timedelta(days=1)
        else:
            cb_dt = datetime.fromisoformat(when_iso)
            if cb_dt.tzinfo is None:
                cb_dt = cb_dt.replace(tzinfo=PKT)
    except Exception:
        return {"ok": False, "reason": "Invalid callback time format."}

    # If the requested callback time is right now or in the past, roll forward to tomorrow
    while cb_dt <= now:
        cb_dt += timedelta(days=1)

    call = await ctx.store.get_call(call_id)

    # If outside calling hours, move to next opening time
    ch = call.brief.calling_hours
    cb_time = cb_dt.time()
    if cb_time < ch.start or cb_time > ch.end:
        # Adjust to opening hours
        if cb_time < ch.start:
            cb_dt = cb_dt.replace(hour=ch.start.hour, minute=ch.start.minute, second=0)
        else:
            cb_dt = (cb_dt + timedelta(days=1)).replace(hour=ch.start.hour, minute=ch.start.minute, second=0)

    ctx.closing = True
    ctx.outcome_set = True
    ctx.outcome = "call_back"
    ctx.callback_at = cb_dt
    return {"ok": True, "callback_at_words": time_words(cb_dt), "callback_at": cb_dt.isoformat()}


async def send_photo(tool_context: ToolContext = None) -> dict[str, Any]:
    """Sends the buyer a photo of the produce on WhatsApp, when they want to see it before agreeing."""
    call_id = tool_context.state.get("call_id") if tool_context else None
    ctx = get_context(call_id) if call_id else None
    if not ctx:
        return {"ok": False, "message": "Call context not found"}

    if "photo_sent" in ctx.flags:  # one photo per call; asking again shouldn't spam the buyer
        return {"ok": True, "message": "The photo was already sent on WhatsApp in this call."}

    call = await ctx.store.get_call(call_id)
    media_url = await item_photo_url(ctx.store, call)
    if media_url is None:
        return {
            "ok": False,
            "message": "No photo is available for this item. Tell the buyer, and describe its condition honestly.",
        }

    delivered = await _notify_buyer(ctx, whatsapp_event("photo", photo_caption(call), media_url))
    await ctx.store.add_outbox(
        OutboxMessage(
            mart_id=call.mart_id,
            kind="photo",
            call_id=call_id,
            to_buyer_id=call.brief.buyer.buyer_id,
            payload={"item": call.brief.item, "media_url": media_url},
            status="sent_in_call" if delivered else "stub_not_sent",
        )
    )
    ctx.flags.append("photo_sent")
    return {"ok": True, "message": "Photo sent to the buyer on WhatsApp."}


async def record_outcome(
    outcome: Literal["declined", "wants_manager", "do_not_call", "wants_photo"],
    note: str,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """Records a final non-deal outcome for the call and triggers call closure.
    Call this immediately when the buyer declines, asks to speak with a human/manager, or requests not to be called again.

    Args:
        outcome: One of 'declined', 'wants_manager', 'do_not_call', 'wants_photo'.
        note: Brief explanation or reason.
    """
    call_id = tool_context.state.get("call_id") if tool_context else None
    ctx = get_context(call_id) if call_id else None
    if not ctx:
        return {"ok": False, "reason": "Call context not found"}

    if ctx.outcome_set:
        return {"ok": False, "reason": "outcome already recorded"}

    call = await ctx.store.get_call(call_id)
    now = ctx.clock() if ctx.clock else datetime.now(PKT)

    if outcome == "do_not_call":
        if getattr(call, "channel", "browser") == "browser" and call.brief.buyer.buyer_id.startswith("places:"):
            if "dnc_roleplay_not_recorded" not in ctx.flags:
                ctx.flags.append("dnc_roleplay_not_recorded")
        else:
            await ctx.store.add_do_not_call(call.mart_id, call.brief.buyer.buyer_id)
    elif outcome == "wants_manager":
        task = StaffTask(
            mart_id=call.mart_id,
            kind="manager_callback",
            call_id=call_id,
            note=note,
            created_at=now,
        )
        await ctx.store.add_staff_task(task)

    ctx.closing = True
    ctx.outcome_set = True
    ctx.outcome = outcome
    return {"ok": True, "recorded": outcome}


def get_negotiator_tools() -> list[FunctionTool]:
    """Returns the list of BLOCKING ADK FunctionTools for the negotiator."""
    tools = [
        FunctionTool(verify_offer),
        FunctionTool(confirm_deal),
        FunctionTool(schedule_callback),
        FunctionTool(send_photo),
        FunctionTool(record_outcome),
    ]
    for t in tools:
        t.behavior = types.Behavior.BLOCKING
    return tools
