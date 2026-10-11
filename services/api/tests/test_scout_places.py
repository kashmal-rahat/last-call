"""Unit tests for PlacesClient and search specs (D47, D49)."""

import json
import math
import pytest
import httpx

from lastcall_shared.models import GeoPoint
from lastcall_api.scout.specs import FIELD_MASK, ATMOSPHERE_FIELDS, SEARCH_SPECS
from lastcall_api.scout.places import (
    PlacesClient,
    PlacesError,
    PlaceRaw,
    compute_bounding_rectangle,
    parse_place_raw,
    PLACES_SEARCH_TEXT_URL,
)


def test_field_mask_contains_no_atmosphere_fields():
    """Enterprise SKU field mask must NOT contain any atmosphere fields."""
    expected_mask = (
        "places.id,"
        "places.displayName,"
        "places.primaryType,"
        "places.types,"
        "places.location,"
        "places.businessStatus,"
        "places.internationalPhoneNumber,"
        "places.currentOpeningHours.openNow,"
        "places.googleMapsUri"
    )
    assert FIELD_MASK == expected_mask

    mask_fields = [f.strip() for f in FIELD_MASK.split(",")]
    # Check both raw names and subfields
    for field in mask_fields:
        leaf = field.split(".")[-1]
        assert leaf not in ATMOSPHERE_FIELDS, f"Field {field} is an atmosphere field!"
        assert field not in ATMOSPHERE_FIELDS, f"Field {field} is an atmosphere field!"


def test_compute_bounding_rectangle_math():
    """Verify delta_lat and delta_lng math at lat 31.4 and radius 10 km."""
    center = GeoPoint(lat=31.4, lng=74.3)
    radius_km = 10.0
    rect = compute_bounding_rectangle(center, radius_km)

    expected_dlat = 10.0 / 111.32
    expected_dlng = 10.0 / (111.32 * math.cos(math.radians(31.4)))

    low = rect["rectangle"]["low"]
    high = rect["rectangle"]["high"]

    assert pytest.approx(low["latitude"], rel=1e-5) == 31.4 - expected_dlat
    assert pytest.approx(high["latitude"], rel=1e-5) == 31.4 + expected_dlat
    assert pytest.approx(low["longitude"], rel=1e-5) == 74.3 - expected_dlng
    assert pytest.approx(high["longitude"], rel=1e-5) == 74.3 + expected_dlng


def test_parse_place_raw_full_and_missing_fields():
    """Verify parsing PlaceRaw with complete and partial/missing fields."""
    full_data = {
        "id": "places/ChIJ123",
        "displayName": {"text": "Fresh Juice Corner", "languageCode": "en"},
        "primaryType": "juice_shop",
        "types": ["juice_shop", "food", "point_of_interest"],
        "location": {"latitude": 31.4697, "longitude": 74.2728},
        "businessStatus": "OPERATIONAL",
        "internationalPhoneNumber": "+92 42 35761234",
        "currentOpeningHours": {"openNow": True},
        "googleMapsUri": "https://maps.google.com/?cid=123",
    }
    p = parse_place_raw(full_data)
    assert p.id == "places/ChIJ123"
    assert p.name == "Fresh Juice Corner"
    assert p.primary_type == "juice_shop"
    assert p.types == ["juice_shop", "food", "point_of_interest"]
    assert p.lat == 31.4697
    assert p.lng == 74.2728
    assert p.business_status == "OPERATIONAL"
    assert p.international_phone == "+92 42 35761234"
    assert p.open_now is True
    assert p.maps_uri == "https://maps.google.com/?cid=123"

    # Missing fields
    minimal_data = {"id": "places/ChIJ456"}
    p_min = parse_place_raw(minimal_data)
    assert p_min.id == "places/ChIJ456"
    assert p_min.name == ""
    assert p_min.primary_type is None
    assert p_min.types == []
    assert p_min.lat is None
    assert p_min.lng is None
    assert p_min.business_status is None
    assert p_min.international_phone is None
    assert p_min.open_now is None
    assert p_min.maps_uri is None


