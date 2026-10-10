# Shelf Photos & Evaluation Dataset Guide

This directory holds produce shelf photos and ground-truth annotations used for evaluating Module 1 (Freshness Inspector).

## Git Ignore & Storage Policy
- **Photos are ignored in Git**: All image files (`*.jpg`, `*.jpeg`, `*.png`, `*.heic`, `*.HEIC`) are ignored via `.gitignore` to keep repository size lean.
- **Only documentation and labels are tracked**: `README.md` and `labels.csv` are tracked in Git.

## Converting HEIC to JPEG
If photos were shot on iPhone in HEIC format, convert them locally using macOS `sips`:
```bash
for f in *.heic *.HEIC; do
  [ -f "$f" ] && sips -s format jpeg "$f" --out "${f%.*}.jpg"
done
```

## Freshness Stages
Ground-truth stages are defined by visual decay characteristics. Refer directly to the stage rubric in **[Appendix A of plans/module-1/plan.md](../../plans/module-1/plan.md)**:
- `fresh`: Firm, bright, sound, no decay.
- `ripening`: Mature, slight softening or color change, peak eating condition.
- `overripe`: Very soft, heavily spotted, wrinkled, still safe for rapid consumption/cooking.
- `spoiled`: Active decay, mold, rot, leakage, insect damage, structural breakdown.
- `unsafe`: Severe decomposition, toxic mold/slime, foul, unfit for human or animal consumption.

## Annotation Schema (`labels.csv`)

Ground-truth labels are written to `data/shelf_photos/labels.csv` with the following columns:

| Column | Type | Description | Example |
|---|---|---|---|
| `filename` | string | Filename of the photo in this folder | `mart_01.jpg` |
| `split` | string | Evaluation split: `dev` (tuning) or `test` (held-out) | `dev` |
| `photo_kind` | string | `normal` or edge category (`edge_blurry`, `edge_dark`, `edge_empty`, `edge_non_produce`, `edge_injection`) | `normal` |
| `series_id` | string | Identifier for time-lapse series of the same shelf/tray (blank if standalone) | `tray_banana_a` |
| `seq` | integer | Sequence order index within time-lapse series (1-indexed) | `1` |
| `item` | string | Ground-truth produce name. Semicolon-separated for synonyms | `banana; yellow banana` |
| `grid` | string | Approximate 3×3 grid position (`top-left`, `center`, `bottom-right`, etc.) | `top-left` |
| `expected_stage` | string | Expected typical piece stage (`fresh`, `ripening`, `overripe`, `spoiled`, `unsafe`) | `ripening` |
| `acceptable_stages` | string | Semicolon-separated acceptable borderline stages | `ripening; overripe` |
| `expected_worst_stage` | string | Expected worst piece stage if individual pieces are worse (leave blank if same as `expected_stage`) | `overripe` |
| `true_count` | integer | Optional ground-truth piece count from manual count | `16` |
| `true_kg` | float | Optional ground-truth weight in kg measured on scale | `2.4` |
| `notes` | string | Human annotator context, edge observations, or defect notes | `Minor bruising on 2 pieces` |
