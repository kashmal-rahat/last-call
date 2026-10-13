"""Tests for Module 4 Scout domain models and MartRules branch/scout configuration."""

import json
from datetime import datetime, time, timezone

import pytest
from pydantic import ValidationError

from lastcall_shared.buyer_keys import mask_phone, phone_key
from lastcall_shared.marts.loader import load_mart_rules
from lastcall_shared.models import (
    Branch,
    BuyerInfo,
    GeoPoint,
    MartInfo,
    MartRules,
    ScoutCandidate,
    ScoutMeta,
    ScoutResult,
)


def test_geopoint_validation():
    p = GeoPoint(lat=31.448133, lng=74.270334)
    assert p.lat == 31.448133
    assert p.lng == 74.270334

    with pytest.raises(ValidationError):
        GeoPoint(lat=91.0, lng=0.0)

    with pytest.raises(ValidationError):
        GeoPoint(lat=0.0, lng=181.0)


def test_branch_validation():
    b = Branch(
        branch_id="johar_town",
        name="Demo Mart Johar Town",
        location="Johar Town, Lahore, Pakistan",
        geo=GeoPoint(lat=31.448133, lng=74.270334),
    )
    assert b.branch_id == "johar_town"

    # Bad branch_id (capital letters or special chars)
    with pytest.raises(ValidationError):
        Branch(
            branch_id="Johar_Town",
            name="Demo Mart",
            location="Lahore",
            geo=GeoPoint(lat=31.4, lng=74.2),
        )

    with pytest.raises(ValidationError):
        Branch(
            branch_id="johar-town",
            name="Demo Mart",
            location="Lahore",
            geo=GeoPoint(lat=31.4, lng=74.2),
        )


def test_mart_rules_scout_radius_limits():
    rules_data = {
        "mart_id": "test_mart",
        "mart": {"name": "Test Mart", "location": "Lahore"},
        "closing_time": "23:00",
        "opening_time": "09:00",
        "prices": [],
        "scout_radius_km": 10.0,
    }
    rules = MartRules.model_validate(rules_data)
    assert rules.scout_radius_km == 10.0

    # Over 10 km fails
    with pytest.raises(ValidationError, match="scout_radius_km"):
        rules_data["scout_radius_km"] = 10.1
        MartRules.model_validate(rules_data)

    # Below 0.5 km fails
    with pytest.raises(ValidationError, match="scout_radius_km"):
        rules_data["scout_radius_km"] = 0.4
        MartRules.model_validate(rules_data)


def test_mart_rules_branch_constraints():
    base = {
        "mart_id": "test_mart",
        "mart": {"name": "Test Mart", "location": "Lahore"},
        "closing_time": "23:00",
        "opening_time": "09:00",
        "prices": [],
    }

    # Duplicate branch IDs
    b1 = {"branch_id": "b1", "name": "B1", "location": "L1", "geo": {"lat": 31.0, "lng": 74.0}}
    b2 = {"branch_id": "b1", "name": "B2", "location": "L2", "geo": {"lat": 31.1, "lng": 74.1}}
    with pytest.raises(ValidationError, match="Duplicate branch_id"):
        MartRules.model_validate({**base, "branches": [b1, b2], "default_branch_id": "b1"})

    # More than 10 branches
    many_branches = [
        {"branch_id": f"b{i}", "name": f"B{i}", "location": f"L{i}", "geo": {"lat": 31.0, "lng": 74.0}}
        for i in range(11)
    ]
    with pytest.raises(ValidationError, match="At most 10 branches"):
        MartRules.model_validate({**base, "branches": many_branches, "default_branch_id": "b0"})

    # Missing default when branches present
    with pytest.raises(ValidationError, match="default_branch_id must be set"):
        MartRules.model_validate({**base, "branches": [b1]})

    # Default not in branches
    with pytest.raises(ValidationError, match="default_branch_id 'b_missing' not found in branches"):
        MartRules.model_validate({**base, "branches": [b1], "default_branch_id": "b_missing"})