@pytest.mark.asyncio
async def test_places_client_headers_body_and_no_key_in_url():
    """PlacesClient sends exact required headers, valid body, and never puts API key in URL."""
    captured_requests = []

    def mock_handler(request: httpx.Request):
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "places/ChIJtest",
                        "displayName": {"text": "Test Juice"},
                        "primaryType": "juice_shop",
                        "internationalPhoneNumber": "+92 300 1234567",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)

    async def fake_token():
        return "mock-oauth-token-12345"

    client = PlacesClient(
        http_client=http_client,
        token_provider=fake_token,
        project_id="test-cloud-project",
    )

    spec = SEARCH_SPECS["juice_shop"]
    center = GeoPoint(lat=31.4697, lng=74.2728)

    results = await client.search(
        spec=spec,
        center=center,
        radius_km=10.0,
        page_size=20,
    )

    assert len(results) == 1
    assert results[0].id == "places/ChIJtest"
    assert results[0].name == "Test Juice"

    assert len(captured_requests) == 1
    req = captured_requests[0]

    # Verify URL has no key= parameter
    assert "key=" not in str(req.url)
    assert req.url == PLACES_SEARCH_TEXT_URL

    # Verify headers
    assert req.headers["Authorization"] == "Bearer mock-oauth-token-12345"
    assert req.headers["X-Goog-User-Project"] == "test-cloud-project"
    assert req.headers["X-Goog-FieldMask"] == FIELD_MASK
    assert req.headers["Content-Type"] == "application/json"

    # Verify body
    body = json.loads(req.content)
    assert body["textQuery"] == "juice shop"
    assert body["pageSize"] == 20
    assert body["languageCode"] == "en"
    assert body["regionCode"] == "PK"
    assert body["rankPreference"] == "DISTANCE"
    assert body["includedType"] == "juice_shop"
    assert body["strictTypeFiltering"] is True
    assert "locationRestriction" in body
    assert "rectangle" in body["locationRestriction"]


@pytest.mark.asyncio
async def test_places_client_retries_429_then_succeeds():
    """PlacesClient retries once on 429 status code."""
    attempts = 0

    def mock_handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "Resource exhausted"}})
        return httpx.Response(
            200,
            json={"places": [{"id": "places/ChIJretry", "displayName": {"text": "Retry Place"}}]},
        )

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)

    client = PlacesClient(
        http_client=http_client,
        token_provider=lambda: pytest.helpers.async_return("mock-token") if hasattr(pytest, "helpers") else None,  # handled below
        project_id="test-cloud-project",
    )

    async def fake_token():
        return "mock-token"

    client._token_provider = fake_token

    results = await client.search(
        spec=SEARCH_SPECS["restaurant"],
        center=GeoPoint(lat=31.4, lng=74.3),
        radius_km=5.0,
        page_size=10,
    )

    assert attempts == 2
    assert len(results) == 1
    assert results[0].id == "places/ChIJretry"


@pytest.mark.asyncio
async def test_places_client_raises_places_error_on_400():
    """PlacesClient raises PlacesError on 400 Bad Request without token in error."""
    def mock_handler(request: httpx.Request):
        return httpx.Response(400, json={"error": {"message": "Invalid field mask"}})

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)

    async def fake_token():
        return "secret-token-must-not-leak"

    client = PlacesClient(
        http_client=http_client,
        token_provider=fake_token,
        project_id="test-cloud-project",
    )

    with pytest.raises(PlacesError) as exc_info:
        await client.search(
            spec=SEARCH_SPECS["bakery"],
            center=GeoPoint(lat=31.4, lng=74.3),
            radius_km=5.0,
            page_size=10,
        )

    assert exc_info.value.status_code == 400
    assert "Invalid field mask" in exc_info.value.message
    assert "secret-token" not in str(exc_info.value)
