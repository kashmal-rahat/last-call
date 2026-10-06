"""Pydantic v2 domain models for Last Call."""

from datetime import datetime
from typing import Annotated, Any, Literal
from pydantic import BaseModel, Field, model_validator


# Common literals and types
Unit = Literal["kg", "dozen"]
Currency = Literal["PKR"]

ProduceStage = Literal["fresh", "ripening", "overripe", "spoiled", "unsafe"]
ProduceIssue = Literal["bruising", "browning", "mould", "rot", "wilting", "other"]

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
    value: Annotated[float, Field(ge=0)]
    confirmed_by_staff: bool = False


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


class ItemAssessment(BaseModel):
    name: str
    position: BoundingBox
    stage: ProduceStage
    score: Annotated[float, Field(ge=0.0, le=100.0)]
    change_since_last: float | None = None
    change_note: str | None = None
    issues: list[ProduceIssue] = Field(default_factory=list)
    quantity: QuantityEstimate
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    needs_staff_check: bool = False


class FreshnessResult(BaseModel):
    schema_version: str = "1.0.0"
    mart_id: str
    batch_id: str
    photo_uri: str
    taken_at: datetime
    items: list[ItemAssessment]
    photo_issues: list[str] = Field(default_factory=list)


class BuyerInfo(BaseModel):
    name: str
    type: BuyerType
    phone: str


class MartInfo(BaseModel):
    name: str
    location: str


class AgentDealBrief(BaseModel):
    """The view of DealBrief exposed to the negotiation agent.

    Intentionally excludes floor_price_per_unit and floor_price_unit to prevent
    leakage during prompt compilation or reasoning.
    """
    schema_version: str = "1.0.0"
    mart_id: str
    batch_id: str
    call_id: str
    item: str
    condition: str
    quantity: Annotated[float, Field(gt=0)]
    quantity_unit: Unit
    buyer: BuyerInfo
    opening_price_per_unit: Annotated[float, Field(gt=0)]
    opening_price_unit: Unit
    pickup_window: str
    pickup_deadline: str
    mart: MartInfo
    payment_terms: str
    language: str = "ur"
    calling_hours: str


class DealBrief(BaseModel):
    schema_version: str = "1.0.0"
    mart_id: str
    batch_id: str
    call_id: str
    item: str
    condition: str
    quantity: Annotated[float, Field(gt=0)]
    quantity_unit: Unit
    buyer: BuyerInfo
    opening_price_per_unit: Annotated[float, Field(gt=0)]
    opening_price_unit: Unit
    floor_price_per_unit: Annotated[float, Field(gt=0)]
    floor_price_unit: Unit
    pickup_window: str
    pickup_deadline: str
    mart: MartInfo
    payment_terms: str
    language: str = "ur"
    calling_hours: str

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
        # Opening price must be >= floor price
        if self.opening_price_per_unit < self.floor_price_per_unit:
            raise ValueError(
                f"Opening price ({self.opening_price_per_unit}) cannot be lower than floor price ({self.floor_price_per_unit})"
            )
        # Payment terms cannot be empty
        if not self.payment_terms or not self.payment_terms.strip():
            raise ValueError("Payment terms cannot be empty")
        return self

    def agent_view(self) -> AgentDealBrief:
        return AgentDealBrief(
            schema_version=self.schema_version,
            mart_id=self.mart_id,
            batch_id=self.batch_id,
            call_id=self.call_id,
            item=self.item,
            condition=self.condition,
            quantity=self.quantity,
            quantity_unit=self.quantity_unit,
            buyer=self.buyer,
            opening_price_per_unit=self.opening_price_per_unit,
            opening_price_unit=self.opening_price_unit,
            pickup_window=self.pickup_window,
            pickup_deadline=self.pickup_deadline,
            mart=self.mart,
            payment_terms=self.payment_terms,
            language=self.language,
            calling_hours=self.calling_hours,
        )


class TranscriptEntry(BaseModel):
    speaker: str
    text: str
    at: str


class CallResult(BaseModel):
    schema_version: str = "1.0.0"
    call_id: str
    batch_id: str
    mart_id: str
    status: CallStatus
    outcome: CallOutcome
    agreed_price_per_unit: float | None = None
    agreed_price_unit: Unit | None = None
    agreed_quantity: float | None = None
    agreed_quantity_unit: Unit | None = None
    pickup_time: str | None = None
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    summary: str = ""
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_deal_outcome(self) -> "CallResult":
        if self.outcome in ("deal", "partial_deal"):
            if self.agreed_price_per_unit is None or self.agreed_price_per_unit <= 0:
                raise ValueError(f"Outcome '{self.outcome}' requires agreed_price_per_unit > 0")
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
            if not self.pickup_time or not self.pickup_time.strip():
                raise ValueError(f"Outcome '{self.outcome}' requires agreed pickup_time")
        return self