def test_mart_rules_branch_lookup():
    b1 = Branch(branch_id="johar", name="Johar", location="Johar", geo=GeoPoint(lat=31.4, lng=74.2))
    b2 = Branch(branch_id="gulberg", name="Gulberg", location="Gulberg", geo=GeoPoint(lat=31.5, lng=74.3))
    rules = MartRules(
        mart_id="test",
        mart=MartInfo(name="Test", location="Lahore"),
        closing_time=time(23, 0),
        opening_time=time(9, 0),
        prices=[],
        branches=[b1, b2],
        default_branch_id="johar",
    )

    # None -> default
    assert rules.branch(None).branch_id == "johar"
    # Specific ID
    assert rules.branch("gulberg").branch_id == "gulberg"
    # Unknown ID raises KeyError
    with pytest.raises(KeyError, match="not found"):
        rules.branch("unknown_branch")


def test_demo_mart_json_loads_valid():
    rules = load_mart_rules("demo_mart")
    assert rules.mart_id == "demo_mart"
    assert rules.mart.name == "Demo Mart"
    assert rules.mart.location == "Lahore, Pakistan"
    assert rules.default_branch_id == "johar_town"
    assert len(rules.branches) == 3
    assert rules.branch(None).branch_id == "johar_town"
    assert rules.branch("bahria_town").name == "Demo Mart Bahria Town"
    assert rules.branch("gulberg").name == "Demo Mart Gulberg"


def test_scout_candidate_and_public_view():
    now = datetime.now(timezone.utc)
    cand = ScoutCandidate(
        rank=1,
        buyer_id="places:ChIJ12345",
        place_id="ChIJ12345",
        name="Fresh Juice Corner",
        buyer_type="juice_shop",
        primary_type="juice_shop",
        phone="+923001234567",
        distance_km=0.8,
        open_now=True,
        maps_uri="https://maps.google.com/?cid=123",
        fit="likely",
        fit_why="Local juice stall; uses ripe bananas for shakes",
        past_deals=2,
        last_deal_at=now,
        reason="Bought from us before · Juice shop · 0.8 km · open now",
    )

    # to_buyer_info
    info = cand.to_buyer_info()
    assert isinstance(info, BuyerInfo)
    assert info.buyer_id == "places:ChIJ12345"
    assert info.name == "Fresh Juice Corner"
    assert info.type == "juice_shop"
    assert info.phone == "+923001234567"

    # public_view masking
    pv = cand.public_view()
    assert "phone" not in pv
    assert pv["phone_masked"] == "+92 ••••••• 567"

    dumped = json.dumps(pv)
    assert "+923001234567" not in dumped
    assert "1234567" not in dumped


def test_scout_result_public_view():
    now = datetime.now(timezone.utc)
    cand = ScoutCandidate(
        rank=1,
        buyer_id="places:ChIJ12345",
        place_id="ChIJ12345",
        name="Fresh Juice Corner",
        buyer_type="juice_shop",
        phone="+923001234567",
        distance_km=0.8,
        fit="likely",
        reason="Juice shop · 0.8 km",
    )
    result = ScoutResult(
        key="insp_1__banana__johar_town",
        mart_id="demo_mart",
        inspection_id="insp_1",
        item_key="banana",
        branch_id="johar_town",
        branch_name="Demo Mart Johar Town",
        step="bulk_sale",
        buyer_types=["juice_shop"],
        searched_at=now,
        expire_at=now,
        buyers=[cand],
        meta=ScoutMeta(latency_ms=120),
    )

    pv = result.public_view()
    dumped = json.dumps(pv)
    assert "+923001234567" not in dumped
    assert pv["buyers"][0]["phone_masked"] == "+92 ••••••• 567"


def test_phone_key_and_mask_phone():
    secret = "test_signing_key_at_least_32_characters_long"
    p1 = "+923001234567"
    p2 = "+923001234568"

    k1 = phone_key(p1, secret)
    k1_repeat = phone_key(p1, secret)
    k2 = phone_key(p2, secret)

    assert k1 == k1_repeat
    assert k1 != k2
    assert k1.startswith("phone:")
    assert len(k1) == len("phone:") + 32
    assert "3001234567" not in k1

    # mask_phone tests
    assert mask_phone("+923001234567") == "+92 ••••••• 567"
    assert mask_phone("+92 42 35761234") == "+92 ••••••• 234"
    assert mask_phone("+14155552671") == "+14 •••••• 671"
    assert mask_phone("1234") == "•234"
    assert mask_phone("") == ""
