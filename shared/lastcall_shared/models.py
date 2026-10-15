import math
from datetime import time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from lastcall_shared import ids
from lastcall_shared.buyer_keys import mask_phone

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
            raise ValueError(f"worst_stage ({self.worst_stage}) cannot be better than stage ({self.stage})")
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
    from_cache: bool = False
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
    photo_stored: bool = False  # D62: the shelf photo is kept (1 day) so the agent can send item crops

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
                raise ValueError(f"Concession fractions must be strictly decreasing: {v[i]} <= {v[i + 1]}")
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


ScoutStep = Literal["bulk_sale", "donate", "animal_feed"]  # ladder steps that need buyers


class StepPlan(BaseModel):
    step: ScoutStep
    buyer_types: list[BuyerType]
    opening_price: int  # 0 for donate
    floor_price: int  # 0 for donate; internal, never sent to the agent or the page's agent view


class BatchAttempt(BaseModel):
    call_id: str
    buyer_id: str  # "places:<id>"; no name or phone (D48)
    rank: int
    buyer_type: BuyerType
    step: ScoutStep
    created_at: AwareDatetime


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
    branch_id: str | None = None
    plans: list[StepPlan] = Field(default_factory=list)
    step_index: int = 0
    then_compost: bool = False
    quantity_confirmed: bool = False
    attempts: list[BatchAttempt] = Field(default_factory=list)
    created_at: AwareDatetime | None = None


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
    channel: Literal["browser", "phone"] = "browser"
    city_style: str | None = None  # None → CITY_STYLE env (scenarios unchanged)

    @model_validator(mode="after")
    def set_default_expire_at(self) -> "CallRecord":
        if self.expire_at is None:
            self.expire_at = self.created_at + timedelta(days=30)
        return self


# Module 3 (Ladder) models and types
LadderStep = Literal["keep", "discount", "bulk_sale", "donate", "animal_feed", "compost"]
ShelfLifeBand = Literal["under_6h", "6_to_24h", "1_to_3_days", "over_3_days"]
StaffAction = Literal[
    "remove_bad_pieces",
    "check_before_off_shelf",
    "identify_item",
    "enter_shelf_price",
    "approve_compost",
]


class StageProfile(BaseModel):
    sellable_for: ShelfLifeBand  # how long produce at this stage still sells to shoppers
    juice_shop: bool
    restaurant: bool
    bakery: bool
    charity: bool  # still good for people to eat


class ProduceProfile(BaseModel):
    key: str  # gemini: f"{produce_key(name)}__v{PROFILE_PROMPT_VERSION}"; manager: f"{produce_key(name)}__manager"
    name: str
    note: str  # one line, e.g. "Leafy green; wilts within hours in heat"
    fresh: StageProfile
    ripening: StageProfile
    overripe: StageProfile
    spoiled_ok_for_cattle: bool  # spoiled but not mouldy: safe as cattle feed?
    overripe_ok_for_cattle: bool
    source: Literal["gemini", "manager", "fallback"]
    model: str = ""
    prompt_version: str
    created_at: AwareDatetime
    votes: int = 1
    uncertain_fields: list[str] = Field(default_factory=list)


class PriceEntry(BaseModel):
    names: list[str]  # the English names the Inspector may use for this produce, e.g. ["okra", "lady finger"]
    prices: dict[Unit, int]  # PKR per unit, each > 0

    @field_validator("prices")
    @classmethod
    def validate_prices(cls, v: dict[Unit, int]) -> dict[Unit, int]:
        for unit, price in v.items():
            if price <= 0:
                raise ValueError(f"Price for unit '{unit}' must be > 0, got {price}")
        return v


class GeoPoint(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]


