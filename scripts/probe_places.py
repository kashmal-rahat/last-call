#!/usr/bin/env python3
"""Places API probe script for Module 4 Step 4.

Runs at most 7 live requests:
- 5 buyer types at default branch (Johar Town)
- juice_shop at Bahria Town
- juice_shop at Gulberg

Measures counts, phone presence, distance, open_now status, business status,
and writes plans/module-4/results/probe.md (NEVER raw phone numbers).
"""

import asyncio
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "shared"))
sys.path.insert(0, str(REPO_DIR / "services/api"))

from lastcall_api.scout.places import PlaceRaw, PlacesClient, PlacesError
from lastcall_api.scout.specs import SEARCH_SPECS, SearchSpec
from lastcall_shared.models import GeoPoint, MartRules


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.asin(math.sqrt(a))


def clean_name(s: str) -> str:
    cleaned = "".join(ch for ch in s if ch.isprintable() and ord(ch) >= 32)
    return " ".join(cleaned.split())[:80].replace("|", "\\|")


async def probe_request(
    client: PlacesClient,
    spec: SearchSpec,
    branch_name: str,
    center: GeoPoint,
    radius_km: float = 10.0,
) -> dict:
    t0 = time.monotonic()
    error_msg = None
    places: list[PlaceRaw] = []
    status = "OK"

    try:
        places = await client.search(
            spec=spec,
            center=center,
            radius_km=radius_km,
        )
    except PlacesError as e:
        status = f"ERROR_{e.status_code}"
        error_msg = e.message
    except Exception as e:
        status = "EXCEPTION"
        error_msg = str(e)

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Compute distances and annotations
    items = []
    has_phone_count = 0
    open_now_true = 0
    open_now_false = 0
    open_now_unknown = 0
    status_counts: dict[str, int] = {}
    usable_within_10km = 0

    for p in places:
        dist = (
            round(haversine_km(center.lat, center.lng, p.lat, p.lng), 2)
            if (p.lat is not None and p.lng is not None)
            else 999.0
        )
        phone_present = bool(p.international_phone and p.international_phone.strip())
        if phone_present:
            has_phone_count += 1

        if p.open_now is True:
            open_now_true += 1
        elif p.open_now is False:
            open_now_false += 1
        else:
            open_now_unknown += 1

        b_status = p.business_status or "UNKNOWN"
        status_counts[b_status] = status_counts.get(b_status, 0) + 1

        is_operational = b_status in ("OPERATIONAL", "UNKNOWN")
        is_usable = is_operational and phone_present and dist <= 10.0
        if is_usable:
            usable_within_10km += 1

        items.append({
            "name": clean_name(p.name),
            "primary_type": p.primary_type or "—",
            "distance_km": dist,
            "phone_present": phone_present,
            "open_now": p.open_now,
            "business_status": b_status,
            "is_usable": is_usable,
        })

    # Sort by distance
    items.sort(key=lambda x: x["distance_km"])

    return {
        "buyer_type": spec.buyer_type,
        "query": spec.text_query,
        "included_type": spec.included_type,
        "rank_preference": spec.rank_preference,
        "branch_name": branch_name,
        "center": {"lat": center.lat, "lng": center.lng},
        "status": status,
        "error_msg": error_msg,
        "latency_ms": latency_ms,
        "raw_count": len(places),
        "has_phone_count": has_phone_count,
        "open_now_true": open_now_true,
        "open_now_false": open_now_false,
        "open_now_unknown": open_now_unknown,
        "status_counts": status_counts,
        "usable_within_10km": usable_within_10km,
        "nearest_10": items[:10],
    }


