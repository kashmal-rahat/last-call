"""Deterministic guardrails and post-processing for Freshness Inspector."""

import math
import re

from pydantic import BaseModel, Field

from lastcall_api.inspector.schema import DetectedItem, InspectorOutput
from lastcall_shared.models import (
    BoundingBox,
    ConfidenceLevel,
    ObservedQuantity,
    PhotoIssue,
    PhotoStatus,
    ProduceIssue,
    ProduceStage,
    QuantityEstimate,
    StaffCheckReason,
    StageLevel,
)

STAGE_ORDER: dict[ProduceStage, int] = {
    "fresh": 0,
    "ripening": 1,
    "overripe": 2,
    "spoiled": 3,
    "unsafe": 4,
}

SCORE_TABLE: dict[tuple[ProduceStage, StageLevel], float] = {
    ("fresh", "early"): 95.0,
    ("fresh", "mid"): 88.0,
    ("fresh", "late"): 81.0,
    ("ripening", "early"): 76.0,
    ("ripening", "mid"): 69.0,
    ("ripening", "late"): 62.0,
    ("overripe", "early"): 55.0,
    ("overripe", "mid"): 46.0,
    ("overripe", "late"): 37.0,
    ("spoiled", "early"): 30.0,
    ("spoiled", "mid"): 21.0,
    ("spoiled", "late"): 12.0,
    ("unsafe", "early"): 8.0,
    ("unsafe", "mid"): 5.0,
    ("unsafe", "late"): 2.0,
}

CONFIDENCE_MAP: dict[ConfidenceLevel, float] = {
    "high": 0.9,
    "medium": 0.65,
    "low": 0.35,
}


class ItemDraft(BaseModel):
    """An assessed item before item_key and historical change fields are attached."""

    name: str
    position: BoundingBox
    grid: str
    in_mixed_crate: bool = False
    issues: list[ProduceIssue] = Field(default_factory=list)
    evidence: str = ""
    stage: ProduceStage
    stage_level: StageLevel
    worst_stage: ProduceStage
    score: float
    observed: ObservedQuantity
    quantity: QuantityEstimate
    confidence: float
    confidence_level: ConfidenceLevel
    needs_staff_check: bool = False
    staff_check_reasons: list[StaffCheckReason] = Field(default_factory=list)
    check_reason: str = ""
    zoomed: bool = False


def _round_tenth(val: float) -> float:
    """Round half up to 0.1. The 1e-9 guards float error (e.g. 0.35*10 = 3.4999…)."""
    return math.floor(val * 10 + 0.5 + 1e-9) / 10


def compute_grid(ymin: int, xmin: int, ymax: int, xmax: int) -> str:
    """Computes the 3x3 grid position cell from 0-1000 integer box coordinates.

    Rows: top, middle, bottom
    Columns: left, center, right
    Middle-middle cell: 'center'
    """
    cy = (ymin + ymax) / 2000.0
    cx = (xmin + xmax) / 2000.0

    r = "top" if cy < 1.0 / 3.0 else ("bottom" if cy > 2.0 / 3.0 else "middle")
    c = "left" if cx < 1.0 / 3.0 else ("right" if cx > 2.0 / 3.0 else "center")

    if r == "middle" and c == "center":
        return "center"
    return f"{r}-{c}"


STAFF_CHECK_PHRASES: dict[StaffCheckReason, str] = {
    "spoiled_or_unsafe": "produce looks spoiled or unsafe",
    "bad_pieces_in_group": "some pieces look spoiled",
    "low_confidence": "low confidence",
    "unknown_produce": "unidentified produce",
    "mixed_crate": "mixed crate",
    "model_flagged": "flagged for review",
    "safety_override": "safety override applied",
    "zoom_disagreement": "close-up reading differed",
}


