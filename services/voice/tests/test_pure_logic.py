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


def test_prompt_template_v1_18_male_voice_consistency():
    from lastcall_voice.negotiator.prompt import PROMPT_VERSION, render_instruction

    assert PROMPT_VERSION == "1.18"
    brief = make_test_brief()
    view = brief.agent_view()

    expected_rule = "Never say a price is the last or lowest ('aakhri', 'last', 'final', 'is se neechay nahi', 'mumkin nahi') unless verify_offer returned decision = final."
    qty_rule = "Never agree to more than the available quantity in the brief."
    sauda_rule = "Never say 'sauda pakka' or close as a deal unless confirm_deal returned ok=true."
    # D76: pickup is by the deadline; the agent states it and never asks for or chooses a time
    pickup_rule = "Say only this deadline: never a start time, and never ask for or choose a pickup time."
    confirm_tool = "confirm_deal(price_per_unit, quantity, buyer_confirmed)"
    # A live call ended with "I have recorded the outcome as declined…" spoken to the buyer
    no_narration = "Never mention your tools, what you recorded or the call's outcome."
    # Short turns (1.9): the opening only asks for a minute; the agent waits after every question
    opening_waits = "Then stop and wait for their answer. Say nothing about the produce yet."
    # Natural sentences, no count (1.13): only "not everything at once" and the stop after a question
    short_turns = "in natural, complete sentences. Say what this moment of the call needs, not everything at once"
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
    assert pickup_rule in male_text and confirm_tool in male_text
    assert no_narration in male_text
    assert "pickup_time_iso" not in male_text

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
    assert no_narration in male_voice
    # 1.14: the laugh is an instruction, not a spoken "Haha"; "jaane dein" (aap), no "yaar" in the lowball line
    assert '"Arey jaane dein, itna to humein bhi wara nahi khaata."' in male_voice
    assert "Haha" not in male_voice and "jaane do yaar" not in male_voice
    # 1.15: Urdu is the product; English only for a buyer speaking English sentences (a judge)
    assert "Language: you call local vendors in Urdu, so open in Urdu." in male_voice
    # 1.17: once in English, every later turn stays English, the pitch included (a live call fell back to Urdu)
    assert "switch to English and stay in English for the rest of the call: every later turn" in male_voice
    assert "stay in Urdu" not in male_voice
    # The language rule comes first in "How to speak", and the tone lines don't pull towards Urdu
    assert male_voice.index("# How to speak\n- Language:") >= 0
    assert "Everyday market language." in male_voice and "everyday Urdu" not in male_voice
    assert "don't repeat the whole introduction" in male_voice
    assert 'Say the unit as "kilo" in Urdu and "kilo" in English' in male_voice
    assert "Punjabi" not in male_voice and '"Ji, main' not in male_voice
    assert "[the price verify_offer returned] ke hisaab se," in male_voice  # 1.18
    assert "[the payment terms]. Pakka?" in male_voice and "cash par" not in male_voice  # from the brief (1.16)
    assert "Current time: 7 October, 12 PM" in male_voice  # no leading zero
    assert '"Soch lein, par maal [the deadline] tak hi ruk sakta hai."' in male_voice
    assert '(In English: "Come on, at that price even we\'d lose money.")' in male_voice
    assert opening_waits in male_voice and short_turns in male_voice
    assert "Do minute milenge? Kaam ki baat hai." in male_voice


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
        buyer_confirmed=True,
        tool_context=tc,
    )
    assert res_qty["ok"] is False
    assert res_qty["available_quantity"] == 50.0
    assert any("Only 50 kilo is available" in r for r in res_qty["reasons"])  # the prompt's unit word
    assert not ctx.outcome_set
    assert await store.get_deal(call.call_id) is None

    # 2. No pickup time is passed: it is the brief's deadline (D76), so there is no time format to get wrong
    # 4. Valid confirmation -> ok: True, deal saved
    res_valid = await confirm_deal(
        price_per_unit=150,
        quantity=40.0,
        buyer_confirmed=True,
        tool_context=tc,
    )
    assert res_valid["ok"] is True
    assert ctx.outcome_set
    assert ctx.agreed_quantity == 40.0
    saved_deal = await store.get_deal(call.call_id)
    assert saved_deal is not None
    assert saved_deal.quantity == 40.0
    assert saved_deal.pickup_time == call.brief.pickup_deadline

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
    assert ans1["unit"] in ("kilo", "darjan")  # the prompt's word, never "kg" / "dozen", so the agent says one word

    # Concession 2
    ans2 = await verify_offer(buyer_offer_per_unit=130, tool_context=tc)
    c2_price = ans2["price_per_unit"]

    assert ctx.negotiation is not None
    assert c1_price in ctx.negotiation.approved_prices
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
    assert pitch_donation == "Humare paas 50 kilo Sindhri Mangoes hain, aap ke idaare ke liye bilkul free."
    assert "shelter" not in pitch_donation

    # 2. Pitch: sale case drops "taaza"
    brief_sale = make_test_brief()
    view_sale = brief_sale.agent_view()
    pitch_sale = generate_pitch(view_sale)
    # One short sentence: what and how much; the condition only when the buyer asks (1.9)
    assert pitch_sale == "Humare paas 50 kilo Sindhri Mangoes hain, rate bohat munasib hai."
    assert "taaza" not in pitch_sale

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
    assert "Lahore market style: warm and friendly" in prompt_lahore
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
    assert cfg_default.language_codes == ["ur", "en"]  # Urdu, and English for judges (D78)
    assert cfg_default.language_hints is None  # the deprecated field is no longer used

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


