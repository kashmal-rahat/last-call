#!/usr/bin/env python3
"""Evaluation runner for Freshness Inspector (Step 6).

Evaluates model against ground-truth labels in data/shelf_photos/labels.csv
and outputs results to data/inspector_runs/<timestamp>.jsonl and plans/module-1/results/eval.md.
"""

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR / "shared"))
sys.path.insert(0, str(REPO_DIR / "services/api"))

from lastcall_api.inspector.eval_metrics import (
    STAGES,
    LabelRow,
    calculate_confusion_matrix,
    calculate_consistency,
    calculate_lenient_stage_accuracy,
    calculate_name_accuracy,
    calculate_per_stage_recall,
    calculate_strict_stage_accuracy,
    calculate_worst_stage_accuracy,
    check_edge_photo,
    find_critical_misses,
    find_false_alarms,
    match_labels_to_predictions,
)
from lastcall_api.inspector.inspector import estimate_cost, inspect_photo
from lastcall_shared.models import FreshnessResult, ItemAssessment


def load_labels(labels_csv: Path, split: str = "test", only_file: str | None = None) -> list[LabelRow]:
    if not labels_csv.exists():
        return []

    rows: list[LabelRow] = []
    with labels_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            row_split = r.get("split", "test").strip()
            if split != "all" and row_split != split:
                continue
            fname = r.get("filename", "").strip()
            if only_file and fname != only_file:
                continue

            accept_stages = [s.strip() for s in r.get("acceptable_stages", "").split(";") if s.strip()]
            t_count = int(r["true_count"]) if r.get("true_count") and r["true_count"].strip().isdigit() else None
            t_kg = float(r["true_kg"]) if r.get("true_kg") and r["true_kg"].strip() else None
            seq_val = int(r["seq"]) if r.get("seq") and r["seq"].strip().isdigit() else None

            row = LabelRow(
                filename=fname,
                split=row_split,
                photo_kind=r.get("photo_kind", "normal").strip() or "normal",
                series_id=r.get("series_id", "").strip(),
                seq=seq_val,
                item=r.get("item", "").strip(),
                grid=r.get("grid", "").strip(),
                expected_stage=r.get("expected_stage", "fresh").strip() or "fresh",
                acceptable_stages=accept_stages,
                expected_worst_stage=r.get("expected_worst_stage", "").strip(),
                true_count=t_count,
                true_kg=t_kg,
                notes=r.get("notes", "").strip(),
            )
            rows.append(row)
    return rows


