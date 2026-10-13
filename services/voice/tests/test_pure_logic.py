"""Unit and property tests for negotiator pure logic: pricing, deals, and price guard."""

from datetime import datetime, time, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from lastcall_shared.models import (
    BatchRecord,
    CallingHours,
    DealBrief,
    MartInfo,
    NegotiationPolicy,
    build_ladder,
    init_negotiation,
)
from lastcall_voice.negotiator.deals import validate_deal_terms
from lastcall_voice.negotiator.price_guard import (
    classify,
    fallback_extract_prices,
    find_prices,
    find_spoken_prices,
    has_spoken_price_cue,
)
from lastcall_voice.negotiator.pricing import OfferDecision, verify_offer

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
# Price Guard: v2 Digits-only Test Cases & Fallback
# ==============================================================================

TEST_DIGIT_PRICE_CASES = [
    # Required regression cases
    ("Toh 60 kilo, Rs 140 per kilo, cash on pickup", [140]),
    ("40 darjan Rs 110 per darjan", [110]),
    ("145 rupay kilo", [145]),
    ("Rs 1,200", [1200]),
    ("۱۴۵ روپے", [145]),
    ("60 kilo aam, 3 baje", []),
    # Additional prefix currency cases
    ("Rs 145", [145]),
    ("Rs. 145", [145]),
    ("₨ 145", [145]),
    ("₹110", [110]),
    ("PKR 145", [145]),
    ("Rs. 180 per kilo", [180]),
    ("aap ne Rs 100 kaha", [100]),
    # Suffix rupee words immediately after number
    ("daam 95 rupaye", [95]),
    ("120 rupay", [120]),
    ("۱۲۰ روپے", [120]),
    # Irrelevant numbers without currency markers (MUST NOT match)
    ("60 kilo aam", []),
    ("3:00 baje", []),
    ("20 darjan", []),
    ("call me at 11 am tomorrow", []),
    ("mere paas 5 cartons hain", []),
    ("address street 4 hai", []),
    ("3 din pehle baat hui thi", []),
]


@pytest.mark.parametrize("text,expected", TEST_DIGIT_PRICE_CASES)
def test_price_guard_find_prices(text: str, expected: list[int]):
    extracted = find_prices(text)
    assert extracted == expected, f"Failed for text '{text}': got {extracted}, expected {expected}"
    # Verify backward compatible alias
    assert find_spoken_prices(text) == expected


def test_price_guard_cues_and_fallback():
    # Spoken cues detection
    assert has_spoken_price_cue("aik sau bees rupay darjan") is True
    assert has_spoken_price_cue("hazaar rupay per crate") is True
    assert has_spoken_price_cue("60 kilo aam 3 baje") is False

    # Faked fallback client success
    class FakeGenaiResponse:
        text = '{"agent_offered_prices": [145]}'

    class FakeModels:
        async def generate_content(self, *args, **kwargs):
            return FakeGenaiResponse()

    class FakeClient:
        class aio:
            models = FakeModels()

    import asyncio

    prices, unchecked = asyncio.run(fallback_extract_prices("aik sau pantalees rupay", FakeClient()))
    assert prices == [145]
    assert unchecked is False

    # Faked fallback client error/timeout
    class BrokenModels:
        async def generate_content(self, *args, **kwargs):
            raise RuntimeError("API timeout")

    class BrokenClient:
        class aio:
            models = BrokenModels()

    prices_err, unchecked_err = asyncio.run(fallback_extract_prices("some text", BrokenClient()))
    assert prices_err == []
    assert unchecked_err is True


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


