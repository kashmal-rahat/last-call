import math
from datetime import time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# All timestamps are timezone-aware (e.g. "2026-10-06T18:00:00+05:00") so that
# deadlines and calling hours can be enforced in code without guessing the zone.


# Common literals and types
Unit = Literal["kg", "dozen"]
Currency = Literal["PKR"]
DealType = Literal["sale", "donation"]
Language = Literal["ur", "en", "pa"]

ProduceStage = Literal["fresh", "ripening", "overripe", "spoiled", "unsafe"]
ProduceIssue = Literal[
    "bruising",
    "browning",
    "dark_spots",
    "yellowing",
    "wilting",
    "shrivelling",
    "soft_spots",
    "splitting",
    "leaking",
    "pest_damage",
    "rot",
    "slime",
    "mould",
]
StageLevel = Literal["early", "mid", "late"]
ConfidenceLevel = Literal["high", "medium", "low"]
QuantityMethod = Literal["count", "fill_level"]
PhotoStatus = Literal["ok", "no_produce", "unreadable"]
PhotoIssue = Literal[
    "blurry",
    "too_dark",
    "overexposed",
    "glare",
    "partly_blocked",
    "too_far",
    "instruction_text",
]
StaffCheckReason = Literal[
    "spoiled_or_unsafe",
    "bad_pieces_in_group",
    "low_confidence",
    "unknown_produce",
    "mixed_crate",
    "safety_override",
    "model_flagged",
    "zoom_disagreement",
]

BuyerType = Literal[
    "juice_shop",
    "restaurant",
    "bakery",
    "charity",
    "dairy_farm",
    "other",
]

CallStatus = Literal["pending", "in_progress", "completed"]
CallOutcome = Literal[
    "deal",
    "partial_deal",
    "declined",
    "call_back",
    "wants_photo",
    "wants_manager",
    "do_not_call",
    "no_answer",
]


class CallingHours(BaseModel):
    start: time
    end: time
    timezone: str

    @model_validator(mode="after")
    def validate_calling_hours(self) -> "CallingHours":
        try:
            ZoneInfo(self.timezone)
        except Exception as e:
            raise ValueError(f"Invalid timezone: '{self.timezone}'") from e
        if self.start >= self.end:
            raise ValueError(f"start time ({self.start}) must be before end time ({self.end})")
        return self


class QuantityEstimate(BaseModel):
    unit: Unit
    low: Annotated[float, Field(ge=0)]
    high: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def validate_range(self) -> "QuantityEstimate":
        if self.low > self.high:
            raise ValueError(f"low quantity ({self.low}) cannot exceed high quantity ({self.high})")
        return self


class ConfirmedQuantity(BaseModel):
    unit: Unit
    amount: Annotated[float, Field(gt=0)]
    confirmed_by_staff: bool


