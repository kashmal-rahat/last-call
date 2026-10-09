"""Stable item key assignment and temporal matching across photos (Step 4)."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pydantic import AwareDatetime

from lastcall_api.inspector.guardrails import STAGE_ORDER, ItemDraft, names_match
from lastcall_shared.models import FreshnessResult, ItemAssessment

PKT = ZoneInfo("Asia/Karachi")


def slug(text: str) -> str:
    """Creates a snake_case slug from string."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return cleaned or "item"


def compute_iou(b1, b2) -> float:
    """Computes Intersection over Union of two BoundingBox objects."""
    inter_ymin = max(b1.ymin, b2.ymin)
    inter_xmin = max(b1.xmin, b2.xmin)
    inter_ymax = min(b1.ymax, b2.ymax)
    inter_xmax = min(b1.xmax, b2.xmax)

    if inter_ymax <= inter_ymin or inter_xmax <= inter_xmin:
        return 0.0

    inter_area = (inter_ymax - inter_ymin) * (inter_xmax - inter_xmin)
    b1_area = (b1.ymax - b1.ymin) * (b1.xmax - b1.xmin)
    b2_area = (b2.ymax - b2.ymin) * (b2.xmax - b2.xmin)
    union_area = b1_area + b2_area - inter_area

    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area


def format_change_note(
    score: float,
    prev_score: float,
    worst_stage: str,
    prev_worst_stage: str,
    prev_taken_at: AwareDatetime,
    now: datetime,
) -> tuple[float, str]:
    """Computes score change and human-readable change note."""
    delta = round(score - prev_score, 1)
    prev_dt = prev_taken_at.astimezone(PKT)
    now_dt = now.astimezone(PKT)

    if prev_dt.date() == now_dt.date():
        time_str = f"today {prev_dt.strftime('%H:%M')}"
    elif prev_dt.date() == (now_dt.date() - timedelta(days=1)):
        time_str = f"yesterday {prev_dt.strftime('%H:%M')}"
    else:
        time_str = prev_dt.strftime("%d %b %H:%M")

    diff = abs(delta)
    points_val = int(diff) if diff.is_integer() else diff

    if delta < -0.01:
        phrase = f"dropped {points_val} points since {time_str}"
    elif delta > 0.01:
        phrase = f"up {points_val} points since {time_str}"
    else:
        phrase = f"no change since {time_str}"

    if STAGE_ORDER.get(worst_stage, 0) > STAGE_ORDER.get(prev_worst_stage, 0):
        phrase += f"; worst pieces now {worst_stage}"

    return delta, phrase


def assign_keys(
    drafts: list[ItemDraft],
    previous: FreshnessResult | None,
    *,
    now: datetime,
) -> list[ItemAssessment]:
    """Pure key assignment and previous-photo matching.

    1. Base key: slug(name) + "_" + slug(grid) with _2, _3 for collisions.
    2. Matching with previous photo: simple names match and IoU >= 0.3.
       Greedy by highest IoU. Reuses previous item_key unless already taken.
    3. Change: change_since_last and change_note computed for matched items.
    """
    # Find candidate matches between drafts and previous items
    matches: dict[int, ItemAssessment] = {}  # draft_idx -> previous_item
    used_prev_keys: set[str] = set()

    if previous and previous.items:
        candidates = []
        for d_idx, draft in enumerate(drafts):
            for prev_item in previous.items:
                if names_match(draft.name, prev_item.name):
                    iou = compute_iou(draft.position, prev_item.position)
                    if iou >= 0.3:
                        candidates.append((iou, d_idx, prev_item))

        # Sort greedy by highest IoU
        candidates.sort(key=lambda x: x[0], reverse=True)
        matched_drafts: set[int] = set()
        matched_prevs: set[str] = set()

        for _, d_idx, prev_item in candidates:
            if d_idx in matched_drafts or prev_item.item_key in matched_prevs:
                continue
            matched_drafts.add(d_idx)
            matched_prevs.add(prev_item.item_key)
            matches[d_idx] = prev_item

    assigned: list[ItemAssessment] = []
    used_keys: set[str] = set()

    for d_idx, draft in enumerate(drafts):
        prev_match = matches.get(d_idx)
        change_since_last = None
        change_note = None
        item_key = None

        if prev_match and prev_match.item_key not in used_keys:
            # Re-use previous key
            item_key = prev_match.item_key
            delta, note = format_change_note(
                score=draft.score,
                prev_score=prev_match.score,
                worst_stage=draft.worst_stage,
                prev_worst_stage=prev_match.worst_stage,
                prev_taken_at=previous.taken_at,
                now=now,
            )
            change_since_last = delta
            change_note = note
        else:
            # Generate base key: slug(name) + "_" + slug(grid)
            base = f"{slug(draft.name)}_{slug(draft.grid)}"
            item_key = base
            counter = 2
            while item_key in used_keys:
                item_key = f"{base}_{counter}"
                counter += 1

        used_keys.add(item_key)

        assessment = ItemAssessment(
            item_key=item_key,
            name=draft.name,
            position=draft.position,
            grid=draft.grid,
            in_mixed_crate=draft.in_mixed_crate,
            issues=draft.issues,
            evidence=draft.evidence,
            stage=draft.stage,
            stage_level=draft.stage_level,
            worst_stage=draft.worst_stage,
            score=draft.score,
            change_since_last=change_since_last,
            change_note=change_note,
            observed=draft.observed,
            quantity=draft.quantity,
            confidence=draft.confidence,
            confidence_level=draft.confidence_level,
            needs_staff_check=draft.needs_staff_check,
            staff_check_reasons=draft.staff_check_reasons,
            check_reason=draft.check_reason,
            zoomed=draft.zoomed,
        )
        assigned.append(assessment)

    return assigned
