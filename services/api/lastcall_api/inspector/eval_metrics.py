"""Pure evaluation metric calculation and label matching for Freshness Inspector (Step 6)."""

from pydantic import BaseModel

from lastcall_api.inspector.guardrails import names_match
from lastcall_shared.models import FreshnessResult, ItemAssessment, ProduceStage

STAGES: list[ProduceStage] = ["fresh", "ripening", "overripe", "spoiled", "unsafe"]


class LabelRow(BaseModel):
    filename: str
    split: str = "test"
    photo_kind: str = "normal"
    series_id: str = ""
    seq: int | None = None
    item: str = ""
    grid: str = ""
    expected_stage: str = "fresh"
    acceptable_stages: list[str] = []
    expected_worst_stage: str = ""
    true_count: int | None = None
    true_kg: float | None = None
    notes: str = ""

    def get_expected_worst(self) -> str:
        return self.expected_worst_stage or self.expected_stage


def _name_matches(label_item: str, pred_name: str) -> bool:
    """Checks whether prediction name matches label item (handling ;-separated names)."""
    p = pred_name.lower().strip()
    if not p:
        return False

    variants = [v.strip().lower() for v in label_item.split(";") if v.strip()]
    for var in variants:
        if var in p or p in var:
            return True
        if names_match(var, p):
            return True
    return False


def _candidate_rank(lbl: "LabelRow", item: ItemAssessment) -> tuple[int, float]:
    """Grid match first, then the largest box."""
    grid_match = 1 if lbl.grid and item.grid == lbl.grid else 0
    box_area = (item.position.ymax - item.position.ymin) * (item.position.xmax - item.position.xmin)
    return (grid_match, box_area)


def match_labels_to_predictions(
    labels: list[LabelRow],
    predictions: list[ItemAssessment],
) -> list[tuple[LabelRow, ItemAssessment | None]]:
    """Matches ground truth label rows to predicted ItemAssessments.

    Rule from Step 6:
    - simple names equal, or one contains the other.
    - with several candidates, prefer the one whose grid equals the label's, then largest box.
    - each prediction is used once.
    """
    matched: list[tuple[LabelRow, ItemAssessment | None]] = []
    used_pred_indices: set[int] = set()

    for lbl in labels:
        if not lbl.item.strip():
            # Edge photo label without specific produce
            matched.append((lbl, None))
            continue

        candidates: list[tuple[int, ItemAssessment]] = []
        for idx, pred in enumerate(predictions):
            if idx in used_pred_indices:
                continue
            if _name_matches(lbl.item, pred.name):
                candidates.append((idx, pred))

        if not candidates:
            matched.append((lbl, None))
            continue

        # Sort candidates:
        # 1. grid match (True first, so 1 before 0)
        # 2. box area (largest first)
        candidates.sort(key=lambda c, lbl=lbl: _candidate_rank(lbl, c[1]), reverse=True)
        best_idx, best_pred = candidates[0]
        used_pred_indices.add(best_idx)
        matched.append((lbl, best_pred))

    return matched


def calculate_strict_stage_accuracy(matches: list[tuple[LabelRow, ItemAssessment | None]]) -> float:
    """Calculates accuracy where predicted stage exactly equals expected_stage."""
    evaluable = [m for m in matches if m[0].item.strip() and m[1] is not None]
    if not evaluable:
        return 0.0
    correct = sum(1 for lbl, pred in evaluable if pred.stage == lbl.expected_stage)
    return correct / len(evaluable)


def calculate_lenient_stage_accuracy(matches: list[tuple[LabelRow, ItemAssessment | None]]) -> float:
    """Calculates accuracy where predicted stage matches expected_stage or any acceptable_stages."""
    evaluable = [m for m in matches if m[0].item.strip() and m[1] is not None]
    if not evaluable:
        return 0.0
    correct = 0
    for lbl, pred in evaluable:
        valid_stages = {lbl.expected_stage} | set(lbl.acceptable_stages)
        if pred.stage in valid_stages:
            correct += 1
    return correct / len(evaluable)


def calculate_worst_stage_accuracy(matches: list[tuple[LabelRow, ItemAssessment | None]]) -> float:
    """Calculates accuracy where predicted worst_stage equals expected_worst_stage."""
    evaluable = [m for m in matches if m[0].item.strip() and m[1] is not None]
    if not evaluable:
        return 0.0
    correct = sum(1 for lbl, pred in evaluable if pred.worst_stage == lbl.get_expected_worst())
    return correct / len(evaluable)


def calculate_per_stage_recall(matches: list[tuple[LabelRow, ItemAssessment | None]]) -> dict[str, float]:
    """Calculates recall for each stage: correct / total_with_that_label."""
    evaluable = [m for m in matches if m[0].item.strip()]
    stage_totals: dict[str, int] = {}
    stage_hits: dict[str, int] = {}

    for stage in STAGES:
        stage_totals[stage] = 0
        stage_hits[stage] = 0

    for lbl, pred in evaluable:
        exp = lbl.expected_stage
        if exp in stage_totals:
            stage_totals[exp] += 1
            if pred is not None and pred.stage == exp:
                stage_hits[exp] += 1

    recall = {}
    for stage in STAGES:
        tot = stage_totals[stage]
        recall[stage] = (stage_hits[stage] / tot) if tot > 0 else 1.0
    return recall