class Branch(BaseModel):
    branch_id: str  # ^[a-z0-9_]{1,30}$, e.g. "johar_town"
    name: str  # "Demo Mart Johar Town" (no retailer brand)
    location: str  # "Johar Town, Lahore, Pakistan" (becomes DealBrief.mart.location in Module 6)
    geo: GeoPoint

    @field_validator("branch_id")
    @classmethod
    def validate_branch_id(cls, v: str) -> str:
        if not ids.BRANCH_ID.match(v):
            raise ValueError(f"branch_id must match '^[a-z0-9_]{{1,30}}$', got '{v}'")
        return v


class MartRules(BaseModel):
    mart_id: str
    mart: MartInfo
    timezone: str = "Asia/Karachi"
    closing_time: time  # 23:00
    opening_time: time = time(9, 0)  # 09:00
    bulk_pickup_hours: float = 2.0  # hours needed for buyer pickup before closing
    discount_window_hours: float = 6  # discounts start at most this many hours before closing
    max_discount_pct: int = 40
    min_discount_pct: int = 10
    bulk_open_pct: int = 60  # opening = shelf × 60%
    bulk_floor_pct: int = 35
    feed_open_pct: int = 15
    feed_floor_pct: int = 5
    price_round_to: int = 5
    note: str = ""  # e.g. "Demo prices, not live market rates"
    prices: list[PriceEntry]

    # Module 4 Scout configuration
    branches: list[Branch] = Field(default_factory=list)
    default_branch_id: str | None = None
    scout_radius_km: float = 10.0
    buyer_cooldown_hours: float = 24.0
    scout_max_buyers: int = 5

    # Module 6 Orchestration configuration
    payment_terms: str = "Cash on pickup"
    calling_hours: CallingHours = Field(
        default_factory=lambda: CallingHours(start=time(9, 0), end=time(21, 0), timezone="Asia/Karachi")
    )
    city_style: Literal["karachi", "lahore", "islamabad"] = "karachi"

    def branch(self, branch_id: str | None = None) -> Branch:
        target_id = branch_id if branch_id is not None else self.default_branch_id
        if not target_id:
            raise KeyError("No branch specified and no default branch configured")
        for b in self.branches:
            if b.branch_id == target_id:
                return b
        raise KeyError(f"Branch '{target_id}' not found")

    @property
    def overnight_hours(self) -> float:
        """Hours from closing_time to next opening_time."""
        close_m = self.closing_time.hour * 60 + self.closing_time.minute
        open_m = self.opening_time.hour * 60 + self.opening_time.minute
        return ((open_m - close_m) % (24 * 60)) / 60.0

    @field_validator("prices")
    @classmethod
    def validate_unique_price_names(cls, v: list[PriceEntry]) -> list[PriceEntry]:
        """A name may appear under one entry only, or its price would depend on the file's order.

        Compared the way the price lookup matches names: ignoring case, spaces and a plural "s" or "es".
        """
        seen: set[str] = set()
        for entry in v:
            for name in entry.names:
                key = "".join(ch for ch in name.lower() if ch.isalnum())
                forms = {key, key.removesuffix("s"), key.removesuffix("es")} - {""}
                if not forms or forms & seen:
                    raise ValueError(f"Price name '{name}' is empty or listed more than once")
                seen |= forms
        return v

    @model_validator(mode="after")
    def validate_rules(self) -> "MartRules":
        try:
            ZoneInfo(self.timezone)
        except Exception as e:
            raise ValueError(f"Invalid timezone: '{self.timezone}'") from e

        if self.opening_time == self.closing_time:
            raise ValueError("opening_time and closing_time cannot be equal")

        if not (0.0 <= self.bulk_pickup_hours <= 6.0):
            raise ValueError(f"bulk_pickup_hours must be between 0 and 6, got {self.bulk_pickup_hours}")

        for name, val in [
            ("max_discount_pct", self.max_discount_pct),
            ("min_discount_pct", self.min_discount_pct),
            ("bulk_open_pct", self.bulk_open_pct),
            ("bulk_floor_pct", self.bulk_floor_pct),
            ("feed_open_pct", self.feed_open_pct),
            ("feed_floor_pct", self.feed_floor_pct),
        ]:
            if val < 1 or val > 100:
                raise ValueError(f"{name} must be between 1 and 100, got {val}")

        if self.min_discount_pct > self.max_discount_pct:
            raise ValueError(
                f"min_discount_pct ({self.min_discount_pct}) cannot exceed max_discount_pct ({self.max_discount_pct})"
            )

        if self.bulk_floor_pct >= self.bulk_open_pct:
            raise ValueError(
                f"bulk_floor_pct ({self.bulk_floor_pct}) must be less than bulk_open_pct ({self.bulk_open_pct})"
            )

        if self.feed_floor_pct >= self.feed_open_pct:
            raise ValueError(
                f"feed_floor_pct ({self.feed_floor_pct}) must be less than feed_open_pct ({self.feed_open_pct})"
            )

        if not (0.5 <= self.scout_radius_km <= 10.0):
            raise ValueError(f"scout_radius_km must be between 0.5 and 10.0, got {self.scout_radius_km}")

        if not (0.0 <= self.buyer_cooldown_hours <= 168.0):
            raise ValueError(f"buyer_cooldown_hours must be between 0.0 and 168.0, got {self.buyer_cooldown_hours}")

        if not (1 <= self.scout_max_buyers <= 10):
            raise ValueError(f"scout_max_buyers must be between 1 and 10, got {self.scout_max_buyers}")

        if len(self.branches) > 10:
            raise ValueError(f"At most 10 branches allowed, got {len(self.branches)}")

        branch_ids = [b.branch_id for b in self.branches]
        if len(set(branch_ids)) != len(branch_ids):
            raise ValueError("Duplicate branch_id found in branches")

        if self.branches:
            if not self.default_branch_id:
                raise ValueError("default_branch_id must be set when branches is non-empty")
            if self.default_branch_id not in branch_ids:
                raise ValueError(f"default_branch_id '{self.default_branch_id}' not found in branches")

        return self


