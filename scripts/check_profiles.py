"""Produce profiles consistency and cost check script (Step 6 & Step 6B).

Generates produce profiles with raw single calls and with 5-vote consensus runs,
measures variation, evaluates Step 4 worked examples, and presents a sense-check table.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from google.genai import types

from lastcall_api.gemini_call import CallUsage, call_structured, get_genai_client
from lastcall_api.ladder.engine import decide_item
from lastcall_api.ladder.profiles import (
    PROFILE_PROMPT_VERSION,
    ProfileOut,
    ProfilesOut,
    build_profile_config,
    check_profile,
    merge_votes,
    produce_key,
)
from lastcall_shared.config import get_settings
from lastcall_shared.marts.loader import load_mart_rules
from lastcall_shared.models import (
    BoundingBox,
    ItemAssessment,
    ObservedQuantity,
    ProduceProfile,
    QuantityEstimate,
)

STANDARD_PRODUCE = [
    "spinach",
    "coriander",
    "banana",
    "mango",
    "guava",
    "tomato",
    "okra",
    "onion",
    "potato",
    "kinnow",
    "apple",
    "bottle gourd",
]

FLASH_INPUT_PRICE_PER_M = 0.75
FLASH_OUTPUT_PRICE_PER_M = 3.75


def calculate_cost(usage: CallUsage) -> float:
    return (usage.input_tokens / 1_000_000.0) * FLASH_INPUT_PRICE_PER_M + (
        usage.output_tokens / 1_000_000.0
    ) * FLASH_OUTPUT_PRICE_PER_M


def compare_profiles(p1: ProfileOut, p2: ProfileOut) -> dict[str, Any]:
    """Compares two raw or consensus profile outputs for identical produce across runs."""
    diffs = []
    # Band comparison
    for stage in ["fresh", "ripening", "overripe"]:
        b1 = getattr(p1, stage).sellable_for
        b2 = getattr(p2, stage).sellable_for
        if b1 != b2:
            diffs.append(f"{stage}.sellable_for: '{b1}' vs '{b2}'")

        # Uses comparison
        for use_field in ["juice_shop", "restaurant", "bakery", "charity"]:
            u1 = getattr(getattr(p1, stage), use_field)
            u2 = getattr(getattr(p2, stage), use_field)
            if u1 != u2:
                diffs.append(f"{stage}.{use_field}: {u1} vs {u2}")

    # Cattle suitability
    if p1.overripe_ok_for_cattle != p2.overripe_ok_for_cattle:
        diffs.append(f"overripe_ok_for_cattle: {p1.overripe_ok_for_cattle} vs {p2.overripe_ok_for_cattle}")
    if p1.spoiled_ok_for_cattle != p2.spoiled_ok_for_cattle:
        diffs.append(f"spoiled_ok_for_cattle: {p1.spoiled_ok_for_cattle} vs {p2.spoiled_ok_for_cattle}")

    return {
        "identical": len(diffs) == 0,
        "diff_count": len(diffs),
        "diffs": diffs,
    }


def to_produce_profile(item: ProfileOut, votes: int = 1, uncertain_fields: list[str] | None = None) -> ProduceProfile:
    pkey = produce_key(item.input_name)
    prof = ProduceProfile(
        key=f"{pkey}__v{PROFILE_PROMPT_VERSION}",
        name=item.input_name,
        note=item.note,
        fresh=item.fresh,
        ripening=item.ripening,
        overripe=item.overripe,
        spoiled_ok_for_cattle=item.spoiled_ok_for_cattle,
        overripe_ok_for_cattle=item.overripe_ok_for_cattle,
        source="gemini",
        model=get_settings().GEMINI_FLASH_MODEL,
        prompt_version=PROFILE_PROMPT_VERSION,
        created_at=datetime.now(timezone.utc),
        votes=votes,
        uncertain_fields=uncertain_fields or [],
    )
    checked, _ = check_profile(prof)
    return checked


def run_worked_examples(profiles_map: dict[str, ProduceProfile]) -> list[dict[str, Any]]:
    rules = load_mart_rules("demo_mart")

    def _item(name: str, stage: str, stage_level: str, worst_stage: str | None = None, issues: list[str] | None = None) -> ItemAssessment:
        ws = worst_stage if worst_stage is not None else stage
        unit = "dozen" if name in ("banana", "kinnow") else "kg"
        return ItemAssessment(
            item_key=f"ex_{name}",
            name=name,
            grid="center",
            position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
            stage=stage,
            stage_level=stage_level,
            worst_stage=ws,
            score=80.0,
            confidence=0.9,
            confidence_level="high",
            issues=issues or [],
            evidence="Worked example inspection",
            observed=ObservedQuantity(method="count", min=10, max=10),
            quantity=QuantityEstimate(unit=unit, low=2.0, high=2.0),
            needs_staff_check=False,
            staff_check_reasons=[],
        )

    examples = [
        ("Fresh banana in morning (H=14)", "banana", "fresh", "early", None, None, 14.0, 180),
        ("Late-ripening banana at 3h to closing (H=3)", "banana", "ripening", "late", None, None, 3.0, 180),
        ("Late-ripening banana at 14h to closing (H=14)", "banana", "ripening", "late", None, None, 14.0, 180),
        ("Overripe spinach at 8h to closing (H=8)", "spinach", "overripe", "mid", None, None, 8.0, 70),
        ("Fresh early spinach at 13h to closing (H=13)", "spinach", "fresh", "early", None, None, 13.0, 70),
        ("Fresh early spinach at 4h to closing (H=4)", "spinach", "fresh", "early", None, None, 4.0, 70),
        ("Overripe potato at 8h to closing (H=8)", "potato", "overripe", "early", None, None, 8.0, 80),
        ("Spoiled tomato without mould (H=4)", "tomato", "spoiled", "early", None, ["rot"], 4.0, 120),
    ]

    results = []
    for title, name, stage, level, ws, issues, H, price in examples:
        item = _item(name, stage, level, ws, issues)
        pkey = produce_key(name)
        prof = profiles_map.get(pkey) or profiles_map.get(name)
        if not prof:
            continue
        dec = decide_item(item, prof, rules, H=H, price=price)
        results.append({
            "title": title,
            "produce": name,
            "stage": f"{stage} ({level})",
            "H": H,
            "shelf_price": price,
            "step": dec.step,
            "discount_pct": dec.discount_pct,
            "discounted_price": dec.discounted_price,
            "opening_price": dec.opening_price,
            "floor_price": dec.floor_price,
            "buyer_types": dec.buyer_types,
            "reason": dec.reason,
        })
    return results


async def run_consensus_batch(
    produce_names: list[str],
    client: Any,
    deadline: float,
) -> tuple[dict[str, tuple[ProfileOut, list[str], int]], CallUsage, int]:
    """Runs 5 parallel calls and merges answers using merge_votes."""
    t0 = time.monotonic()
    user_prompt = "Produce names: " + json.dumps(produce_names)
    config = build_profile_config()

    coros = [
        call_structured(
            client=client,
            contents=[user_prompt],
            config=config,
            schema=ProfilesOut,
            deadline=deadline,
            max_attempts=1,
            per_attempt_timeout=15.0,
            hedge_after_s=15.0,
            label="ConsensusVote",
        )
        for _ in range(5)
    ]
    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    answers_by_key: dict[str, list[ProfileOut]] = {produce_key(m): [] for m in produce_names}
    total_usage = CallUsage(0, 0, 0)

    for res in raw_results:
        if isinstance(res, Exception):
            continue
        out, usage, _, _ = res
        total_usage = CallUsage(
            input_tokens=total_usage.input_tokens + usage.input_tokens,
            output_tokens=total_usage.output_tokens + usage.output_tokens,
            cached_tokens=total_usage.cached_tokens + usage.cached_tokens,
        )
        for p in out.profiles:
            pkey = produce_key(p.input_name)
            if pkey in answers_by_key:
                answers_by_key[pkey].append(p)

    merged_by_key: dict[str, tuple[ProfileOut, list[str], int]] = {}
    for name in produce_names:
        pkey = produce_key(name)
        answers = answers_by_key.get(pkey, [])
        if len(answers) >= 3:
            merged_item, uncertain = merge_votes(answers)
            merged_by_key[pkey] = (merged_item, uncertain, len(answers))
        elif answers:
            merged_by_key[pkey] = (answers[0], ["insufficient_votes"], len(answers))

    lat_ms = int((time.monotonic() - t0) * 1000)
    return merged_by_key, total_usage, lat_ms


async def check_profiles_flow(
    produce_names: list[str] = STANDARD_PRODUCE,
    client: Any = None,
    output_md_path: Path | None = None,
) -> dict[str, Any]:
    if client is None:
        client = get_genai_client()

    config = build_profile_config()
    user_prompt = "Produce names: " + json.dumps(produce_names)

    # 1. Raw run 1
    t0 = time.monotonic()
    deadline1 = time.monotonic() + 45.0
    out1, usage1, attempts1, _ = await call_structured(
        client=client,
        contents=[user_prompt],
        config=config,
        schema=ProfilesOut,
        deadline=deadline1,
        label="ProduceProfiles_Raw1",
    )
    lat_raw1 = int((time.monotonic() - t0) * 1000)
    cost_raw1 = calculate_cost(usage1)

    # 2. Raw run 2
    t1 = time.monotonic()
    deadline2 = time.monotonic() + 45.0
    out2, usage2, attempts2, _ = await call_structured(
        client=client,
        contents=[user_prompt],
        config=config,
        schema=ProfilesOut,
        deadline=deadline2,
        label="ProduceProfiles_Raw2",
    )
    lat_raw2 = int((time.monotonic() - t1) * 1000)
    cost_raw2 = calculate_cost(usage2)

    # 3. Compare raw runs
    raw_dict1 = {produce_key(p.input_name): p for p in out1.profiles}
    raw_dict2 = {produce_key(p.input_name): p for p in out2.profiles}

    raw_comparisons = {}
    raw_diff_count = 0
    raw_total_fields_differing = 0

    for name in produce_names:
        pkey = produce_key(name)
        p1 = raw_dict1.get(pkey)
        p2 = raw_dict2.get(pkey)
        if p1 and p2:
            comp = compare_profiles(p1, p2)
            raw_comparisons[pkey] = comp
            if not comp["identical"]:
                raw_diff_count += 1
                raw_total_fields_differing += comp["diff_count"]

    # 4. Consensus run 1 (5 parallel votes)
    c_map1, c_usage1, c_lat1 = await run_consensus_batch(produce_names, client, time.monotonic() + 45.0)
    c_cost1 = calculate_cost(c_usage1)

    # 5. Consensus run 2 (5 parallel votes)
    c_map2, c_usage2, c_lat2 = await run_consensus_batch(produce_names, client, time.monotonic() + 45.0)
    c_cost2 = calculate_cost(c_usage2)

    # 6. Compare consensus runs
    consensus_comparisons = {}
    consensus_diff_count = 0
    consensus_total_fields_differing = 0

    for name in produce_names:
        pkey = produce_key(name)
        entry1 = c_map1.get(pkey)
        entry2 = c_map2.get(pkey)
        if entry1 and entry2:
            comp = compare_profiles(entry1[0], entry2[0])
            consensus_comparisons[pkey] = comp
            if not comp["identical"]:
                consensus_diff_count += 1
                consensus_total_fields_differing += comp["diff_count"]

    # 7. Convert Consensus Run 1 profiles and evaluate worked examples
    consensus_profiles = {}
    for pkey, (merged_item, uncertain, v_count) in c_map1.items():
        consensus_profiles[pkey] = to_produce_profile(merged_item, votes=v_count, uncertain_fields=uncertain)
    worked_results = run_worked_examples(consensus_profiles)

    # 8. Format Markdown report (Title: Profile check, N3)
    raw_rate = (raw_diff_count / len(produce_names)) * 100 if produce_names else 0.0
    c_rate = (consensus_diff_count / len(produce_names)) * 100 if produce_names else 0.0

    lines = [
        "# Profile check (Step 6 & 6B)",
        "",
        "## Summary",
        f"- **Model**: `{get_settings().GEMINI_FLASH_MODEL}` (Vertex AI `eu`)",
        f"- **Produce tested**: {len(produce_names)} items",
        f"- **Raw Single-Call Runs**: {raw_diff_count}/{len(produce_names)} produce varied ({raw_rate:.1f}%), with {raw_total_fields_differing} differing fields.",
        f"- **5-Vote Consensus Runs**: {consensus_diff_count}/{len(produce_names)} produce varied ({c_rate:.1f}%), with {consensus_total_fields_differing} differing fields.",
        f"- **Raw Latency & Cost (per call)**: ~{lat_raw1} ms | Cost: ${cost_raw1:.6f}",
        f"- **5-Vote Consensus Latency & Cost**: {c_lat1} ms (5 parallel requests) | Tokens: {c_usage1.input_tokens} in, {c_usage1.output_tokens} out | Cost: ${c_cost1:.6f}",
        "",
        "> [!IMPORTANT]",
        "> **Why We Store Produce Profiles & Use 5-Vote Consensus:**",
        f"> Raw single-call variation ({raw_diff_count}/{len(produce_names)} varied) produces model jitter. A 5-vote consensus stabilizes the profile ({consensus_diff_count}/{len(produce_names)} varied), records uncertain fields, and storing once under `{{produce}}__v1` eliminates per-request API calls while allowing instant manager overrides (`__manager`).",
        "",
        "## Generated Profiles (5-Vote Consensus Run 1)",
        "| Produce | Fresh Band | Ripening Band | Overripe Band | Uses (Fresh) | Uses (Ripe) | Uses (Overripe) | Cattle (Over/Spoiled) | Note | Votes | Uncertain Fields | Sense check (user) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for name in produce_names:
        pkey = produce_key(name)
        entry = c_map1.get(pkey)
        if entry:
            p, uncertain, v_count = entry
            f_uses = [u for u in ["juice_shop", "restaurant", "bakery", "charity"] if getattr(p.fresh, u)]
            r_uses = [u for u in ["juice_shop", "restaurant", "bakery", "charity"] if getattr(p.ripening, u)]
            o_uses = [u for u in ["juice_shop", "restaurant", "bakery", "charity"] if getattr(p.overripe, u)]
            cattle = f"{p.overripe_ok_for_cattle}/{p.spoiled_ok_for_cattle}"
            note_esc = p.note.replace("|", "/")
            uncert_str = ", ".join(uncertain) if uncertain else "none"
            lines.append(
                f"| {name} | `{p.fresh.sellable_for}` | `{p.ripening.sellable_for}` | `{p.overripe.sellable_for}` | {', '.join(f_uses) or 'none'} | {', '.join(r_uses) or 'none'} | {', '.join(o_uses) or 'none'} | {cattle} | {note_esc} | {v_count} | {uncert_str} | |"
            )

    lines.extend([
        "",
        "## Variation Comparison: Raw (Single-Call) vs 5-Vote Consensus",
        "| Produce | Raw (Single-Call) Variation | 5-Vote Consensus Variation |",
        "|---|---|---|",
    ])

    for name in produce_names:
        pkey = produce_key(name)
        raw_comp = raw_comparisons.get(pkey, {"identical": True, "diffs": []})
        c_comp = consensus_comparisons.get(pkey, {"identical": True, "diffs": []})

        raw_status = "✓ Identical" if raw_comp["identical"] else f"✗ Differed ({raw_comp['diff_count']}): " + "; ".join(raw_comp["diffs"])
        c_status = "✓ Identical" if c_comp["identical"] else f"✗ Differed ({c_comp['diff_count']}): " + "; ".join(c_comp["diffs"])
        lines.append(f"| {name} | {raw_status} | {c_status} |")

    lines.extend([
        "",
        "## Step 4 Worked Examples Decisions (Using 5-Vote Consensus Profiles)",
        "| Case | Produce | Stage & Level | H to Closing | Shelf Price | Engine Step | Pricing / Discount | Buyer Types | Reason |",
        "|---|---|---|---|---|---|---|---|---|",
    ])

    for r in worked_results:
        pricing_str = "-"
        if r["step"] == "discount":
            pricing_str = f"-{r['discount_pct']}% (Rs {r['discounted_price']})"
        elif r["step"] in ("bulk_sale", "animal_feed"):
            pricing_str = f"Open Rs {r['opening_price']} / Floor Rs {r['floor_price']}"

        buyers_str = ", ".join(r["buyer_types"]) if r["buyer_types"] else "-"
        reason_esc = r["reason"].replace("|", "/")
        lines.append(
            f"| {r['title']} | {r['produce']} | {r['stage']} | {r['H']}h | Rs {r['shelf_price']} | `{r['step']}` | {pricing_str} | {buyers_str} | {reason_esc} |"
        )

    md_content = "\n".join(lines) + "\n"

    if output_md_path:
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(md_content, encoding="utf-8")

    return {
        "raw_diff_count": raw_diff_count,
        "consensus_diff_count": consensus_diff_count,
        "total_produce": len(produce_names),
        "raw_cost_usd": cost_raw1 + cost_raw2,
        "consensus_cost_usd": c_cost1 + c_cost2,
        "markdown": md_content,
    }


def main():
    parser = argparse.ArgumentParser(description="Check produce profiles consistency and cost.")
    parser.add_argument("--output-md", type=str, default="plans/module-3/results/profiles.md")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    out_path = repo_root / args.output_md

    print("Running produce profiles consistency check (Raw vs 5-Vote Consensus)...")
    results = asyncio.run(
        check_profiles_flow(
            produce_names=STANDARD_PRODUCE,
            output_md_path=out_path,
        )
    )
    print(f"Check complete! Results written to: {out_path}")
    print(f"Raw variation between runs: {results['raw_diff_count']}/{results['total_produce']} produce differed.")
    print(f"5-Vote consensus variation: {results['consensus_diff_count']}/{results['total_produce']} produce differed.")


if __name__ == "__main__":
    main()
