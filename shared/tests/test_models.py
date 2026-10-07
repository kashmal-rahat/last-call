"""Tests for shared domain models, constraints, and security isolation."""

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from pydantic import ValidationError

from lastcall_shared.models import (
    BoundingBox,
    BuyerInfo,
    CallResult,
    ConfirmedQuantity,
    DealBrief,
    FreshnessResult,
    ItemAssessment,
    MartInfo,
    QuantityEstimate,
)
from lastcall_shared.logging_utils import mask_phone, mask_pii_in_text, CloudLoggingJsonFormatter
import logging

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_valid_freshness_from_fixture():
    with open(FIXTURES_DIR / "valid_freshness.json") as f:
        data = json.load(f)
    result = FreshnessResult.model_validate(data)
    assert result.mart_id == "mart_khi_001"
    assert len(result.items) == 1
    assert result.items[0].quantity.unit == "kg"
    assert result.items[0].issues == ["bruising"]


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
    assert brief.opening_price_per_unit >= brief.floor_price_per_unit


def test_floor_price_isolation_in_agent_view():
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

    # Verify buyer phone is omitted from agent_view (architecture §7 privacy)
    assert not hasattr(agent_view.buyer, "phone")
    assert "phone" not in dump_dict["buyer"]

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

    data["opening_price_per_unit"] = 120.0
    data["floor_price_per_unit"] = 150.0
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
    from lastcall_shared.models import AgentDealBrief
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
    data["opening_price_per_unit"] = 0.0
    data["floor_price_per_unit"] = 0.0
    donation_brief = DealBrief.model_validate(data)
    assert donation_brief.deal_type == "donation"
    assert donation_brief.opening_price_per_unit == 0.0

    agent_brief = donation_brief.agent_view()
    assert agent_brief.deal_type == "donation"
    assert agent_brief.opening_price_per_unit == 0.0

    # Invalid donation brief: price > 0
    bad_donation = dict(data)
    bad_donation["opening_price_per_unit"] = 50.0
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
        agreed_price_per_unit=0.0,
        agreed_price_unit="kg",
        agreed_quantity=40.0,
        agreed_quantity_unit="kg",
        pickup_time="2026-10-06T19:00:00+05:00",
        summary="Donated to Edhi Foundation.",
    )
    assert donation_call.deal_type == "donation"
    assert donation_call.agreed_price_per_unit == 0.0

    # Invalid donation call result: agreed price > 0
    with pytest.raises(ValidationError, match="Agreed price must be 0"):
        CallResult(
            call_id="call_don_002",
            batch_id="batch_01",
            mart_id="mart_01",
            status="completed",
            deal_type="donation",
            outcome="deal",
            agreed_price_per_unit=15.0,
            agreed_price_unit="kg",
            agreed_quantity=40.0,
            agreed_quantity_unit="kg",
            pickup_time="2026-10-06T19:00:00+05:00",
        )


def test_phone_masking():
    # Pakistani mobile formats
    assert mask_phone("+923001234567") == "+9230******67"
    assert mask_phone("03001234567") == "03001****67"
    assert mask_phone("923001234567") == "92300*****67"
    assert mask_phone("123") == "***"

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
    assert "+9230******67" in parsed["message"]