class LadderDecision(BaseModel):
    item_key: str
    name: str
    step: LadderStep
    allowed_steps: list[LadderStep]
    next_steps: list[LadderStep] = []
    unit: Unit
    sellable_hours: float | None = None
    shelf_price: int | None = None
    discount_pct: int | None = None
    discounted_price: int | None = None
    opening_price: int | None = None  # bulk_sale, animal_feed
    floor_price: int | None = None  # internal; never given to buyer-facing agents
    buyer_types: list[BuyerType] = []
    buyer_condition: str = ""  # becomes DealBrief.condition in Module 6
    offer_quantity: float | None = None  # steps with buyers: the amount offered unless staff enter one (D71)
    reason: str
    staff_actions: list[StaffAction] = []
    on_hold: bool = False
    needs_approval: bool = False
    needs_price: bool = False
    recheck_next_photo: bool = False
    profile_key: str | None = None
    profile_source: Literal["gemini", "manager", "fallback"] | None = None
    profile_votes: int | None = None
    profile_uncertain_fields: list[str] = []

    @model_validator(mode="after")
    def validate_decision(self) -> "LadderDecision":
        if self.step not in self.allowed_steps:
            raise ValueError(f"step '{self.step}' is not in allowed_steps {self.allowed_steps}")

        if self.opening_price is not None and self.floor_price is not None:
            if self.opening_price < self.floor_price:
                raise ValueError(
                    f"opening_price ({self.opening_price}) cannot be below floor_price ({self.floor_price})"
                )

        if self.step != "discount":
            if self.discount_pct is not None or self.discounted_price is not None:
                raise ValueError(
                    f"discount_pct and discounted_price only allowed when step == 'discount', got step '{self.step}'"
                )

        if self.step == "donate":
            if any(
                p is not None for p in [self.discount_pct, self.discounted_price, self.opening_price, self.floor_price]
            ):
                raise ValueError("donate step has no prices")

        return self


