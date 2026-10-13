"""Scout orchestration: parallel Places searches, filtering, fit screening, ranking, and storage (D46, D48, D50, D52, Step 8)."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import httpx

from lastcall_api.scout.fit import screen_fit
from lastcall_api.scout.places import PlaceRaw, PlacesClient
from lastcall_api.scout.rank import apply_filters, normalise_phone, rank
from lastcall_api.scout.specs import SEARCH_SPECS
from lastcall_shared.buyer_keys import phone_key
from lastcall_shared.config import get_settings
from lastcall_shared.models import (
    Branch,
    BuyerType,
    LadderDecision,
    MartRules,
    ScoutMeta,
    ScoutResult,
    ScoutStep,
)
from lastcall_shared.store import CallStore

logger = logging.getLogger("lastcall_api.scout")

SCOUT_LIST_TTL = timedelta(hours=1)


class ScoutNotApplicable(Exception):
    """Raised when the step does not scout buyers or no matching specs exist."""


class ScoutCapReached(Exception):
    """Raised when the daily Places requests cap is reached."""


class ScoutFailed(Exception):
    """Raised when all Places searches fail."""


@dataclass(frozen=True)
class ScoutTarget:
    """Target specification for scouting buyers (independent of current decision step)."""

    inspection_id: str
    item_key: str
    item: str
    condition: str
    step: ScoutStep
    buyer_types: tuple[BuyerType, ...]

    @classmethod
    def from_decision(cls, decision: LadderDecision, inspection_id: str) -> "ScoutTarget":
        if decision.step not in ("bulk_sale", "donate", "animal_feed"):
            raise ScoutNotApplicable(f"Decision step '{decision.step}' does not require buyer scouting")
        return cls(
            inspection_id=inspection_id,
            item_key=decision.item_key,
            item=decision.name,
            condition=decision.buyer_condition,
            step=decision.step,  # type: ignore
            buyer_types=tuple(decision.buyer_types),
        )


async def run_scout(
    target: ScoutTarget,
    *,
    rules: MartRules,
    branch: Branch,
    store: CallStore,
    places: PlacesClient | None = None,
    genai_client: Any = None,
    now: datetime,
    reserve_places: Callable[[int], Awaitable[bool]] | None = None,
) -> ScoutResult:
    """Executes the full Scout pipeline within a 25 s total time budget (D46, D48, D50, D52)."""
    start_time = time.monotonic()
    deadline = start_time + 25.0

    # 1. Filter to valid types with specs, cap at 3
    valid_types: list[BuyerType] = [t for t in target.buyer_types if t in SEARCH_SPECS][:3]
    if not valid_types:
        raise ScoutNotApplicable("No valid buyer types with search specs found")

    # 2. Daily places request cap reservation check
    if reserve_places is not None:
        allowed = await reserve_places(len(valid_types))
        if not allowed:
            raise ScoutCapReached("Daily buyer-search limit reached")

    # 3. Parallel Places searches with shared HTTP client (N2, N4)
    all_raw_places: list[PlaceRaw] = []
    buyer_type_of: dict[str, BuyerType] = {}
    failed_searches: list[BuyerType] = []

    async with httpx.AsyncClient(timeout=8.0) as shared_http_client:
        client = places if places is not None else PlacesClient(http_client=shared_http_client)

        async def _search_one(b_type: BuyerType) -> tuple[BuyerType, list[PlaceRaw] | Exception]:
            spec = SEARCH_SPECS[b_type]
            try:
                res = await client.search(
                    spec=spec,
                    center=branch.geo,
                    radius_km=rules.scout_radius_km,
                    deadline=deadline,
                )
                return b_type, res
            except Exception as e:
                logger.warning(
                    "Places search exception",
                    extra={"buyer_type": b_type, "error_class": e.__class__.__name__},
                )
                return b_type, e

        search_tasks = [_search_one(t) for t in valid_types]
        search_outcomes = await asyncio.gather(*search_tasks)

    for b_type, outcome in search_outcomes:
        if isinstance(outcome, Exception):
            failed_searches.append(b_type)
        else:
            for p in outcome:
                all_raw_places.append(p)
                if p.id not in buyer_type_of:
                    buyer_type_of[p.id] = b_type

    if len(failed_searches) == len(valid_types):
        raise ScoutFailed(f"All Places searches failed: {failed_searches}")

    # 4. Batch reads: Buyer histories and DNC entries
    phone_secret = get_settings().APP_SIGNING_KEY.get_secret_value()
    buyer_ids = [f"places:{p.id}" for p in all_raw_places]
    histories = await store.get_buyer_histories(rules.mart_id, buyer_ids)

    dnc_query_keys = list(buyer_ids)
    for p in all_raw_places:
        norm = normalise_phone(p.international_phone)
        if norm:
            dnc_query_keys.append(phone_key(norm, phone_secret))
    dnc = await store.get_do_not_call(rules.mart_id, dnc_query_keys)

    # 5. Deterministic code filters
    kept, skipped = apply_filters(
        all_raw_places,
        center=branch.geo,
        rules=rules,
        histories=histories,
        dnc=dnc,
        now=now,
        buyer_type_of=buyer_type_of,
        phone_secret=phone_secret,
    )

    # 6. Gemini fit screening within remaining time budget
    fits, fit_usage, fit_stats = await screen_fit(
        kept,
        item=target.item,
        condition=target.condition,
        step=target.step,
        client=genai_client,
        deadline=deadline,
    )

    # Count unlikely fits in skipped
    unlikely_count = sum(1 for c in kept if fits.get(c.place_id, ("possible", ""))[0] == "unlikely")
    if unlikely_count > 0:
        skipped["unlikely_fit"] = unlikely_count

    # 7. Ranking
    buyers, screened_out = rank(
        kept,
        fits=fits,
        histories=histories,
        max_buyers=rules.scout_max_buyers,
        tz=ZoneInfo(rules.timezone),
    )

    # 8. Assemble ScoutResult and save
    latency_ms = int((time.monotonic() - start_time) * 1000)
    meta = ScoutMeta(
        latency_ms=latency_ms,
        places_requests=len(valid_types),
        places_results=len(all_raw_places),
        failed_searches=failed_searches,
        fit_calls=fit_stats["fit_calls"],
        fit_fallback=fit_stats["fit_fallback"],
        fit_prompt_version=fit_stats["fit_prompt_version"],
        input_tokens=fit_usage.input_tokens,
        output_tokens=fit_usage.output_tokens,
        reused=False,
    )

    key = f"{target.inspection_id}__{target.item_key}__{branch.branch_id}"
    scout_result = ScoutResult(
        key=key,
        mart_id=rules.mart_id,
        inspection_id=target.inspection_id,
        item_key=target.item_key,
        branch_id=branch.branch_id,
        branch_name=branch.name,
        step=target.step,
        buyer_types=valid_types,
        searched_at=now,
        expire_at=now + SCOUT_LIST_TTL,
        buyers=buyers,
        skipped=skipped,
        screened_out=screened_out,
        meta=meta,
        attribution="Google Maps",
    )

    await store.save_scout_result(scout_result)

    # 9. Structured logging: strictly operational metadata, ZERO names, phones or reasons
    logger.info(
        "scout_completed",
        extra={
            "key": scout_result.key,
            "step": scout_result.step,
            "requests": meta.places_requests,
            "results": meta.places_results,
            "kept": len(kept),
            "buyers": len(buyers),
            "skipped": skipped,
            "fit_fallback": meta.fit_fallback,
            "latency_ms": meta.latency_ms,
            "tokens": meta.input_tokens + meta.output_tokens,
        },
    )

    return scout_result
