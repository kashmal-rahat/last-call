"""Unit tests for Scout filtering, ranking, and reason construction (D50, D52, Step 5)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from lastcall_api.scout.places import PlaceRaw
from lastcall_api.scout.rank import (
    MAX_FIT_CANDIDATES,
    FilteredCandidate,
    apply_filters,
    build_reason,
    distance_km,
    normalise_phone,
    rank,
    sanitise_name,
)
from lastcall_shared.models import (
    BuyerHistory,
    GeoPoint,
    MartRules,
)

SECRET = "test-secret-at-least-32-chars-long-12345"
CENTER = GeoPoint(lat=31.448133, lng=74.270334)  # Johar Town
from pathlib import Path

DEMO_MART_PATH = Path(__file__).resolve().parents[3] / "shared/lastcall_shared/marts/demo_mart.json"
RULES = MartRules.model_validate_json(DEMO_MART_PATH.read_text())
NOW = datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)
TZ = ZoneInfo("Asia/Karachi")


def test_normalise_phone():
    """Validates international phone numbers to E.164 or None."""
    assert normalise_phone("+92 300 1234567") == "+923001234567"
    assert normalise_phone("+92 42 35761234") == "+924235761234"
    assert normalise_phone("+1 (555) 234-5678") == "+15552345678"
    assert normalise_phone("1234") is None
    assert normalise_phone("03001234567") is None  # no leading +
    assert normalise_phone("") is None
    assert normalise_phone(None) is None


def test_distance_km():
    """Haversine test against known delta (0.01 deg latitude approx 1.11 km)."""
    p1 = GeoPoint(lat=31.0, lng=74.0)
    p2 = GeoPoint(lat=31.01, lng=74.0)
    d = distance_km(p1, p2)
    assert pytest.approx(d, rel=1e-2) == 1.112


def test_sanitise_name():
    """Sanitises names: drops control chars, collapses whitespace, caps at 80 chars."""
    raw = "  Fresh \t Juice \n Corner \x00\x1f " + "A" * 100
    cleaned = sanitise_name(raw)
    assert cleaned.startswith("Fresh Juice Corner")
    assert "\t" not in cleaned and "\n" not in cleaned
    assert len(cleaned) <= 80


def test_place_id_with_slash_is_skipped(caplog):
    """m2: Place ID with slash must be skipped with a warning log."""
    bad_place = PlaceRaw(id="places/ChIJ123", name="Bad ID", lat=31.44, lng=74.27, international_phone="+923001234567")
    kept, skipped = apply_filters(
        [bad_place],
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=set(),
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == 0
    assert any("Skipping place with invalid '/'" in r.message for r in caplog.records)


def test_filter_dedupe_by_place_id():
    """First buyer type in decision order wins for duplicate place_id."""
    p1 = PlaceRaw(id="ChIJ_dup", name="Dup 1", lat=31.448, lng=74.270, international_phone="+923001111111")
    p2 = PlaceRaw(id="ChIJ_dup", name="Dup 2", lat=31.448, lng=74.270, international_phone="+923001111111")

    buyer_types = {"ChIJ_dup": "juice_shop"}
    kept, skipped = apply_filters(
        [p1, p2],
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=set(),
        now=NOW,
        buyer_type_of=buyer_types,
        phone_secret=SECRET,
    )
    assert len(kept) == 1
    assert kept[0].name == "Dup 1"
    assert skipped == {}


def test_filter_not_operational():
    """Places with business_status != OPERATIONAL are skipped."""
    p_closed = PlaceRaw(id="ChIJ_closed", name="Closed", business_status="CLOSED_PERMANENTLY", lat=31.448, lng=74.270, international_phone="+923001111111")
    p_temp = PlaceRaw(id="ChIJ_temp", name="Temp Closed", business_status="CLOSED_TEMPORARILY", lat=31.448, lng=74.270, international_phone="+923001111111")
    p_ok = PlaceRaw(id="ChIJ_ok", name="Ok", business_status="OPERATIONAL", lat=31.448, lng=74.270, international_phone="+923001111111")
    p_none = PlaceRaw(id="ChIJ_none", name="None Status", business_status=None, lat=31.448, lng=74.270, international_phone="+923002222222")

    kept, skipped = apply_filters(
        [p_closed, p_temp, p_ok, p_none],
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=set(),
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == 2
    assert skipped.get("not_operational") == 2


def test_filter_too_far():
    """Places beyond scout_radius_km are skipped."""
    p_near = PlaceRaw(id="ChIJ_near", name="Near", lat=31.45, lng=74.27, international_phone="+923001111111")  # ~0.2 km
    p_far = PlaceRaw(id="ChIJ_far", name="Far", lat=31.60, lng=74.27, international_phone="+923002222222")   # ~16.8 km

    kept, skipped = apply_filters(
        [p_near, p_far],
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=set(),
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == 1
    assert kept[0].place_id == "ChIJ_near"
    assert skipped.get("too_far") == 1


def test_filter_no_phone():
    """Places without a valid E.164 phone are skipped."""
    p_no_phone = PlaceRaw(id="ChIJ_no_ph", name="No Phone", lat=31.45, lng=74.27, international_phone=None)
    p_bad_phone = PlaceRaw(id="ChIJ_bad_ph", name="Bad Phone", lat=31.45, lng=74.27, international_phone="12345")
    p_good = PlaceRaw(id="ChIJ_good_ph", name="Good", lat=31.45, lng=74.27, international_phone="+923001234567")

    kept, skipped = apply_filters(
        [p_no_phone, p_bad_phone, p_good],
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=set(),
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == 1
    assert kept[0].place_id == "ChIJ_good_ph"
    assert skipped.get("no_phone") == 2


def test_filter_do_not_call_by_place_id_and_phone_key():
    """Places in DNC by buyer_id or phone_key are skipped."""
    from lastcall_shared.buyer_keys import phone_key

    pk_blocked = phone_key("+923009999999", SECRET)
    dnc = {"places:ChIJ_dnc_id", pk_blocked}

    p_dnc_id = PlaceRaw(id="ChIJ_dnc_id", name="DNC ID", lat=31.45, lng=74.27, international_phone="+923001111111")
    p_dnc_phone = PlaceRaw(id="ChIJ_other_id", name="DNC Phone", lat=31.45, lng=74.27, international_phone="+923009999999")
    p_ok = PlaceRaw(id="ChIJ_ok", name="Ok", lat=31.45, lng=74.27, international_phone="+923002222222")

    kept, skipped = apply_filters(
        [p_dnc_id, p_dnc_phone, p_ok],
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=dnc,
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == 1
    assert kept[0].place_id == "ChIJ_ok"
    assert skipped.get("do_not_call") == 2


def test_filter_cooldown():
    """Places called within buyer_cooldown_hours without a deal are skipped."""
    hist_recent_declined = BuyerHistory(
        mart_id="demo_mart",
        place_id="ChIJ_recent_declined",
        buyer_id="places:ChIJ_recent_declined",
        last_called_at=NOW - timedelta(hours=5),
        last_outcome="declined",
    )
    hist_recent_deal = BuyerHistory(
        mart_id="demo_mart",
        place_id="ChIJ_recent_deal",
        buyer_id="places:ChIJ_recent_deal",
        last_called_at=NOW - timedelta(hours=5),
        last_outcome="deal",
    )
    hist_old_declined = BuyerHistory(
        mart_id="demo_mart",
        place_id="ChIJ_old_declined",
        buyer_id="places:ChIJ_old_declined",
        last_called_at=NOW - timedelta(hours=25),
        last_outcome="declined",
    )

    histories = {
        "places:ChIJ_recent_declined": hist_recent_declined,
        "places:ChIJ_recent_deal": hist_recent_deal,
        "places:ChIJ_old_declined": hist_old_declined,
    }

    p1 = PlaceRaw(id="ChIJ_recent_declined", name="Rec Dec", lat=31.45, lng=74.27, international_phone="+923001111111")
    p2 = PlaceRaw(id="ChIJ_recent_deal", name="Rec Deal", lat=31.45, lng=74.27, international_phone="+923002222222")
    p3 = PlaceRaw(id="ChIJ_old_declined", name="Old Dec", lat=31.45, lng=74.27, international_phone="+923003333333")

    kept, skipped = apply_filters(
        [p1, p2, p3],
        center=CENTER,
        rules=RULES,
        histories=histories,
        dnc=set(),
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == 2
    assert {c.place_id for c in kept} == {"ChIJ_recent_deal", "ChIJ_old_declined"}
    assert skipped.get("cooldown") == 1


def test_filter_duplicate_phone():
    """Between two places with the same phone, nearer listing is kept."""
    # p_near is 0.2 km away, p_far is 1.0 km away
    p_near = PlaceRaw(id="ChIJ_near", name="Branch Near", lat=31.45, lng=74.27, international_phone="+923005555555")
    p_far = PlaceRaw(id="ChIJ_far", name="Branch Far", lat=31.456, lng=74.27, international_phone="+923005555555")

    kept, skipped = apply_filters(
        [p_far, p_near],  # far encountered first in input
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=set(),
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == 1
    assert kept[0].place_id == "ChIJ_near"
    assert skipped.get("duplicate_phone") == 1


def test_filter_order():
    """Verifies sequential filter order priority (first matching reason applies)."""
    # A candidate that is NOT_OPERATIONAL, TOO_FAR, and NO_PHONE -> must be skipped as not_operational
    p = PlaceRaw(id="ChIJ_multi", name="Multi", business_status="CLOSED_PERMANENTLY", lat=32.0, lng=75.0, international_phone=None)
    kept, skipped = apply_filters(
        [p],
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=set(),
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == 0
    assert skipped == {"not_operational": 1}


def test_max_fit_candidates_cap_and_not_screened():
    """45 surviving candidates -> 40 nearest kept, 5 skipped as not_screened (D52)."""
    places = []
    for i in range(45):
        # lat staggered slightly so distances are distinct
        places.append(
            PlaceRaw(
                id=f"ChIJ_{i:02d}",
                name=f"Shop {i}",
                lat=31.448 + i * 0.001,
                lng=74.270,
                international_phone=f"+9230000000{i:02d}",
                business_status="OPERATIONAL",
            )
        )

    kept, skipped = apply_filters(
        places,
        center=CENTER,
        rules=RULES,
        histories={},
        dnc=set(),
        now=NOW,
        buyer_type_of={},
        phone_secret=SECRET,
    )
    assert len(kept) == MAX_FIT_CANDIDATES  # 40
    assert skipped.get("not_screened") == 5


def test_rank_worked_example():
    """Worked example from plan.md line 317.

    A juice shop 0.8 km, likely, closed (False)
    B bakery 3 km, possible, open (True)
    C juice shop 6 km, likely, hours unknown (None)
    D bakery 1 km, likely, open (True)
    Expected order: D, C, B, A.
    """
    candidates = [
        FilteredCandidate("A", "Juice A", "juice_shop", "juice_shop", [], "+923001111111", 0.8, False, None),
        FilteredCandidate("B", "Bakery B", "bakery", "bakery", [], "+923002222222", 3.0, True, None),
        FilteredCandidate("C", "Juice C", "juice_shop", "juice_shop", [], "+923003333333", 6.0, None, None),
        FilteredCandidate("D", "Bakery D", "bakery", "bakery", [], "+923004444444", 1.0, True, None),
    ]

    fits = {
        "A": ("likely", "Good shop"),
        "B": ("possible", "Standard bakery"),
        "C": ("likely", "Known juice place"),
        "D": ("likely", "Great bakery"),
    }

    ranked, screened_out = rank(candidates, fits, histories={}, max_buyers=5, tz=TZ)
    assert [c.place_id for c in ranked] == ["D", "C", "B", "A"]
    assert [c.rank for c in ranked] == [1, 2, 3, 4]
    assert screened_out == []


def test_rank_six_candidates_table():
    """Full sort order tested on 6 diverse candidates with history, fits, hours, and distances."""
    hist1 = BuyerHistory(
        mart_id="demo_mart",
        place_id="P1",
        buyer_id="places:P1",
        deals=2,
        last_deal_at=NOW - timedelta(days=2),
        last_deal_price=120,
        last_deal_unit="kg",
    )
    hist2 = BuyerHistory(
        mart_id="demo_mart",
        place_id="P2",
        buyer_id="places:P2",
        deals=1,
        last_deal_at=NOW - timedelta(days=5),
        last_deal_price=100,
        last_deal_unit="kg",
    )
    histories = {"places:P1": hist1, "places:P2": hist2}

    candidates = [
        FilteredCandidate("P6", "Shop 6", "juice_shop", None, [], "+923006666666", 2.0, False, None),  # closed, possible
        FilteredCandidate("P5", "Shop 5", "restaurant", None, [], "+923005555555", 1.5, True, None),   # open, possible
        FilteredCandidate("P4", "Shop 4", "bakery", None, [], "+923004444444", 0.5, True, None),       # open, likely
        FilteredCandidate("P3", "Shop 3", "juice_shop", None, [], "+923003333333", 1.2, None, None),   # unknown, likely
        FilteredCandidate("P2", "Shop 2", "restaurant", None, [], "+923002222222", 3.0, True, None),   # deal 5d ago
        FilteredCandidate("P1", "Shop 1", "juice_shop", None, [], "+923001111111", 5.0, False, None),  # deal 2d ago (newer)
    ]

    fits = {
        "P1": ("likely", ""),
        "P2": ("possible", ""),
        "P3": ("likely", ""),
        "P4": ("likely", ""),
        "P5": ("possible", ""),
        "P6": ("possible", ""),
    }

    # Expected order:
    # 1. P1 (deal 2d ago)
    # 2. P2 (deal 5d ago)
    # 3. P4 (no deal, open, likely, 0.5 km)
    # 4. P3 (no deal, unknown hours, likely, 1.2 km)
    # 5. P5 (no deal, open, possible, 1.5 km)
    # P6 is 6th, but max_buyers=5 cuts it off
    ranked, screened_out = rank(candidates, fits, histories=histories, max_buyers=5, tz=TZ)
    assert [c.place_id for c in ranked] == ["P1", "P2", "P4", "P3", "P5"]
    assert len(ranked) == 5


def test_rank_screened_out_unlikely():
    """Candidates with fit=='unlikely' are excluded from buyers and placed in screened_out."""
    candidates = [
        FilteredCandidate("U1", "Bad Shop 1", "juice_shop", None, [], "+923001111111", 5.0, True, None),
        FilteredCandidate("U2", "Bad Shop 2", "restaurant", None, [], "+923002222222", 1.0, True, None),
        FilteredCandidate("OK", "Good Shop", "bakery", None, [], "+923003333333", 2.0, True, None),
    ]

    fits = {
        "U1": ("unlikely", "Far away corporate office"),
        "U2": ("unlikely", "High-end luxury fine dining"),
        "OK": ("likely", "Standard local bakery"),
    }

    ranked, screened_out = rank(candidates, fits, histories={}, max_buyers=5, tz=TZ)
    assert len(ranked) == 1
    assert ranked[0].place_id == "OK"

    assert len(screened_out) == 2
    # Screened out sorted nearest first: U2 (1.0 km) before U1 (5.0 km)
    assert screened_out[0].name == "Bad Shop 2"
    assert screened_out[0].distance_km == 1.0
    assert screened_out[0].why == "High-end luxury fine dining"
    assert screened_out[1].name == "Bad Shop 1"
    assert screened_out[1].distance_km == 5.0
    # No phone or place_id on ScreenedOut
    assert not hasattr(screened_out[0], "phone")
    assert not hasattr(screened_out[0], "place_id")


def test_build_reason_text():
    """Verifies reason text formatting for past deals, open, closed, and unknown hours."""
    # Past deal
    hist = BuyerHistory(
        mart_id="demo_mart",
        place_id="123",
        buyer_id="places:123",
        deals=1,
        last_deal_at=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
        last_deal_price=110,
        last_deal_unit="kg",
    )
    r1 = build_reason("juice_shop", distance_km=0.6, open_now=True, history=hist, tz=TZ)
    assert r1 == "Bought from us 11 Oct (Rs 110/kg) · Juice shop · 0.6 km · open now"

    # No past deal, unknown hours
    r2 = build_reason("bakery", distance_km=2.3, open_now=None, history=None, tz=TZ)
    assert r2 == "Bakery · 2.3 km · hours unknown"

    # No past deal, closed now
    r3 = build_reason("restaurant", distance_km=4.1, open_now=False, history=None, tz=TZ)
    assert r3 == "Restaurant · 4.1 km · closed now"
