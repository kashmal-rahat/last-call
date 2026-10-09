#!/usr/bin/env python3
"""Smoke test script for Module 1 Freshness Inspector (Step 5).

Runs 6 smoke photos through inspect_photo, tests single pass and zoom pass,
saves bounding box overlays to data/probe/inspector_boxes_<n>.jpg,
and close-up crops to data/probe/inspector_crop_<n>_<i>.jpg.
Writes smoke verification results to plans/module-1/results/smoke.md.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import io
from pathlib import Path
import sys

from PIL import Image, ImageDraw

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "shared"))
sys.path.insert(0, str(REPO_DIR / "services/api"))

from lastcall_api.inspector.images import crop_group, prepare_image
from lastcall_api.inspector.inspector import THINKING_LEVEL, estimate_cost, inspect_photo
from lastcall_shared.models import FreshnessResult, ItemAssessment


def draw_bounding_boxes(
    raw_image: bytes,
    items: list[ItemAssessment],
    output_path: Path,
) -> None:
    """Draws bounding boxes and labels on an image."""
    img = Image.open(io.BytesIO(raw_image)).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    for item in items:
        ymin = int(round(item.position.ymin * h))
        xmin = int(round(item.position.xmin * w))
        ymax = int(round(item.position.ymax * h))
        xmax = int(round(item.position.xmax * w))

        # Color based on stage
        color = "#22c55e"  # green: fresh
        if item.stage == "ripening":
            color = "#eab308"  # yellow
        elif item.stage == "overripe":
            color = "#f97316"  # orange
        elif item.stage in ("spoiled", "unsafe"):
            color = "#ef4444"  # red

        draw.rectangle([xmin, ymin, xmax, ymax], outline=color, width=3)

        z_tag = " [Z]" if item.zoomed else ""
        label = f"{item.name} · {item.stage}/{item.worst_stage}{z_tag}"

        # Draw text background
        draw.text((xmin + 4, max(0, ymin - 18)), label, fill=color)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="JPEG", quality=90)


async def run_smoke(photo_paths: list[Path], zoom: bool = False, thinking: str = "medium") -> list[dict]:
    results = []
    probe_dir = REPO_DIR / "data/probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    for idx, path in enumerate(photo_paths, start=1):
        print(f"\n[{idx}/{len(photo_paths)}] Inspecting {path.name} (zoom={zoom}, thinking={thinking})...")
        raw = path.read_bytes()
        now = datetime.now(timezone.utc)

        t_start = datetime.now()
        res = None
        try:
            res = await inspect_photo(
                raw,
                mart_id="smoke_mart",
                shelf_id=f"smoke_shelf_{idx}",
                now=now,
                zoom=zoom,
                thinking_level=thinking,
            )
        except Exception as exc:
            orig = getattr(exc, "original_exc", None)
            orig_name = type(orig).__name__ if orig is not None else "None"
            print(f"  ❌ Failed {path.name}: {exc} (orig_exc={orig_name}: {orig})")
            error_reason = str(exc)
            orig_error_type = orig_name
            res = None

        dur = (datetime.now() - t_start).total_seconds()

        box_path = probe_dir / f"inspector_boxes_{idx}.jpg"
        if res is None:
            record = {
                "index": idx,
                "filename": path.name,
                "status": "error",
                "error_reason": error_reason,
                "orig_error_type": orig_error_type,
                "items_count": 0,
                "items": [],
                "zoomed_groups": 0,
                "zoom_failures": 0,
                "crops": [],
                "crop_images": [],
                "box_image": str(box_path.relative_to(REPO_DIR)) if box_path.exists() else "",
                "latency_ms": int(dur * 1000),
                "calls": 1,
                "input_tokens": 0,
                "output_tokens": 0,
                "thought_tokens": 0,
                "candidate_tokens": 0,
                "cached_tokens": 0,
                "cost_usd": 0.0,
            }
            results.append(record)
            continue

        meta = res.inspector
        in_tok = meta.input_tokens if meta else 0
        out_tok = meta.output_tokens if meta else 0
        thought_tok = meta.thoughts_tokens if meta else 0
        cand_tok = meta.candidates_tokens if meta else 0
        cached_tok = meta.cached_tokens if meta else 0
        calls = meta.calls if meta else 1
        lat_ms = meta.latency_ms if meta else int(dur * 1000)

        cost = estimate_cost(meta) if meta else 0.0

        # Draw box overlays
        draw_bounding_boxes(raw, res.items, box_path)

        # Save crops if zoomed
        crops_saved = []
        if zoom and res.items:
            prep = prepare_image(raw)
            for item_i, item in enumerate(res.items):
                if item.zoomed:
                    # Convert BoundingBox to 0-1000 int
                    box_2d = [
                        int(round(item.position.ymin * 1000)),
                        int(round(item.position.xmin * 1000)),
                        int(round(item.position.ymax * 1000)),
                        int(round(item.position.xmax * 1000)),
                    ]
                    crop_data = crop_group(prep.full, box_2d)
                    crop_path = probe_dir / f"inspector_crop_{idx}_{item_i}.jpg"
                    crop_path.write_bytes(crop_data)
                    crops_saved.append(str(crop_path.relative_to(REPO_DIR)))

        record = {
            "index": idx,
            "filename": path.name,
            "status": res.photo_status,
            "items_count": len(res.items),
            "items": [
                {
                    "name": item.name,
                    "stage": item.stage,
                    "stage_level": item.stage_level,
                    "worst_stage": item.worst_stage,
                    "score": item.score,
                    "confidence": item.confidence,
                    "confidence_level": item.confidence_level,
                    "observed": f"{item.observed.min}-{item.observed.max} ({item.observed.method})",
                    "quantity": f"{item.quantity.low}-{item.quantity.high} {item.quantity.unit}",
                    "needs_staff_check": item.needs_staff_check,
                    "check_reason": item.check_reason,
                    "zoomed": item.zoomed,
                }
                for item in res.items
            ],
            "latency_ms": lat_ms,
            "calls": calls,
            "zoomed_groups": meta.zoomed_groups if meta else 0,
            "zoom_failures": meta.zoom_failures if meta else 0,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "thought_tokens": thought_tok,
            "candidate_tokens": cand_tok,
            "cached_tokens": cached_tok,
            "cost_usd": cost,
            "box_image": str(box_path.relative_to(REPO_DIR)),
            "crop_images": crops_saved,
        }
        results.append(record)

        print(f"  ✓ {res.photo_status}: {len(res.items)} groups | {lat_ms}ms | {calls} call(s) | {in_tok} in / {out_tok} out ({thought_tok} thoughts / {cand_tok} ans) | ${cost:.5f}")
        for it in res.items:
            chk = f" [CHECK: {it.check_reason}]" if it.needs_staff_check else ""
            z_str = " (zoomed)" if it.zoomed else ""
            print(f"     - {it.name}: {it.stage}.{it.stage_level} (worst: {it.worst_stage}), score={it.score}{z_str}{chk}")

    return results


def write_smoke_markdown(results: list[dict], zoom: bool, thinking: str = "medium"):
    results_dir = REPO_DIR / "plans/module-1/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = results_dir / "smoke.md"

    mode_name = "Zoom Pass" if zoom else "Single Pass"
    section_title = f"{mode_name} (thinking={thinking})"
    md = []

    existing_content = ""
    if report_path.exists():
        existing_content = report_path.read_text(encoding="utf-8")

    if not existing_content:
        md.append("# Module 1: Freshness Inspector Smoke Verification\n")
        md.append(f"Tested on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        md.append("Model: `gemini-3.8-flash` on Vertex AI (`eu`), `media_resolution=HIGH`\n\n")

    md.append(f"## {section_title}\n\n")
    md.append("| # | Photo | Status | Groups | Zoomed | Latency (s) | Calls | Input Tok | Out (Thoughts / Ans) | Cached Tok | Cost ($) |\n")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|\n")

    for r in results:
        lat_s = f"{r['latency_ms'] / 1000.0:.2f}"
        out_split = f"{r['output_tokens']} ({r.get('thought_tokens', 0)} / {r.get('candidate_tokens', 0)})"
        status_str = r['status']
        if r['status'] == 'error' and r.get('orig_error_type'):
            status_str = f"error ({r['orig_error_type']})"
        md.append(
            f"| {r['index']} | `{r['filename']}` | {status_str} | {r['items_count']} | {r['zoomed_groups']} | {lat_s} | {r['calls']} | {r['input_tokens']} | {out_split} | {r['cached_tokens']} | ${r['cost_usd']:.5f} |\n"
        )

    md.append("\n### Item Comparisons per Photo\n\n")
    for r in results:
        md.append(f"#### Photo {r['index']}: `{r['filename']}`\n")
        md.append(f"- **Overlay Box Image**: `[{r['box_image']}](file://{REPO_DIR}/{r['box_image']})`\n")
        if r['crop_images']:
            md.append("- **Close-up Crops**:\n")
            for c in r['crop_images']:
                md.append(f"  - `[{c}](file://{REPO_DIR}/{c})`\n")
        md.append("- **Groups Detected**:\n")
        if not r['items']:
            if r['status'] == 'error':
                md.append(f"  - *Inspection failed: {r.get('error_reason')} (orig: {r.get('orig_error_type')})*\n")
            else:
                md.append("  - *No items detected*\n")
        for item in r['items']:
            chk = f" *(Staff check: {item['check_reason']})*" if item['needs_staff_check'] else ""
            z_mark = " **[Zoomed]**" if item['zoomed'] else ""
            md.append(
                f"  - **{item['name']}**: stage `{item['stage']}` (`{item['stage_level']}`), worst stage `{item['worst_stage']}`, confidence `{item['confidence_level']}`, score `{item['score']}`, observed `{item['observed']}`, quantity `{item['quantity']}`{z_mark}{chk}\n"
            )
        md.append("\n")

    new_section = "".join(md)
    if existing_content:
        # If this exact section title already exists, replace it
        marker = f"## {section_title}"
        if marker in existing_content:
            parts = existing_content.split(f"\n---\n\n{marker}")
            if len(parts) == 2:
                # Keep everything before marker, replace the rest
                report_path.write_text(parts[0] + "\n---\n\n" + new_section, encoding="utf-8")
            else:
                report_path.write_text(existing_content + "\n---\n\n" + new_section, encoding="utf-8")
        else:
            report_path.write_text(existing_content + "\n---\n\n" + new_section, encoding="utf-8")
    else:
        report_path.write_text(new_section, encoding="utf-8")
    print(f"\nSaved smoke report to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smoke test for Freshness Inspector")
    parser.add_argument("--zoom", action="store_true", default=False, help="Enable pass-2 zoom")
    parser.add_argument("--thinking", choices=["low", "medium"], default=THINKING_LEVEL, help="Thinking level for Gemini Flash")
    args = parser.parse_args()

    photos_dir = REPO_DIR / "data/shelf_photos"
    smoke_files = [photos_dir / f"smoke{i}.png" for i in range(1, 7)]
    valid_photos = [p for p in smoke_files if p.exists()]

    if not valid_photos:
        print(f"Error: No smoke photos found in {photos_dir}")
        sys.exit(1)

    print(f"Running smoke check on {len(valid_photos)} photos (zoom={args.zoom}, thinking={args.thinking})...")
    smoke_results = asyncio.run(run_smoke(valid_photos, zoom=args.zoom, thinking=args.thinking))
    write_smoke_markdown(smoke_results, zoom=args.zoom, thinking=args.thinking)
