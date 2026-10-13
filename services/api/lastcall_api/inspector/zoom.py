"""Pass-2 zoom selection and reading merger (Module 1, D29)."""

from lastcall_api.inspector.guardrails import STAGE_ORDER
from lastcall_api.inspector.matching import names_match
from lastcall_api.inspector.schema import DetectedItem, InspectorOutput
from lastcall_shared.models import ConfidenceLevel, ProduceStage, StaffCheckReason

_DOUBT_ISSUES = {"mould", "slime", "rot", "leaking", "pest_damage"}
MAX_ZOOM_BOX_AREA = 0.40


def _lower_confidence(conf: ConfidenceLevel) -> ConfidenceLevel:
    if conf == "high":
        return "medium"
    return "low"


def _worse_stage(s1: ProduceStage, s2: ProduceStage) -> ProduceStage:
    if STAGE_ORDER.get(s2, 0) > STAGE_ORDER.get(s1, 0):
        return s2
    return s1


def _box_area(box_2d: list[int]) -> float:
    ymin, xmin, ymax, xmax = box_2d
    return ((ymax - ymin) / 1000.0) * ((xmax - xmin) / 1000.0)


def select_for_zoom(items: list[DetectedItem], *, max_crops: int = 6) -> list[int]:
    """Selects and prioritizes groups qualifying for pass-2 zoom inspection.

    A group qualifies if its box area <= MAX_ZOOM_BOX_AREA (0.40) and any of:
    1. visible_issues contains mould, slime, rot, leaking or pest_damage
    2. worst_stage != stage
    3. confidence is medium or low
    4. stage_level == "late"
    5. there are >= 2 groups and the box covers < 15% of the photo
    6. method count with wide range (max > 1.5 * min and max > 10)

    Sorts by the first rule each item meets (rule 1 first), then by box area (smaller first).
    Returns at most max_crops indices.
    """
    total_groups = len(items)
    qualified: list[tuple[int, float, int]] = []  # (rule_priority, box_area, item_idx)

    for idx, item in enumerate(items):
        area = _box_area(item.box_2d)
        if area > MAX_ZOOM_BOX_AREA:
            continue

        rule = None
        issues_set = set(item.visible_issues or [])

        # Rule 1
        if issues_set & _DOUBT_ISSUES:
            rule = 1
        # Rule 2
        elif item.worst_stage != item.stage:
            rule = 2
        # Rule 3
        elif item.confidence in ("medium", "low"):
            rule = 3
        # Rule 4
        elif item.stage_level == "late":
            rule = 4
        # Rule 5
        elif total_groups >= 2 and area < 0.15:
            rule = 5
        # Rule 6
        elif item.observed.method == "count" and item.observed.max > 1.5 * item.observed.min and item.observed.max > 10:
            rule = 6

        if rule is not None:
            qualified.append((rule, area, idx))

    # Sort by rule priority asc, then box area asc (smaller first)
    qualified.sort(key=lambda x: (x[0], x[1]))
    return [idx for _, _, idx in qualified[:max_crops]]


def merge_zoom(
    base: DetectedItem,
    crop: InspectorOutput | None,
) -> tuple[DetectedItem, list[StaffCheckReason]]:
    """Merges a pass-1 base reading with its pass-2 close-up reading.

    Returns: (merged_item, extra_staff_check_reasons)
    """
    extra_reasons: list[StaffCheckReason] = []

    # 1. No usable crop reading: keep base, lower confidence one level, no extra reasons
    if crop is None or crop.photo_status != "ok" or not crop.items:
        lowered = base.model_copy(update={"confidence": _lower_confidence(base.confidence)})
        return lowered, extra_reasons

    # 2. Pick the crop item: simple name equals base's, preferring largest box
    matched_candidates = []
    for c_item in crop.items:
        if names_match(c_item.name, base.name):
            matched_candidates.append((_box_area(c_item.box_2d), c_item))

    if not matched_candidates:
        # Name mismatch: keep base, set confidence low, add zoom_disagreement
        extra_reasons.append("zoom_disagreement")
        disagreed = base.model_copy(update={"confidence": "low"})
        return disagreed, extra_reasons

    # Pick candidate with largest box
    matched_candidates.sort(key=lambda x: x[0], reverse=True)
    crop_item = matched_candidates[0][1]

    # 3. Merge fields
    # Stage, stage_level, evidence from crop
    stage = crop_item.stage
    stage_level = crop_item.stage_level
    evidence = crop_item.evidence

    # Quantity: if both used method "count", take from crop; otherwise keep base
    if base.observed.method == "count" and crop_item.observed.method == "count":
        observed = crop_item.observed
        sale_min = crop_item.sale_min
        sale_max = crop_item.sale_max
    else:
        observed = base.observed
        sale_min = base.sale_min
        sale_max = base.sale_max

    # Issues: union of both
    seen_issues = list(base.visible_issues)
    for iss in crop_item.visible_issues:
        if iss not in seen_issues:
            seen_issues.append(iss)

    # Worst stage: worse of the two
    worst_stage = _worse_stage(base.worst_stage, crop_item.worst_stage)

    # Check reason: crop's if not empty, else base's
    check_reason = crop_item.check_reason if crop_item.check_reason.strip() else base.check_reason

    # needs_staff_check: either one
    needs_staff_check = base.needs_staff_check or crop_item.needs_staff_check

    # Confidence: crop's, but if stages >= 2 steps apart -> low + zoom_disagreement
    confidence = crop_item.confidence
    if abs(STAGE_ORDER.get(base.stage, 0) - STAGE_ORDER.get(crop_item.stage, 0)) >= 2:
        confidence = "low"
        extra_reasons.append("zoom_disagreement")

    merged = base.model_copy(
        update={
            "stage": stage,
            "stage_level": stage_level,
            "worst_stage": worst_stage,
            "evidence": evidence,
            "observed": observed,
            "sale_min": sale_min,
            "sale_max": sale_max,
            "visible_issues": seen_issues,
            "confidence": confidence,
            "needs_staff_check": needs_staff_check,
            "check_reason": check_reason,
        }
    )

    return merged, extra_reasons
