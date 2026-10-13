"""Live check for Scout pipeline across 3 produce items and branches (Step 8).

Runs 5 live runs (<= 7 Places requests total):
1. Overripe banana (bulk sale: juice_shop, bakery) @ Johar Town (default branch) -> 2 Places calls
2. Overripe spinach (donate: charity) @ Johar Town (default branch) -> 1 Places call
3. Cattle-safe produce (animal feed: dairy_farm) @ Johar Town (default branch) -> 1 Places call
4. Contrast 1: Overripe banana (bulk sale: juice_shop, bakery) @ Gulberg (commercial) -> 2 Places calls
5. Contrast 2: Cattle-safe produce (animal feed: dairy_farm) @ Bahria Town (suburban) -> 1 Places call

Writes results to plans/module-4/results/scout-check.md.
ZERO phone numbers written!
"""

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lastcall_api.gemini_call import get_genai_client
from lastcall_api.ladder.engine import decide_item, find_price
from lastcall_api.scout.scout import ScoutTarget, run_scout
from lastcall_shared.models import (
    BoundingBox,
    ItemAssessment,
    MartRules,
    ObservedQuantity,
    QuantityEstimate,
    ScoutResult,
)
from lastcall_shared.store import InMemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_FILE = REPO_ROOT / "plans/module-4/results/scout-check.md"
RULES_FILE = REPO_ROOT / "shared/lastcall_shared/marts/demo_mart.json"