class BoundingBox(BaseModel):
    ymin: Annotated[float, Field(ge=0.0, le=1.0)]
    xmin: Annotated[float, Field(ge=0.0, le=1.0)]
    ymax: Annotated[float, Field(ge=0.0, le=1.0)]
    xmax: Annotated[float, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def validate_bounds(self) -> "BoundingBox":
        if self.ymin > self.ymax:
            raise ValueError(f"ymin ({self.ymin}) cannot be greater than ymax ({self.ymax})")
        if self.xmin > self.xmax:
            raise ValueError(f"xmin ({self.xmin}) cannot be greater than xmax ({self.xmax})")
        return self


class ObservedQuantity(BaseModel):
    method: QuantityMethod
    min: Annotated[int, Field(ge=0)]
    max: Annotated[int, Field(ge=0)]  # pieces for "count", percent full for "fill_level"

    @model_validator(mode="after")
    def validate_range(self) -> "ObservedQuantity":
        if self.min > self.max:
            raise ValueError(f"min ({self.min}) cannot exceed max ({self.max})")
        if self.method == "fill_level" and self.max > 100:
            raise ValueError(f"fill_level max ({self.max}) cannot exceed 100")
        return self


class ItemAssessment(BaseModel):
    item_key: str  # Stable key per crate/slot on shelf to match items across photos (R1)
    name: str
    position: BoundingBox
    grid: str  # "top-left" … "bottom-right", derived from the box
    in_mixed_crate: bool = False
    issues: list[ProduceIssue] = Field(default_factory=list)
    evidence: str = ""
    stage: ProduceStage  # typical piece
    stage_level: StageLevel
    worst_stage: ProduceStage  # worst piece; never better than stage
    score: Annotated[float, Field(ge=0.0, le=100.0)]  # computed in code
    change_since_last: float | None = None
    change_note: str | None = None
    observed: ObservedQuantity
    quantity: QuantityEstimate  # kg or dozen (D4)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]  # computed in code from confidence_level
    confidence_level: ConfidenceLevel
    needs_staff_check: bool = False
    staff_check_reasons: list[StaffCheckReason] = Field(default_factory=list)
    check_reason: str = ""  # the model's sentence for staff
    zoomed: bool = False  # True if pass 2 re-read this group

    @model_validator(mode="after")
    def validate_worst_stage(self) -> "ItemAssessment":
        order = {"fresh": 0, "ripening": 1, "overripe": 2, "spoiled": 3, "unsafe": 4}
        if order.get(self.worst_stage, 0) < order.get(self.stage, 0):
            raise ValueError(
                f"worst_stage ({self.worst_stage}) cannot be better than stage ({self.stage})"
            )
        return self


class InspectorMeta(BaseModel):
    model: str
    prompt_version: str
    thinking_level: str
    latency_ms: int  # whole inspection, both passes
    calls: int = 1  # Gemini calls, including retries and zoom calls
    hedges: int = 0  # Number of hedged calls spawned
    zoomed_groups: int = 0
    zoom_failures: int = 0  # crops whose call failed (pass 1 reading kept)
    input_tokens: int = 0  # summed over all calls
    output_tokens: int = 0  # candidates + thoughts, summed
    cached_tokens: int = 0
    thoughts_tokens: int = 0
    candidates_tokens: int = 0


class FreshnessResult(BaseModel):
    schema_version: str = "3.0.0"
    mart_id: str
    shelf_id: str
    inspection_id: str
    previous_inspection_id: str | None = None
    photo_uri: str
    taken_at: AwareDatetime
    photo_status: PhotoStatus = "ok"
    photo_note: str = ""
    photo_issues: list[PhotoIssue] = Field(default_factory=list)
    items: list[ItemAssessment]
    inspector: InspectorMeta | None = None

    @model_validator(mode="after")
    def validate_photo_status(self) -> "FreshnessResult":
        if self.photo_status != "ok" and len(self.items) > 0:
            raise ValueError(f"items must be empty when photo_status is '{self.photo_status}'")
        return self


class AgentBuyerInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: BuyerType


class BuyerInfo(BaseModel):
    buyer_id: str  # Stable ID (e.g. Google Places place_id or test:<slug>) (R2)
    name: str
    type: BuyerType
    phone: str


class MartInfo(BaseModel):
    name: str
    location: str


class AgentDealBrief(BaseModel):
    """The view of DealBrief exposed to the negotiation agent.

    Intentionally excludes floor_price_per_unit, floor_price_unit, buyer.phone,
    and buyer.buyer_id to prevent leakage during prompt compilation or reasoning.
    extra="forbid" means a new DealBrief field breaks agent_view() until someone
    decides whether the agent may see it.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "2.0.0"
    mart_id: str
    batch_id: str
    call_id: str
    deal_type: DealType = "sale"
    item: str
    condition: str
    quantity: Annotated[float, Field(gt=0)]
    quantity_unit: Unit
    quantity_confirmed_by_staff: bool = False
    buyer: AgentBuyerInfo
    opening_price_per_unit: Annotated[int, Field(ge=0)]
    opening_price_unit: Unit
    market_rate_per_unit: Annotated[int, Field(ge=0)] | None = None
    currency: Currency = "PKR"
    pickup_window: str
    pickup_deadline: AwareDatetime
    mart: MartInfo
    payment_terms: str
    language: Language = "ur"
    calling_hours: CallingHours


class DealBrief(BaseModel):
    schema_version: str = "2.0.0"
    mart_id: str
    batch_id: str
    call_id: str
    deal_type: DealType = "sale"
    item: str
    condition: str
    # Staff-confirmed amount, or the low end of the photo estimate when False.
    quantity: Annotated[float, Field(gt=0)]
    quantity_unit: Unit
    quantity_confirmed_by_staff: bool = False
    buyer: BuyerInfo
    opening_price_per_unit: Annotated[int, Field(ge=0)]
    opening_price_unit: Unit
    floor_price_per_unit: Annotated[int, Field(ge=0)]
    floor_price_unit: Unit
    market_rate_per_unit: Annotated[int, Field(ge=0)] | None = None
    currency: Currency = "PKR"
    pickup_window: str
    pickup_deadline: AwareDatetime
    mart: MartInfo
    payment_terms: str
    language: Language = "ur"
    calling_hours: CallingHours

    @model_validator(mode="after")
    def validate_pricing_and_units(self) -> "DealBrief":
        # D4: Price unit must match quantity unit
        if self.opening_price_unit != self.quantity_unit:
            raise ValueError(
                f"Opening price unit ({self.opening_price_unit}) must match quantity unit ({self.quantity_unit})"
            )
        if self.floor_price_unit != self.quantity_unit:
            raise ValueError(
                f"Floor price unit ({self.floor_price_unit}) must match quantity unit ({self.quantity_unit})"
            )
        # Pricing rules based on deal_type (R3: integer PKR prices)
        if self.deal_type == "donation":
            if self.opening_price_per_unit != 0:
                raise ValueError("Opening price must be 0 for a donation")
            if self.floor_price_per_unit != 0:
                raise ValueError("Floor price must be 0 for a donation")
        else:
            if self.opening_price_per_unit <= 0:
                raise ValueError("Opening price must be > 0 for a sale")
            if self.floor_price_per_unit <= 0:
                raise ValueError("Floor price must be > 0 for a sale")
            if self.opening_price_per_unit < self.floor_price_per_unit:
                raise ValueError(
                    f"Opening price ({self.opening_price_per_unit}) cannot be lower than floor price ({self.floor_price_per_unit})"
                )
        # Payment terms cannot be empty
        if not self.payment_terms or not self.payment_terms.strip():
            raise ValueError("Payment terms cannot be empty")
        return self

    def agent_view(self) -> AgentDealBrief:
        dump = self.model_dump(exclude={"floor_price_per_unit", "floor_price_unit"})
        if "buyer" in dump and isinstance(dump["buyer"], dict):
            dump["buyer"].pop("phone", None)
            dump["buyer"].pop("buyer_id", None)  # R2: agent does not need internal buyer_id
        return AgentDealBrief.model_validate(dump)


class TranscriptEntry(BaseModel):
    speaker: str
    text: str
    at: AwareDatetime


class CallResult(BaseModel):
    schema_version: str = "2.0.0"
    call_id: str
    batch_id: str
    mart_id: str
    status: CallStatus
    deal_type: DealType = "sale"
    # Only set once the call is completed (D6).
    outcome: CallOutcome | None = None
    agreed_price_per_unit: Annotated[int, Field(ge=0)] | None = None
    agreed_price_unit: Unit | None = None
    currency: Currency = "PKR"
    agreed_quantity: float | None = None
    agreed_quantity_unit: Unit | None = None
    pickup_time: AwareDatetime | None = None
    callback_at: AwareDatetime | None = None  # R2: Enforced when outcome == "call_back"
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    summary: str = ""
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_deal_outcome(self) -> "CallResult":
        if self.status == "completed" and self.outcome is None:
            raise ValueError("A completed call requires an outcome")
        if self.status != "completed" and self.outcome is not None:
            raise ValueError(f"A call with status '{self.status}' cannot have an outcome yet")

        # R2: validate callback_at timing
        if self.outcome == "call_back":
            if self.callback_at is None:
                raise ValueError("Outcome 'call_back' requires callback_at timestamp")
        else:
            if self.callback_at is not None:
                raise ValueError(f"Outcome '{self.outcome}' cannot have callback_at timestamp")

        # Validate deal terms
        if self.outcome in ("deal", "partial_deal"):
            if self.deal_type == "donation":
                if self.agreed_price_per_unit != 0:
                    raise ValueError("Agreed price must be 0 for a donation deal")
            else:
                if self.agreed_price_per_unit is None or self.agreed_price_per_unit <= 0:
                    raise ValueError(f"Outcome '{self.outcome}' requires agreed_price_per_unit > 0 for a sale")
            if self.agreed_price_unit is None:
                raise ValueError(f"Outcome '{self.outcome}' requires agreed_price_unit")
            if self.agreed_quantity is None or self.agreed_quantity <= 0:
                raise ValueError(f"Outcome '{self.outcome}' requires agreed_quantity > 0")
            if self.agreed_quantity_unit is None:
                raise ValueError(f"Outcome '{self.outcome}' requires agreed_quantity_unit")
            if self.agreed_price_unit != self.agreed_quantity_unit:
                raise ValueError(
                    f"Agreed price unit ({self.agreed_price_unit}) must match agreed quantity unit ({self.agreed_quantity_unit})"
                )
            if self.pickup_time is None:
                raise ValueError(f"Outcome '{self.outcome}' requires agreed pickup_time")
        return self


# ==============================================================================
# Module 2: Negotiator Domain Models, Policy and State
# ==============================================================================

class NegotiationPolicy(BaseModel):
    concession_fractions: list[float] = Field(default_factory=lambda: [0.4, 0.3, 0.2, 0.1])
    round_to: int = 5
    max_call_seconds: int = 300
    wrapup_warning_seconds: int = 30

    @field_validator("concession_fractions")
    @classmethod
    def validate_fractions(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("concession_fractions cannot be empty")
        for x in v:
            if x <= 0:
                raise ValueError(f"Each concession fraction must be > 0, got {x}")
        for i in range(len(v) - 1):
            if v[i] <= v[i + 1]:
                raise ValueError(f"Concession fractions must be strictly decreasing: {v[i]} <= {v[i+1]}")
        total = sum(v)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Concession fractions must sum to 1.0 ± 1e-6, got {total}")
        return v


class NegotiationState(BaseModel):
    ladder: list[int]
    rung: int = 0
    approved_prices: list[int] = Field(default_factory=list)
    last_buyer_offer: int | None = None
    accepted_price: int | None = None
    quoted: bool = False


def round_half_up(val: float) -> int:
    """Rounds half up to nearest integer (e.g. 2.5 -> 3, 2.4 -> 2)."""
    return math.floor(val + 0.5)


def build_ladder(opening: int, floor: int, policy: NegotiationPolicy) -> list[int]:
    """Builds a deterministic price ladder from opening down to floor price.

    Let O = opening, F = floor, gap = O - F.
    - If gap == 0: ladder is [O].
    - Otherwise, for each fraction f, step = max(round_to, round_half_up(gap*f/round_to)*round_to).
      prev = max(F, prev - step). Stop once prev == F.
    - If fractions run out before reaching F, append F.
    """
    gap = opening - floor
    if gap <= 0:
        return [opening]

    ladder = [opening]
    prev = opening
    for f in policy.concession_fractions:
        step = max(policy.round_to, round_half_up((gap * f) / policy.round_to) * policy.round_to)
        prev = max(floor, prev - step)
        ladder.append(prev)
        if prev == floor:
            break

    if ladder[-1] != floor:
        ladder.append(floor)
    return ladder


def init_negotiation(brief: DealBrief, policy: NegotiationPolicy) -> NegotiationState:
    """Initializes the negotiation state with the price ladder and starting approved price."""
    if brief.deal_type == "donation":
        ladder = [0]
        approved = [0]
    else:
        ladder = build_ladder(brief.opening_price_per_unit, brief.floor_price_per_unit, policy)
        approved = [ladder[0]]

    return NegotiationState(
        ladder=ladder,
        rung=0,
        approved_prices=approved,
        last_buyer_offer=None,
        accepted_price=None,
    )


class BatchRecord(BaseModel):
    batch_id: str
    mart_id: str
    inspection_id: str
    item_key: str
    item: str
    unit: Unit
    total_quantity: Annotated[float, Field(gt=0)]
    remaining_quantity: Annotated[float, Field(ge=0)]
    status: Literal[
        "finding_buyers",
        "in_negotiation",
        "partly_sold",
        "sold",
        "awaiting_compost_approval",
        "composted",
        "needs_attention",
    ] = "finding_buyers"
    locked_by_call: str | None = None
    locked_until: AwareDatetime | None = None


class DealRecord(BaseModel):
    mart_id: str
    call_id: str
    batch_id: str
    buyer_id: str
    deal_type: DealType
    price_per_unit: Annotated[int, Field(ge=0)]
    unit: Unit
    quantity: Annotated[float, Field(gt=0)]
    pickup_time: AwareDatetime
    pickup_deadline: AwareDatetime
    payment_terms: str
    status: str = "agreed"
    created_at: AwareDatetime


class OutboxMessage(BaseModel):
    mart_id: str
    kind: Literal["whatsapp_confirmation", "photo"]
    call_id: str
    to_buyer_id: str
    payload: dict[str, Any]
    status: str = "stub_not_sent"


class StaffTask(BaseModel):
    mart_id: str
    kind: Literal["manager_callback"]
    call_id: str
    note: str
    created_at: AwareDatetime


class UsageRecord(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class CallRecord(BaseModel):
    call_id: str
    mart_id: str
    batch_id: str
    brief: DealBrief
    policy: NegotiationPolicy
    negotiation: NegotiationState
    status: CallStatus = "pending"
    session_nonce: str | None = None
    result: CallResult | None = None
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    created_at: AwareDatetime
    expire_at: AwareDatetime | None = None
    usage: UsageRecord = Field(default_factory=UsageRecord)

    @model_validator(mode="after")
    def set_default_expire_at(self) -> "CallRecord":
        if self.expire_at is None:
            self.expire_at = self.created_at + timedelta(days=30)
        return self
