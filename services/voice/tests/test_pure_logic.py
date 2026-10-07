"""Unit and property tests for negotiator pure logic: pricing, deals, and price guard."""

from datetime import datetime, time, timedelta, timezone
import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

from lastcall_shared.models import (
    AgentDealBrief,
    BatchRecord,
    CallingHours,
    DealBrief,
    MartInfo,
    NegotiationPolicy,
    NegotiationState,
    build_ladder,
    init_negotiation,
)
from lastcall_voice.negotiator.pricing import OfferDecision, verify_offer
from lastcall_voice.negotiator.deals import validate_deal_terms
from lastcall_voice.negotiator.price_guard import classify, find_spoken_prices

PKT = timezone(timedelta(hours=5))
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=PKT)


def make_test_brief(floor: int = 120, opening: int = 180, deal_type: str = "sale") -> DealBrief:
    return DealBrief(
        mart_id="mart_khi_01",
        batch_id="batch_01",
        call_id="call_01",
        deal_type=deal_type,
        item="Sindhri Mangoes",
        condition="Ripe, minor spots",
        quantity=50.0,
        quantity_unit="kg",
        quantity_confirmed_by_staff=True,
        buyer={"buyer_id": "test:b1", "name": "Al Madina Juice", "type": "juice_shop", "phone": "+923001234567"},
        opening_price_per_unit=opening if deal_type == "sale" else 0,
        opening_price_unit="kg",
        floor_price_per_unit=floor if deal_type == "sale" else 0,
        floor_price_unit="kg",
        market_rate_per_unit=200 if deal_type == "sale" else None,
        pickup_window="2:00 PM to 6:00 PM",
        pickup_deadline=NOW + timedelta(hours=6),
        mart=MartInfo(name="Metro Mart", location="Gulshan-e-Iqbal, Karachi"),
        payment_terms="Cash on collection",
        calling_hours=CallingHours(start=time(9, 0), end=time(21, 0), timezone="Asia/Karachi"),
    )


# ==============================================================================
# Step 3: Shared Models & Floor Isolation Tests
# ==============================================================================

def test_negotiation_policy_validation():
    # Valid default policy
    p = NegotiationPolicy()
    assert len(p.concession_fractions) == 4
    assert sum(p.concession_fractions) == 1.0

    # Non-decreasing fractions rejected
    with pytest.raises(ValidationError):
        NegotiationPolicy(concession_fractions=[0.2, 0.3, 0.3, 0.2])

    # Sum != 1.0 rejected
    with pytest.raises(ValidationError):
        NegotiationPolicy(concession_fractions=[0.5, 0.3, 0.1])


def test_floor_isolation_163_in_agent_view_and_ladder():
    brief = make_test_brief(floor=163, opening=250)
    agent_view = brief.agent_view()
    json_dump = agent_view.model_dump_json()

    # "163" must not be anywhere in agent_view
    assert "163" not in json_dump
    assert not hasattr(agent_view, "floor_price_per_unit")

    # Step through entire ladder; floor 163 appears only at final rung
    policy = NegotiationPolicy()
    state = init_negotiation(brief, policy)

    decisions: list[OfferDecision] = []
    # Quote turn
    d = verify_offer(state, policy, "sale", None)
    decisions.append(d)
    assert "163" not in str(d.model_dump())

    # Counter until final
    while d.decision not in ("final", "accept"):
        d = verify_offer(state, policy, "sale", 100)  # lowball offer
        decisions.append(d)
        if d.decision != "final":
            assert d.price_per_unit > 163
            assert "163" not in str(d.model_dump())

    # Final decision reaches floor 163
    assert d.decision == "final"
    assert d.price_per_unit == 163
    # Result must NOT name the floor
    dump_dict = d.model_dump()
    assert "floor" not in dump_dict
    assert "floor_price" not in dump_dict


# ==============================================================================
# Step 4: Property Tests (Hypothesis)
# ==============================================================================

@given(
    opening=st.integers(min_value=50, max_value=1000),
    floor=st.integers(min_value=10, max_value=500),
    round_to=st.sampled_from([1, 5, 10]),
)
def test_ladder_properties(opening: int, floor: int, round_to: int):
    if opening < floor:
        opening, floor = floor, opening
    policy = NegotiationPolicy(round_to=round_to)
    ladder = build_ladder(opening, floor, policy)

    # 1. Every price is >= F and is an int
    assert all(isinstance(p, int) for p in ladder)
    assert all(p >= floor for p in ladder)

    # 2. Ladder starts at opening and ends at floor
    assert ladder[0] == opening
    assert ladder[-1] == floor

    # 3. Ladder strictly decreases if opening > floor
    if opening > floor:
        for i in range(len(ladder) - 1):
            assert ladder[i] > ladder[i + 1]

        # 4. Each concession step <= one before
        steps = [ladder[i] - ladder[i + 1] for i in range(len(ladder) - 1)]
        for i in range(len(steps) - 1):
            # Because steps are rounded, later steps should not be larger than earlier steps
            assert steps[i + 1] <= steps[i] or abs(steps[i + 1] - steps[i]) <= round_to