def find_critical_misses(matches: list[tuple[LabelRow, ItemAssessment | None]]) -> list[dict]:
    """Finds critical misses: label stage or worst stage is spoiled/unsafe,

    predicted worst_stage is fresh/ripening AND needs_staff_check is False.
    """
    misses = []
    bad_stages = {"spoiled", "unsafe"}
    benign_stages = {"fresh", "ripening"}

    for lbl, pred in matches:
        if not lbl.item.strip():
            continue
        is_bad = lbl.expected_stage in bad_stages or lbl.get_expected_worst() in bad_stages
        if not is_bad:
            continue

        if pred is None:
            # Undetected bad produce is also a critical miss
            misses.append(
                {
                    "filename": lbl.filename,
                    "item": lbl.item,
                    "expected": lbl.expected_stage,
                    "predicted": "not_detected",
                    "staff_check": False,
                    "evidence": "Produce group was not detected by model.",
                }
            )
        elif pred.worst_stage in benign_stages and not pred.needs_staff_check:
            misses.append(
                {
                    "filename": lbl.filename,
                    "item": lbl.item,
                    "expected": lbl.expected_stage,
                    "predicted": pred.worst_stage,
                    "staff_check": pred.needs_staff_check,
                    "evidence": pred.evidence,
                }
            )
    return misses


def find_false_alarms(matches: list[tuple[LabelRow, ItemAssessment | None]]) -> list[dict]:
    """Finds false alarms: fresh/ripening label predicted spoiled/unsafe."""
    alarms = []
    bad_stages = {"spoiled", "unsafe"}
    benign_stages = {"fresh", "ripening"}

    for lbl, pred in matches:
        if not lbl.item.strip() or pred is None:
            continue
        if lbl.expected_stage in benign_stages and lbl.get_expected_worst() in benign_stages:
            if pred.worst_stage in bad_stages or pred.stage in bad_stages:
                alarms.append(
                    {
                        "filename": lbl.filename,
                        "item": lbl.item,
                        "expected": lbl.expected_stage,
                        "predicted": pred.stage,
                        "predicted_worst": pred.worst_stage,
                        "evidence": pred.evidence,
                    }
                )
    return alarms


def calculate_name_accuracy(matches: list[tuple[LabelRow, ItemAssessment | None]]) -> float:
    """Calculates name accuracy over matched groups."""
    evaluable = [m for m in matches if m[0].item.strip() and m[1] is not None]
    if not evaluable:
        return 0.0
    correct = sum(1 for lbl, pred in evaluable if _name_matches(lbl.item, pred.name))
    return correct / len(evaluable)


def calculate_confusion_matrix(matches: list[tuple[LabelRow, ItemAssessment | None]]) -> dict[str, dict[str, int]]:
    """Builds a 5x5 confusion matrix: matrix[expected][predicted]."""
    matrix: dict[str, dict[str, int]] = {exp: {pred: 0 for pred in STAGES} for exp in STAGES}
    for lbl, pred in matches:
        if not lbl.item.strip() or pred is None:
            continue
        exp = lbl.expected_stage
        actual = pred.stage
        if exp in matrix and actual in matrix[exp]:
            matrix[exp][actual] += 1
    return matrix


def check_edge_photo(photo_kind: str, result: FreshnessResult) -> bool:
    """Verifies edge photo rules from Step 6:

    - blurry/dark -> unreadable, or ok with the issue listed and every item low or medium confidence.
    - no_produce / not_produce -> photo_status == 'no_produce'.
    - injection -> instruction_text in photo_issues and items still assessed or no_produce.
    """
    if photo_kind in ("blurry", "dark"):
        if result.photo_status == "unreadable":
            return True
        if result.photo_status == "ok":
            has_issue = any(i in (result.photo_issues or []) for i in ("blurry", "too_dark"))
            all_low_or_med = all(it.confidence_level in ("low", "medium") for it in result.items)
            return has_issue and all_low_or_med
        return False

    if photo_kind in ("no_produce", "not_produce"):
        return result.photo_status == "no_produce"

    if photo_kind == "injection":
        return "instruction_text" in (result.photo_issues or [])

    return True


def calculate_consistency(run1_items: list[ItemAssessment], run2_items: list[ItemAssessment]) -> float:
    """Calculates consistency between runs: share of matched items with same stage and worst stage."""
    if not run1_items or not run2_items:
        return 1.0 if not run1_items and not run2_items else 0.0

    # Match items between run 1 and run 2 by name and spatial proximity
    matches = 0
    consistent = 0

    for it1 in run1_items:
        # Find best candidate in run2
        cand = [it2 for it2 in run2_items if it1.name == it2.name]
        if not cand:
            continue
        # Pick closest center
        c1y = (it1.position.ymin + it1.position.ymax) / 2.0
        c1x = (it1.position.xmin + it1.position.xmax) / 2.0
        cand.sort(
            key=lambda it2: (
                ((it2.position.ymin + it2.position.ymax) / 2.0 - c1y) ** 2
                + ((it2.position.xmin + it2.position.xmax) / 2.0 - c1x) ** 2
            )
        )
        best2 = cand[0]
        matches += 1
        if it1.stage == best2.stage and it1.worst_stage == best2.worst_stage:
            consistent += 1

    return (consistent / matches) if matches > 0 else 1.0
