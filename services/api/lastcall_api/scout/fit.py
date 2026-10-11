"""Gemini fit screening for Scout candidates (D46, Step 6)."""

import json
from pathlib import Path
import time
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from lastcall_shared.logging_utils import setup_structured_logging
from lastcall_shared.models import BuyerFit, ScoutStep, UsageRecord
from lastcall_api.gemini_call import CallUsage, GeminiCallError, call_structured, get_genai_client
from lastcall_api.scout.rank import FilteredCandidate

logger = setup_structured_logging(service_name="scout_fit")

FIT_PROMPT_VERSION = "1"

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


async def screen_fit(
    candidates: list[FilteredCandidate],
    *,
    item: str,
    condition: str,
    step: ScoutStep,
    client: genai.Client | None = None,
    deadline: float | None = None,
) -> tuple[dict[str, tuple[BuyerFit, str]], UsageRecord, dict[str, Any]]:
    """Screens candidate businesses against item and condition using structured Gemini call (D46).

    Never raises on GeminiCallError; falls back gracefully to ('possible', '').
    """
    assert len(candidates) <= 40, f"At most 40 candidates allowed for fit screening, got {len(candidates)}"

    stats: dict[str, Any] = {
        "fit_calls": 0,
        "fit_fallback": False,
        "fit_prompt_version": FIT_PROMPT_VERSION,
    }

    if not candidates:
        return {}, UsageRecord(), stats

    ref_to_place_id: dict[str, str] = {
        f"c{i + 1}": c.place_id for i, c in enumerate(candidates)
    }

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

    if client is None:
        client = get_genai_client()

    if deadline is None:
        deadline = time.monotonic() + 25.0

    config = build_fit_config()
    stats["fit_calls"] = 1

    try:
        out_raw, call_usage, attempts, was_hedged = await call_structured(
            client=client,
            contents=[user_text],
            config=config,
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
        return result_fits, usage, stats

    except Exception as exc:
        reason = getattr(exc, "reason", None)
        logger.warning(
            "Fit screening call failed; falling back to possible",
            extra={
                "error_class": exc.__class__.__name__,
                "reason": str(reason) if reason else None,
            },
        )
        stats["fit_fallback"] = True
        result_fits = {c.place_id: ("possible", "") for c in candidates}
        return result_fits, UsageRecord(), stats