def test_fallback_config_and_parsing():
    """D68: the spoken-price fallback asks for a schema at thinking LOW with no sampling parameters, drops
    non-positive prices, and treats an answer that breaks the schema as unchecked (never as "no prices")."""
    import asyncio

    from lastcall_voice.negotiator.price_guard import PriceAudit, fallback_extract_prices

    class Resp:
        def __init__(self, text):
            self.text = text

    class Models:
        def __init__(self, text):
            self.text, self.config = text, None

        async def generate_content(self, *, model, contents, config):
            self.config = config
            return Resp(self.text)

    class Client:
        def __init__(self, text):
            self.aio = type("Aio", (), {"models": Models(text)})()

    ok = Client('{"agent_offered_prices": [145, 0, -5]}')
    prices, unchecked = asyncio.run(fallback_extract_prices("ek sau pentalis rupay", ok, model="m"))
    assert (prices, unchecked) == ([145], False)

    cfg = ok.aio.models.config
    assert cfg.response_schema is PriceAudit
    assert cfg.response_mime_type == "application/json"
    assert str(cfg.thinking_config.thinking_level).lower().endswith("low")
    for key in ("temperature", "top_p", "top_k", "seed", "candidate_count", "presence_penalty", "frequency_penalty"):
        assert getattr(cfg, key) is None, key

    for bad in ('{"agent_offered_prices": ["sau"]}', '{"prices": [145]}', "not json"):
        assert asyncio.run(fallback_extract_prices("ek sau rupay", Client(bad), model="m")) == ([], True), bad


def test_prompt_says_the_condition_in_urdu_and_never_reads_the_english():
    """D77: with spoken words in the brief, the pitch and the quality line use them and the English never reaches
    the prompt; feed-only stock is never called fine inside. Briefs without them (scenarios) keep the old lines."""
    from lastcall_shared.condition_words import FEED_ONLY
    from lastcall_voice.negotiator.prompt import generate_pitch, render_instruction

    english = "Very ripe; dark spots, browning. Yellow peels with heavy dark spotting."
    brief = make_test_brief().model_copy(
        update={"condition": english, "condition_spoken": "thoray pakke huay aur daaghi"}
    )
    view = brief.agent_view()
    prompt = render_instruction(view, mode="voice", now=NOW)

    assert generate_pitch(view) == (
        "Humare paas 50 kilo Sindhri Mangoes hain, bas thoray pakke huay aur daaghi hain, "
        "lekin juice aur shake ke liye bilkul theek."
    )
    assert '"Bahar se thoray pakke huay aur daaghi hain, andar se maal theek hai.' in prompt
    assert "dark spots" not in prompt and "Very ripe" not in prompt
    assert "say the Pitching line, or the same in English if the call is in English" in prompt  # 1.17

    feed = render_instruction(
        make_test_brief().model_copy(update={"condition_spoken": FEED_ONLY}).agent_view(), mode="voice", now=NOW
    )
    assert "Yeh maal chaare ke liye hai, khane ke liye nahi." in feed and "andar se maal theek hai" not in feed

    old = render_instruction(make_test_brief().agent_view(), mode="voice", now=NOW)
    assert "Bahar se thora ripe hai, andar se maal theek hai." in old


