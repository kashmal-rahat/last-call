"""Tests for shared domain models, constraints, and security isolation."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from lastcall_shared.logging_utils import (
    CloudLoggingJsonFormatter,
    mask_phone,
    mask_pii_in_text,
    setup_structured_logging,
)
from lastcall_shared.models import (
    AgentDealBrief,
    BoundingBox,
    CallResult,
    DealBrief,
    FreshnessResult,
    ItemAssessment,
    MartInfo,
    ObservedQuantity,
    QuantityEstimate,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_valid_freshness_from_fixture():
    with open(FIXTURES_DIR / "valid_freshness.json") as f:
        data = json.load(f)
    result = FreshnessResult.model_validate(data)
    assert result.schema_version == "3.0.0"
    assert result.mart_id == "mart_khi_001"
    assert result.inspection_id == "insp_20261006_01"
    assert result.shelf_id == "shelf_produce_01"
    assert result.photo_status == "ok"
    assert result.previous_inspection_id is None
    assert len(result.items) == 1
    assert result.items[0].item_key == "mango_top_left"
    assert result.items[0].grid == "top-left"
    assert result.items[0].stage_level == "mid"
    assert result.items[0].quantity.unit == "kg"
    assert result.items[0].observed.method == "count"
    assert result.items[0].issues == ["bruising"]
    assert result.inspector is not None
    assert result.inspector.model == "gemini-3.8-flash"


def test_item_assessment_worst_stage_cannot_be_better():
    # Valid: worst_stage == stage or worse
    item = ItemAssessment(
        item_key="k1",
        name="banana",
        position=BoundingBox(ymin=0, xmin=0, ymax=0.5, xmax=0.5),
        grid="top-left",
        stage="ripening",
        stage_level="mid",
        worst_stage="spoiled",
        score=69.0,
        observed=ObservedQuantity(method="count", min=10, max=12),
        quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
        confidence=0.9,
        confidence_level="high",
    )
    assert item.worst_stage == "spoiled"

    # Invalid: worst_stage (fresh) is better than stage (ripening)
    with pytest.raises(ValidationError, match="worst_stage .* cannot be better than stage"):
        ItemAssessment(
            item_key="k1",
            name="banana",
            position=BoundingBox(ymin=0, xmin=0, ymax=0.5, xmax=0.5),
            grid="top-left",
            stage="ripening",
            stage_level="mid",
            worst_stage="fresh",
            score=69.0,
            observed=ObservedQuantity(method="count", min=10, max=12),
            quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
            confidence=0.9,
            confidence_level="high",
        )


def test_freshness_result_photo_status_no_produce_items_empty():
    # Invalid: photo_status != 'ok' with items
    item = ItemAssessment(
        item_key="k1",
        name="banana",
        position=BoundingBox(ymin=0, xmin=0, ymax=0.5, xmax=0.5),
        grid="top-left",
        stage="fresh",
        stage_level="early",
        worst_stage="fresh",
        score=95.0,
        observed=ObservedQuantity(method="count", min=10, max=12),
        quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
        confidence=0.9,
        confidence_level="high",
    )
    with pytest.raises(ValidationError, match="items must be empty when photo_status is"):
        FreshnessResult(
            mart_id="m1",
            shelf_id="s1",
            inspection_id="i1",
            photo_uri="upload:sha256:abc",
            taken_at="2026-10-09T10:00:00Z",
            photo_status="no_produce",
            items=[item],
        )

    # Valid: photo_status="no_produce" with empty items
    res = FreshnessResult(
        mart_id="m1",
        shelf_id="s1",
        inspection_id="i1",
        photo_uri="upload:sha256:abc",
        taken_at="2026-10-09T10:00:00Z",
        photo_status="no_produce",
        items=[],
    )
    assert res.photo_status == "no_produce"


def test_observed_quantity_validation():
    # Valid count
    oq = ObservedQuantity(method="count", min=5, max=10)
    assert oq.min == 5

    # Invalid: min > max
    with pytest.raises(ValidationError, match="min .* cannot exceed max"):
        ObservedQuantity(method="count", min=15, max=10)

    # Valid fill level
    oq_fill = ObservedQuantity(method="fill_level", min=20, max=80)
    assert oq_fill.max == 80

    # Invalid: fill level max > 100
    with pytest.raises(ValidationError, match="fill_level max .* cannot exceed 100"):
        ObservedQuantity(method="fill_level", min=20, max=110)


def test_bounding_box_validation():
    # Valid
    box = BoundingBox(ymin=0.1, xmin=0.2, ymax=0.8, xmax=0.9)
    assert box.ymin == 0.1

    # Invalid: inverted ymin/ymax
    with pytest.raises(ValidationError):
        BoundingBox(ymin=0.8, xmin=0.2, ymax=0.1, xmax=0.9)

    # Invalid: out of bounds
    with pytest.raises(ValidationError):
        BoundingBox(ymin=-0.1, xmin=0.2, ymax=0.8, xmax=0.9)


def test_quantity_estimate_validation():
    # Valid
    q = QuantityEstimate(unit="kg", low=10.0, high=20.0)
    assert q.low <= q.high

    # Invalid: low > high
    with pytest.raises(ValidationError):
        QuantityEstimate(unit="kg", low=25.0, high=20.0)

    # Invalid: negative
    with pytest.raises(ValidationError):
        QuantityEstimate(unit="kg", low=-5.0, high=10.0)


def test_deal_brief_from_fixture():
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)
    brief = DealBrief.model_validate(data)
    assert brief.item == "Sindhri Mangoes"
    assert brief.currency == "PKR"
    assert brief.buyer.buyer_id == "test:al_madina_juice"
    assert isinstance(brief.opening_price_per_unit, int)
    assert isinstance(brief.floor_price_per_unit, int)
    assert brief.opening_price_per_unit >= brief.floor_price_per_unit


def test_floor_price_and_buyer_isolation_in_agent_view():
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)
    brief = DealBrief.model_validate(data)
    agent_view = brief.agent_view()

    # Verify attribute does not exist on agent view
    assert not hasattr(agent_view, "floor_price_per_unit")
    assert not hasattr(agent_view, "floor_price_unit")

    # Verify serialized dump does not contain floor price
    dump_dict = agent_view.model_dump()
    assert "floor_price_per_unit" not in dump_dict
    assert "floor_price_unit" not in dump_dict

    # Verify buyer phone and buyer_id are omitted from agent_view (R2 & privacy)
    assert not hasattr(agent_view.buyer, "phone")
    assert not hasattr(agent_view.buyer, "buyer_id")
    assert "phone" not in dump_dict["buyer"]
    assert "buyer_id" not in dump_dict["buyer"]

    json_str = agent_view.model_dump_json()
    assert "floor_price" not in json_str
    assert str(brief.floor_price_per_unit) not in json_str
    assert brief.buyer.phone not in json_str


def test_price_unit_mismatch_rejected():
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)

    # Change price unit to dozen while quantity is kg
    data["opening_price_unit"] = "dozen"
    with pytest.raises(ValidationError, match="must match quantity unit"):
        DealBrief.model_validate(data)

    data["opening_price_unit"] = "kg"
    data["floor_price_unit"] = "dozen"
    with pytest.raises(ValidationError, match="must match quantity unit"):
        DealBrief.model_validate(data)


def test_opening_below_floor_rejected():
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)

    data["opening_price_per_unit"] = 120
    data["floor_price_per_unit"] = 150
    with pytest.raises(ValidationError, match="cannot be lower than floor price"):
        DealBrief.model_validate(data)


def test_empty_payment_terms_rejected():
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)

    data["payment_terms"] = "   "
    with pytest.raises(ValidationError, match="Payment terms cannot be empty"):
        DealBrief.model_validate(data)


def test_call_result_deal_requires_terms():
    # Valid deal from fixture
    with open(FIXTURES_DIR / "valid_call_result.json") as f:
        data = json.load(f)
    res = CallResult.model_validate(data)
    assert res.outcome == "deal"
    assert isinstance(res.agreed_price_per_unit, int)

    # Incomplete deal: missing pickup time
    bad_data = dict(data)
    bad_data["pickup_time"] = None
    with pytest.raises(ValidationError, match="requires agreed pickup_time"):
        CallResult.model_validate(bad_data)

    # Incomplete deal: missing agreed price
    bad_data2 = dict(data)
    bad_data2["agreed_price_per_unit"] = None
    with pytest.raises(ValidationError, match="agreed_price_per_unit > 0"):
        CallResult.model_validate(bad_data2)


def test_call_result_declined_allows_no_terms():
    call = CallResult(
        call_id="call_999",
        batch_id="batch_01",
        mart_id="mart_01",
        status="completed",
        outcome="declined",
        summary="Buyer declined the offer due to existing stock.",
    )
    assert call.outcome == "declined"
    assert call.agreed_price_per_unit is None


def test_call_result_callback_at_enforcement():
    # 1. outcome == "call_back" requires callback_at
    with pytest.raises(ValidationError, match="requires callback_at timestamp"):
        CallResult(
            call_id="call_cb_001",
            batch_id="batch_01",
            mart_id="mart_01",
            status="completed",
            outcome="call_back",
            callback_at=None,
        )

    # 2. outcome == "call_back" with valid callback_at passes
    cb_valid = CallResult(
        call_id="call_cb_002",
        batch_id="batch_01",
        mart_id="mart_01",
        status="completed",
        outcome="call_back",
        callback_at="2026-10-07T15:00:00+05:00",
    )
    assert cb_valid.outcome == "call_back"
    assert cb_valid.callback_at is not None

    # 3. outcome != "call_back" cannot have callback_at
    with pytest.raises(ValidationError, match="cannot have callback_at timestamp"):
        CallResult(
            call_id="call_cb_003",
            batch_id="batch_01",
            mart_id="mart_01",
            status="completed",
            outcome="declined",
            callback_at="2026-10-07T15:00:00+05:00",
        )


def test_call_result_status_outcome_separation():
    # 1. In-progress call without outcome is valid (D6)
    in_prog = CallResult(
        call_id="call_101",
        batch_id="batch_01",
        mart_id="mart_01",
        status="in_progress",
    )
    assert in_prog.status == "in_progress"
    assert in_prog.outcome is None

    # 2. In-progress call with an outcome is rejected
    with pytest.raises(ValidationError, match="cannot have an outcome yet"):
        CallResult(
            call_id="call_102",
            batch_id="batch_01",
            mart_id="mart_01",
            status="in_progress",
            outcome="declined",
        )

    # 3. Completed call without an outcome is rejected
    with pytest.raises(ValidationError, match="completed call requires an outcome"):
        CallResult(
            call_id="call_103",
            batch_id="batch_01",
            mart_id="mart_01",
            status="completed",
            outcome=None,
        )


def test_deal_brief_staff_confirmation_and_agent_view_forbid():
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)

    data["quantity_confirmed_by_staff"] = True
    brief = DealBrief.model_validate(data)
    assert brief.quantity_confirmed_by_staff is True

    agent_view = brief.agent_view()
    assert agent_view.quantity_confirmed_by_staff is True

    # Extra attributes are forbidden on AgentDealBrief
    agent_dict = agent_view.model_dump()
    agent_dict["leaked_internal_metric"] = 123
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentDealBrief.model_validate(agent_dict)


def test_timezone_naive_datetime_rejected():
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)

    # Naive timestamp without timezone offset
    data["pickup_deadline"] = "2026-10-06T18:00:00"
    with pytest.raises(ValidationError, match="Input should have timezone info"):
        DealBrief.model_validate(data)


def test_donation_deal_brief_and_call_result():
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)

    # Valid donation brief: 0 PKR prices
    data["deal_type"] = "donation"
    data["opening_price_per_unit"] = 0
    data["floor_price_per_unit"] = 0
    data["payment_terms"] = "none"
    donation_brief = DealBrief.model_validate(data)
    assert donation_brief.deal_type == "donation"
    assert donation_brief.opening_price_per_unit == 0

    agent_brief = donation_brief.agent_view()
    assert agent_brief.deal_type == "donation"
    assert agent_brief.opening_price_per_unit == 0

    # Invalid donation brief: price > 0
    bad_donation = dict(data)
    bad_donation["opening_price_per_unit"] = 50
    with pytest.raises(ValidationError, match="Opening price must be 0 for a donation"):
        DealBrief.model_validate(bad_donation)

    # Valid donation call result
    donation_call = CallResult(
        call_id="call_don_001",
        batch_id="batch_01",
        mart_id="mart_01",
        status="completed",
        deal_type="donation",
        outcome="deal",
        agreed_price_per_unit=0,
        agreed_price_unit="kg",
        agreed_quantity=40.0,
        agreed_quantity_unit="kg",
        pickup_time="2026-10-06T19:00:00+05:00",
        summary="Donated to Edhi Foundation.",
    )
    assert donation_call.deal_type == "donation"
    assert donation_call.agreed_price_per_unit == 0

    # Invalid donation call result: agreed price > 0
    with pytest.raises(ValidationError, match="Agreed price must be 0"):
        CallResult(
            call_id="call_don_002",
            batch_id="batch_01",
            mart_id="mart_01",
            status="completed",
            deal_type="donation",
            outcome="deal",
            agreed_price_per_unit=15,
            agreed_price_unit="kg",
            agreed_quantity=40.0,
            agreed_quantity_unit="kg",
            pickup_time="2026-10-06T19:00:00+05:00",
        )


def test_phone_masking():
    # Pakistani mobile formats
    # One rule for logs and the page: country code and the last 3 digits only
    assert mask_phone("+923001234567") == "+92 ••••••• 567"
    assert mask_phone("03001234567") == "••••••••567"
    assert mask_phone("923001234567") == "•••••••••567"
    assert mask_phone("123") == "•••"
    assert "1234" not in mask_pii_in_text("Called +923001234567")

    # Pakistani landlines (Karachi 021, Lahore 042)
    assert "021-34567890" not in mask_pii_in_text("Karachi shop: 021-34567890")
    assert "042 35761234" not in mask_pii_in_text("Lahore bakery: 042 35761234")
    assert "923001234567" not in mask_pii_in_text("Called 923001234567")

    # Critical: plain IDs and timestamps must NOT be masked
    id_text = "mart_khi_001 batch_2026_10_06_01"
    assert mask_pii_in_text(id_text) == id_text

    timestamp_text = "2026-10-06T18:00:00+05:00"
    assert mask_pii_in_text(timestamp_text) == timestamp_text


def test_cloud_logging_formatter():
    formatter = CloudLoggingJsonFormatter(service_name="api-test")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test_models.py",
        lineno=100,
        msg="Dialed +923001234567 successfully",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    parsed = json.loads(formatted)
    assert parsed["severity"] == "INFO"
    assert parsed["serviceContext"]["service"] == "api-test"
    assert "+923001234567" not in parsed["message"]
    assert "+92 ••••••• 567" in parsed["message"]


def test_calling_hours_validation():
    from datetime import time

    from lastcall_shared.models import CallingHours

    # 1. Valid calling hours
    ch = CallingHours(start=time(9, 0), end=time(18, 0), timezone="Asia/Karachi")
    assert ch.start == time(9, 0)
    assert ch.end == time(18, 0)
    assert ch.timezone == "Asia/Karachi"

    # 2. Inverted time range (start >= end)
    with pytest.raises(ValidationError, match="start time .* must be before end time"):
        CallingHours(start=time(20, 0), end=time(10, 0), timezone="Asia/Karachi")

    # 3. Same start and end
    with pytest.raises(ValidationError, match="start time .* must be before end time"):
        CallingHours(start=time(12, 0), end=time(12, 0), timezone="Asia/Karachi")

    # 4. Invalid timezone
    with pytest.raises(ValidationError, match="Invalid timezone"):
        CallingHours(start=time(10, 0), end=time(18, 0), timezone="Invalid/Fake_Zone")

    # 5. DealBrief missing calling_hours is rejected (F3: no silent default)
    with open(FIXTURES_DIR / "valid_deal_brief.json") as f:
        data = json.load(f)
    bad_brief = dict(data)
    del bad_brief["calling_hours"]
    with pytest.raises(ValidationError, match="Field required"):
        DealBrief.model_validate(bad_brief)


def test_uvicorn_error_masking(capsys):
    """Verifies that setup_structured_logging configures uvicorn.error to output masked JSON to stdout (F4)."""
    # Setup loggers via production function under test
    setup_structured_logging(service_name="voice-test")
    uv_err = logging.getLogger("uvicorn.error")

    # Log an ASGI exception containing a phone number directly through uvicorn.error
    try:
        raise ValueError("Failed connecting to Twilio for buyer phone +923001234567")
    except Exception:
        uv_err.error("Exception in ASGI application", exc_info=True)

    captured = capsys.readouterr()
    assert captured.out.strip() != "", "Expected output on stdout"
    assert "+923001234567" not in captured.out
    assert "+92 ••••••• 567" in captured.out

    # Verify JSON structure
    log_line = [line for line in captured.out.strip().split("\n") if line.strip()][-1]
    parsed = json.loads(log_line)
    assert parsed["severity"] == "ERROR"
    assert parsed["serviceContext"]["service"] == "voice-test"
    assert "+923001234567" not in parsed["exception"]
    assert "+92 ••••••• 567" in parsed["exception"]


def test_ladder_models_valid():
    from datetime import time

    from lastcall_shared.marts.loader import load_mart_rules
    from lastcall_shared.models import (
        LadderDecision,
        LadderMeta,
        LadderResult,
        ProduceProfile,
        StageProfile,
    )

    # Load demo_mart rules
    rules = load_mart_rules("demo_mart")
    assert rules.mart_id == "demo_mart"
    assert rules.closing_time == time(23, 0)
    assert len(rules.prices) >= 20

    # Stage profile and produce profile
    fresh_sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    rip_sp = StageProfile(sellable_for="6_to_24h", juice_shop=True, restaurant=True, bakery=True, charity=True)
    over_sp = StageProfile(sellable_for="under_6h", juice_shop=True, restaurant=False, bakery=True, charity=True)

    prof = ProduceProfile(
        key="banana__v1",
        name="banana",
        note="Tropical fruit; ripens quickly at room temp",
        fresh=fresh_sp,
        ripening=rip_sp,
        overripe=over_sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="gemini",
        prompt_version="1",
        created_at=datetime.now(timezone.utc),
    )
    assert prof.key == "banana__v1"

    # Valid LadderDecision (discount)
    dec = LadderDecision(
        item_key="banana_1",
        name="banana",
        step="discount",
        allowed_steps=["keep", "discount"],
        unit="dozen",
        shelf_price=180,
        discount_pct=25,
        discounted_price=135,
        reason="Ripening banana 3h to closing",
    )
    assert dec.step == "discount"

    # Valid LadderResult
    res = LadderResult(
        mart_id="demo_mart",
        inspection_id="insp_123",
        decided_at=datetime.now(timezone.utc),
        hours_until_closing=3.0,
        decisions=[dec],
        meta=LadderMeta(latency_ms=15, profiles_used=1),
    )
    assert res.decisions[0].discounted_price == 135


def test_ladder_decision_step_outside_allowed_fails():
    from lastcall_shared.models import LadderDecision

    with pytest.raises(ValidationError, match="not in allowed_steps"):
        LadderDecision(
            item_key="item_1",
            name="spinach",
            step="bulk_sale",
            allowed_steps=["keep", "discount"],  # bulk_sale not allowed
            unit="kg",
            reason="test",
        )


def test_ladder_decision_opening_below_floor_fails():
    from lastcall_shared.models import LadderDecision

    with pytest.raises(ValidationError, match="opening_price .* cannot be below floor_price"):
        LadderDecision(
            item_key="item_1",
            name="guava",
            step="bulk_sale",
            allowed_steps=["bulk_sale", "donate"],
            unit="kg",
            opening_price=30,
            floor_price=50,  # floor > opening
            reason="test",
        )


def test_ladder_decision_donate_has_no_prices():
    from lastcall_shared.models import LadderDecision

    with pytest.raises(ValidationError, match="donate step has no prices"):
        LadderDecision(
            item_key="item_1",
            name="guava",
            step="donate",
            allowed_steps=["donate", "compost"],
            unit="kg",
            opening_price=50,  # prices not allowed on donate
            reason="test",
        )


def test_ladder_decision_discount_fields_only_on_discount():
    from lastcall_shared.models import LadderDecision

    with pytest.raises(ValidationError, match="discount_pct and discounted_price only allowed when step == 'discount'"):
        LadderDecision(
            item_key="item_1",
            name="apple",
            step="keep",
            allowed_steps=["keep", "discount"],
            unit="kg",
            discount_pct=20,
            reason="test",
        )


def test_mart_rules_invalid_percentages():
    from datetime import time

    from lastcall_shared.models import MartRules

    mart = MartInfo(name="Test Mart", location="Karachi")

    # min_discount > max_discount
    with pytest.raises(ValidationError, match="min_discount_pct .* cannot exceed max_discount_pct"):
        MartRules(
            mart_id="test",
            mart=mart,
            closing_time=time(23, 0),
            min_discount_pct=50,
            max_discount_pct=40,
            prices=[],
        )

    # bulk_floor >= bulk_open
    with pytest.raises(ValidationError, match="bulk_floor_pct .* must be less than bulk_open_pct"):
        MartRules(
            mart_id="test",
            mart=mart,
            closing_time=time(23, 0),
            bulk_open_pct=30,
            bulk_floor_pct=35,
            prices=[],
        )

    # percentage > 100
    with pytest.raises(ValidationError, match="must be between 1 and 100"):
        MartRules(
            mart_id="test",
            mart=mart,
            closing_time=time(23, 0),
            max_discount_pct=150,
            prices=[],
        )

    # opening_time == closing_time
    with pytest.raises(ValidationError, match="opening_time and closing_time cannot be equal"):
        MartRules(
            mart_id="test",
            mart=mart,
            closing_time=time(23, 0),
            opening_time=time(23, 0),
            prices=[],
        )

    # bulk_pickup_hours < 0 or > 6
    with pytest.raises(ValidationError, match="bulk_pickup_hours must be between 0 and 6"):
        MartRules(
            mart_id="test",
            mart=mart,
            closing_time=time(23, 0),
            bulk_pickup_hours=7.0,
            prices=[],
        )

    # overnight_hours property
    r = MartRules(
        mart_id="test",
        mart=mart,
        closing_time=time(23, 0),
        opening_time=time(9, 0),
        prices=[],
    )
    assert r.overnight_hours == 10.0


def test_loader_unknown_mart_raises_key_error():
    from lastcall_shared.marts.loader import load_mart_rules

    with pytest.raises(KeyError, match="Unknown mart"):
        load_mart_rules("non_existent_mart_999")


def test_mart_rules_price_names_unique():
    """A produce name may appear under only one price entry (ignoring case, spacing and plurals)."""
    from datetime import time

    from lastcall_shared.models import MartRules, PriceEntry

    mart = MartInfo(name="Test Mart", location="Lahore")
    lemon = PriceEntry(names=["lemon", "lime"], prices={"kg": 220})

    MartRules(mart_id="test", mart=mart, closing_time=time(23, 0), prices=[lemon])  # valid

    for clash in (["Lime"], ["sweet lime", "LE MON"], ["limes"], [""]):
        with pytest.raises(ValidationError, match="empty or listed more than once"):
            MartRules(
                mart_id="test",
                mart=mart,
                closing_time=time(23, 0),
                prices=[lemon, PriceEntry(names=clash, prices={"kg": 150})],
            )