def test_prompt_template_v1_6_male_voice_consistency():
    from lastcall_voice.negotiator.prompt import PROMPT_VERSION, render_instruction

    assert PROMPT_VERSION == "1.6"
    brief = make_test_brief()
    view = brief.agent_view()

    expected_rule = "Never say a price is the last or lowest ('aakhri', 'last', 'final', 'is se neechay nahi', 'mumkin nahi') unless verify_offer returned decision = final."
    qty_rule = "Never agree to more than the available quantity in the brief."
    sauda_rule = "Never say 'sauda pakka' or close as a deal unless confirm_deal returned ok=true."
    repeat_rule = "To repeat a price, call verify_offer with no arguments. Only set buyer_asks_lower=true when the buyer asks for a lower price without naming a number."

    # Male rendering in text mode
    male_text = render_instruction(
        view,
        mode="text",
        agent_gender="male",
        city_style="- Karachi market style",
        now=NOW,
    )
    assert "main bol raha hoon" in male_text
    assert "kar deta hoon" in male_text
    assert "keh raha tha" in male_text
    assert "ka AI assistant hoon" in male_text
    assert "Photo bhej deta hoon" in male_text
    assert "bol rahi" not in male_text
    assert "kar deti" not in male_text
    assert "keh rahi thi" not in male_text
    assert "ki AI assistant" not in male_text
    assert "Text testing mode" in male_text
    assert "Rs 145 per kilo" in male_text
    assert expected_rule in male_text
    assert qty_rule in male_text
    assert sauda_rule in male_text
    assert repeat_rule in male_text

    # Voice mode: also consistently male
    male_voice = render_instruction(
        view,
        mode="voice",
        agent_gender="male",
        city_style="- Karachi market style",
        now=NOW,
    )
    assert "main bol raha hoon" in male_voice
    assert "kar deta hoon" in male_voice
    assert "keh raha tha" in male_voice
    assert "ka AI assistant hoon" in male_voice
    assert "Photo bhej deta hoon" in male_voice
    assert "bol rahi" not in male_voice
    assert "kar deti" not in male_voice
    assert "keh rahi thi" not in male_voice
    assert "ki AI assistant" not in male_voice
    assert "Text testing mode" not in male_voice
    assert "plainly in words" in male_voice
    assert expected_rule in male_voice
    assert qty_rule in male_voice
    assert sauda_rule in male_voice
    assert repeat_rule in male_voice


@pytest.mark.asyncio
async def test_confirm_deal_c0_validations():

    from lastcall_shared.scenarios.loader import build_call
    from lastcall_shared.store import InMemoryStore
    from lastcall_voice.call_context import CallContext, register_context, unregister_context
    from lastcall_voice.negotiator.tools import confirm_deal

    store = InMemoryStore(clock=lambda: NOW)
    brief = make_test_brief(floor=100, opening=150)
    policy = NegotiationPolicy()
    state = init_negotiation(brief, policy)
    state.approved_prices = [150, 130]

    call, batch = build_call("easy_yes", now=NOW)
    call.negotiation = state
    batch.remaining_quantity = 50.0
    await store.create_call(call, batch)
    await store.lock_batch(batch.batch_id, call.call_id, NOW + timedelta(minutes=10))

    ctx = CallContext(store=store, call_id=call.call_id, clock=lambda: NOW)
    register_context(ctx)

    tc = type("MockTC", (), {"state": {"call_id": call.call_id}})()

    # 1. Asking for 60 when 50 is available -> ok: False, available_quantity=50.0, no deal saved
    res_qty = await confirm_deal(
        price_per_unit=130,
        quantity=60.0,
        pickup_time_iso=(NOW + timedelta(hours=2)).isoformat(),
        buyer_confirmed=True,
        tool_context=tc,
    )
    assert res_qty["ok"] is False
    assert res_qty["available_quantity"] == 50.0
    assert any("Only 50" in r for r in res_qty["reasons"])
    assert not ctx.outcome_set
    assert await store.get_deal(call.call_id) is None

    # 2. Naive time (missing timezone) -> ok: False
    res_naive = await confirm_deal(
        price_per_unit=130,
        quantity=40.0,
        pickup_time_iso="2026-10-07T14:00:00",
        buyer_confirmed=True,
        tool_context=tc,
    )
    assert res_naive["ok"] is False
    assert any("ask the buyer for the pickup time again" in r for r in res_naive["reasons"])

    # 3. Past time -> ok: False
    res_past = await confirm_deal(
        price_per_unit=130,
        quantity=40.0,
        pickup_time_iso=(NOW - timedelta(hours=1)).isoformat(),
        buyer_confirmed=True,
        tool_context=tc,
    )
    assert res_past["ok"] is False
    assert any("ask the buyer for the pickup time again" in r for r in res_past["reasons"])

    # 4. Valid confirmation -> ok: True, deal saved
    res_valid = await confirm_deal(
        price_per_unit=150,
        quantity=40.0,
        pickup_time_iso=(NOW + timedelta(hours=2)).isoformat(),
        buyer_confirmed=True,
        tool_context=tc,
    )
    assert res_valid["ok"] is True
    assert ctx.outcome_set
    assert ctx.agreed_quantity == 40.0
    saved_deal = await store.get_deal(call.call_id)
    assert saved_deal is not None
    assert saved_deal.quantity == 40.0

    unregister_context(call.call_id)


