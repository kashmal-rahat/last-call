"""Filtering, ranking, and reason construction for Scout candidates (pure logic, no I/O).

D50, D52, Step 5.
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from lastcall_api.scout.places import PlaceRaw
from lastcall_shared.buyer_keys import phone_key
from lastcall_shared.logging_utils import setup_structured_logging
from lastcall_shared.models import (
    BuyerFit,
    BuyerHistory,
    BuyerType,
    GeoPoint,
    MartRules,
    ScoutCandidate,
    ScreenedOut,
    SkipReason,
)

logger = setup_structured_logging(service_name="scout_rank")

MAX_FIT_CANDIDATES = 40

_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")

TYPE_NAMES: dict[BuyerType, str] = {
    "juice_shop": "Juice shop",
    "restaurant": "Restaurant",
    "bakery": "Bakery",
    "charity": "Charity",
    "dairy_farm": "Dairy farm",
    "other": "Other",
}


def normalise_phone(international: str | None) -> str | None:
    """Normalises an international phone number to E.164.

    Keeps '+' and digits. Validates format: ^\\+[1-9]\\d{7,14}$.
    Returns None if missing or invalid.
    """
    if not international or not isinstance(international, str):
        return None
    cleaned = "".join(ch for ch in international if ch == "+" or ch.isdigit())
    if _PHONE_RE.match(cleaned):
        return cleaned
    return None


def distance_km(a: GeoPoint, b: GeoPoint) -> float:
    """Computes haversine great-circle distance between two GeoPoints (R = 6371.0088 km)."""
    r = 6371.0088
    lat1, lon1 = math.radians(a.lat), math.radians(a.lng)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lng)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(h))


def sanitise_name(s: str) -> str:
    """Removes control characters, collapses whitespace, and caps length at 80 chars."""
    cleaned = "".join(ch for ch in s if ch.isprintable() and ord(ch) >= 32)
    return " ".join(cleaned.split())[:80]


@dataclass
class FilteredCandidate:
    place_id: str
    name: str
    buyer_type: BuyerType
    primary_type: str | None
    types: list[str]
    phone: str
    distance_km: float
    open_now: bool | None
    maps_uri: str | None


def apply_filters(
    places: list[PlaceRaw],
    *,
    center: GeoPoint,
    rules: MartRules,
    histories: dict[str, BuyerHistory],
    dnc: set[str],
    now: datetime,
    buyer_type_of: dict[str, BuyerType],
    phone_secret: str,
) -> tuple[list[FilteredCandidate], dict[SkipReason, int]]:
    """Applies code-level deterministic business filters (D50, D52).

    1. Dedupes by place_id (first buyer type in decision order wins).
    2. Filters in order:
       - not_operational
       - too_far
       - no_phone
       - do_not_call
       - cooldown
       - duplicate_phone
    3. Caps at MAX_FIT_CANDIDATES (40 nearest); any remainder counted as not_screened.
    """
    skipped: dict[SkipReason, int] = {}

    # 1. Dedupe by place ID first
    seen_place_ids: set[str] = set()
    deduped: list[PlaceRaw] = []
    for p in places:
        if "/" in p.id:
            logger.warning("Skipping place with invalid '/' in place_id", extra={"place_id": p.id})
            continue
        if p.id not in seen_place_ids:
            seen_place_ids.add(p.id)
            deduped.append(p)

    # 2. Sequential filters 1-5
    survivors: list[FilteredCandidate] = []
    for p in deduped:
        b_type = buyer_type_of.get(p.id, "other")

        # Filter 1: not_operational (missing/None counts as operational)
        status = p.business_status or "OPERATIONAL"
        if status != "OPERATIONAL":
            skipped["not_operational"] = skipped.get("not_operational", 0) + 1
            continue

        # Filter 2: too_far
        if p.lat is None or p.lng is None:
            skipped["too_far"] = skipped.get("too_far", 0) + 1
            continue
        dist = round(distance_km(center, GeoPoint(lat=p.lat, lng=p.lng)), 1)
        if dist > rules.scout_radius_km:
            skipped["too_far"] = skipped.get("too_far", 0) + 1
            continue

        # Filter 3: no_phone
        phone = normalise_phone(p.international_phone)
        if not phone:
            skipped["no_phone"] = skipped.get("no_phone", 0) + 1
            continue

        # Filter 4: do_not_call
        buyer_id = f"places:{p.id}"
        pk = phone_key(phone, phone_secret)
        if buyer_id in dnc or pk in dnc:
            skipped["do_not_call"] = skipped.get("do_not_call", 0) + 1
            continue

        # Filter 5: cooldown
        hist = histories.get(buyer_id)
        if hist and hist.last_called_at:
            delta_hours = (now - hist.last_called_at).total_seconds() / 3600.0
            if delta_hours < rules.buyer_cooldown_hours and hist.last_outcome not in ("deal", "partial_deal"):
                skipped["cooldown"] = skipped.get("cooldown", 0) + 1
                continue

        survivors.append(
            FilteredCandidate(
                place_id=p.id,
                name=sanitise_name(p.name),
                buyer_type=b_type,
                primary_type=p.primary_type,
                types=list(p.types),
                phone=phone,
                distance_km=dist,
                open_now=p.open_now,
                maps_uri=p.maps_uri,
            )
        )

    # Filter 6: duplicate_phone (keep nearer listing, ties broken by place_id)
    survivors.sort(key=lambda c: (c.distance_km, c.place_id))
    seen_phones: set[str] = set()
    kept_after_phone_dedup: list[FilteredCandidate] = []
    for c in survivors:
        if c.phone in seen_phones:
            skipped["duplicate_phone"] = skipped.get("duplicate_phone", 0) + 1
        else:
            seen_phones.add(c.phone)
            kept_after_phone_dedup.append(c)

    # 40-nearest cap: keep MAX_FIT_CANDIDATES nearest, count remainder as not_screened
    if len(kept_after_phone_dedup) > MAX_FIT_CANDIDATES:
        overflow = len(kept_after_phone_dedup) - MAX_FIT_CANDIDATES
        skipped["not_screened"] = skipped.get("not_screened", 0) + overflow
        kept = kept_after_phone_dedup[:MAX_FIT_CANDIDATES]
    else:
        kept = kept_after_phone_dedup

    return kept, skipped


def build_reason(
    buyer_type: BuyerType,
    distance_km: float,
    open_now: bool | None,
    history: BuyerHistory | None,
    tz: ZoneInfo | timezone,
) -> str:
    """Constructs verifiable English reason fact line (D50)."""
    type_label = TYPE_NAMES.get(buyer_type, "Other")

    if open_now is True:
        hours_str = "open now"
    elif open_now is False:
        hours_str = "closed now"
    else:
        hours_str = "hours unknown"

    dist_str = f"{distance_km:.1f} km"

    if history and history.deals > 0 and history.last_deal_at:
        dt = history.last_deal_at.astimezone(tz)
        date_str = f"{dt.day} {dt.strftime('%b')}"
        if history.last_deal_price is not None and history.last_deal_unit:
            deal_prefix = f"Bought from us {date_str} (Rs {history.last_deal_price}/{history.last_deal_unit}) · "
        elif history.last_deal_price is not None:
            deal_prefix = f"Bought from us {date_str} (Rs {history.last_deal_price}) · "
        else:
            deal_prefix = f"Bought from us {date_str} · "
        return f"{deal_prefix}{type_label} · {dist_str} · {hours_str}"

    return f"{type_label} · {dist_str} · {hours_str}"


def rank(
    kept: list[FilteredCandidate],
    fits: dict[str, tuple[BuyerFit, str]],
    histories: dict[str, BuyerHistory],
    max_buyers: int,
    tz: ZoneInfo | timezone,
) -> tuple[list[ScoutCandidate], list[ScreenedOut]]:
    """Ranks candidates according to D50 sort rules and extracts ScreenedOut candidates.

    Sort order:
    1. past_deals > 0 first (newest last_deal_at first)
    2. not closed (open_now True or None) before closed (False)
    3. fit likely before possible
    4. open_now True before None
    5. distance ascending
    6. place_id ascending
    """
    screened_out_raw: list[ScreenedOut] = []
    viable: list[FilteredCandidate] = []

    for c in kept:
        fit_val, fit_why = fits.get(c.place_id, ("possible", ""))
        if fit_val == "unlikely":
            screened_out_raw.append(
                ScreenedOut(
                    name=c.name,
                    buyer_type=c.buyer_type,
                    distance_km=c.distance_km,
                    why=fit_why[:100],
                )
            )
        else:
            viable.append(c)

    # ScreenedOut sorted nearest first, capped at 10
    screened_out_raw.sort(key=lambda s: (s.distance_km, s.name))
    screened_out = screened_out_raw[:10]

    def sort_key(c: FilteredCandidate) -> tuple[Any, ...]:
        hist = histories.get(f"places:{c.place_id}")
        past_deals = hist.deals if hist else 0
        has_deal_flag = 0 if past_deals > 0 else 1

        last_deal_ts = -hist.last_deal_at.timestamp() if (hist and hist.last_deal_at) else 0.0

        is_closed_flag = 1 if c.open_now is False else 0

        fit_val, _ = fits.get(c.place_id, ("possible", ""))
        fit_flag = 0 if fit_val == "likely" else 1

        open_pref = 0 if c.open_now is True else (1 if c.open_now is None else 2)

        return (
            has_deal_flag,
            last_deal_ts,
            is_closed_flag,
            fit_flag,
            open_pref,
            c.distance_km,
            c.place_id,
        )

    viable.sort(key=sort_key)

    candidates: list[ScoutCandidate] = []
    for idx, c in enumerate(viable[:max_buyers], 1):
        fit_val, fit_why = fits.get(c.place_id, ("possible", ""))
        hist = histories.get(f"places:{c.place_id}")
        reason_line = build_reason(
            buyer_type=c.buyer_type,
            distance_km=c.distance_km,
            open_now=c.open_now,
            history=hist,
            tz=tz,
        )
        candidates.append(
            ScoutCandidate(
                rank=idx,
                buyer_id=f"places:{c.place_id}",
                place_id=c.place_id,
                name=c.name,
                buyer_type=c.buyer_type,
                primary_type=c.primary_type,
                phone=c.phone,
                distance_km=c.distance_km,
                open_now=c.open_now,
                maps_uri=c.maps_uri,
                fit=fit_val,
                fit_why=fit_why[:100],
                past_deals=hist.deals if hist else 0,
                last_deal_at=hist.last_deal_at if hist else None,
                reason=reason_line,
            )
        )

    return candidates, screened_out
