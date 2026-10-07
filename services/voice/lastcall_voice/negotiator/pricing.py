"""Pricing and offer evaluation pure logic for Module 2 Negotiator."""

from typing import Annotated, Literal
from pydantic import BaseModel, Field
from lastcall_shared.models import DealType, NegotiationPolicy, NegotiationState, Unit, build_ladder


class OfferDecision(BaseModel):
    decision: Literal["quote", "counter", "accept", "final", "donation"]
    price_per_unit: Annotated[int, Field(ge=0)]
    offer_band: Literal["at_or_above", "lowball", "close", "none"]
    unit: Unit | None = None


def verify_offer(
    state: NegotiationState,
    policy: NegotiationPolicy,
    deal_type: DealType,
    buyer_offer: int | None = None,
    unit: Unit | None = None,
) -> OfferDecision:
    """Verifies a buyer offer against the deterministic negotiation ladder.

    Evaluation rules apply in strict order:
    1. Donation -> donation, price 0.
    2. No offer -> quote, at ladder[rung].
    3. Offer at or above our price -> accept, at ladder[rung]. Set accepted_price.
    4. Offer within the next step -> accept, at buyer_offer. Add to approved_prices, set accepted_price.
    5. Next rung available -> counter. rung += 1, add ladder[rung] to approved_prices.
    6. Otherwise -> final, at ladder[rung].

    offer_band:
    - at_or_above if offer >= ladder[rung_before_call]
    - lowball if offer <= 0.5 * ladder[rung_before_call]
    - close otherwise
    - none if no offer
    """
    rung_before = state.rung
    current_price = state.ladder[rung_before]

    if deal_type == "donation":
        decision: Literal["quote", "counter", "accept", "final", "donation"] = "donation"
        price = 0
        state.accepted_price = 0
    elif buyer_offer is None:
        decision = "quote"
        price = current_price
    elif buyer_offer >= current_price:
        decision = "accept"
        price = current_price
        state.accepted_price = price
        if price not in state.approved_prices:
            state.approved_prices.append(price)
    elif (state.rung + 1 < len(state.ladder)) and (buyer_offer >= state.ladder[state.rung + 1]):
        decision = "accept"
        price = buyer_offer
        state.accepted_price = price
        if price not in state.approved_prices:
            state.approved_prices.append(price)
    elif state.rung + 1 < len(state.ladder):
        state.rung += 1
        price = state.ladder[state.rung]
        if price not in state.approved_prices:
            state.approved_prices.append(price)
        if state.rung == len(state.ladder) - 1:
            decision = "final"
        else:
            decision = "counter"
    else:
        decision = "final"
        price = current_price

    state.last_buyer_offer = buyer_offer

    # Calculate offer band relative to current price before call
    if buyer_offer is None:
        offer_band: Literal["at_or_above", "lowball", "close", "none"] = "none"
    elif buyer_offer >= current_price:
        offer_band = "at_or_above"
    elif buyer_offer <= 0.5 * current_price:
        offer_band = "lowball"
    else:
        offer_band = "close"

    return OfferDecision(
        decision=decision,
        price_per_unit=price,
        offer_band=offer_band,
        unit=unit,
    )
