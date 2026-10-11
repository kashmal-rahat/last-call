"""Places API (New) client using ADC OAuth and Enterprise field masks (D47, D49)."""

import asyncio
from dataclasses import dataclass, field
import math
import random
from typing import Any, Awaitable, Callable

import httpx
from lastcall_shared.config import get_settings
from lastcall_shared.models import GeoPoint
from lastcall_api.scout.specs import FIELD_MASK, SearchSpec

PLACES_SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"

_credentials = None
_token_lock = asyncio.Lock()


async def get_oauth_token() -> str:
    """Returns a valid OAuth access token from ADC under the cloud-platform scope."""
    global _credentials
    if _credentials is None:
        import google.auth
        _credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])

    if not _credentials.valid:
        async with _token_lock:
            if not _credentials.valid:
                import google.auth.transport.requests
                req = google.auth.transport.requests.Request()
                await asyncio.to_thread(_credentials.refresh, req)

    return _credentials.token


class PlacesError(Exception):
    """Raised when the Places API returns an unhandled HTTP error."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"Places API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message


@dataclass
class PlaceRaw:
    id: str
    name: str
    primary_type: str | None = None
    types: list[str] = field(default_factory=list)
    lat: float | None = None
    lng: float | None = None
    business_status: str | None = None
    international_phone: str | None = None
    open_now: bool | None = None
    maps_uri: str | None = None


def compute_bounding_rectangle(center: GeoPoint, radius_km: float) -> dict[str, Any]:
    """Computes a bounding box rectangle around center for Places locationRestriction."""
    delta_lat = radius_km / 111.32
    delta_lng = radius_km / (111.32 * math.cos(math.radians(center.lat)))
    return {
        "rectangle": {
            "low": {
                "latitude": center.lat - delta_lat,
                "longitude": center.lng - delta_lng,
            },
            "high": {
                "latitude": center.lat + delta_lat,
                "longitude": center.lng + delta_lng,
            },
        }
    }


def parse_place_raw(p: dict[str, Any]) -> PlaceRaw:
    """Parses a raw Places API (New) object into PlaceRaw."""
    place_id = p.get("id", "")
    display_name = p.get("displayName")
    if isinstance(display_name, dict):
        name = display_name.get("text", "")
    elif isinstance(display_name, str):
        name = display_name
    else:
        name = ""

    primary_type = p.get("primaryType")
    types = p.get("types") or []
    location = p.get("location") or {}
    lat = location.get("latitude")
    lng = location.get("longitude")
    business_status = p.get("businessStatus")
    phone = p.get("internationalPhoneNumber")

    current_hours = p.get("currentOpeningHours") or {}
    open_now = current_hours.get("openNow") if isinstance(current_hours, dict) else None

    maps_uri = p.get("googleMapsUri")

    return PlaceRaw(
        id=place_id,
        name=name,
        primary_type=primary_type,
        types=types,
        lat=lat,
        lng=lng,
        business_status=business_status,
        international_phone=phone,
        open_now=open_now,
        maps_uri=maps_uri,
    )


class PlacesClient:
    """Client for Google Places API (New) Text Search."""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        token_provider: Callable[[], Awaitable[str]] | None = None,
        project_id: str | None = None,
    ):
        self._http_client = http_client
        self._token_provider = token_provider or get_oauth_token
        self._project_id = project_id or get_settings().GOOGLE_CLOUD_PROJECT

    async def search(
        self,
        spec: SearchSpec,
        center: GeoPoint,
        radius_km: float,
        page_size: int,
    ) -> list[PlaceRaw]:
        """Runs a Text Search for spec around center within radius_km."""
        token = await self._token_provider()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Goog-User-Project": self._project_id,
            "X-Goog-FieldMask": FIELD_MASK,
            "Content-Type": "application/json",
        }

        body: dict[str, Any] = {
            "textQuery": spec.text_query,
            "pageSize": page_size,
            "languageCode": "en",
            "regionCode": "PK",
            "rankPreference": spec.rank_preference,
            "locationRestriction": compute_bounding_rectangle(center, radius_km),
        }

        if spec.included_type:
            body["includedType"] = spec.included_type
        if spec.strict_type_filtering is not None:
            body["strictTypeFiltering"] = spec.strict_type_filtering

        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=8.0)
            close_client = True

        try:
            attempt = 0
            while attempt < 2:
                resp = await client.post(PLACES_SEARCH_TEXT_URL, headers=headers, json=body)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    attempt += 1
                    jitter = random.uniform(0.8, 1.2)
                    await asyncio.sleep(1.0 * jitter)
                    continue

                if resp.status_code >= 400:
                    try:
                        err_data = resp.json()
                        err_msg = err_data.get("error", {}).get("message", resp.text)
                    except Exception:
                        err_msg = resp.text
                    raise PlacesError(status_code=resp.status_code, message=err_msg)

                data = resp.json()
                raw_places = data.get("places") or []
                return [parse_place_raw(p) for p in raw_places]

            raise PlacesError(status_code=resp.status_code, message="Failed after retry")
        finally:
            if close_client:
                await client.aclose()