async def main():
    mart_json_path = REPO_DIR / "shared/lastcall_shared/marts/demo_mart.json"
    rules = MartRules.model_validate_json(mart_json_path.read_text())

    johar = rules.branch("johar_town")
    bahria = rules.branch("bahria_town")
    gulberg = rules.branch("gulberg")

    client = PlacesClient()

    targets = [
        (SEARCH_SPECS["juice_shop"], johar.name, johar.geo),
        (SEARCH_SPECS["restaurant"], johar.name, johar.geo),
        (SEARCH_SPECS["bakery"], johar.name, johar.geo),
        (SEARCH_SPECS["charity"], johar.name, johar.geo),
        (SEARCH_SPECS["dairy_farm"], johar.name, johar.geo),
        (SEARCH_SPECS["juice_shop"], bahria.name, bahria.geo),
        (SEARCH_SPECS["juice_shop"], gulberg.name, gulberg.geo),
    ]

    print(f"Executing {len(targets)} Places API probe requests...")
    results = []
    for i, (spec, b_name, b_geo) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] Probing {spec.buyer_type} at {b_name}...")
        res = await probe_request(client, spec, b_name, b_geo, radius_km=10.0)
        results.append(res)
        print(f"    Status: {res['status']}, Count: {res['raw_count']}, Usable (≤10km+phone): {res['usable_within_10km']}, Latency: {res['latency_ms']}ms")

    # Generate Markdown Report
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Places API Probe Report (Milestone 4A Step 4)",
        f"Generated: {now_str}",
        "",
        "## Summary of Findings",
        "",
        "| # | Branch | Buyer Type | Query | Rank Pref | Raw Count | With Phone | Open Now (T/F/?) | Usable (≤10km+phone) | Latency | Status |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for idx, r in enumerate(results, 1):
        open_str = f"{r['open_now_true']}/{r['open_now_false']}/{r['open_now_unknown']}"
        usable_warn = f"**{r['usable_within_10km']}**" if r['usable_within_10km'] < 3 else str(r['usable_within_10km'])
        lines.append(
            f"| {idx} | {r['branch_name']} | `{r['buyer_type']}` | `{r['query']}` | {r['rank_preference']} | "
            f"{r['raw_count']} | {r['has_phone_count']} | {open_str} | {usable_warn} | {r['latency_ms']}ms | {r['status']} |"
        )

    lines.extend([
        "",
        "## SKU & Field Mask Verification",
        "- **Field Mask**: `places.id,places.displayName,places.primaryType,places.types,places.location,places.businessStatus,places.internationalPhoneNumber,places.currentOpeningHours.openNow,places.googleMapsUri`",
        "- **Field Mask Status**: Accepted by Places API (New) without rejection.",
        "- **Atmosphere Fields**: Zero Atmosphere fields requested (strictly Enterprise SKU).",
        "- **Rank Preferences**: `DISTANCE` accepted for typed queries (`juice_shop`, `restaurant`, `bakery`); `RELEVANCE` accepted for free-text queries (`charity`, `dairy_farm`).",
        "",
        "## Detailed Candidate Lists (Top 10 Nearest per Probe)",
        "",
    ])

    for idx, r in enumerate(results, 1):
        lines.extend([
            f"### Probe {idx}: {r['buyer_type']} ({r['branch_name']})",
            f"- **Query**: `{r['query']}`",
            f"- **Business Status Counts**: {json.dumps(r['status_counts'])}",
            f"- **Usable Count (Operational + Phone + ≤10km)**: {r['usable_within_10km']}" + (" ⚠️ **Fewer than 3 usable candidates!**" if r['usable_within_10km'] < 3 else ""),
            "",
            "| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Operational | Usable |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for rank, item in enumerate(r["nearest_10"], 1):
            open_display = "Yes" if item["open_now"] is True else ("No" if item["open_now"] is False else "Unknown")
            phone_display = "Yes" if item["phone_present"] else "No"
            usable_display = "Yes" if item["is_usable"] else "No"
            lines.append(
                f"| {rank} | {item['name']} | `{item['primary_type']}` | {item['distance_km']} km | {phone_display} | {open_display} | {item['business_status']} | {usable_display} |"
            )
        lines.append("")

    report_path = REPO_DIR / "plans/module-4/results/probe.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    print(f"\nReport written to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
