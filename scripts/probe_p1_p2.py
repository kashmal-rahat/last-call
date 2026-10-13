#!/usr/bin/env python3
"""P1 & P2 diagnostic checks for Module 4 Step 4.

Runs:
- P1: Two charity query variants at Johar Town:
  A: "welfare trust dastarkhwan"
  B: "dastarkhwan"
- P2: One Nearby Search diagnostic at Gulberg for juice_shop (radius 5,000m)

Appends results to plans/module-4/results/probe.md (escaping any '|' characters).
"""

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "shared"))
sys.path.insert(0, str(REPO_DIR / "services/api"))

sys.path.insert(0, str(REPO_DIR / "scripts"))

from probe_places import clean_name, haversine_km, probe_request

from lastcall_api.scout.places import PlacesClient, get_oauth_token, parse_place_raw
from lastcall_api.scout.specs import FIELD_MASK, SearchSpec
from lastcall_shared.config import get_settings
from lastcall_shared.models import GeoPoint, MartRules


def escape_table(s: str) -> str:
    return clean_name(s).replace("|", "\\|")


async def run_nearby_search(
    center: GeoPoint,
    radius_meters: float = 5000.0,
    included_types: list[str] = None,
    rank_pref: str = "DISTANCE",
) -> tuple[int, int, list[dict], str | None]:
    token = await get_oauth_token()
    project_id = get_settings().GOOGLE_CLOUD_PROJECT
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Goog-User-Project": project_id,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }
    body = {
        "includedTypes": included_types or ["juice_shop"],
        "maxResultCount": 20,
        "rankPreference": rank_pref,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": center.lat,
                    "longitude": center.lng,
                },
                "radius": radius_meters,
            }
        },
        "languageCode": "en",
        "regionCode": "PK",
    }

    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.post(
            "https://places.googleapis.com/v1/places:searchNearby",
            headers=headers,
            json=body,
        )
    latency_ms = int((time.monotonic() - t0) * 1000)

    if resp.status_code >= 400:
        return resp.status_code, latency_ms, [], resp.text

    data = resp.json()
    places_raw = data.get("places") or []
    items = []
    for p_json in places_raw:
        p = parse_place_raw(p_json)
        dist = (
            round(haversine_km(center.lat, center.lng, p.lat, p.lng), 2)
            if (p.lat is not None and p.lng is not None)
            else 999.0
        )
        phone_present = bool(p.international_phone and p.international_phone.strip())
        b_status = p.business_status or "UNKNOWN"
        is_operational = b_status in ("OPERATIONAL", "UNKNOWN")
        is_usable = is_operational and phone_present and dist <= (radius_meters / 1000.0)
        items.append(
            {
                "name": escape_table(p.name),
                "primary_type": p.primary_type or "—",
                "distance_km": dist,
                "phone_present": phone_present,
                "open_now": p.open_now,
                "business_status": b_status,
                "is_usable": is_usable,
            }
        )
    items.sort(key=lambda x: x["distance_km"])
    return resp.status_code, latency_ms, items, None


