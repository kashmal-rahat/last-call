"""Produce freshness inspection engine using Gemini 3.8 Flash (Module 1)."""

import asyncio
import json
import logging
import random
import secrets
import time
from collections import Counter
from datetime import datetime
from functools import lru_cache
from typing import Any, NamedTuple

import pydantic
from google import genai
from google.genai import types
from google.genai.errors import APIError

from lastcall_api.gemini_call import (
    CallUsage,
    GeminiCallError,
    _is_retryable_error,
    call_structured,
    get_genai_client,
)
from lastcall_api.inspector.guardrails import apply_guardrails, clean_item, merge_neighbours
from lastcall_api.inspector.images import crop_group, prepare_image
from lastcall_api.inspector.matching import assign_keys
from lastcall_api.inspector.prompt import PROMPT_VERSION, SYSTEM_PROMPT, user_text, zoom_text
from lastcall_api.inspector.schema import InspectorOutput
from lastcall_api.inspector.zoom import merge_zoom, select_for_zoom
from lastcall_shared.config import get_settings
from lastcall_shared.logging_utils import setup_structured_logging
from lastcall_shared.models import FreshnessResult, InspectorMeta

logger = setup_structured_logging(service_name="inspector")

THINKING_LEVEL = "low"
ZOOM_ENABLED = True

# Gemini 3.8 Flash pricing constants (per 1M tokens)
FLASH_INPUT_PRICE_PER_M = 0.75
FLASH_OUTPUT_PRICE_PER_M = 3.75


def estimate_cost(meta: InspectorMeta) -> float:
    """Estimates USD cost for an inspection based on input and output tokens."""
    return (meta.input_tokens / 1_000_000.0) * FLASH_INPUT_PRICE_PER_M + (
        meta.output_tokens / 1_000_000.0
    ) * FLASH_OUTPUT_PRICE_PER_M


FORBIDDEN_CONFIG_KEYS = {"temperature", "top_p", "top_k", "seed", "candidate_count", "presence_penalty", "frequency_penalty"}


class InspectorError(Exception):
    """Raised when an inspection fails after retries or due to budget."""

    def __init__(self, reason: str, original_exc: Exception | None = None):
        super().__init__(reason)
        self.reason = reason
        self.original_exc = original_exc


def build_config(thinking_level: str = THINKING_LEVEL) -> types.GenerateContentConfig:
    """Builds Gemini configuration obeying D30 (zero forbidden keys)."""
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=InspectorOutput,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
    )


HEDGE_AFTER_S: float = 12.0


async def _call(
    client: genai.Client,
    image_jpeg: bytes,
    prompt_text: str,
    config: types.GenerateContentConfig,
    deadline: float,
    *,
    max_attempts: int = 3,
    per_attempt_timeout: float = 30.0,
) -> tuple[InspectorOutput, CallUsage, int, bool]:
    """Executes a single Gemini inspection call with retries and timeout within the deadline budget.

    Returns: (output, usage, attempts_count, was_hedged)
    """
    contents = [
        types.Part.from_bytes(data=image_jpeg, mime_type="image/jpeg"),
        prompt_text,
    ]
    try:
        out, usage, attempts, was_hedged = await call_structured(
            client=client,
            contents=contents,
            config=config,
            schema=InspectorOutput,
            deadline=deadline,
            max_attempts=max_attempts,
            per_attempt_timeout=per_attempt_timeout,
            hedge_after_s=HEDGE_AFTER_S,
            label="Inspection",
        )
        return out, usage, attempts, was_hedged  # type: ignore[return-value]
    except GeminiCallError as exc:
        raise InspectorError(exc.reason, original_exc=exc.original_exc) from exc


