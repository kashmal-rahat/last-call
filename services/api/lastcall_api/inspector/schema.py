"""Output schema returned by Gemini Flash for produce inspection.

Per D30 and Vertex AI guidelines:
- Zero Field constraints and zero Pydantic validators.
- All validation, clamping, safety overrides, and scoring are executed in code.
"""

from pydantic import BaseModel
from lastcall_shared.models import (
    ConfidenceLevel,
    PhotoIssue,
    PhotoStatus,
    ProduceIssue,
    ProduceStage,
    QuantityMethod,
    StageLevel,
    Unit,
)


class ObservedOut(BaseModel):
    method: QuantityMethod
    min: int
    max: int


class DetectedItem(BaseModel):
    name: str
    box_2d: list[int]  # [ymin, xmin, ymax, xmax], 0–1000 scale
    in_mixed_crate: bool
    visible_issues: list[ProduceIssue]
    evidence: str
    stage: ProduceStage
    stage_level: StageLevel
    worst_stage: ProduceStage
    observed: ObservedOut
    sale_unit: Unit
    sale_min: float
    sale_max: float
    confidence: ConfidenceLevel
    needs_staff_check: bool
    check_reason: str


class InspectorOutput(BaseModel):
    photo_status: PhotoStatus
    photo_note: str
    photo_issues: list[PhotoIssue]
    items: list[DetectedItem]