def test_pitch_frames_the_condition_with_what_it_suits():
    """1.13: every kind of buyer has a use phrase; fresh stock isn't excused, feed-only stock is said plainly."""
    from typing import get_args

    from lastcall_shared.condition_words import FEED_ONLY
    from lastcall_shared.models import BuyerType
    from lastcall_voice.negotiator.prompt import USE_FOR, generate_pitch

    assert set(USE_FOR) == set(get_args(BuyerType))

    def pitch(condition: str, buyer_type: str = "bakery", deal_type: str = "sale") -> str:
        brief = make_test_brief(deal_type=deal_type).model_copy(update={"condition_spoken": condition})
        brief.buyer.type = buyer_type
        return generate_pitch(brief.agent_view())

    assert pitch("thoray pakke huay") == (
        "Humare paas 50 kilo Sindhri Mangoes hain, bas thoray pakke huay hain, lekin bakery items ke liye bilkul theek."
    )
    assert pitch("taaza") == "Humare paas 50 kilo Sindhri Mangoes hain, bilkul taaza."
    assert pitch(FEED_ONLY, "dairy_farm") == (
        "Humare paas 50 kilo Sindhri Mangoes hain, khane ke liye nahi, lekin chaare ke liye bilkul theek."
    )
    assert pitch("thoray pakke huay", "charity", "donation") == (
        "Humare paas 50 kilo Sindhri Mangoes hain, bas thoray pakke huay hain, lekin bilkul khane ke qabil, "
        "aap ke idaare ke liye bilkul free."
    )


def test_prompt_unit_words_follow_the_item_and_the_language():
    """1.15: an item sold by the dozen is "darjan" in Urdu and "dozen" in English; the price example matches."""
    from lastcall_voice.negotiator.prompt import render_instruction

    brief = make_test_brief().model_copy(
        update={"quantity_unit": "dozen", "opening_price_unit": "dozen", "floor_price_unit": "dozen"}
    )
    prompt = render_instruction(brief.agent_view(), mode="voice", now=NOW)
    assert 'Say the unit as "darjan" in Urdu and "dozen" in English' in prompt
    assert 'for example "aik sau bees rupay darjan"' in prompt


def test_spoken_price_cue_in_every_script_the_transcriber_writes():
    """The safety net's trigger also reads Hindi script, which the transcriber sometimes writes for Urdu speech
    (round 57 probe), in either Unicode form of the dotted letter; a price-free sentence doesn't trigger it."""
    import unicodedata

    assert has_spoken_price_cue("Aik sau das rupay darjan")
    assert has_spoken_price_cue("ایک سو دس روپے درجن")
    assert has_spoken_price_cue("एक सौ दस रुपये दर्जन")
    assert has_spoken_price_cue("दो हजार")
    one_char = "दो ह\u095bार"  # the dotted letter as one character (U+095B ज़)
    two_chars = "दो ह\u091c\u093cार"  # ज (U+091C) and a separate dot (U+093C)
    assert one_char != two_chars and unicodedata.normalize("NFC", one_char) == two_chars
    assert has_spoken_price_cue(one_char) and has_spoken_price_cue(two_chars)
    assert not has_spoken_price_cue("सोच लें, माल आज रात दस बजे तक रुक सकता है")