async def main():
    mart_json_path = REPO_DIR / "shared/lastcall_shared/marts/demo_mart.json"
    rules = MartRules.model_validate_json(mart_json_path.read_text())

    johar = rules.branch("johar_town")
    gulberg = rules.branch("gulberg")

    client = PlacesClient()

    print("--- Running P1: Charity Query Variants at Johar Town ---")
    spec_a = SearchSpec(
        buyer_type="charity",
        text_query="welfare trust dastarkhwan",
        included_type=None,
        strict_type_filtering=None,
        rank_preference="RELEVANCE",
    )
    spec_b = SearchSpec(
        buyer_type="charity",
        text_query="dastarkhwan",
        included_type=None,
        strict_type_filtering=None,
        rank_preference="RELEVANCE",
    )

    print("[P1-A] Probing 'welfare trust dastarkhwan'...")
    res_a = await probe_request(client, spec_a, johar.name, johar.geo, radius_km=10.0, page_size=20)
    print(
        f"       Raw count: {res_a['raw_count']}, Usable ≤10km: {res_a['usable_within_10km']}, Latency: {res_a['latency_ms']}ms"
    )

    print("[P1-B] Probing 'dastarkhwan'...")
    res_b = await probe_request(client, spec_b, johar.name, johar.geo, radius_km=10.0, page_size=20)
    print(
        f"       Raw count: {res_b['raw_count']}, Usable ≤10km: {res_b['usable_within_10km']}, Latency: {res_b['latency_ms']}ms"
    )

    print("\n--- Running P2: Nearby Search (New) Diagnostic at Gulberg ---")
    status_code, lat_nearby, items_nearby, err_nearby = await run_nearby_search(
        center=gulberg.geo,
        radius_meters=5000.0,
        included_types=["juice_shop"],
        rank_pref="DISTANCE",
    )
    print(f"[P2] Status: {status_code}, Count: {len(items_nearby)}, Latency: {lat_nearby}ms")
    if err_nearby:
        print(f"     Error: {err_nearby}")
    else:
        nearest_dist = items_nearby[0]["distance_km"] if items_nearby else None
        print(f"     Nearest juice shop in Nearby Search: {nearest_dist} km (Text Search nearest was 4.42 km)")

    # Format Markdown to append to probe.md
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "",
        "---",
        "",
        f"## P1 & P2 Diagnostic Results ({now_str})",
        "",
        "### P1: Charity Query Variants (Johar Town, 10 km radius)",
        "",
        "| Query | Raw Count | With Phone | Open Now (T/F/?) | Usable (≤10km+phone) | Latency | Status |",
        "|---|---|---|---|---|---|---|",
    ]

    for label, r in [("`welfare trust dastarkhwan` (A)", res_a), ("`dastarkhwan` (B)", res_b)]:
        open_str = f"{r['open_now_true']}/{r['open_now_false']}/{r['open_now_unknown']}"
        lines.append(
            f"| {label} | {r['raw_count']} | {r['has_phone_count']} | {open_str} | **{r['usable_within_10km']}** | {r['latency_ms']}ms | {r['status']} |"
        )

    lines.extend(
        [
            "",
            "#### P1-A Top Candidates (`welfare trust dastarkhwan`):",
            "",
            "| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Usable |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for rank, item in enumerate(res_a["nearest_10"][:10], 1):
        lines.append(
            f"| {rank} | {escape_table(item['name'])} | `{item['primary_type']}` | {item['distance_km']} km | {'Yes' if item['phone_present'] else 'No'} | {'Yes' if item['open_now'] is True else ('No' if item['open_now'] is False else 'Unknown')} | {'Yes' if item['is_usable'] else 'No'} |"
        )

    lines.extend(
        [
            "",
            "#### P1-B Top Candidates (`dastarkhwan`):",
            "",
            "| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Usable |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for rank, item in enumerate(res_b["nearest_10"][:10], 1):
        lines.append(
            f"| {rank} | {escape_table(item['name'])} | `{item['primary_type']}` | {item['distance_km']} km | {'Yes' if item['phone_present'] else 'No'} | {'Yes' if item['open_now'] is True else ('No' if item['open_now'] is False else 'Unknown')} | {'Yes' if item['is_usable'] else 'No'} |"
        )

    lines.extend(
        [
            "",
            "### P2: Gulberg Nearby Search Diagnostic (`searchNearby`, 5000m radius)",
            f"- **Status Code**: {status_code}",
            f"- **Latency**: {lat_nearby}ms",
            f"- **Raw Results Count**: {len(items_nearby)}",
            "- **Text Search Nearest Baseline**: 4.42 km (`Maulvi Juice Corner`)",
        ]
    )

    if items_nearby:
        nearest_d = items_nearby[0]["distance_km"]
        lines.append(f"- **Nearby Search Nearest Distance**: {nearest_d} km")
        lines.extend(
            [
                "",
                "| # | Name | Primary Type | Distance (km) | Phone Present | Open Now | Usable |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for rank, item in enumerate(items_nearby[:10], 1):
            lines.append(
                f"| {rank} | {escape_table(item['name'])} | `{item['primary_type']}` | {item['distance_km']} km | {'Yes' if item['phone_present'] else 'No'} | {'Yes' if item['open_now'] is True else ('No' if item['open_now'] is False else 'Unknown')} | {'Yes' if item['is_usable'] else 'No'} |"
            )
    else:
        lines.append(f"- **Nearby Search Results**: None found within 5,000 m (or error: {err_nearby}).")

    probe_path = REPO_DIR / "plans/module-4/results/probe.md"
    existing_content = probe_path.read_text()
    # Also fix any unescaped '|' in the existing table (fix M2)
    # Particularly "Bismillah Fresh Juice & Dahi bhally | Johar Town Lahore"
    existing_fixed = existing_content.replace(
        "Bismillah Fresh Juice & Dahi bhally | Johar Town Lahore",
        "Bismillah Fresh Juice & Dahi bhally \\| Johar Town Lahore",
    )
    probe_path.write_text(existing_fixed + "\n" + "\n".join(lines) + "\n")
    print(f"\nAppended P1 & P2 results to: {probe_path}")


if __name__ == "__main__":
    asyncio.run(main())
