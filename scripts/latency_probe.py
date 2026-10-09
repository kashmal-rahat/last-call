#!/usr/bin/env python3
"""Latency probe script for Gemini 3.8 Flash (Step 1 diagnosis).

Sends smoke3.png 12 times sequentially, single pass, thinking low, no zoom,
calling _call directly with a 60s timeout and no retries.
Computes min, p50, p90, max and writes plans/module-1/results/latency.md.
"""

import asyncio
from datetime import datetime, timezone
import math
from pathlib import Path
import sys
import time

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "shared"))
sys.path.insert(0, str(REPO_DIR / "services/api"))

from lastcall_api.inspector.images import prepare_image
from lastcall_api.inspector.inspector import (
    _call,
    build_config,
    get_genai_client,
)
from lastcall_api.inspector.prompt import user_text
from lastcall_shared.config import get_settings


def percentile(data: list[float], p: float) -> float:
    """Calculates the p-th percentile with linear interpolation."""
    if not data:
        return 0.0
    sorted_d = sorted(data)
    k = (len(sorted_d) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_d[int(k)]
    return sorted_d[f] * (c - k) + sorted_d[c] * (k - f)


async def run_latency_probe(photo_path: Path, iterations: int = 12) -> dict:
    raw_bytes = photo_path.read_bytes()
    image_jpeg = prepare_image(raw_bytes).jpeg
    config = build_config("low")
    prompt_text = user_text()
    client = get_genai_client()

    records = []
    latencies = []

    print(f"Running latency probe on {photo_path.name} ({iterations} sequential calls)...")
    print("Settings: thinking=low, single pass, timeout=60s, max_attempts=1 (no retries)\n")

    for i in range(1, iterations + 1):
        t0 = time.monotonic()
        deadline = t0 + 60.0
        error_msg = None
        error_type = None
        usage = None

        try:
            output, usage, attempts, was_hedged = await _call(
                client=client,
                image_jpeg=image_jpeg,
                prompt_text=prompt_text,
                config=config,
                deadline=deadline,
                max_attempts=1,
                per_attempt_timeout=60.0,
            )
            lat = time.monotonic() - t0
            latencies.append(lat)
            records.append({
                "call": i,
                "latency_s": lat,
                "status": "ok",
                "items_count": len(output.items),
                "in_tokens": usage.input_tokens,
                "out_tokens": usage.output_tokens,
                "thought_tokens": usage.thought_tokens,
                "cand_tokens": usage.candidate_tokens,
                "error": None,
            })
            print(f"  [{i:02d}/{iterations}] ok | {lat:.2f}s | {len(output.items)} items | tokens: in={usage.input_tokens}, out={usage.output_tokens} (thoughts={usage.thought_tokens})")
        except Exception as exc:
            lat = time.monotonic() - t0
            orig = getattr(exc, "original_exc", None)
            orig_name = type(orig).__name__ if orig is not None else type(exc).__name__
            error_msg = str(exc)
            error_type = orig_name
            records.append({
                "call": i,
                "latency_s": lat,
                "status": "error",
                "items_count": 0,
                "in_tokens": 0,
                "out_tokens": 0,
                "thought_tokens": 0,
                "cand_tokens": 0,
                "error": f"{error_msg} ({error_type})",
            })
            print(f"  [{i:02d}/{iterations}] ERROR | {lat:.2f}s | {error_msg} ({error_type})")

    p_min = min(latencies) if latencies else 0.0
    p_50 = percentile(latencies, 50.0)
    p_90 = percentile(latencies, 90.0)
    p_max = max(latencies) if latencies else 0.0

    return {
        "photo": photo_path.name,
        "iterations": iterations,
        "records": records,
        "latencies": latencies,
        "min": p_min,
        "p50": p_50,
        "p90": p_90,
        "max": p_max,
        "errors_count": sum(1 for r in records if r["status"] == "error"),
    }


def write_latency_report(result: dict, output_path: Path) -> None:
    settings = get_settings()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Module 1: Latency Diagnosis Probe",
        f"Tested on: {now_utc}",
        f"Photo: `{result['photo']}`",
        f"Model: `{settings.GEMINI_FLASH_MODEL}` on Vertex AI (`{settings.GOOGLE_CLOUD_LOCATION}`)",
        "Configuration: `thinking_level=low`, single pass, timeout=60s, retries=0",
        "",
        "## Summary Statistics",
        "",
        "| Metric | Value (s) |",
        "|---|---|",
        f"| **Calls** | {result['iterations']} |",
        f"| **Errors** | {result['errors_count']} |",
        f"| **Min Latency** | {result['min']:.2f}s |",
        f"| **p50 Latency (median)** | {result['p50']:.2f}s |",
        f"| **p90 Latency** | {result['p90']:.2f}s |",
        f"| **Max Latency** | {result['max']:.2f}s |",
        "",
        "## Per-Call Latency Log",
        "",
        "| # | Status | Latency (s) | Items | In Tok | Out (Thoughts / Cand) | Error |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in result["records"]:
        out_tok_str = f"{r['out_tokens']} ({r['thought_tokens']} / {r['cand_tokens']})" if r["status"] == "ok" else "-"
        err_str = r["error"] or "-"
        lines.append(
            f"| {r['call']} | {r['status']} | {r['latency_s']:.2f} | {r['items_count']} | {r['in_tokens']} | {out_tok_str} | {err_str} |"
        )

    lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote latency probe results to {output_path}")


def main() -> None:
    photo_path = REPO_DIR / "data/shelf_photos/smoke3.png"
    if not photo_path.exists():
        print(f"Error: {photo_path} does not exist")
        sys.exit(1)

    result = asyncio.run(run_latency_probe(photo_path, iterations=12))
    out_file = REPO_DIR / "plans/module-1/results/latency.md"
    write_latency_report(result, out_file)


if __name__ == "__main__":
    main()
