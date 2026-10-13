"""Shared Gemini structured call helper with retries, hedging and budget control."""

import asyncio
import json
import random
import time
from functools import lru_cache
from typing import Any, NamedTuple

import pydantic
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

from lastcall_shared.config import get_settings
from lastcall_shared.logging_utils import setup_structured_logging

logger = setup_structured_logging(service_name="gemini_call")


class GeminiCallError(Exception):
    """Raised when a Gemini call fails after retries or due to budget."""

    def __init__(self, reason: str, original_exc: Exception | None = None):
        super().__init__(reason)
        self.reason = reason
        self.original_exc = original_exc


class CallUsage(NamedTuple):
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    thought_tokens: int = 0
    candidate_tokens: int = 0


def _is_retryable_error(exc: Exception) -> bool:
    """Determines whether a Gemini API error should be retried.

    Retry only on:
    - google.genai.errors.APIError with code 429 or >= 500
    - Timeouts (asyncio.TimeoutError, TimeoutError)
    - Empty response or JSON / validation parse errors
    Any other API error (e.g. 400 INVALID_ARGUMENT) is NOT retried.
    """
    if isinstance(
        exc, (asyncio.TimeoutError, TimeoutError, ValueError, json.JSONDecodeError, pydantic.ValidationError)
    ):
        return True

    if isinstance(exc, APIError):
        code = getattr(exc, "code", None)
        if code is not None:
            return code == 429 or code >= 500
        return False

    return False


@lru_cache
def get_genai_client() -> genai.Client:
    """Returns a cached genai Client configured for Vertex AI in the configured region."""
    settings = get_settings()
    return genai.Client(
        vertexai=settings.GOOGLE_GENAI_USE_VERTEXAI,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.GOOGLE_CLOUD_LOCATION,
    )


async def call_structured(
    client: genai.Client,
    contents: list[Any],
    config: types.GenerateContentConfig,
    schema: type[BaseModel],
    deadline: float,
    *,
    max_attempts: int = 3,
    per_attempt_timeout: float = 30.0,
    hedge_after_s: float = 12.0,
    label: str = "Gemini",
) -> tuple[BaseModel, CallUsage, int, bool]:
    """Executes a single structured Gemini call with retries and timeout within the deadline budget.

    Returns: (output, usage, attempts_count, was_hedged)
    """
    settings = get_settings()
    model_id = settings.GEMINI_FLASH_MODEL

    last_error: Exception | None = None
    attempts = 0
    was_hedged = False

    for attempt_idx in range(max_attempts):
        now = time.monotonic()
        remaining = deadline - now
        if remaining < 5.0:
            raise GeminiCallError(f"{label} budget exceeded", original_exc=last_error)

        attempt_timeout = min(per_attempt_timeout, remaining)
        attempts += 1

        try:

            async def _generate():
                return await client.aio.models.generate_content(
                    model=model_id,
                    contents=contents,
                    config=config,
                )

            task1 = asyncio.create_task(_generate())
            task2: asyncio.Task | None = None
            resp = None

            hedge_delay = min(hedge_after_s, attempt_timeout)
            done, _ = await asyncio.wait({task1}, timeout=hedge_delay)

            if task1 in done:
                resp = await task1
            else:
                remaining_attempt_timeout = max(0.0, attempt_timeout - hedge_delay)
                if remaining_attempt_timeout >= 3.0:
                    # Hedged request: start second identical request
                    task2 = asyncio.create_task(_generate())
                    attempts += 1
                    was_hedged = True

                    pending = {task1, task2}
                    last_hedge_err = None
                    start_wait = time.monotonic()

                    while pending:
                        curr_remaining = remaining_attempt_timeout - (time.monotonic() - start_wait)
                        if curr_remaining <= 0:
                            break
                        done_set, pending = await asyncio.wait(
                            pending,
                            timeout=curr_remaining,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if not done_set:
                            break

                        for t in done_set:
                            try:
                                resp = t.result()
                                break
                            except Exception as err:
                                last_hedge_err = err

                        if resp is not None:
                            for p in pending:
                                p.cancel()
                            if pending:
                                await asyncio.gather(*pending, return_exceptions=True)
                            break

                    if resp is None:
                        for p in pending:
                            p.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        if last_hedge_err is not None:
                            raise last_hedge_err
                        raise asyncio.TimeoutError("Hedged requests timed out")
                else:
                    # Less than 3s remain in attempt: do not hedge, wait for task1
                    done_set, _ = await asyncio.wait({task1}, timeout=remaining_attempt_timeout)
                    if task1 in done_set:
                        resp = await task1
                    else:
                        task1.cancel()
                        await asyncio.gather(task1, return_exceptions=True)
                        raise asyncio.TimeoutError("Request timed out")

            # Parse output
            output: BaseModel | None = None
            if hasattr(resp, "parsed") and resp.parsed is not None:
                if isinstance(resp.parsed, schema):
                    output = resp.parsed
                elif isinstance(resp.parsed, dict):
                    output = schema.model_validate(resp.parsed)
                elif isinstance(resp.parsed, BaseModel):
                    output = schema.model_validate(resp.parsed.model_dump())

            if output is None:
                text_content = resp.text if hasattr(resp, "text") and resp.text else ""
                if not text_content.strip():
                    raise ValueError("Empty response received from model")
                output = schema.model_validate_json(text_content)

            # Extract usage metadata strictly from the winning response
            usage_meta = getattr(resp, "usage_metadata", None)
            input_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
            cached_tokens = getattr(usage_meta, "cached_content_token_count", 0) or 0
            cand_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
            thought_tokens = getattr(usage_meta, "thoughts_token_count", 0) or 0
            output_tokens = cand_tokens + thought_tokens

            usage = CallUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                thought_tokens=thought_tokens,
                candidate_tokens=cand_tokens,
            )
            return output, usage, attempts, was_hedged

        except (asyncio.TimeoutError, TimeoutError) as exc:
            last_error = exc
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise GeminiCallError(f"{label} non-retryable error: {exc}", original_exc=exc) from exc
            last_error = exc
            if attempt_idx == max_attempts - 1:
                break

        # Sleep with ±20% jitter: 2s then 4s
        if attempt_idx < max_attempts - 1:
            base_sleep = 2.0 if attempt_idx == 0 else 4.0
            jitter = random.uniform(0.8, 1.2)
            sleep_sec = base_sleep * jitter
            if (deadline - time.monotonic()) - sleep_sec < 5.0:
                break
            await asyncio.sleep(sleep_sec)

    raise GeminiCallError(f"{label} call failed after retries", original_exc=last_error)
