"""Search specifications and field masks for Google Places API (New)."""

from dataclasses import dataclass
from typing import Literal

from lastcall_shared.models import BuyerType

# Enterprise SKU constant field mask (Pro + Enterprise fields only, NO Atmosphere fields).
FIELD_MASK: str = (
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

# Known Atmosphere fields (which bill as Enterprise + Atmosphere, $40/1k).
ATMOSPHERE_FIELDS = frozenset(
    [
        "reviews",
        "dineIn",
        "delivery",
        "takeout",
        "curbsidePickup",
        "reservable",
        "servesBreakfast",
        "servesLunch",
        "servesDinner",
        "servesBeer",
        "servesWine",
        "servesBrunch",
        "servesVegetarianFood",
        "outdoorSeating",
        "liveMusic",
        "menuForChildren",
        "servesCocktails",
        "servesDessert",
        "servesCoffee",
        "goodForChildren",
        "allowsDogs",
        "restroom",
        "goodForGroups",
        "goodForWatchingSports",
        "paymentOptions",
        "parkingOptions",
        "accessibilityOptions",
    ]
)


@dataclass(frozen=True)
class SearchSpec:
    buyer_type: BuyerType
    endpoint: Literal["searchNearby", "searchText"]
    text_query: str | None = None
    included_type: str | None = None
    strict_type_filtering: bool | None = None
    rank_preference: Literal["DISTANCE", "RELEVANCE"] = "DISTANCE"

    def __post_init__(self):
        if self.endpoint == "searchNearby":
            if not self.included_type or not self.included_type.strip():
                raise ValueError("endpoint 'searchNearby' requires a non-empty included_type")
        elif self.endpoint == "searchText":
            if not self.text_query or not self.text_query.strip():
                raise ValueError("endpoint 'searchText' requires a non-empty text_query")


SEARCH_SPECS: dict[BuyerType, SearchSpec] = {
    "juice_shop": SearchSpec(
        buyer_type="juice_shop",
        endpoint="searchNearby",
        included_type="juice_shop",
        rank_preference="DISTANCE",
    ),
    "restaurant": SearchSpec(
        buyer_type="restaurant",
        endpoint="searchNearby",
        included_type="restaurant",
        rank_preference="DISTANCE",
    ),
    "bakery": SearchSpec(
        buyer_type="bakery",
        endpoint="searchNearby",
        included_type="bakery",
        rank_preference="DISTANCE",
    ),
    "charity": SearchSpec(
        buyer_type="charity",
        endpoint="searchText",
        text_query="dastarkhwan",
        included_type=None,
        rank_preference="RELEVANCE",
    ),
    "dairy_farm": SearchSpec(
        buyer_type="dairy_farm",
        endpoint="searchText",
        text_query="dairy farm cattle farm",
        included_type=None,
        rank_preference="RELEVANCE",
    ),
}