def sanitize_table_text(text: str) -> str:
    """Escapes pipes and replaces newlines to keep markdown tables valid (M2)."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


async def main() -> None:
    rules = MartRules.model_validate_json(RULES_FILE.read_text())
    branch_map = {b.branch_id: b for b in rules.branches}
    johar_town = branch_map["johar_town"]
    gulberg = branch_map["gulberg"]
    bahria_town = branch_map["bahria_town"]

    genai_client = get_genai_client()
    now = datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)

    # 1. Target 1: Engine decision for banana
    from lastcall_shared.firestore_store import FirestoreStore

    fs = FirestoreStore()
    profiles = await fs.get_profiles(["banana__v1"])
    banana_prof = profiles.get("banana__v1")
    if not banana_prof:
        raise RuntimeError("banana__v1 profile not found in store!")

    banana_item = ItemAssessment(
        item_key="banana_grp1",
        name="banana",
        grid="center",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        stage="overripe",
        stage_level="mid",
        worst_stage="overripe",
        score=75.0,
        confidence=0.9,
        confidence_level="high",
        issues=[],
        observed=ObservedQuantity(method="count", min=12, max=12),
        quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
    )
    banana_price = find_price(rules, "banana", "dozen") or 100
    banana_dec = decide_item(banana_item, banana_prof, rules, H=6.0, price=banana_price)
    target_banana = ScoutTarget.from_decision(banana_dec, "insp_live_check_001")

    # 2. Target 2: Hand-built donate target (Module 6 escalation path)
    target_spinach = ScoutTarget(
        inspection_id="insp_live_check_002",
        item_key="spinach_grp1",
        item="Spinach",
        condition="Overripe, wilting leaves, edible and safe for cooking today",
        step="donate",
        buyer_types=("charity",),
    )

    # 3. Target 3: Hand-built animal feed target
    target_feed = ScoutTarget(
        inspection_id="insp_live_check_003",
        item_key="carrot_grp1",
        item="Carrot",
        condition="Spoiled, broken and soft, safe for cattle feed",
        step="animal_feed",
        buyer_types=("dairy_farm",),
    )

    runs = [
        ("Run 1: Overripe Banana (Bulk Sale) @ Johar Town (Default)", target_banana, johar_town),
        ("Run 2: Overripe Spinach (Donate) @ Johar Town (Default)", target_spinach, johar_town),
        ("Run 3: Cattle-Safe Produce (Animal Feed) @ Johar Town (Default)", target_feed, johar_town),
        ("Run 4 (Contrast): Overripe Banana (Bulk Sale) @ Gulberg (Commercial)", target_banana, gulberg),
        ("Run 5 (Contrast): Cattle-Safe Produce (Animal Feed) @ Bahria Town (Suburban)", target_feed, bahria_town),
    ]

    if "--run-1-only" in sys.argv:
        runs = runs[:1]

    results: list[tuple[str, ScoutResult, float]] = []

    total_places_calls = 0
    print("=" * 60)
    print(f"Starting Scout live verification ({len(runs)} runs)...")
    print("=" * 60)

    for run_name, target, branch in runs:
        print(f"\nExecuting {run_name}...")
        t0 = time.monotonic()
        # Clean ephemeral in-memory store for each run
        run_store = InMemoryStore(clock=lambda: now)
        res = await run_scout(
            target,
            rules=rules,
            branch=branch,
            store=run_store,
            genai_client=genai_client,
            now=now,
            reserve_places=None,
        )
        elapsed_s = time.monotonic() - t0
        total_places_calls += res.meta.places_requests
        results.append((run_name, res, elapsed_s))
        print(
            f"  -> Done in {elapsed_s:.2f}s | Places requests: {res.meta.places_requests} "
            f"| Raw results: {res.meta.places_results} | Kept: {len(res.buyers)} | Fit fallback: {res.meta.fit_fallback}"
        )

    if len(runs) == 1:
        run_name, r, elapsed_s = results[0]
        print(f"\n{'=' * 60}")
        print("RUN 1 DETAILED RESULTS:")
        print(f"  Latency: {r.meta.latency_ms} ms ({elapsed_s:.2f} s)")
        print(f"  Tokens: {r.meta.input_tokens} in / {r.meta.output_tokens} out")
        print(f"  Fit Fallback: {r.meta.fit_fallback}")
        print(f"  Places requests: {r.meta.places_requests}")
        print(f"  Raw places found: {r.meta.places_results}")
        print(f"  Buyers returned: {len(r.buyers)}")
        print(f"  Skipped counts: {r.skipped}")
        print("  Top 5 Buyers:")
        for b in r.buyers[:5]:
            open_str = "open now" if b.open_now is True else ("closed now" if b.open_now is False else "unknown")
            print(
                f"    #{b.rank} {b.name} ({b.buyer_type}, {b.distance_km:.1f} km, {open_str}) [{b.fit}]: {b.fit_why} | {b.reason}"
            )
        print("  Screened out (unlikely):")
        for so in r.screened_out:
            print(f"    - {so.name} ({so.buyer_type}, {so.distance_km:.1f} km): {so.why}")
        print(f"{'=' * 60}\n")

        # Update Run 1 in scout-check.md if file exists
        if RESULTS_FILE.exists():
            content = RESULTS_FILE.read_text(encoding="utf-8")
            # Replace Run 1 summary row
            import re

            row_pattern = r"\| Run 1: Overripe Banana \(Bulk Sale\) @ Johar Town \(Default\) \| [^|]+ \| [^|]+ \| \d+ \| \d+ \| \d+ \| \d+ ms \| \d+ / \d+ \| (?:True|False) \|"
            new_row = (
                f"| Run 1: Overripe Banana (Bulk Sale) @ Johar Town (Default) | {r.step} ({', '.join(r.buyer_types)}) | "
                f"{r.branch_name} | {r.meta.places_requests} | {r.meta.places_results} | {len(r.buyers)} | "
                f"{r.meta.latency_ms} ms | {r.meta.input_tokens} / {r.meta.output_tokens} | {r.meta.fit_fallback} |"
            )
            content = re.sub(row_pattern, new_row, content)

            # Rebuild Run 1 section
            sec_lines = [
                "## Run 1: Overripe Banana (Bulk Sale) @ Johar Town (Default)",
                "",
                f"- **Branch:** `{r.branch_id}` ({r.branch_name})",
                f"- **Step:** `{r.step}`",
                f"- **Buyer Types Searched:** `{', '.join(r.buyer_types)}`",
                f"- **Places Requests:** {r.meta.places_requests} | **Raw Places Returned:** {r.meta.places_results}",
                f"- **Latency:** {r.meta.latency_ms} ms | **Tokens:** {r.meta.input_tokens} in / {r.meta.output_tokens} out",
                f"- **Skipped Counts:** `{r.skipped}`",
                "",
                "### Top Ranked Buyers",
                "",
                "| Rank | Business Name | Type | Distance | Open Now | Fit | Why | Reason | Sense check (user) |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            for b in r.buyers[:5]:
                open_str = "open now" if b.open_now is True else ("closed now" if b.open_now is False else "unknown")
                sec_lines.append(
                    f"| {b.rank} | {sanitize_table_text(b.name)} | {b.buyer_type} | {b.distance_km:.1f} km | "
                    f"{open_str} | **{b.fit}** | {sanitize_table_text(b.fit_why)} | {sanitize_table_text(b.reason)} | |"
                )
            sec_lines.extend(["", "### Screened Out / Unlikely Fits", ""])
            if not r.screened_out:
                sec_lines.append("*No candidates screened out as unlikely fit.*")
            else:
                sec_lines.extend(
                    [
                        "| Business Name | Type | Distance | Fit Why | Sense check (user) |",
                        "|---|---|---|---|---|",
                    ]
                )
                for so in r.screened_out:
                    sec_lines.append(
                        f"| {sanitize_table_text(so.name)} | {so.buyer_type} | {so.distance_km:.1f} km | "
                        f"{sanitize_table_text(so.why)} | |"
                    )
            sec_lines.extend(["", "---"])
            new_sec = "\n".join(sec_lines)

            sec_pattern = r"## Run 1: Overripe Banana \(Bulk Sale\) @ Johar Town \(Default\).*?---"
            content = re.sub(sec_pattern, new_sec, content, flags=re.DOTALL)
            RESULTS_FILE.write_text(content, encoding="utf-8")
            print(f"Updated Run 1 in {RESULTS_FILE}")
        return

    print("\nAll 5 runs completed!")
    print(f"Total Places API requests used: {total_places_calls} (budget: <= 7)")

    # Build scout-check.md
    md: list[str] = [
        "# Module 4 Scout Verification Check (`scout-check.md`)",
        "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Total Live Places API Requests:** {total_places_calls} / 7 budget",
        "**Strict Privacy Assurance:** Zero phone numbers are stored or printed in this document.",
        "",
        "---",
        "",
        "## Summary of Runs",
        "",
        "| Run | Target / Step | Branch | Places Reqs | Raw Found | Final Buyers | Latency | Tokens (In/Out) | Fit Fallback |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for run_name, r, elapsed_s in results:
        md.append(
            f"| {sanitize_table_text(run_name)} | {r.step} ({', '.join(r.buyer_types)}) | {r.branch_name} | "
            f"{r.meta.places_requests} | {r.meta.places_results} | {len(r.buyers)} | {r.meta.latency_ms} ms | "
            f"{r.meta.input_tokens} / {r.meta.output_tokens} | {r.meta.fit_fallback} |"
        )

    md.extend(["", "---", ""])

    for run_name, r, elapsed_s in results:
        md.extend(
            [
                f"## {run_name}",
                "",
                f"- **Branch:** `{r.branch_id}` ({r.branch_name})",
                f"- **Step:** `{r.step}`",
                f"- **Buyer Types Searched:** `{', '.join(r.buyer_types)}`",
                f"- **Places Requests:** {r.meta.places_requests} | **Raw Places Returned:** {r.meta.places_results}",
                f"- **Latency:** {r.meta.latency_ms} ms | **Tokens:** {r.meta.input_tokens} in / {r.meta.output_tokens} out",
                f"- **Skipped Counts:** `{r.skipped}`",
                "",
                "### Top Ranked Buyers",
                "",
                "| Rank | Business Name | Type | Distance | Open Now | Fit | Why | Reason | Sense check (user) |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
        )

        if not r.buyers:
            md.append("| - | *No buyers found* | - | - | - | - | - | - | |")
        else:
            for b in r.buyers[:5]:
                open_str = "open now" if b.open_now is True else ("closed now" if b.open_now is False else "unknown")
                md.append(
                    f"| {b.rank} | {sanitize_table_text(b.name)} | {b.buyer_type} | {b.distance_km:.1f} km | "
                    f"{open_str} | **{b.fit}** | {sanitize_table_text(b.fit_why)} | {sanitize_table_text(b.reason)} | |"
                )

        md.extend(["", "### Screened Out / Unlikely Fits", ""])
        if not r.screened_out:
            md.append("*No candidates screened out as unlikely fit.*")
        else:
            md.extend(
                [
                    "| Business Name | Type | Distance | Fit Why | Sense check (user) |",
                    "|---|---|---|---|---|",
                ]
            )
            for so in r.screened_out:
                md.append(
                    f"| {sanitize_table_text(so.name)} | {so.buyer_type} | {so.distance_km:.1f} km | "
                    f"{sanitize_table_text(so.why)} | |"
                )

        md.extend(["", "---", ""])

    # Branch Comparison
    # Compare Run 1 (Banana @ Johar Town) vs Run 4 (Banana @ Gulberg)
    r_banana_johar = results[0][1]
    r_banana_gulberg = results[3][1]

    # Calculate place ID overlap (M3)
    pids_johar = {b.place_id for b in r_banana_johar.buyers}
    pids_gulberg = {b.place_id for b in r_banana_gulberg.buyers}
    overlap_count = len(pids_johar & pids_gulberg)

    md.extend(
        [
            "## Branch Contrast Analysis",
            "",
            "### Bulk Sale Contrast: Johar Town (Suburban Residential) vs Gulberg (Dense Commercial)",
            "",
            f"- **Place ID Overlap (M3):** {overlap_count} overlapping places out of "
            f"{len(pids_johar)} (Johar Town) and {len(pids_gulberg)} (Gulberg).",
            f"- **Johar Town Average Top-5 Distance:** "
            f"{(sum(b.distance_km for b in r_banana_johar.buyers[:5]) / max(1, len(r_banana_johar.buyers[:5]))):.2f} km",
            f"- **Gulberg Average Top-5 Distance:** "
            f"{(sum(b.distance_km for b in r_banana_gulberg.buyers[:5]) / max(1, len(r_banana_gulberg.buyers[:5]))):.2f} km",
            "",
            "| Aspect | Johar Town (`johar_town`) | Gulberg (`gulberg`) |",
            "|---|---|---|",
            f"| Raw Places Found | {r_banana_johar.meta.places_results} | {r_banana_gulberg.meta.places_results} |",
            f"| Qualified Buyers | {len(r_banana_johar.buyers)} | {len(r_banana_gulberg.buyers)} |",
            f"| Top 1 Buyer | {sanitize_table_text(r_banana_johar.buyers[0].name if r_banana_johar.buyers else 'None')} ({r_banana_johar.buyers[0].distance_km:.1f} km) | {sanitize_table_text(r_banana_gulberg.buyers[0].name if r_banana_gulberg.buyers else 'None')} ({r_banana_gulberg.buyers[0].distance_km:.1f} km) |",
            f"| Top 2 Buyer | {sanitize_table_text(r_banana_johar.buyers[1].name if len(r_banana_johar.buyers) > 1 else 'None')} ({r_banana_johar.buyers[1].distance_km:.1f} km) | {sanitize_table_text(r_banana_gulberg.buyers[1].name if len(r_banana_gulberg.buyers) > 1 else 'None')} ({r_banana_gulberg.buyers[1].distance_km:.1f} km) |",
            f"| Skipped Breakdown | `{r_banana_johar.skipped}` | `{r_banana_gulberg.skipped}` |",
            "",
            "### Animal Feed Contrast: Johar Town vs Bahria Town (Peri-Urban / Cattle Area)",
            "",
        ]
    )

    r_feed_johar = results[2][1]
    r_feed_bahria = results[4][1]
    pids_feed_johar = {b.place_id for b in r_feed_johar.buyers}
    pids_feed_bahria = {b.place_id for b in r_feed_bahria.buyers}
    feed_overlap = len(pids_feed_johar & pids_feed_bahria)

    md.extend(
        [
            f"- **Place ID Overlap (M3):** {feed_overlap} overlapping places.",
            f"- **Johar Town Qualified Dairy Farms:** {len(r_feed_johar.buyers)}",
            f"- **Bahria Town Qualified Dairy Farms:** {len(r_feed_bahria.buyers)}",
            "",
            "| Aspect | Johar Town (`johar_town`) | Bahria Town (`bahria_town`) |",
            "|---|---|---|",
            f"| Raw Results | {r_feed_johar.meta.places_results} | {r_feed_bahria.meta.places_results} |",
            f"| Qualified Buyers | {len(r_feed_johar.buyers)} | {len(r_feed_bahria.buyers)} |",
            f"| Top-ranked buyer | {sanitize_table_text(r_feed_johar.buyers[0].name if r_feed_johar.buyers else 'None')} ({r_feed_johar.buyers[0].distance_km:.1f} km) | {sanitize_table_text(r_feed_bahria.buyers[0].name if r_feed_bahria.buyers else 'None')} ({r_feed_bahria.buyers[0].distance_km:.1f} km) |",
            f"| Skipped Breakdown | `{r_feed_johar.skipped}` | `{r_feed_bahria.skipped}` |",
            "",
        ]
    )

    RESULTS_FILE.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote full report to {RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
