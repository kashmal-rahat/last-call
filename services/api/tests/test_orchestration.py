"""Unit and contract tests for Module 6 Orchestration: handoff and loop (Milestone 6A Steps 3 & 4)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lastcall_api.orchestration.handoff import (
    NeedsPrice,
    ScoutNotApplicable,
    build_call_record,
    build_step_plans,
    initial_quantity,
    pickup_window,
    time_words,
)
from lastcall_api.orchestration.loop import next_action
from lastcall_shared import buyer_keys
from lastcall_shared.models import (
    BatchAttempt,
    BatchRecord,
    Branch,
    GeoPoint,
    ItemAssessment,
    LadderDecision,
    MartInfo,
    MartRules,
    PriceEntry,
    QuantityEstimate,
    ScoutCandidate,
    ScoutMeta,
    ScoutResult,
    StepPlan,
)

PKT = ZoneInfo("Asia/Karachi")


@pytest.fixture
def demo_rules() -> MartRules:
    return MartRules(
        mart_id="demo_mart",
        mart=MartInfo(name="Demo Mart Johar Town", location="Johar Town, Lahore, Pakistan"),
        timezone="Asia/Karachi",
        closing_time=time(23, 0),
        opening_time=time(9, 0),
        bulk_pickup_hours=2.0,
        bulk_open_pct=60,
        bulk_floor_pct=35,
        feed_open_pct=15,
        feed_floor_pct=5,
        price_round_to=5,
        payment_terms="Cash on pickup",
        city_style="lahore",
        prices=[
            PriceEntry(names=["banana", "kela"], prices={"dozen": 180}),
        ],
        branches=[
            Branch(
                branch_id="johar_town",
                name="Demo Mart Johar Town",
                location="Johar Town, Lahore",
                geo=GeoPoint(lat=31.448, lng=74.270),
            )
        ],
        default_branch_id="johar_town",
    )


def test_build_step_plans_banana_worked_example(demo_rules):
    # banana, dozen, shelf Rs 180, bulk sale with next steps donate and animal feed
    decision = LadderDecision(
        item_key="item_banana_1",
        name="banana",
        unit="dozen",
        shelf_price=180,
        step="bulk_sale",
        allowed_steps=["discount", "bulk_sale", "donate", "animal_feed"],
        opening_price=110,
        floor_price=65,
        buyer_types=["juice_shop", "bakery"],
        next_steps=["donate", "animal_feed"],
        reason="Ripe banana",
        buyer_condition="Ripe bananas, ideal for shakes or baking",
    )

    plans, then_compost = build_step_plans(decision, demo_rules)
    assert then_compost is False
    assert len(plans) == 3

    # 1. bulk sale: opening 110, floor 65, buyers juice shops and bakeries
    assert plans[0].step == "bulk_sale"
    assert plans[0].opening_price == 110
    assert plans[0].floor_price == 65
    assert set(plans[0].buyer_types) == {"juice_shop", "bakery"}

    # 2. donate: 0/0, charities
    assert plans[1].step == "donate"
    assert plans[1].opening_price == 0
    assert plans[1].floor_price == 0
    assert plans[1].buyer_types == ["charity"]

    # 3. animal feed: opening 25, floor 10, dairy farms
    assert plans[2].step == "animal_feed"
    assert plans[2].opening_price == 25
    assert plans[2].floor_price == 10
    assert plans[2].buyer_types == ["dairy_farm"]


def test_build_step_plans_spoiled_produce_with_compost(demo_rules):
    decision = LadderDecision(
        item_key="item_spoiled_1",
        name="banana",
        unit="dozen",
        shelf_price=180,
        step="animal_feed",
        allowed_steps=["animal_feed", "compost"],
        opening_price=25,
        floor_price=10,
        buyer_types=["dairy_farm"],
        next_steps=["compost"],
        reason="Spoiled, safe for cattle",
        buyer_condition="Suitable for cattle feed",
    )

    plans, then_compost = build_step_plans(decision, demo_rules)
    assert then_compost is True
    assert len(plans) == 1
    assert plans[0].step == "animal_feed"
    assert plans[0].opening_price == 25
    assert plans[0].floor_price == 10


def test_build_step_plans_exceptions(demo_rules):
    # keep decision -> ScoutNotApplicable
    decision_keep = LadderDecision(
        item_key="item_k",
        name="banana",
        unit="dozen",
        shelf_price=180,
        step="keep",
        allowed_steps=["keep", "discount"],
        reason="Fresh",
    )
    with pytest.raises(ScoutNotApplicable):
        build_step_plans(decision_keep, demo_rules)

    # needs_price -> NeedsPrice
    decision_needs_price = LadderDecision(
        item_key="item_np",
        name="banana",
        unit="dozen",
        step="bulk_sale",
        allowed_steps=["bulk_sale"],
        needs_price=True,
        reason="Needs price",
    )
    with pytest.raises(NeedsPrice):
        build_step_plans(decision_needs_price, demo_rules)


def _make_item(low: float, high: float) -> ItemAssessment:
    from lastcall_shared.models import BoundingBox, ObservedQuantity

    return ItemAssessment(
        item_key="k1",
        name="banana",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        grid="center",
        stage="fresh",
        stage_level="mid",
        worst_stage="fresh",
        score=90.0,
        confidence=0.9,
        confidence_level="high",
        observed=ObservedQuantity(method="count", min=int(low), max=int(high)),
        quantity=QuantityEstimate(unit="kg", low=low, high=high),
    )


def test_initial_quantity():
    # Low > 0 -> low
    assert initial_quantity(_make_item(15.0, 25.0)) == 15.0
    # Low == 0, High > 0 -> high
    assert initial_quantity(_make_item(0.0, 10.0)) == 10.0
    # Low == 0, High == 0 -> None
    assert initial_quantity(_make_item(0.0, 0.0)) is None
    # Rounded down as people say it (D71)
    assert initial_quantity(_make_item(2.1, 2.9)) == 2.0
    assert initial_quantity(_make_item(0.0, 3.6)) == 3.5


@pytest.mark.parametrize(
    "mart_time,start,deadline",
    [
        ("14:00", "11 14:00", "11 17:00"),  # 3 h from now
        ("13:16", "11 13:15", "11 16:15"),  # rounded down to the quarter hour
        ("19:00:04", "11 19:00", "11 22:00"),  # a call just after a preset's 19:00 reads "7 PM to 10 PM"
        ("20:00", "11 20:00", "11 23:00"),  # 3 h, exactly to closing
        ("20:50", "11 20:45", "11 23:00"),  # rounded, then cut at closing
        ("21:00", "11 21:00", "11 23:00"),  # 2 h left: still today
        ("21:01", "12 09:00", "12 12:00"),  # under 2 h left: tomorrow's opening
        ("23:30", "12 09:00", "12 12:00"),  # closed: tomorrow's opening
        ("03:00", "11 09:00", "11 12:00"),  # before opening: today's opening
    ],
)
def test_pickup_window_table(demo_rules, mart_time, start, deadline):
    """D75: 3 h (the mart's `pickup_window_hours`) from now rounded down to the quarter hour, never past closing."""

    def at(day_time: str) -> datetime:
        day, clock = day_time.split()
        return datetime.fromisoformat(f"2026-10-{day}T{clock}").replace(tzinfo=PKT)

    s, d = pickup_window(demo_rules, at(f"11 {mart_time}"))
    assert (s, d) == (at(start), at(deadline))
    if s.day == 11 and mart_time != "03:00":
        assert s <= at(f"11 {mart_time}") < d  # now is inside the window


def test_pickup_window_words_are_times_people_say(demo_rules):
    """What the agent says and the page shows: quarter hours, and the date when pickup is tomorrow."""
    s, d = pickup_window(demo_rules, datetime(2026, 10, 11, 13, 16, tzinfo=PKT))
    assert f"{time_words(s)} to {time_words(d)}" == "11 October, 1:15 PM to 11 October, 4:15 PM"
    s, d = pickup_window(demo_rules, datetime(2026, 10, 11, 21, 30, tzinfo=PKT))
    assert f"{time_words(s)} to {time_words(d)}" == "12 October, 9 AM to 12 October, 12 PM"


def test_build_call_record(demo_rules):
    now = datetime(2026, 10, 11, 14, 0, 0, tzinfo=PKT)
    branch = demo_rules.branches[0]

    plan = StepPlan(
        step="bulk_sale",
        buyer_types=["juice_shop"],
        opening_price=110,
        floor_price=65,
    )
    batch = BatchRecord(
        batch_id="batch_banana_1",
        mart_id="demo_mart",
        inspection_id="insp_1",
        item_key="item_banana_1",
        item="banana",
        unit="dozen",
        total_quantity=50.0,
        remaining_quantity=35.0,
        quantity_confirmed=True,
    )
    decision = LadderDecision(
        item_key="item_banana_1",
        name="banana",
        unit="dozen",
        shelf_price=180,
        step="bulk_sale",
        allowed_steps=["bulk_sale"],
        opening_price=110,
        floor_price=65,
        buyer_types=["juice_shop"],
        buyer_condition="Slightly bruised, very sweet",
        reason="Bulk clearance",
    )
    candidate = ScoutCandidate(
        rank=1,
        buyer_id="places:ChIJ_real_buyer_lahore",
        place_id="ChIJ_real_buyer_lahore",
        name="Al-Rehman Juice Corner",
        buyer_type="juice_shop",
        phone="+923001234567",
        distance_km=1.2,
        open_now=True,
        fit="likely",
        reason="Juice shop · 1.2 km · open now",
    )

    call_rec = build_call_record(
        batch=batch,
        plan=plan,
        candidate=candidate,
        decision=decision,
        rules=demo_rules,
        branch=branch,
        now=now,
    )

    # 1. Quantity matches batch.remaining_quantity
    assert call_rec.brief.quantity == 35.0
    assert call_rec.brief.quantity_confirmed_by_staff is True

    # 2. Stored brief has NO full E.164 phone digits (+923001234567)
    assert "+923001234567" not in call_rec.brief.buyer.phone
    assert call_rec.brief.buyer.phone == buyer_keys.mask_phone("+923001234567")

    # 3. agent_view() JSON contains neither floor price nor phone digits
    view = call_rec.brief.agent_view()
    view_json = view.model_dump_json()
    assert ":65" not in view_json  # floor price as a value (the random call_id may contain "65")
    assert "1234567" not in view_json  # raw phone digits
    assert not hasattr(view, "floor_price_per_unit")

    # 4. Expiration is 24 h from created_at for places: buyer
    assert call_rec.expire_at == call_rec.created_at + timedelta(hours=24)
    assert call_rec.channel == "browser"
    assert call_rec.city_style == "lahore"

    # Donation brief is 0/0
    plan_don = StepPlan(step="donate", buyer_types=["charity"], opening_price=0, floor_price=0)
    call_don = build_call_record(
        batch=batch,
        plan=plan_don,
        candidate=candidate,
        decision=decision,
        rules=demo_rules,
        branch=branch,
        now=now,
    )
    assert call_don.brief.deal_type == "donation"
    assert call_don.brief.opening_price_per_unit == 0
    assert call_don.brief.floor_price_per_unit == 0


def test_build_call_record_runs_the_pickup_window_on_the_batchs_mart_time(demo_rules):
    """D74: real 02:00, batch at "4 h left" (mart 19:00): pickup today 19:00–22:00; the record stays in real time."""
    real = datetime(2026, 10, 16, 2, 0, tzinfo=PKT)
    batch = BatchRecord(
        batch_id="batch_banana_1",
        mart_id="demo_mart",
        inspection_id="insp_1",
        item_key="item_banana_1",
        item="banana",
        unit="dozen",
        total_quantity=10.0,
        remaining_quantity=10.0,
        clock_offset_s=17 * 3600,
    )
    plan = StepPlan(step="bulk_sale", buyer_types=["juice_shop"], opening_price=110, floor_price=65)
    decision = LadderDecision(
        item_key="item_banana_1",
        name="banana",
        unit="dozen",
        shelf_price=180,
        step="bulk_sale",
        allowed_steps=["bulk_sale"],
        opening_price=110,
        floor_price=65,
        buyer_types=["juice_shop"],
        buyer_condition="Very ripe",
        reason="Overripe: juice shops can use it.",
    )
    candidate = ScoutCandidate(
        rank=1,
        buyer_id="places:ChIJ_a",
        place_id="ChIJ_a",
        name="Sample Juice",
        buyer_type="juice_shop",
        phone="+920000000000",
        distance_km=1.0,
        open_now=None,
        fit="likely",
        reason="Juice shop",
    )

    call = build_call_record(
        batch=batch,
        plan=plan,
        candidate=candidate,
        decision=decision,
        rules=demo_rules,
        branch=demo_rules.branches[0],
        now=real,
    )

    assert call.brief.pickup_deadline == datetime(2026, 10, 16, 22, 0, tzinfo=PKT)
    assert call.brief.pickup_window == "16 October, 7 PM to 16 October, 10 PM"
    assert call.clock_offset_s == 17 * 3600  # the voice service runs the call on the same time
    assert call.created_at == real


def test_next_action_table_driven(demo_rules):
    now = datetime(2026, 10, 11, 14, 0, 0, tzinfo=PKT)
    candidate1 = ScoutCandidate(
        rank=1,
        buyer_id="places:b1",
        place_id="b1",
        name="Buyer 1",
        buyer_type="juice_shop",
        phone="+923001111111",
        distance_km=0.5,
        open_now=True,
        fit="likely",
        reason="Nearby",
    )
    candidate2 = ScoutCandidate(
        rank=2,
        buyer_id="places:b2",
        place_id="b2",
        name="Buyer 2",
        buyer_type="juice_shop",
        phone="+923002222222",
        distance_km=1.0,
        open_now=True,
        fit="likely",
        reason="Nearby",
    )

    plans = [
        StepPlan(step="bulk_sale", buyer_types=["juice_shop"], opening_price=110, floor_price=65),
        StepPlan(step="donate", buyer_types=["charity"], opening_price=0, floor_price=0),
    ]

    scout_bulk = ScoutResult(
        key="scout_k",
        mart_id="demo_mart",
        branch_id="johar_town",
        branch_name="Demo Mart Johar Town",
        inspection_id="insp_1",
        item_key="k",
        step="bulk_sale",
        buyer_types=["juice_shop"],
        buyers=[candidate1, candidate2],
        searched_at=now,
        expire_at=now + timedelta(hours=1),
        meta=ScoutMeta(latency_ms=100),
    )

    # 1. remaining_quantity <= 0 -> sold
    b_sold = BatchRecord(
        batch_id="b_1",
        mart_id="demo_mart",
        inspection_id="i",
        item_key="k",
        item="banana",
        unit="dozen",
        total_quantity=50.0,
        remaining_quantity=0.0,
        plans=plans,
    )
    assert next_action(b_sold, scout_bulk, {}, demo_rules, now).kind == "sold"

    # 2. locked_until > now -> busy
    b_busy = BatchRecord(
        batch_id="b_1",
        mart_id="demo_mart",
        inspection_id="i",
        item_key="k",
        item="banana",
        unit="dozen",
        total_quantity=50.0,
        remaining_quantity=50.0,
        plans=plans,
        locked_until=now + timedelta(minutes=5),
    )
    assert next_action(b_busy, scout_bulk, {}, demo_rules, now).kind == "busy"

    # 3. scout is None -> needs_search
    b_free = BatchRecord(
        batch_id="b_1",
        mart_id="demo_mart",
        inspection_id="i",
        item_key="k",
        item="banana",
        unit="dozen",
        total_quantity=50.0,
        remaining_quantity=50.0,
        plans=plans,
    )
    assert next_action(b_free, None, {}, demo_rules, now).kind == "needs_search"

    # 4. First buyer offered -> call #1
    act_call1 = next_action(b_free, scout_bulk, {}, demo_rules, now)
    assert act_call1.kind == "call"
    assert act_call1.buyer.buyer_id == "places:b1"

    # 5. Pending call doesn't use up buyer
    attempt_pending = BatchAttempt(
        call_id="c_pend",
        buyer_id="places:b1",
        rank=1,
        buyer_type="juice_shop",
        step="bulk_sale",
        created_at=now,
    )
    b_pend = b_free.model_copy(update={"attempts": [attempt_pending]})
    # call_status indicates c_pend is pending
    act_pend = next_action(b_pend, scout_bulk, {"c_pend": "pending"}, demo_rules, now)
    assert act_pend.kind == "call"
    assert act_pend.buyer.buyer_id == "places:b1"

    # 6. After call #1 completed (e.g. partial deal or declined), next buyer #2 is offered
    attempt1 = BatchAttempt(
        call_id="c_1",
        buyer_id="places:b1",
        rank=1,
        buyer_type="juice_shop",
        step="bulk_sale",
        created_at=now,
    )
    b_partial = b_free.model_copy(
        update={
            "remaining_quantity": 30.0,
            "attempts": [attempt1],
        }
    )
    act_call2 = next_action(b_partial, scout_bulk, {"c_1": "completed"}, demo_rules, now)
    assert act_call2.kind == "call"
    assert act_call2.buyer.buyer_id == "places:b2"

    # 7. Both buyers called -> next_step
    attempt2 = BatchAttempt(
        call_id="c_2",
        buyer_id="places:b2",
        rank=2,
        buyer_type="juice_shop",
        step="bulk_sale",
        created_at=now,
    )
    b_exhausted = b_free.model_copy(update={"attempts": [attempt1, attempt2]})
    act_next = next_action(b_exhausted, scout_bulk, {"c_1": "completed", "c_2": "completed"}, demo_rules, now)
    assert act_next.kind == "next_step"
    assert act_next.step == "donate"

    # 8. All steps exhausted and then_compost=True -> compost_approval
    b_compost = b_free.model_copy(
        update={
            "step_index": 1,  # on step "donate" (last step)
            "then_compost": True,
            "attempts": [
                BatchAttempt(
                    call_id="cd", buyer_id="places:charity", rank=1, buyer_type="charity", step="donate", created_at=now
                )
            ],
        }
    )
    scout_donate = ScoutResult(
        key="scout_d",
        mart_id="demo_mart",
        branch_id="johar_town",
        branch_name="Demo Mart Johar Town",
        inspection_id="insp_1",
        item_key="k",
        step="donate",
        buyer_types=["charity"],
        buyers=[
            ScoutCandidate(
                rank=1,
                buyer_id="places:charity",
                place_id="charity",
                name="Dastarkhwan",
                buyer_type="charity",
                phone="+923000000000",
                distance_km=2.0,
                open_now=True,
                fit="likely",
                reason="Charity",
            )
        ],
        searched_at=now,
        expire_at=now + timedelta(hours=1),
        meta=ScoutMeta(latency_ms=100),
    )
    act_compost = next_action(b_compost, scout_donate, {"cd": "completed"}, demo_rules, now)
    assert act_compost.kind == "compost_approval"

    # 9. All steps exhausted and then_compost=False -> no_buyer
    b_no_buyer = b_compost.model_copy(update={"then_compost": False})
    act_no_buyer = next_action(b_no_buyer, scout_donate, {"cd": "completed"}, demo_rules, now)
    assert act_no_buyer.kind == "no_buyer"

    # m1 (a): 5 completed calls in current step with buyers still on the list -> next_step
    scout_with_remaining = scout_bulk.model_copy(
        update={
            "buyers": [
                ScoutCandidate(
                    rank=i,
                    buyer_id=f"places:b{i}",
                    place_id=f"b{i}",
                    name=f"Buyer {i}",
                    buyer_type="juice_shop",
                    phone=f"+92300111111{i}",
                    distance_km=0.5,
                    open_now=True,
                    fit="likely",
                    reason="Nearby",
                )
                for i in range(1, 7)
            ]
        }
    )
    attempts_5 = [
        BatchAttempt(
            call_id=f"c_{i}", buyer_id=f"places:b{i}", rank=i, buyer_type="juice_shop", step="bulk_sale", created_at=now
        )
        for i in range(1, 6)
    ]
    statuses_5 = {f"c_{i}": "completed" for i in range(1, 6)}
    b_5_completed = b_free.model_copy(update={"attempts": attempts_5})
    act_5 = next_action(b_5_completed, scout_with_remaining, statuses_5, demo_rules, now)
    assert act_5.kind == "next_step"
    assert act_5.step == "donate"

    # m1 (b): scout list for another step (donate list while on bulk_sale) -> needs_search
    act_other_step = next_action(b_free, scout_donate, {}, demo_rules, now)
    assert act_other_step.kind == "needs_search"

    # m1 (c): empty buyer list -> next_step
    scout_empty = scout_bulk.model_copy(update={"buyers": []})
    act_empty = next_action(b_free, scout_empty, {}, demo_rules, now)
    assert act_empty.kind == "next_step"
    assert act_empty.step == "donate"