async def inspect_photo(
    image: bytes,
    *,
    mart_id: str,
    shelf_id: str,
    previous: FreshnessResult | None = None,
    now: datetime,
    bin_capacity_kg: float | None = None,
    client: genai.Client | None = None,
    zoom: bool | None = None,
    thinking_level: str | None = None,
) -> FreshnessResult:
    """Inspects a shelf photo and returns a structured FreshnessResult."""
    t0 = time.monotonic()
    deadline = t0 + 60.0

    # 1. Prepare image (ValueError propagates on bad image)
    prep = prepare_image(image)

    active_client = client or get_genai_client()
    active_thinking = thinking_level or THINKING_LEVEL
    cfg = build_config(thinking_level=active_thinking)

    # 2. Pass 1
    pass1_prompt = user_text(bin_capacity_kg)
    pass1_out, pass1_usage, p1_calls, p1_hedged = await _call(
        active_client,
        prep.jpeg,
        pass1_prompt,
        cfg,
        deadline,
    )

    total_calls = p1_calls
    total_hedges = 1 if p1_hedged else 0
    total_in_tokens = pass1_usage.input_tokens
    total_out_tokens = pass1_usage.output_tokens
    total_cached_tokens = pass1_usage.cached_tokens
    total_thought_tokens = pass1_usage.thought_tokens
    zoomed_count = 0
    zoom_failures = 0

    zoom_results: dict[int, tuple[list[Any], bool]] = {}
    final_output = pass1_out

    should_zoom = ZOOM_ENABLED if zoom is None else zoom

    # 3. Clean pass-1 items ONCE right after pass 1
    # Both zoom (if enabled) and guardrails operate on this one list
    cleaned_pass1 = [c for c in (clean_item(i) for i in pass1_out.items) if c is not None]
    cleaned_pass1 = merge_neighbours(cleaned_pass1)
    final_output = pass1_out.model_copy(update={"items": cleaned_pass1})

    # Pass 2 zoom branch (executed when zoom is enabled and photo_status == "ok")
    if pass1_out.photo_status == "ok" and should_zoom and (deadline - time.monotonic()) >= 10.0:
        selected_indices = select_for_zoom(cleaned_pass1, max_crops=6)
        if selected_indices:
            # Crop and call in parallel
            async def _run_crop(idx: int):
                base_item = cleaned_pass1[idx]
                try:
                    crop_bytes = crop_group(prep.full, base_item.box_2d)
                    crop_out, crop_usage, calls, crop_hedged = await _call(
                        active_client,
                        crop_bytes,
                        zoom_text(base_item.name),
                        cfg,
                        deadline,
                    )
                    return idx, crop_out, crop_usage, calls, crop_hedged
                except Exception:
                    return idx, None, CallUsage(0, 0, 0, 0, 0), 1, False

            crop_tasks = [_run_crop(idx) for idx in selected_indices]
            crop_results = await asyncio.gather(*crop_tasks, return_exceptions=True)

            merged_items = list(cleaned_pass1)
            for res in crop_results:
                if isinstance(res, Exception):
                    continue

                idx, crop_out, crop_usage, calls, crop_hedged = res
                total_calls += calls
                if crop_hedged:
                    total_hedges += 1
                total_in_tokens += crop_usage.input_tokens
                total_out_tokens += crop_usage.output_tokens
                total_cached_tokens += crop_usage.cached_tokens
                total_thought_tokens += crop_usage.thought_tokens

                base_item = cleaned_pass1[idx]
                if crop_out is None:
                    zoom_failures += 1
                    merged_item, extra_reasons = merge_zoom(base_item, None)
                    merged_items[idx] = merged_item
                else:
                    merged_item, extra_reasons = merge_zoom(base_item, crop_out)
                    merged_items[idx] = merged_item
                    zoom_results[idx] = (extra_reasons, True)
                    zoomed_count += 1

            final_output = pass1_out.model_copy(update={"items": merged_items})

    # 6. Apply guardrails and assign keys
    photo_status, photo_note, photo_issues, drafts = apply_guardrails(final_output, zoom=zoom_results)
    items = assign_keys(drafts, previous, now=now)

    latency_ms = int(round((time.monotonic() - t0) * 1000))
    settings = get_settings()

    meta = InspectorMeta(
        model=settings.GEMINI_FLASH_MODEL,
        prompt_version=PROMPT_VERSION,
        thinking_level=active_thinking,
        latency_ms=latency_ms,
        calls=total_calls,
        hedges=total_hedges,
        zoomed_groups=zoomed_count,
        zoom_failures=zoom_failures,
        input_tokens=total_in_tokens,
        output_tokens=total_out_tokens,
        cached_tokens=total_cached_tokens,
        thoughts_tokens=total_thought_tokens,
    )

    inspection_id = f"insp_{now:%Y%m%d_%H%M%S}_{secrets.token_hex(3)}"
    prev_id = previous.inspection_id if previous else None

    result = FreshnessResult(
        schema_version="3.0.0",
        mart_id=mart_id,
        shelf_id=shelf_id,
        inspection_id=inspection_id,
        previous_inspection_id=prev_id,
        photo_uri=f"upload:sha256:{prep.sha256}",
        taken_at=now,
        photo_status=photo_status,
        photo_note=photo_note,
        photo_issues=photo_issues,
        items=items,
        inspector=meta,
    )

    # 7. Structured log: never log images, names, evidence, or notes
    stage_counts = dict(Counter(i.stage for i in items))
    staff_check_count = sum(1 for i in items if i.needs_staff_check)

    logger.info(
        "photo_inspected",
        extra={
            "extra_fields": {
                "inspection_id": inspection_id,
                "photo_status": photo_status,
                "photo_issues": photo_issues,
                "item_count": len(items),
                "stage_counts": stage_counts,
                "staff_check_count": staff_check_count,
                "zoomed_groups": zoomed_count,
                "zoom_failures": zoom_failures,
                "latency_ms": latency_ms,
                "input_tokens": total_in_tokens,
                "output_tokens": total_out_tokens,
                "cached_tokens": total_cached_tokens,
                "calls": total_calls,
            }
        },
    )

    return result
