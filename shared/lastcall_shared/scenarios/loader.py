"""Scenario loader and call record generator for Last Call."""

import json
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime

from lastcall_shared.clock import PKT
from lastcall_shared.models import (
    BatchRecord,
    BuyerInfo,
    CallingHours,
    CallRecord,
    DealBrief,
    MartInfo,
    NegotiationPolicy,
    init_negotiation,
)

SCENARIOS_DIR = Path(__file__).parent


def parse_relative_offset(offset_str: str) -> timedelta:
    s = offset_str.strip()
    if s.startswith("+"):
        s = s[1:]
    if s.endswith("h"):
        return timedelta(hours=float(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=float(s[:-1]))
    if s.endswith("d"):
        return timedelta(days=float(s[:-1]))
    return timedelta(hours=4)


def load_scenario(name_or_path: str) -> dict[str, Any]:
    """Loads a scenario dictionary by slug name or file path."""
    p = Path(name_or_path)
    if not p.exists():
        p = SCENARIOS_DIR / f"{name_or_path}.json"
    if not p.exists():
        raise FileNotFoundError(f"Scenario not found: {name_or_path}")

    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def list_scenarios() -> list[str]:
    """Lists all available scenario slugs."""
    return [p.stem for p in SCENARIOS_DIR.glob("*.json")]


def build_call(
    scenario_data_or_slug: dict[str, Any] | str,
    now: AwareDatetime | None = None,
) -> tuple[CallRecord, BatchRecord]:
    """Builds a fresh CallRecord and BatchRecord from a scenario definition.

    - Resolves relative times against now (in Asia/Karachi).
    - Generates unique call_id, batch_id, and test buyer_id (test:{slug}:{call_id}).
    - Initializes the deterministic negotiation state and policy.
    """
    if isinstance(scenario_data_or_slug, str):
        data = load_scenario(scenario_data_or_slug)
    else:
        data = dict(scenario_data_or_slug)

    slug = data.get("slug", "deal")
    if now is None:
        now = datetime.now(PKT)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=PKT)

    call_id = f"call_{slug}_{uuid.uuid4().hex[:8]}"
    batch_id = f"batch_{slug}_{uuid.uuid4().hex[:8]}"
    buyer_id = f"test:{slug}:{call_id}"
    inspection_id = f"insp_{slug}_{uuid.uuid4().hex[:8]}"

    # Relative deadlines
    deadline_offset = parse_relative_offset(data.get("pickup_deadline", "+4h"))
    pickup_deadline = now + deadline_offset

    # Relative pickup window formatting
    raw_window = data.get("pickup_window", ["+1h", "+4h"])
    if isinstance(raw_window, list) and len(raw_window) == 2:
        t_start = (now + parse_relative_offset(raw_window[0])).strftime("%I:%M %p")
        t_end = (now + parse_relative_offset(raw_window[1])).strftime("%I:%M %p")
        pickup_window = f"{t_start} to {t_end}"
    else:
        pickup_window = str(raw_window)

    buyer_data = dict(data["buyer"])
    buyer_data["buyer_id"] = buyer_id
    buyer = BuyerInfo.model_validate(buyer_data)

    calling_hours_data = data["calling_hours"]
    if isinstance(calling_hours_data["start"], str):
        h, m, s = map(int, calling_hours_data["start"].split(":"))
        ch_start = time(h, m, s)
    else:
        ch_start = calling_hours_data["start"]

    if isinstance(calling_hours_data["end"], str):
        h, m, s = map(int, calling_hours_data["end"].split(":"))
        ch_end = time(h, m, s)
    else:
        ch_end = calling_hours_data["end"]

    calling_hours = CallingHours(
        start=ch_start,
        end=ch_end,
        timezone=calling_hours_data.get("timezone", "Asia/Karachi"),
    )

    mart = MartInfo.model_validate(data["mart"])

    brief = DealBrief(
        mart_id=data.get("mart_id", "mart_khi_001"),
        batch_id=batch_id,
        call_id=call_id,
        deal_type=data.get("deal_type", "sale"),
        item=data["item"],
        condition=data["condition"],
        quantity=float(data["quantity"]),
        quantity_unit=data["unit"],
        quantity_confirmed_by_staff=data.get("quantity_confirmed_by_staff", True),
        buyer=buyer,
        opening_price_per_unit=data.get("opening_price_per_unit", 0),
        opening_price_unit=data["unit"],
        floor_price_per_unit=data.get("floor_price_per_unit", 0),
        floor_price_unit=data["unit"],
        market_rate_per_unit=data.get("market_rate_per_unit"),
        pickup_window=pickup_window,
        pickup_deadline=pickup_deadline,
        mart=mart,
        payment_terms=data["payment_terms"],
        language=data.get("language", "ur"),
        calling_hours=calling_hours,
    )

    batch = BatchRecord(
        batch_id=batch_id,
        mart_id=brief.mart_id,
        inspection_id=inspection_id,
        item_key=f"crate_{slug}_01",
        item=brief.item,
        unit=brief.quantity_unit,
        total_quantity=brief.quantity,
        remaining_quantity=brief.quantity,
        status="finding_buyers",
    )

    policy = NegotiationPolicy()
    state = init_negotiation(brief, policy)

    call_record = CallRecord(
        call_id=call_id,
        mart_id=brief.mart_id,
        batch_id=batch_id,
        brief=brief,
        policy=policy,
        negotiation=state,
        status="pending",
        session_nonce=uuid.uuid4().hex,
        created_at=now,
    )

    return call_record, batch