async def run_evaluation(
    *,
    labels_csv: Path = REPO_DIR / "data/shelf_photos/labels.csv",
    photos_dir: Path = REPO_DIR / "data/shelf_photos",
    runs_dir: Path = REPO_DIR / "data/inspector_runs",
    results_dir: Path = REPO_DIR / "plans/module-1/results",
    split: str = "test",
    runs: int = 2,
    only: str | None = None,
    concurrency: int = 2,
    max_minutes: int = 30,
    no_zoom: bool = False,
    compare_zoom: bool = False,
    inspect_fn=inspect_photo,
) -> dict:
    labels = load_labels(labels_csv, split=split, only_file=only)
    if not labels:
        print(f"No labels found in {labels_csv} for split '{split}'.")
        return {}

    runs_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    zoom_modes = [False, True] if compare_zoom else [not no_zoom]
    all_mode_results = {}

    for zoom_flag in zoom_modes:
        mode_label = "zoom_on" if zoom_flag else "zoom_off"
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        jsonl_path = runs_dir / f"eval_{mode_label}_{ts}.jsonl"

        # Group labels by filename
        files_map: dict[str, list[LabelRow]] = {}
        for row in labels:
            files_map.setdefault(row.filename, []).append(row)

        # Identify series vs single photos
        series_groups: dict[str, list[str]] = {}
        single_files: list[str] = []

        for fname, lbl_list in files_map.items():
            first_lbl = lbl_list[0]
            if first_lbl.series_id:
                series_groups.setdefault(first_lbl.series_id, []).append(fname)
            else:
                single_files.append(fname)

        # Sort series files by seq
        for _s_id, s_files in series_groups.items():
            s_files.sort(key=lambda fn: files_map[fn][0].seq or 0)

        sem = asyncio.Semaphore(concurrency)
        deadline = time.monotonic() + (max_minutes * 60)

        run_outputs: list[dict] = []
        # Key: (filename, run_idx) -> FreshnessResult
        results_by_run: dict[tuple[str, int], FreshnessResult | None] = {}
        errors_by_run: dict[tuple[str, int], str] = {}

        async def inspect_single(
            fname: str,
            run_idx: int,
            prev: FreshnessResult | None,
            *,
            deadline: float = deadline,
            sem: asyncio.Semaphore = sem,
            zoom_flag: bool = zoom_flag,
        ):
            if time.monotonic() > deadline:
                return fname, run_idx, None, "Timeout: run deadline exceeded"
            img_path = photos_dir / fname
            if not img_path.exists():
                return fname, run_idx, None, f"File not found: {fname}"
            raw = img_path.read_bytes()
            now = datetime.now(timezone.utc)
            async with sem:
                try:
                    res = await inspect_fn(
                        raw,
                        mart_id="eval_mart",
                        shelf_id="eval_shelf",
                        previous=prev,
                        now=now,
                        zoom=zoom_flag,
                    )
                    return fname, run_idx, res, None
                except Exception as exc:
                    orig = getattr(exc, "original_exc", None)
                    orig_name = type(orig).__name__ if orig is not None else type(exc).__name__
                    return fname, run_idx, None, f"{exc} ({orig_name})"

        # Execute single photos across runs
        tasks = []
        for run_i in range(runs):
            for fname in single_files:
                tasks.append(inspect_single(fname, run_i, None))

        single_results = await asyncio.gather(*tasks)
        for fname, run_i, res, err in single_results:
            results_by_run[(fname, run_i)] = res
            if err:
                errors_by_run[(fname, run_i)] = err
            if res:
                run_outputs.append(
                    {
                        "filename": fname,
                        "run": run_i,
                        "result": res.model_dump(mode="json"),
                    }
                )

        # Execute series photos in seq order
        for run_i in range(runs):
            for _s_id, s_files in series_groups.items():
                prev_res = None
                for fname in s_files:
                    _, _, cur_res, err = await inspect_single(fname, run_i, prev_res)
                    results_by_run[(fname, run_i)] = cur_res
                    if err:
                        errors_by_run[(fname, run_i)] = err
                    if cur_res:
                        run_outputs.append(
                            {
                                "filename": fname,
                                "run": run_i,
                                "result": cur_res.model_dump(mode="json"),
                            }
                        )
                    prev_res = cur_res

        # Write jsonl
        with jsonl_path.open("w", encoding="utf-8") as f:
            for item in run_outputs:
                f.write(json.dumps(item) + "\n")

        # Exclude errored photos in run 0 from accuracy/critical-miss metrics
        errored_photos_run0 = {fname: err for (fname, r_idx), err in errors_by_run.items() if r_idx == 0}

        # Compute metrics for run 0
        run0_matches = []
        all_predictions_run0: list[ItemAssessment] = []
        latencies: list[float] = []
        total_cost = 0.0
        total_calls = 0
        zoomed_groups_count = 0
        zoom_failures_count = 0
        edge_pass_count = 0
        edge_total_count = 0

        for fname, lbl_list in files_map.items():
            if fname in errored_photos_run0:
                continue

            res = results_by_run.get((fname, 0))
            if res and res.inspector:
                latencies.append(res.inspector.latency_ms / 1000.0)
                total_calls += res.inspector.calls
                zoomed_groups_count += res.inspector.zoomed_groups
                zoom_failures_count += res.inspector.zoom_failures
                cost = estimate_cost(res.inspector)
                total_cost += cost

            items = res.items if res else []
            all_predictions_run0.extend(items)
            matches = match_labels_to_predictions(lbl_list, items)
            run0_matches.extend(matches)

            for row in lbl_list:
                if row.photo_kind != "normal":
                    edge_total_count += 1
                    if res and check_edge_photo(row.photo_kind, res):
                        edge_pass_count += 1

        strict_acc = calculate_strict_stage_accuracy(run0_matches)
        lenient_acc = calculate_lenient_stage_accuracy(run0_matches)
        worst_acc = calculate_worst_stage_accuracy(run0_matches)
        recalls = calculate_per_stage_recall(run0_matches)
        critical_misses = find_critical_misses(run0_matches)
        false_alarms = find_false_alarms(run0_matches)
        name_acc = calculate_name_accuracy(run0_matches)
        cm = calculate_confusion_matrix(run0_matches)

        # Quantity metrics (split by zoomed vs not zoomed)
        count_in_range_all, count_total_all = 0, 0
        count_in_range_zoom, count_total_zoom = 0, 0
        count_in_range_nozoom, count_total_nozoom = 0, 0
        count_widths_all, count_widths_zoom, count_widths_nozoom = [], [], []

        kg_in_range_all, kg_total_all = 0, 0
        kg_in_range_zoom, kg_total_zoom = 0, 0
        kg_in_range_nozoom, kg_total_nozoom = 0, 0
        kg_widths_all, kg_widths_zoom, kg_widths_nozoom = [], [], []

        for lbl, pred in run0_matches:
            if pred is None:
                continue
            is_zoomed = bool(pred.zoomed)
            if lbl.true_count is not None and pred.observed is not None:
                c_min = pred.observed.min
                c_max = pred.observed.max
                width = c_max - c_min
                in_rng = c_min <= lbl.true_count <= c_max

                count_total_all += 1
                count_widths_all.append(width)
                if in_rng:
                    count_in_range_all += 1
                if is_zoomed:
                    count_total_zoom += 1
                    count_widths_zoom.append(width)
                    if in_rng:
                        count_in_range_zoom += 1
                else:
                    count_total_nozoom += 1
                    count_widths_nozoom.append(width)
                    if in_rng:
                        count_in_range_nozoom += 1

            if lbl.true_kg is not None and pred.quantity is not None:
                k_min = pred.quantity.low
                k_max = pred.quantity.high
                width = k_max - k_min
                in_rng = k_min <= lbl.true_kg <= k_max

                kg_total_all += 1
                kg_widths_all.append(width)
                if in_rng:
                    kg_in_range_all += 1
                if is_zoomed:
                    kg_total_zoom += 1
                    kg_widths_zoom.append(width)
                    if in_rng:
                        kg_in_range_zoom += 1
                else:
                    kg_total_nozoom += 1
                    kg_widths_nozoom.append(width)
                    if in_rng:
                        kg_in_range_nozoom += 1

        def _med(vals: list[float]) -> float:
            return float(statistics.median(vals)) if vals else 0.0

        quantity_metrics = {
            "count_acc_all": (count_in_range_all / count_total_all) if count_total_all else 1.0,
            "count_acc_zoom": (count_in_range_zoom / count_total_zoom) if count_total_zoom else 1.0,
            "count_acc_nozoom": (count_in_range_nozoom / count_total_nozoom) if count_total_nozoom else 1.0,
            "count_median_width_all": _med(count_widths_all),
            "count_median_width_zoom": _med(count_widths_zoom),
            "count_median_width_nozoom": _med(count_widths_nozoom),
            "kg_acc_all": (kg_in_range_all / kg_total_all) if kg_total_all else 1.0,
            "kg_acc_zoom": (kg_in_range_zoom / kg_total_zoom) if kg_total_zoom else 1.0,
            "kg_acc_nozoom": (kg_in_range_nozoom / kg_total_nozoom) if kg_total_nozoom else 1.0,
            "kg_median_width_all": _med(kg_widths_all),
            "kg_median_width_zoom": _med(kg_widths_zoom),
            "kg_median_width_nozoom": _med(kg_widths_nozoom),
        }

        # Time-lapse monotonicity check
        series_violations = 0
        max_score_rise = 0.0
        for _s_id, s_files in series_groups.items():
            prev_shelf_score = None
            for fname in s_files:
                if fname in errored_photos_run0:
                    continue
                res = results_by_run.get((fname, 0))
                if res and res.items:
                    avg_score = sum(it.score for it in res.items) / len(res.items)
                    if prev_shelf_score is not None:
                        rise = avg_score - prev_shelf_score
                        if rise > max_score_rise:
                            max_score_rise = rise
                        if rise > 7.0:
                            series_violations += 1
                    prev_shelf_score = avg_score

        # Staff-check rate
        staff_check_count = sum(1 for it in all_predictions_run0 if it.needs_staff_check)
        staff_check_rate = (staff_check_count / len(all_predictions_run0)) if all_predictions_run0 else 0.0

        # Unknown produce rate
        unknown_count = sum(1 for it in all_predictions_run0 if it.name == "unknown produce")
        unknown_rate = (unknown_count / len(all_predictions_run0)) if all_predictions_run0 else 0.0

        # Detection recall
        detected_labels = sum(1 for lbl, pred in run0_matches if lbl.item.strip() and pred is not None)
        total_eval_labels = sum(1 for lbl, _ in run0_matches if lbl.item.strip())
        det_recall = (detected_labels / total_eval_labels) if total_eval_labels else 1.0
        extra_groups = max(0, len(all_predictions_run0) - detected_labels)

        # Consistency across runs
        consistencies = []
        if runs >= 2:
            for fname in files_map:
                if fname in errored_photos_run0:
                    continue
                res1 = results_by_run.get((fname, 0))
                res2 = results_by_run.get((fname, 1))
                if res1 and res2:
                    c = calculate_consistency(res1.items, res2.items)
                    consistencies.append(c)
        consistency_val = (sum(consistencies) / len(consistencies)) if consistencies else 1.0

        # Latency percentiles
        latencies.sort()
        p50 = latencies[len(latencies) // 2] if latencies else 0.0
        p90 = latencies[int(len(latencies) * 0.9)] if latencies else 0.0
        valid_count = max(1, len(files_map) - len(errored_photos_run0))
        avg_cost = total_cost / valid_count

        try:
            rel_jsonl = str(jsonl_path.relative_to(REPO_DIR))
        except ValueError:
            rel_jsonl = str(jsonl_path)

        # 3 example results with evidence
        example_results = []
        for (fname, r_idx), res in results_by_run.items():
            if r_idx == 0 and res and res.items:
                example_results.append(
                    {
                        "filename": fname,
                        "photo_status": res.photo_status,
                        "items": [
                            {
                                "name": it.name,
                                "stage": it.stage,
                                "worst_stage": it.worst_stage,
                                "confidence": it.confidence,
                                "score": it.score,
                                "quantity": f"{it.quantity.low}-{it.quantity.high} {it.quantity.unit}"
                                if it.quantity
                                else "-",
                                "evidence": it.evidence,
                                "needs_staff_check": it.needs_staff_check,
                                "check_reason": it.check_reason,
                            }
                            for it in res.items
                        ],
                    }
                )
                if len(example_results) == 3:
                    break

        all_mode_results[mode_label] = {
            "strict_acc": strict_acc,
            "lenient_acc": lenient_acc,
            "worst_acc": worst_acc,
            "recalls": recalls,
            "critical_misses": critical_misses,
            "false_alarms": false_alarms,
            "name_acc": name_acc,
            "unknown_rate": unknown_rate,
            "detection_recall": det_recall,
            "extra_groups": extra_groups,
            "edge_pass_rate": (edge_pass_count / edge_total_count) if edge_total_count else 1.0,
            "consistency": consistency_val,
            "p50_latency": p50,
            "p90_latency": p90,
            "avg_cost": avg_cost,
            "confusion_matrix": cm,
            "zoomed_count": zoomed_groups_count,
            "zoom_failures": zoom_failures_count,
            "quantity_metrics": quantity_metrics,
            "series_violations": series_violations,
            "max_score_rise": max_score_rise,
            "staff_check_rate": staff_check_rate,
            "errors_count": len(errored_photos_run0),
            "errors": [{"filename": fn, "reason": reas} for fn, reas in errored_photos_run0.items()],
            "examples": example_results,
            "results_by_run": results_by_run,
            "jsonl_path": rel_jsonl,
        }

    # Groups whose stage or worst_stage changed after zoom
    zoom_stage_changes = 0
    if compare_zoom and "zoom_off" in all_mode_results and "zoom_on" in all_mode_results:
        off_res = all_mode_results["zoom_off"]["results_by_run"]
        on_res = all_mode_results["zoom_on"]["results_by_run"]
        for fname in files_map:
            r_off = off_res.get((fname, 0))
            r_on = on_res.get((fname, 0))
            if r_off and r_on:
                for it_off, it_on in zip(r_off.items, r_on.items, strict=False):
                    if (it_off.stage != it_on.stage) or (it_off.worst_stage != it_on.worst_stage):
                        zoom_stage_changes += 1
    if "zoom_on" in all_mode_results:
        all_mode_results["zoom_on"]["zoom_stage_changes"] = zoom_stage_changes

    # Generate eval.md
    write_eval_markdown(all_mode_results, results_dir / "eval.md", compare_zoom=compare_zoom)
    return all_mode_results


def write_eval_markdown(mode_results: dict, output_path: Path, compare_zoom: bool = False):
    md = []
    md.append("# Freshness Inspector Evaluation Results (Module 1)\n")
    md.append(f"Generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")

    if compare_zoom and "zoom_off" in mode_results and "zoom_on" in mode_results:
        z_off = mode_results["zoom_off"]
        z_on = mode_results["zoom_on"]
        md.append("## Zoom Comparison (Evidence for D29)\n\n")
        md.append("| Metric | Target | Zoom OFF | Zoom ON |\n")
        md.append("|---|---|---|---|\n")
        md.append(f"| Stage accuracy (strict) | ≥ 80% | {z_off['strict_acc']:.1%} | {z_on['strict_acc']:.1%} |\n")
        md.append(f"| Worst-stage accuracy | report | {z_off['worst_acc']:.1%} | {z_on['worst_acc']:.1%} |\n")
        md.append(
            f"| **Critical misses** | **0** | **{len(z_off['critical_misses'])}** | **{len(z_on['critical_misses'])}** |\n"
        )
        md.append(f"| False alarms | report | {len(z_off['false_alarms'])} | {len(z_on['false_alarms'])} |\n")
        md.append(f"| Groups whose stage changed | report | - | {z_on.get('zoom_stage_changes', 0)} |\n")
        md.append(
            f"| Latency p50 / p90 | ≤ 10s / ≤ 20s | {z_off['p50_latency']:.2f}s / {z_off['p90_latency']:.2f}s | {z_on['p50_latency']:.2f}s / {z_on['p90_latency']:.2f}s |\n"
        )
        md.append(f"| Average cost per inspection | report | ${z_off['avg_cost']:.5f} | ${z_on['avg_cost']:.5f} |\n\n")

    main_key = "zoom_on" if "zoom_on" in mode_results else list(mode_results.keys())[0]
    res = mode_results[main_key]

    md.append("## Overall Metrics\n\n")
    md.append("| Metric | Target | Result |\n")
    md.append("|---|---|---|\n")
    md.append(f"| Stage accuracy, strict (run 1) | ≥ 80% | {res['strict_acc']:.1%} |\n")
    md.append(f"| Stage accuracy, lenient | report | {res['lenient_acc']:.1%} |\n")
    md.append(f"| Worst-stage accuracy | report | {res['worst_acc']:.1%} |\n")
    md.append(f"| **Critical misses** | **0** | **{len(res['critical_misses'])}** |\n")
    md.append(f"| False alarms | report | {len(res['false_alarms'])} |\n")
    md.append(f"| Name accuracy | report | {res['name_acc']:.1%} |\n")
    md.append(f"| Unknown produce rate | report | {res['unknown_rate']:.1%} |\n")
    md.append(f"| Detection recall | report | {res['detection_recall']:.1%} |\n")
    md.append(f"| Extra groups | report | {res['extra_groups']} |\n")
    md.append(f"| Edge photo pass rate | 100% | {res['edge_pass_rate']:.1%} |\n")
    md.append(f"| Consistency across runs | ≥ 90% | {res['consistency']:.1%} |\n")
    qm = res["quantity_metrics"]
    md.append(
        f"| Quantity (count in range: all / zoom / no-zoom) | report | {qm['count_acc_all']:.1%} / {qm['count_acc_zoom']:.1%} / {qm['count_acc_nozoom']:.1%} |\n"
    )
    md.append(
        f"| Quantity (count median width: all / zoom / no-zoom) | report | {qm['count_median_width_all']:.1f} / {qm['count_median_width_zoom']:.1f} / {qm['count_median_width_nozoom']:.1f} |\n"
    )
    md.append(
        f"| Quantity (kg in range: all / zoom / no-zoom) | report | {qm['kg_acc_all']:.1%} / {qm['kg_acc_zoom']:.1%} / {qm['kg_acc_nozoom']:.1%} |\n"
    )
    md.append(
        f"| Quantity (kg median width: all / zoom / no-zoom) | report | {qm['kg_median_width_all']:.1f}kg / {qm['kg_median_width_zoom']:.1f}kg / {qm['kg_median_width_nozoom']:.1f}kg |\n"
    )
    md.append(
        f"| Time-lapse (score never rises > 7 pts) | report | {res['series_violations']} violations (max rise: +{res['max_score_rise']:.1f} pts) |\n"
    )
    md.append(f"| Staff-check rate | report | {res['staff_check_rate']:.1%} |\n")
    md.append(f"| Latency p50 / p90 | ≤ 10s / ≤ 20s | {res['p50_latency']:.2f}s / {res['p90_latency']:.2f}s |\n")
    md.append(f"| Zoomed groups / Zoom failures | report | {res['zoomed_count']} / {res['zoom_failures']} |\n")
    if "zoom_stage_changes" in res:
        md.append(f"| Groups whose stage changed after zoom | report | {res['zoom_stage_changes']} |\n")
    md.append(f"| Cost per inspection | report | ${res['avg_cost']:.5f} |\n")
    md.append(f"| Errors | 0 | {res['errors_count']} |\n\n")

    if res["errors"]:
        md.append("### Inspection Errors\n\n")
        for err_item in res["errors"]:
            md.append(f"- **{err_item['filename']}**: `{err_item['reason']}`\n")
        md.append("\n")

    md.append("### Per-Stage Recall\n\n")
    md.append("| Stage | Recall |\n|---|---|\n")
    for st, rec in res["recalls"].items():
        md.append(f"| `{st}` | {rec:.1%} |\n")

    md.append("\n### 5x5 Confusion Matrix (Rows: Expected, Columns: Predicted)\n\n")
    cm = res["confusion_matrix"]
    md.append("| Expected \\ Pred | " + " | ".join(f"`{s}`" for s in STAGES) + " |\n")
    md.append("|---" * (len(STAGES) + 1) + "|\n")
    for exp in STAGES:
        row_vals = " | ".join(str(cm.get(exp, {}).get(pred, 0)) for pred in STAGES)
        md.append(f"| `{exp}` | {row_vals} |\n")

    if res.get("examples"):
        md.append("\n### Example Inspection Results with Evidence\n\n")
        for i, ex in enumerate(res["examples"], 1):
            md.append(f"#### Example {i}: `{ex['filename']}` (status: {ex['photo_status']})\n")
            for it in ex["items"]:
                sc = f" *(Staff check: {it['check_reason']})*" if it["needs_staff_check"] else ""
                md.append(
                    f"- **{it['name']}**: stage `{it['stage']}` (worst: `{it['worst_stage']}`, conf: `{it['confidence']}`, score: {it['score']}, qty: {it['quantity']}){sc}\n"
                )
                md.append(f'  - *Evidence:* "{it["evidence"]}"\n')
            md.append("\n")

    output_path.write_text("".join(md), encoding="utf-8")
    print(f"Saved evaluation markdown to {output_path}")


async def main():
    parser = argparse.ArgumentParser(description="Evaluate Freshness Inspector against labelled dataset.")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test", help="Dataset split to evaluate")
    parser.add_argument("--runs", type=int, default=2, help="Number of evaluation runs per photo")
    parser.add_argument("--only", type=str, default=None, help="Evaluate only a specific photo filename")
    parser.add_argument("--concurrency", type=int, default=2, help="Max concurrent inspections")
    parser.add_argument("--max-minutes", type=int, default=30, help="Max run duration in minutes")
    parser.add_argument("--no-zoom", action="store_true", help="Disable Pass 2 zoom")
    parser.add_argument("--compare-zoom", action="store_true", help="Run both zoom-off and zoom-on to compare")

    args = parser.parse_args()
    await run_evaluation(
        split=args.split,
        runs=args.runs,
        only=args.only,
        concurrency=args.concurrency,
        max_minutes=args.max_minutes,
        no_zoom=args.no_zoom,
        compare_zoom=args.compare_zoom,
    )


if __name__ == "__main__":
    asyncio.run(main())
