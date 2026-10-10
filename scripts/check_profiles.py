"""Produce profiles consistency and cost check script (Step 6).

Generates produce profiles twice without saving to measure variation across raw runs,
evaluates Step 4 worked examples, and presents a sense-check table for review.
"""

import argparse
import asyncio
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
    """Compares two raw profile outputs for identical produce across runs."""
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


def to_produce_profile(item: ProfileOut) -> ProduceProfile:
    from datetime import datetime, timezone

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


async def check_profiles_flow(
    produce_names: list[str] = STANDARD_PRODUCE,
    client: Any = None,
    output_md_path: Path | None = None,
) -> dict[str, Any]:
    if client is None:
        client = get_genai_client()

    config = build_profile_config()
    user_prompt = "Produce names: " + json.dumps(produce_names)

    # 1. Raw run 1 (monotonic clock)
    t0 = time.monotonic()
    deadline1 = time.monotonic() + 45.0
    out1, usage1, attempts1, _ = await call_structured(
        client=client,
        contents=[user_prompt],
        config=config,
        schema=ProfilesOut,
        deadline=deadline1,
        label="ProduceProfiles_Run1",
    )
    lat1 = int((time.monotonic() - t0) * 1000)
    cost1 = calculate_cost(usage1)

    # 2. Raw run 2 (monotonic clock)
    t1 = time.monotonic()
    deadline2 = time.monotonic() + 45.0
    out2, usage2, attempts2, _ = await call_structured(
        client=client,
        contents=[user_prompt],
        config=config,
        schema=ProfilesOut,
        deadline=deadline2,
        label="ProduceProfiles_Run2",
    )
    lat2 = int((time.monotonic() - t1) * 1000)
    cost2 = calculate_cost(usage2)

    # 3. Compare runs
    profiles_dict1 = {produce_key(p.input_name): p for p in out1.profiles}
    profiles_dict2 = {produce_key(p.input_name): p for p in out2.profiles}

    comparisons = {}
    differences_count = 0
    total_fields_differing = 0

    for name in produce_names:
        pkey = produce_key(name)
        p1 = profiles_dict1.get(pkey)
        p2 = profiles_dict2.get(pkey)
        if p1 and p2:
            comp = compare_profiles(p1, p2)
            comparisons[pkey] = comp
            if not comp["identical"]:
                differences_count += 1
                total_fields_differing += comp["diff_count"]

    # 4. Convert Run 1 into ProduceProfile objects and test worked examples
    converted_profiles = {k: to_produce_profile(p) for k, p in profiles_dict1.items()}
    worked_results = run_worked_examples(converted_profiles)

    # 5. Format Markdown report
    diff_rate = (differences_count / len(produce_names)) * 100 if produce_names else 0.0

    lines = [
        "# Produce Profiles Accuracy & Consistency Report (Step 6)",
        "",
        "## Summary",
        f"- **Model**: `{get_settings().GEMINI_FLASH_MODEL}` (Vertex AI `eu`)",
        f"- **Produce tested**: {len(produce_names)} items",
        f"- **Run 1 Latency**: {lat1} ms | Tokens: {usage1.input_tokens} in, {usage1.output_tokens} out | Cost: ${cost1:.6f}",
        f"- **Run 2 Latency**: {lat2} ms | Tokens: {usage2.input_tokens} in, {usage2.output_tokens} out | Cost: ${cost2:.6f}",
        f"- **Raw Variation (Run 1 vs Run 2)**: {differences_count}/{len(produce_names)} produce varied ({diff_rate:.1f}%), with {total_fields_differing} total differing fields.",
        "",
        "> [!IMPORTANT]",
        "> **Why We Store Produce Profiles:**",
        "> Without storing profiles, decisions would inherit raw model jitter across queries. Storing Gemini profiles once under `{produce}__v1` eliminates per-batch API calls, brings decision latency down to sub-millisecond code execution, guarantees 100% decision repeatability, and allows instant manager overrides (`__manager`).",
        "",
        "## Generated Profiles (Run 1)",
        "| Produce | Fresh Band | Ripening Band | Overripe Band | Uses (Fresh) | Uses (Ripe) | Uses (Overripe) | Cattle (Over/Spoiled) | Note | Sense check (user) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for name in produce_names:
        pkey = produce_key(name)
        p = profiles_dict1.get(pkey)
        if p:
            f_uses = [u for u in ["juice_shop", "restaurant", "bakery", "charity"] if getattr(p.fresh, u)]
            r_uses = [u for u in ["juice_shop", "restaurant", "bakery", "charity"] if getattr(p.ripening, u)]
            o_uses = [u for u in ["juice_shop", "restaurant", "bakery", "charity"] if getattr(p.overripe, u)]
            cattle = f"{p.overripe_ok_for_cattle}/{p.spoiled_ok_for_cattle}"
            note_esc = p.note.replace("|", "/")
            lines.append(
                f"| {name} | `{p.fresh.sellable_for}` | `{p.ripening.sellable_for}` | `{p.overripe.sellable_for}` | {', '.join(f_uses) or 'none'} | {', '.join(r_uses) or 'none'} | {', '.join(o_uses) or 'none'} | {cattle} | {note_esc} | |"
            )

    lines.extend([
        "",
        "## Variation Analysis Across Uncached Runs",
        "| Produce | Run 1 == Run 2 | Differing Fields |",
        "|---|---|---|",
    ])

    for name in produce_names:
        pkey = produce_key(name)
        comp = comparisons.get(pkey, {"identical": True, "diffs": []})
        status = "✓ Identical" if comp["identical"] else f"✗ Differed ({comp['diff_count']})"
        diff_str = "; ".join(comp["diffs"]) if comp["diffs"] else "None"
        lines.append(f"| {name} | {status} | {diff_str} |")

    lines.extend([
        "",
        "## Step 4 Worked Examples Decisions (Using Generated Profiles)",
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
        "run1_latency_ms": lat1,
        "run1_cost_usd": cost1,
        "run2_latency_ms": lat2,
        "run2_cost_usd": cost2,
        "differences_count": differences_count,
        "total_produce": len(produce_names),
        "markdown": md_content,
    }


def main():
    parser = argparse.ArgumentParser(description="Check produce profiles consistency and cost.")
    parser.add_argument("--output-md", type=str, default="plans/module-3/results/profiles.md")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    out_path = repo_root / args.output_md

    print("Running produce profiles consistency check...")
    results = asyncio.run(
        check_profiles_flow(
            produce_names=STANDARD_PRODUCE,
            output_md_path=out_path,
        )
    )
    print(f"Check complete! Results written to: {out_path}")
    print(f"Run 1 Latency: {results['run1_latency_ms']}ms | Cost: ${results['run1_cost_usd']:.6f}")
    print(f"Run 2 Latency: {results['run2_latency_ms']}ms | Cost: ${results['run2_cost_usd']:.6f}")
    print(f"Raw variation between runs: {results['differences_count']}/{results['total_produce']} produce differed.")


if __name__ == "__main__":
    main()