@pytest.mark.asyncio
async def test_fresh_state_in_price_guard_c1():
    from lastcall_shared.scenarios.loader import build_call
    from lastcall_shared.store import InMemoryStore
    from lastcall_voice.call_context import CallContext, register_context, unregister_context
    from lastcall_voice.negotiator import price_guard
    from lastcall_voice.negotiator.tools import verify_offer

    store = InMemoryStore(clock=lambda: NOW)
    call, batch = build_call("hard_bargainer", now=NOW)
    await store.create_call(call, batch)

    ctx = CallContext(store=store, call_id=call.call_id, clock=lambda: NOW, negotiation=call.negotiation)
    register_context(ctx)

    tc = type("MockTC", (), {"state": {"call_id": call.call_id}})()

    stale_negotiation = call.negotiation.model_copy(deep=True)

    # Concession 1
    ans1 = await verify_offer(buyer_offer_per_unit=130, tool_context=tc)
    c1_price = ans1["price_per_unit"]

    # Concession 2
    ans2 = await verify_offer(buyer_offer_per_unit=130, tool_context=tc)
    c2_price = ans2["price_per_unit"]

    assert ctx.negotiation is not None
    assert c2_price in ctx.negotiation.approved_prices

    agent_text = f"Main Rs {c2_price} mein de sakta hoon"
    prices = price_guard.find_prices(agent_text)

    # Classifying against initial stale negotiation fails as "unapproved"
    stale_cls = price_guard.classify(
        prices=prices,
        floor=call.brief.floor_price_per_unit,
        approved_prices=stale_negotiation.approved_prices,
        current_price=stale_negotiation.ladder[stale_negotiation.rung],
    )
    assert stale_cls == "unapproved"

    # Classifying against fresh ctx.negotiation succeeds as "ok"
    current_neg = ctx.negotiation
    fresh_cls = price_guard.classify(
        prices=prices,
        floor=call.brief.floor_price_per_unit,
        approved_prices=current_neg.approved_prices,
        current_price=current_neg.ladder[current_neg.rung],
    )
    assert fresh_cls == "ok"

    unregister_context(call.call_id)


@pytest.mark.asyncio
async def test_spoken_price_guard_fallback_c2():
    import asyncio

    from lastcall_voice.negotiator.price_guard import fallback_extract_prices

    class FakeResp:
        def __init__(self, text: str):
            self.text = text

    class FakeModels:
        def __init__(self, text: str, delay: float = 0.0):
            self._text = text
            self._delay = delay

        async def generate_content(self, **kwargs):
            if self._delay:
                await asyncio.sleep(self._delay)
            return FakeResp(self._text)

    class FakeAio:
        def __init__(self, text: str, delay: float = 0.0):
            self.models = FakeModels(text, delay)

    class FakeClient:
        def __init__(self, text: str, delay: float = 0.0):
            self.aio = FakeAio(text, delay)

    # 1. Success case
    fake_client = FakeClient('{"agent_offered_prices": [145]}')
    prices, unchecked = await fallback_extract_prices(
        "ek sau pentalis rupay mein de doonga",
        client=fake_client,
        timeout=1.0,
    )
    assert prices == [145]
    assert unchecked is False

    # 2. Timeout case -> unchecked=True
    timeout_client = FakeClient('{"agent_offered_prices": [145]}', delay=0.5)
    prices, unchecked = await fallback_extract_prices(
        "ek sau pentalis rupay mein de doonga",
        client=timeout_client,
        timeout=0.05,
    )
    assert prices == []
    assert unchecked is True