def names_match(n1: str, n2: str) -> bool:
    """Checks if two produce names match, tolerating trailing 's' or 'es'."""
    s1 = re.sub(r"[^a-z0-9]", "", n1.lower())
    s2 = re.sub(r"[^a-z0-9]", "", n2.lower())
    if s1 == s2:
        return True

    stems1 = {s1}
    stems2 = {s2}
    if s1.endswith("s"):
        stems1.add(s1[:-1])
    if s1.endswith("es"):
        stems1.add(s1[:-2])
    if s2.endswith("s"):
        stems2.add(s2[:-1])
    if s2.endswith("es"):
        stems2.add(s2[:-2])

    return bool(stems1 & stems2)


def merge_two_items(i1: DetectedItem, i2: DetectedItem) -> DetectedItem:
    """Merges two neighbour items of the same produce."""
    area1 = (i1.box_2d[2] - i1.box_2d[0]) * (i1.box_2d[3] - i1.box_2d[1])
    area2 = (i2.box_2d[2] - i2.box_2d[0]) * (i2.box_2d[3] - i2.box_2d[1])
    larger, smaller = (i1, i2) if area1 >= area2 else (i2, i1)

    box_union = [
        min(i1.box_2d[0], i2.box_2d[0]),
        min(i1.box_2d[1], i2.box_2d[1]),
        max(i1.box_2d[2], i2.box_2d[2]),
        max(i1.box_2d[3], i2.box_2d[3]),
    ]

    worst = max([i1.worst_stage, i2.worst_stage], key=lambda s: STAGE_ORDER.get(s, 0))
    issues = list(dict.fromkeys(i1.visible_issues + i2.visible_issues))
    needs_staff = i1.needs_staff_check or i2.needs_staff_check
    reason = i1.check_reason.strip() or i2.check_reason.strip()

    conf_order = {"low": 0, "medium": 1, "high": 2}
    conf = min([i1.confidence, i2.confidence], key=lambda c: conf_order.get(c, 0))

    if i1.observed.method == i2.observed.method and i1.observed.method == "count":
        from lastcall_api.inspector.schema import ObservedOut

        obs = ObservedOut(
            method="count",
            min=i1.observed.min + i2.observed.min,
            max=i1.observed.max + i2.observed.max,
        )
    else:
        obs = larger.observed

    if i1.sale_unit == i2.sale_unit:
        sale_unit = larger.sale_unit
        sale_min = i1.sale_min + i2.sale_min
        sale_max = i1.sale_max + i2.sale_max
    else:
        sale_unit = larger.sale_unit
        sale_min = larger.sale_min
        sale_max = larger.sale_max

    return DetectedItem(
        name=larger.name,
        box_2d=box_union,
        in_mixed_crate=False,
        visible_issues=issues,
        evidence=larger.evidence,
        stage=larger.stage,
        stage_level=larger.stage_level,
        worst_stage=worst,
        observed=obs,
        sale_unit=sale_unit,
        sale_min=sale_min,
        sale_max=sale_max,
        confidence=conf,
        needs_staff_check=needs_staff,
        check_reason=reason,
    )


def merge_neighbours(items: list[DetectedItem]) -> list[DetectedItem]:
    """Merges neighbouring crates of the same produce in code.

    Two groups merge when their simple names match and their boxes overlap or
    the gap between them is at most 30 on the 0-1000 scale, both horizontally and vertically.
    Repeat until nothing merges. Never merge groups with in_mixed_crate True.
    """
    current = list(items)
    while True:
        merged_any = False
        n = len(current)
        for i in range(n):
            for j in range(i + 1, n):
                item_i = current[i]
                item_j = current[j]
                if item_i.in_mixed_crate or item_j.in_mixed_crate:
                    continue
                if item_i.name.strip().lower() == "unknown produce" or item_j.name.strip().lower() == "unknown produce":
                    continue
                if not names_match(item_i.name, item_j.name):
                    continue

                gap_y = max(0, max(item_i.box_2d[0], item_j.box_2d[0]) - min(item_i.box_2d[2], item_j.box_2d[2]))
                gap_x = max(0, max(item_i.box_2d[1], item_j.box_2d[1]) - min(item_i.box_2d[3], item_j.box_2d[3]))

                if gap_y <= 30 and gap_x <= 30:
                    merged = merge_two_items(item_i, item_j)
                    new_list = [current[k] for k in range(n) if k not in (i, j)]
                    new_list.insert(i, merged)
                    current = new_list
                    merged_any = True
                    break
            if merged_any:
                break
        if not merged_any:
            break
    return current