class LadderMeta(BaseModel):
    latency_ms: int
    profiles_used: int
    profiles_generated: int = 0
    profile_calls: int = 0
    fallback_profiles: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class LadderResult(BaseModel):
    schema_version: str = "1.0.0"
    mart_id: str
    inspection_id: str
    decided_at: AwareDatetime
    hours_until_closing: float
    decisions: list[LadderDecision]
    meta: LadderMeta


# ==============================================================================
# Module 4: Scout Domain Models and Types
# ==============================================================================

# ScoutStep defined above with StepPlan and BatchRecord
BuyerFit = Literal["likely", "possible", "unlikely"]
SkipReason = Literal[
    "not_operational",
    "too_far",
    "no_phone",
    "do_not_call",
    "cooldown",
    "duplicate_phone",
    "unlikely_fit",
]  # "closed now" is a rank, not a skip (D50)


class BuyerHistory(BaseModel):  # our own data; no Places content (D48)
    mart_id: str
    buyer_id: str  # "places:<place_id>"
    place_id: str
    calls: int = 0
    deals: int = 0
    last_called_at: AwareDatetime | None = None
    last_outcome: CallOutcome | None = None
    last_deal_at: AwareDatetime | None = None
    last_deal_price: int | None = None
    last_deal_unit: Unit | None = None


class ScoutCandidate(BaseModel):
    rank: int  # 1-based
    buyer_id: str  # "places:<place_id>"
    place_id: str
    name: str  # sanitised: control chars removed, ≤ 80 chars
    buyer_type: BuyerType  # the searched type it matched
    primary_type: str | None = None
    phone: str  # E.164, internal; never in API responses
    distance_km: float  # 1 decimal
    open_now: bool | None = None  # None = hours unknown; False = closed now (kept, ranked lower)
    maps_uri: str | None = None
    fit: BuyerFit
    fit_why: str = ""  # Gemini, ≤ 100 chars
    past_deals: int = 0
    last_deal_at: AwareDatetime | None = None
    reason: str  # facts line built in code

    def to_buyer_info(self) -> BuyerInfo:
        return BuyerInfo(
            buyer_id=self.buyer_id,
            name=self.name,
            type=self.buyer_type,
            phone=self.phone,
        )

    def public_view(self) -> dict:
        d = self.model_dump(mode="json")
        d.pop("phone", None)
        d["phone_masked"] = mask_phone(self.phone)
        return d


class ScreenedOut(BaseModel):  # shown to judges: what Gemini excluded and why
    name: str  # sanitised
    buyer_type: BuyerType  # the type it was searched as
    distance_km: float
    why: str  # Gemini's reason, ≤ 100 chars


class ScoutMeta(BaseModel):
    latency_ms: int
    places_requests: int = 0
    places_results: int = 0
    failed_searches: list[BuyerType] = Field(default_factory=list)
    fit_calls: int = 0
    fit_fallback: bool = False
    fit_prompt_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reused: bool = False


class ScoutResult(BaseModel):
    schema_version: str = "1.0.0"
    key: str  # f"{inspection_id}__{item_key}__{branch_id}" (= Module 6 batch ID + branch ID)
    mart_id: str
    inspection_id: str
    item_key: str
    branch_id: str  # the search centre; reuse requires the same branch
    branch_name: str
    step: ScoutStep
    buyer_types: list[BuyerType]
    searched_at: AwareDatetime
    expire_at: AwareDatetime  # searched_at + SCOUT_LIST_TTL (1 h): reused until then, unusable after, then Firestore TTL deletes it
    buyers: list[ScoutCandidate] = Field(default_factory=list)  # ≤ scout_max_buyers
    skipped: dict[SkipReason, int] = Field(default_factory=dict)
    screened_out: list[ScreenedOut] = Field(
        default_factory=list
    )  # up to 10 businesses Gemini rated unlikely, nearest first (no phone, no place ID)
    meta: ScoutMeta
    attribution: str = "Google Maps"

    def public_view(self) -> dict:
        d = self.model_dump(mode="json")
        d["buyers"] = [b.public_view() for b in self.buyers]
        return d