def test_prompt_h5_cleanups():
    from lastcall_voice.negotiator.prompt import generate_pitch, render_instruction

    # 1. Pitch: donation case uses "aap ke idaare ke liye"
    brief_donation = make_test_brief(deal_type="donation")
    view_donation = brief_donation.agent_view()
    pitch_donation = generate_pitch(view_donation)
    assert "aap ke idaare ke liye bilkul free" in pitch_donation
    assert "shelter" not in pitch_donation

    # 2. Pitch: sale case drops "taaza"
    brief_sale = make_test_brief()
    view_sale = brief_sale.agent_view()
    pitch_sale = generate_pitch(view_sale)
    assert "taaza" not in pitch_sale
    assert "condition Ripe, minor spots" in pitch_sale
    assert "rate bohat munasib hai" in pitch_sale

    # 3. Quality doubt line in prompt uses condition_short
    rendered_sale = render_instruction(view_sale, now=NOW)
    assert "Chhilka thora daagi" not in rendered_sale
    # condition is "Ripe, minor spots" -> condition_short is "ripe"
    assert (
        "Bahar se thora ripe hai, andar se maal theek hai. Photo bhej deta hoon, khud tasalli kar lein."
        in rendered_sale
    )

    # 4. City style mapping
    prompt_lahore = render_instruction(view_sale, city_style="lahore", now=NOW)
    assert "Lahori style: Punjabi-flavoured words where natural" in prompt_lahore
    assert "- lahore" not in prompt_lahore

    prompt_karachi = render_instruction(view_sale, city_style="karachi", now=NOW)
    assert "Karachi market style: polite, friendly, business-minded" in prompt_karachi

    prompt_isb = render_instruction(view_sale, city_style="islamabad", now=NOW)
    assert "Islamabad style: polite, formal and courteous market tone" in prompt_isb

    prompt_custom = render_instruction(view_sale, city_style="- Custom market style", now=NOW)
    assert "- Custom market style" in prompt_custom


def test_input_audio_transcription_vocabulary_h5():
    from lastcall_voice.live_session import (
        BASE_MARKET_VOCABULARY,
        CUSTOM_VOCABULARY,
        build_input_transcription_config,
    )

    assert "Sindhri" not in BASE_MARKET_VOCABULARY
    assert "Sindhri" not in CUSTOM_VOCABULARY

    cfg_default = build_input_transcription_config()
    assert "Sindhri" not in cfg_default.custom_vocabulary

    cfg_sindhri = build_input_transcription_config(item_words=["Sindhri", "Mangoes"])
    assert "Sindhri" in cfg_sindhri.custom_vocabulary
    assert "Mangoes" in cfg_sindhri.custom_vocabulary

    cfg_kinnow = build_input_transcription_config(item_words=["Kinnow", "Oranges"])
    assert "Kinnow" in cfg_kinnow.custom_vocabulary
    assert "Oranges" in cfg_kinnow.custom_vocabulary
    assert "Sindhri" not in cfg_kinnow.custom_vocabulary


def test_verify_offer_no_numeric_offer_ladder_progression():
    brief = make_test_brief(floor=130, opening=180)
    policy = NegotiationPolicy()
    state = init_negotiation(brief, policy)
    # easy_yes ladder: [180, 160, 145, 135, 130]

    # 1. Opening quote
    d0 = verify_offer(state, policy, "sale", None, buyer_asks_lower=False)
    assert d0.decision == "quote"
    assert d0.price_per_unit == 180
    assert state.rung == 0
    assert state.quoted is True

    # 2. Repeated call with no offer and buyer_asks_lower=False -> returns same price, decision "repeat"
    d_rep = verify_offer(state, policy, "sale", None, buyer_asks_lower=False)
    assert d_rep.decision == "repeat"
    assert d_rep.price_per_unit == 180
    assert state.rung == 0

    # 3. Buyer asks to reduce price without number -> moves exactly one rung to 160
    d1 = verify_offer(state, policy, "sale", None, buyer_asks_lower=True)
    assert d1.decision == "counter"
    assert d1.price_per_unit == 160
    assert state.rung == 1
    assert 160 in state.approved_prices

    # 4. Repeat after concession -> returns 160 without moving
    d1_rep = verify_offer(state, policy, "sale", None, buyer_asks_lower=False)
    assert d1_rep.decision == "repeat"
    assert d1_rep.price_per_unit == 160
    assert state.rung == 1

    # 5. Buyer asks lower again -> moves to 145
    d2 = verify_offer(state, policy, "sale", None, buyer_asks_lower=True)
    assert d2.decision == "counter"
    assert d2.price_per_unit == 145
    assert state.rung == 2

    # 6. Buyer agrees at 140 -> accept at 140
    d_acc = verify_offer(state, policy, "sale", 140)
    assert d_acc.decision == "accept"
    assert d_acc.price_per_unit == 140
    assert state.accepted_price == 140

    # 7. After accept, repeated no-offer calls return accepted price 140 without moving
    d_after_acc = verify_offer(state, policy, "sale", None, buyer_asks_lower=False)
    assert d_after_acc.price_per_unit == 140
    assert d_after_acc.decision == "repeat"

    # 8. After accept, even buyer_asks_lower=True returns accepted price 140 without moving
    d_try_lower = verify_offer(state, policy, "sale", None, buyer_asks_lower=True)
    assert d_try_lower.price_per_unit == 140