def clean_item(item: DetectedItem) -> DetectedItem | None:
    """Pure helper for Rules 1-2. Used right after pass 1 and during guardrails.

    1. Box: exactly 4 numbers, clamped to 0-1000. Dropped if ymin >= ymax or xmin >= xmax.
    2. Name: strip, lowercase, collapse spaces, max 40 chars. Empty -> 'unknown produce'.
    """
    if not isinstance(item.box_2d, list) or len(item.box_2d) != 4:
        return None

    try:
        ymin, xmin, ymax, xmax = [int(v) for v in item.box_2d]
    except (ValueError, TypeError):
        return None

    # Clamp to 0–1000
    ymin = max(0, min(1000, ymin))
    xmin = max(0, min(1000, xmin))
    ymax = max(0, min(1000, ymax))
    xmax = max(0, min(1000, xmax))

    if ymin >= ymax or xmin >= xmax:
        return None

    cleaned_box = [ymin, xmin, ymax, xmax]

    # Clean name
    raw_name = item.name or ""
    clean_name = re.sub(r"\s+", " ", raw_name).strip().lower()
    if len(clean_name) > 40:
        clean_name = clean_name[:40].strip()
    if not clean_name:
        clean_name = "unknown produce"

    # Return copy with cleaned box and name
    return item.model_copy(update={"box_2d": cleaned_box, "name": clean_name})


