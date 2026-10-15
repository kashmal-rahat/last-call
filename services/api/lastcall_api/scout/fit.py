"""Gemini fit screening for Scout candidates (D46, Step 6; in parallel groups, D73)."""

import asyncio
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from lastcall_api.gemini_call import call_structured
from lastcall_api.scout.rank import FilteredCandidate
from lastcall_shared.genai_client import get_genai_client
from lastcall_shared.models import BuyerFit, ScoutStep, UsageRecord

logger = logging.getLogger("lastcall_api.scout.fit")

FIT_PROMPT_VERSION = "1"

# Businesses per Gemini call (D73). Each business is judged on its own (D46), so the list is screened as
# even groups in parallel: the answer's length, and so its time, is set by the largest group, not the list.
MAX_FIT_GROUP = 10

_PROMPT_PATH = Path(__file__).resolve().parent / "fit_prompt.md"
FIT_SYSTEM_PROMPT = _PROMPT_PATH.read_text().strip()

DEAL_WORDS: dict[ScoutStep, str] = {
    "bulk_sale": "sell in bulk at a reduced price",
    "donate": "give free to people in need",
    "animal_feed": "sell cheaply as animal feed",
}


class FitOut(BaseModel):
    ref: str
    fit: BuyerFit
    why: str


class FitsOut(BaseModel):
    fits: list[FitOut]


def build_fit_config() -> types.GenerateContentConfig:
    """Builds GenerateContentConfig for fit screening complying with D30."""
    return types.GenerateContentConfig(
        system_instruction=FIT_SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=FitsOut,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
    )


def fit_groups(candidates: list[FilteredCandidate]) -> list[list[FilteredCandidate]]:
    """Even groups of at most MAX_FIT_GROUP, dealt round-robin (23 → 8, 8, 7; 40 → 4 × 10).

    Round-robin, not consecutive slices: the list comes sorted nearest first (rank.apply_filters), so
    slices would put all the nearest businesses in one call; dealt, every group gets the same spread of
    distances (and so a natural mix of buyer types), and every call sees a list like the whole one.
    """
    if not candidates:
        return []
    count = math.ceil(len(candidates) / MAX_FIT_GROUP)
    return [candidates[i::count] for i in range(count)]


async def screen_fit(
    candidates: list[FilteredCandidate],
    *,
    item: str,
    condition: str,
    step: ScoutStep,
    client: genai.Client | None = None,
    deadline: float | None = None,
) -> tuple[dict[str, tuple[BuyerFit, str]], UsageRecord, dict[str, Any]]:
    """Screens candidate businesses against item and condition (D46), one structured Gemini call per group,
    all at once under the same deadline (D73).

    Never raises on a Gemini failure: a group that fails falls back to ('possible', '') for its businesses
    only, and fit_fallback is set. The ranking of the merged verdicts is code's (rank.py), as before.
    """
    assert len(candidates) <= 40, f"At most 40 candidates allowed for fit screening, got {len(candidates)}"

    stats: dict[str, Any] = {
        "fit_calls": 0,
        "fit_fallback": False,
        "fit_prompt_version": FIT_PROMPT_VERSION,
    }

    groups = fit_groups(candidates)
    if not groups:
        return {}, UsageRecord(), stats

    if client is None:
        client = get_genai_client()
    if deadline is None:
        deadline = time.monotonic() + 25.0

    outcomes = await asyncio.gather(
        *(
            _screen_group(group, item=item, condition=condition, step=step, client=client, deadline=deadline)
            for group in groups
        )
    )

    result_fits: dict[str, tuple[BuyerFit, str]] = {}
    usage = UsageRecord()
    for group_fits, group_usage, fell_back in outcomes:
        result_fits.update(group_fits)
        usage.input_tokens += group_usage.input_tokens
        usage.output_tokens += group_usage.output_tokens
        stats["fit_fallback"] = stats["fit_fallback"] or fell_back
    stats["fit_calls"] = len(groups)
    return result_fits, usage, stats


async def _screen_group(
    candidates: list[FilteredCandidate],
    *,
    item: str,
    condition: str,
    step: ScoutStep,
    client: genai.Client,
    deadline: float,
) -> tuple[dict[str, tuple[BuyerFit, str]], UsageRecord, bool]:
    """One Gemini call for one group: (verdict per place ID, usage, fell back). Never raises on a Gemini failure."""
    # Short refs, local to this call: Gemini never sees place IDs or phones
    ref_to_place_id: dict[str, str] = {f"c{i + 1}": c.place_id for i, c in enumerate(candidates)}

    biz_list = [
        {
            "ref": f"c{i + 1}",
            "name": c.name,
            "searched_as": c.buyer_type,
            "primary_type": c.primary_type or "",
            "types": c.types[:5],
        }
        for i, c in enumerate(candidates)
    ]

    user_payload = {
        "produce": item,
        "condition": condition,
        "deal": DEAL_WORDS.get(step, "sell in bulk at a reduced price"),
        "businesses": biz_list,
    }
    user_text = json.dumps(user_payload)

    try:
        out_raw, call_usage, attempts, was_hedged = await call_structured(
            client=client,
            contents=[user_text],
            config=build_fit_config(),
            schema=FitsOut,
            deadline=deadline,
            max_attempts=2,
            per_attempt_timeout=12.0,
            hedge_after_s=6.0,
            label="Scout fit",
        )

        out: FitsOut = out_raw  # type: ignore
        seen_refs: set[str] = set()
        result_fits: dict[str, tuple[BuyerFit, str]] = {}

        for f in out.fits:
            if f.ref not in ref_to_place_id or f.ref in seen_refs:
                continue
            seen_refs.add(f.ref)
            pid = ref_to_place_id[f.ref]
            fit_val: BuyerFit = f.fit if f.fit in ("likely", "possible", "unlikely") else "possible"
            why_str = (f.why or "").strip()[:100]
            result_fits[pid] = (fit_val, why_str)

        # Default any missing candidate to ("possible", "")
        for c in candidates:
            if c.place_id not in result_fits:
                result_fits[c.place_id] = ("possible", "")

        usage = UsageRecord(
            input_tokens=call_usage.input_tokens,
            output_tokens=call_usage.output_tokens,
        )
        return result_fits, usage, False

    except Exception as exc:
        reason = getattr(exc, "reason", None)
        logger.warning(
            "Fit screening call failed; falling back to possible",
            extra={
                "error_class": exc.__class__.__name__,
                "reason": str(reason) if reason else None,
                "group_size": len(candidates),
            },
        )
        return {c.place_id: ("possible", "") for c in candidates}, UsageRecord(), True
