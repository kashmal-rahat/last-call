"""Orchestration of Ladder decisions for an inspection (Module 3)."""

import logging
import time
from collections import Counter
from datetime import datetime
from typing import Any

from google import genai

from lastcall_api.ladder.engine import clock_offset, decide_item, find_price, hours_until_closing
from lastcall_api.ladder.profiles import resolve_profiles
from lastcall_shared.models import (
    FreshnessResult,
    LadderDecision,
    LadderMeta,
    LadderResult,
    MartRules,
)

logger = logging.getLogger("lastcall_api.ladder")


async def decide_inspection(
    result: FreshnessResult,
    *,
    rules: MartRules,
    store: Any,
    now: datetime,
    hours_override: float | None = None,
    price_overrides: dict[str, int] | None = None,
    client: genai.Client | None = None,
) -> LadderResult:
    """Decides clearance ladder steps for all items in a freshness inspection."""
    start_t = time.monotonic()
    H = hours_until_closing(rules, now, override=hours_override)
    offset_s = clock_offset(rules, now, override=hours_override)

    # photo_status != "ok" -> no decisions
    if result.photo_status != "ok":
        latency_ms = int((time.monotonic() - start_t) * 1000)
        meta = LadderMeta(
            latency_ms=latency_ms,
            profiles_used=0,
            profiles_generated=0,
            profile_calls=0,
            fallback_profiles=0,
            input_tokens=0,
            output_tokens=0,
        )
        return LadderResult(
            mart_id=rules.mart_id,
            inspection_id=result.inspection_id,
            decided_at=now,
            hours_until_closing=H,
            clock_offset_s=offset_s,
            decisions=[],
            meta=meta,
        )

    # 1. Resolve profiles for all item names (20s budget, monotonic clock)
    deadline = time.monotonic() + 20.0
    names = [item.name for item in result.items]

    profiles, usage, stats = await resolve_profiles(
        names,
        store=store,
        client=client,
        deadline=deadline,
    )

    unique_profiles = {p.key: p for p in profiles.values()}

    # 2. Decide each item, preserving the inspection's order
    decisions: list[LadderDecision] = []
    price_overrides = price_overrides or {}

    for item in result.items:
        profile = profiles[item.name]
        if item.item_key in price_overrides:
            shelf_price = price_overrides[item.item_key]
        else:
            shelf_price = find_price(rules, item.name, item.quantity.unit)

        decision = decide_item(
            item=item,
            profile=profile,
            rules=rules,
            H=H,
            price=shelf_price,
        )
        decisions.append(decision)

    latency_ms = int((time.monotonic() - start_t) * 1000)
    meta = LadderMeta(
        latency_ms=latency_ms,
        profiles_used=len(unique_profiles),
        profiles_generated=stats.generated,
        profile_calls=stats.calls,
        fallback_profiles=stats.fallbacks,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )

    # 3. Structured log: never produce names, evidence, reasons or notes
    step_counts = dict(Counter(d.step for d in decisions))
    logger.info(
        "decide_inspection complete",
        extra={
            "inspection_id": result.inspection_id,
            "mart_id": rules.mart_id,
            "items_count": len(result.items),
            "step_counts": step_counts,
            "profiles_used": meta.profiles_used,
            "profiles_generated": meta.profiles_generated,
            "profile_calls": meta.profile_calls,
            "fallback_profiles": meta.fallback_profiles,
            "latency_ms": meta.latency_ms,
            "input_tokens": meta.input_tokens,
            "output_tokens": meta.output_tokens,
        },
    )

    return LadderResult(
        mart_id=rules.mart_id,
        inspection_id=result.inspection_id,
        decided_at=now,
        hours_until_closing=H,
        clock_offset_s=offset_s,
        decisions=decisions,
        meta=meta,
    )