def test_verify_offer_decision_transitions():
    brief = make_test_brief(floor=100, opening=150)
    policy = NegotiationPolicy()
    state = init_negotiation(brief, policy)

    # 1. No offer -> quote
    d1 = verify_offer(state, policy, "sale", None)
    assert d1.decision == "quote"
    assert d1.price_per_unit == 150
    assert d1.offer_band == "none"

    # 2. Offer >= current price -> accept at current price
    d2 = verify_offer(state, policy, "sale", 160)
    assert d2.decision == "accept"
    assert d2.price_per_unit == 150
    assert d2.offer_band == "at_or_above"

    # 3. Offer within next rung -> accept at buyer offer
    state = init_negotiation(brief, policy)
    next_price = state.ladder[1]
    d3 = verify_offer(state, policy, "sale", next_price + 2)
    assert d3.decision == "accept"
    assert d3.price_per_unit == next_price + 2

    # 4. Lowball offer -> counter with lowball band
    state = init_negotiation(brief, policy)
    d4 = verify_offer(state, policy, "sale", 50)
    assert d4.decision == "counter"
    assert d4.offer_band == "lowball"

    # 5. Donation mode -> donation at 0
    d_don = verify_offer(state, policy, "donation", 50)
    assert d_don.decision == "donation"
    assert d_don.price_per_unit == 0


# ==============================================================================
# Deals Validation Tests
# ==============================================================================

def test_validate_deal_terms_scenarios():
    brief = make_test_brief(floor=100, opening=150)
    policy = NegotiationPolicy()
    state = init_negotiation(brief, policy)
    state.approved_prices = [150, 130, 110]

    batch = BatchRecord(
        batch_id="batch_01",
        mart_id="mart_khi_01",
        inspection_id="insp_01",
        item_key="crate_1",
        item="Mangoes",
        unit="kg",
        total_quantity=50.0,
        remaining_quantity=50.0,
    )

    # 1. Perfect valid terms
    pickup = NOW + timedelta(hours=2)
    reasons = validate_deal_terms(state, brief, batch, 130, 40.0, pickup, True, NOW)
    assert reasons == []

    # 2. Unapproved price
    reasons = validate_deal_terms(state, brief, batch, 125, 40.0, pickup, True, NOW)
    assert any("not among negotiated" in r for r in reasons)

    # 3. Price below floor
    reasons = validate_deal_terms(state, brief, batch, 90, 40.0, pickup, True, NOW)
    assert any("below minimum floor" in r for r in reasons)

    # 4. Quantity exceeds batch
    reasons = validate_deal_terms(state, brief, batch, 130, 60.0, pickup, True, NOW)
    assert any("exceeds available" in r for r in reasons)

    # 5. Pickup past deadline
    late_pickup = brief.pickup_deadline + timedelta(hours=1)
    reasons = validate_deal_terms(state, brief, batch, 130, 40.0, late_pickup, True, NOW)
    assert any("exceeds pickup deadline" in r for r in reasons)

    # 6. Buyer not confirmed
    reasons = validate_deal_terms(state, brief, batch, 130, 40.0, pickup, False, NOW)
    assert any("not clearly confirmed" in r for r in reasons)


# ==============================================================================
# Price Guard: 30+ Spoken Price Cases & Classification
# ==============================================================================

TEST_SPOKEN_PRICE_CASES = [
    # Roman Urdu plain numbers with price context
    ("aik sau bees rupay darjan", [120]),
    ("rate dedh sau rupay hai", [150]),
    ("paune do sau rupay per kilo", [175]),
    ("sawa sau rupay rate hai", [125]),
    ("dhai sau rupay mein le lo", [250]),
    ("paune teen sau rupaye", [275]),
    ("sau rupay ka rate", [100]),
    ("hazaar rupay per crate", [1000]),
    ("tees rupay kilo", [30]),
    ("chalis rupaye kilo", [40]),
    ("pachaas rupay daam hai", [50]),
    ("athasi rupay per darjan", [88]),
    ("pachaanve rupay ka rate", [95]),
    ("chhiyasi rupay rupaye", [86]),
    ("nabbe rupay daam", [90]),
    ("satattar rupaye", [77]),
    ("ikkees rupay ka darjan", [21]),
    ("chhappan rupaye", [56]),
    ("do sau pachaas rupay", [250]),
    ("aik sau athasi rupay", [188]),
    # Western digits with context
    ("120 rupay", [120]),
    ("rate 150 rs hai", [150]),
    ("Rs. 180 per kilo", [180]),
    ("daam 95 rupaye", [95]),
    # Urdu script with context
    ("ایک سو بیس روپے درجن", [120]),
    ("ڈیڑھ سو روپے ریٹ", [150]),
    ("پونے دو سو روپے", [175]),
    ("سوا سو روپے", [125]),
    ("ڈھائی سو روپے دام", [250]),
    ("پچانوے روپے فی کلو", [95]),
    ("اٹھاسی روپے ریٹ", [88]),
    # Urdu digits with context
    ("۱۲۰ روپے", [120]),
    ("۱۵۰ روپے کلو", [150]),
    # Irrelevant numbers without price context (MUST NOT match)
    ("call me at 11 am tomorrow", []),
    ("mere paas 5 cartons hain", []),
    ("address street 4 hai", []),
    ("3 din pehle baat hui thi", []),
]


@pytest.mark.parametrize("text,expected", TEST_SPOKEN_PRICE_CASES)
def test_price_guard_find_spoken_prices(text: str, expected: list[int]):
    extracted = find_spoken_prices(text)
    assert extracted == expected, f"Failed for text '{text}': got {extracted}, expected {expected}"


def test_price_guard_classify():
    floor = 100
    approved = [150, 130, 110]
    current = 130

    # Below floor
    assert classify([90], floor, approved, current) == "below_floor"
    assert classify([130, 85], floor, approved, current) == "below_floor"

    # Unapproved price (< current and not in approved)
    assert classify([120], floor, approved, current) == "unapproved"

    # Approved price
    assert classify([110], floor, approved, current) == "ok"
    assert classify([130], floor, approved, current) == "ok"

    # Price above current is ok
    assert classify([140], floor, approved, current) == "ok"
    assert classify([160], floor, approved, current) == "ok"