def apply_guardrails(
    out: InspectorOutput,
    *,
    zoom: dict[int, tuple[list[StaffCheckReason], bool]] | None = None,
) -> tuple[PhotoStatus, str, list[PhotoIssue], list[ItemDraft]]:
    """Applies deterministic post-processing, safety rules, scoring, and staff checks.

    Returns: (photo_status, photo_note, photo_issues, list[ItemDraft])
    """
    zoom_map = zoom or {}

    # Dedupe photo issues preserving order
    deduped_issues: list[PhotoIssue] = []
    for issue in out.photo_issues:
        if issue not in deduped_issues:
            deduped_issues.append(issue)

    photo_note = (out.photo_note or "").strip()[:200]
    photo_status = out.photo_status

    if photo_status != "ok":
        return photo_status, photo_note, deduped_issues, []

    drafts: list[ItemDraft] = []

    for idx, item in enumerate(out.items):
        cleaned = clean_item(item)
        if cleaned is None:
            continue

        ymin, xmin, ymax, xmax = cleaned.box_2d
        position = BoundingBox(
            ymin=ymin / 1000.0,
            xmin=xmin / 1000.0,
            ymax=ymax / 1000.0,
            xmax=xmax / 1000.0,
        )
        grid = compute_grid(ymin, xmin, ymax, xmax)
        name = cleaned.name

        # 3. Worst stage never better than stage
        stage = cleaned.stage
        worst_stage = cleaned.worst_stage
        if STAGE_ORDER.get(worst_stage, 0) < STAGE_ORDER.get(stage, 0):
            worst_stage = stage

        # 4. Safety override
        extra_reasons: list[StaffCheckReason] = []
        issues = cleaned.visible_issues or []
        prev_worst = worst_stage

        if "mould" in issues or "slime" in issues:
            worst_stage = "unsafe"
        elif ("rot" in issues or "leaking" in issues) and STAGE_ORDER.get(worst_stage, 0) < STAGE_ORDER.get("spoiled", 0):
            worst_stage = "spoiled"

        if worst_stage != prev_worst:
            extra_reasons.append("safety_override")

        # 5. Score from stage + stage_level
        score = SCORE_TABLE.get((stage, cleaned.stage_level), 50.0)

        # 6. Confidence numeric mapping
        conf_num = CONFIDENCE_MAP.get(cleaned.confidence, 0.65)

        # 7. Staff check reasons
        reasons: list[StaffCheckReason] = []
        if stage in ("spoiled", "unsafe"):
            reasons.append("spoiled_or_unsafe")
        elif worst_stage in ("spoiled", "unsafe"):
            reasons.append("bad_pieces_in_group")

        if cleaned.confidence == "low":
            reasons.append("low_confidence")

        if name == "unknown produce":
            reasons.append("unknown_produce")

        if cleaned.in_mixed_crate:
            reasons.append("mixed_crate")

        if cleaned.needs_staff_check:
            reasons.append("model_flagged")

        # Incorporate safety override reason
        for r in extra_reasons:
            if r not in reasons:
                reasons.append(r)

        # Incorporate zoom reasons if passed
        zoomed_flag = False
        if idx in zoom_map:
            z_reasons, z_flag = zoom_map[idx]
            zoomed_flag = z_flag
            for zr in z_reasons:
                if zr not in reasons:
                    reasons.append(zr)

        needs_staff_check = bool(reasons)
        check_reason = (cleaned.check_reason or "").strip()
        if not check_reason and needs_staff_check:
            parts = []
            for r in reasons:
                phrase = STAFF_CHECK_PHRASES.get(r, r.replace("_", " "))
                if not parts:
                    parts.append(phrase[0].upper() + phrase[1:])
                else:
                    parts.append(phrase[0].lower() + phrase[1:])
            check_reason = "; ".join(parts) + "."

        # 8. Observed quantity
        o_min = max(0, cleaned.observed.min)
        o_max = max(0, cleaned.observed.max)
        if o_min > o_max:
            o_min, o_max = o_max, o_min
        if cleaned.observed.method == "fill_level":
            o_min = min(100, o_min)
            o_max = min(100, o_max)
        observed = ObservedQuantity(method=cleaned.observed.method, min=o_min, max=o_max)

        # 9. Sale quantity
        if cleaned.sale_unit == "dozen" and cleaned.observed.method == "count":
            s_low = _round_tenth(observed.min / 12.0)
            s_high = _round_tenth(observed.max / 12.0)
        else:
            s_low = _round_tenth(max(0.0, cleaned.sale_min))
            s_high = _round_tenth(max(0.0, cleaned.sale_max))
            if s_low > s_high:
                s_low, s_high = s_high, s_low

        sale_quantity = QuantityEstimate(unit=cleaned.sale_unit, low=s_low, high=s_high)

        # 10. Trim text fields to 240 chars
        evidence = (cleaned.evidence or "").strip()[:240]
        check_reason = check_reason[:240]

        draft = ItemDraft(
            name=name,
            position=position,
            grid=grid,
            in_mixed_crate=cleaned.in_mixed_crate,
            issues=issues,
            evidence=evidence,
            stage=stage,
            stage_level=cleaned.stage_level,
            worst_stage=worst_stage,
            score=score,
            observed=observed,
            quantity=sale_quantity,
            confidence=conf_num,
            confidence_level=cleaned.confidence,
            needs_staff_check=needs_staff_check,
            staff_check_reasons=reasons,
            check_reason=check_reason,
            zoomed=zoomed_flag,
        )
        drafts.append(draft)

    # If more than 12 items, keep the 12 largest groups by box area first
    if len(drafts) > 12:
        drafts.sort(
            key=lambda d: (d.position.ymax - d.position.ymin) * (d.position.xmax - d.position.xmin),
            reverse=True,
        )
        drafts = drafts[:12]

    # Sort kept groups top-to-bottom, then left-to-right
    drafts.sort(key=lambda d: (d.position.ymin, d.position.xmin))

    # If status is ok but no items survive, set status to no_produce
    if len(drafts) == 0:
        return "no_produce", "No produce found", deduped_issues, []

    return photo_status, photo_note, deduped_issues, drafts
