"""Deal term validation and outcome resolution pure logic."""

from pydantic import AwareDatetime

from lastcall_shared.models import BatchRecord, DealBrief, NegotiationState


def validate_deal_terms(
    state: NegotiationState,
    brief: DealBrief,
    batch: BatchRecord,
    price: int,
    quantity: float,
    pickup_time: AwareDatetime,
    buyer_confirmed: bool,
    now: AwareDatetime,
) -> list[str]:
    """Validates deal terms before saving.

    Returns a list of plain-language reasons. Empty list means terms are valid.
    Rules:
    - Price:
      - Sale: price is in approved_prices and >= floor_price_per_unit.
      - Donation: price is 0.
    - Quantity: 0 < quantity <= batch.remaining_quantity, in the brief's unit.
    - Pickup time: now < pickup_time <= brief.pickup_deadline, and timezone-aware.
    - Confirmation: buyer_confirmed is True.
    """
    reasons: list[str] = []

    # 1. Price validation
    if brief.deal_type == "donation":
        if price != 0:
            reasons.append("Donation price must be 0.")
    else:
        if price < brief.floor_price_per_unit:
            reasons.append("Agreed price cannot be below minimum floor price.")
        elif price not in state.approved_prices:
            reasons.append("Agreed price was not among negotiated and approved prices.")

    # 2. Quantity validation
    if quantity <= 0:
        reasons.append("Quantity must be greater than zero.")
    elif quantity > batch.remaining_quantity:
        reasons.append(
            f"Quantity ({quantity}) exceeds available remaining stock ({batch.remaining_quantity})."
        )

    # 3. Pickup time validation
    if pickup_time.tzinfo is None:
        reasons.append("Pickup time must include timezone information.")
    else:
        if pickup_time <= now:
            reasons.append("Pickup time must be in the future.")
        if pickup_time > brief.pickup_deadline:
            reasons.append(
                f"Pickup time ({pickup_time.isoformat()}) exceeds pickup deadline ({brief.pickup_deadline.isoformat()})."
            )

    # 4. Confirmation check
    if not buyer_confirmed:
        reasons.append("Buyer has not clearly confirmed the deal terms.")

    return reasons
