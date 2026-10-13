"""Tests for shared gemini_call.call_structured helper."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.genai import errors, types
from pydantic import BaseModel

from lastcall_api.gemini_call import (
    GeminiCallError,
    call_structured,
)


class DummyTarget(BaseModel):
    message: str
    count: int


class FakeResponse:
    def __init__(self, parsed=None, text="", prompt_tokens=42, cand_tokens=18):
        self.parsed = parsed
        self.text = text
        self.usage_metadata = MagicMock(
            prompt_token_count=prompt_tokens,
            candidates_token_count=cand_tokens,
            thoughts_token_count=5,
            cached_content_token_count=0,
        )


class FakeGenAIClient:
    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.call_count = 0
        self.aio = MagicMock()
        self.aio.models.generate_content = self._generate_content

    async def _generate_content(self, model, contents, config):
        self.call_count += 1
        if not self.responses:
            raise RuntimeError("No more responses configured in FakeGenAIClient")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.mark.asyncio
async def test_call_structured_parses_into_target_schema():
    expected = DummyTarget(message="hello", count=7)
    client = FakeGenAIClient([FakeResponse(parsed=expected)])
    config = types.GenerateContentConfig(response_schema=DummyTarget)

    deadline = asyncio.get_event_loop().time() + 10.0
    out, usage, attempts, hedged = await call_structured(
        client=client,
        contents=["test-prompt"],
        config=config,
        schema=DummyTarget,
        deadline=deadline,
        label="TestGemini",
    )

    assert out == expected
    assert isinstance(out, DummyTarget)
    assert out.message == "hello"
    assert out.count == 7
    assert usage.input_tokens == 42
    assert usage.output_tokens == 23  # 18 + 5
    assert attempts == 1
    assert hedged is False


@pytest.mark.asyncio
async def test_call_structured_retries_on_429_then_succeeds():
    err_429 = errors.APIError(429, "Resource exhausted")
    expected = DummyTarget(message="recovered", count=1)
    client = FakeGenAIClient([err_429, FakeResponse(parsed=expected)])
    config = types.GenerateContentConfig(response_schema=DummyTarget)

    deadline = asyncio.get_event_loop().time() + 15.0
    out, usage, attempts, hedged = await call_structured(
        client=client,
        contents=["test-prompt"],
        config=config,
        schema=DummyTarget,
        deadline=deadline,
        label="TestGemini",
    )

    assert out.message == "recovered"
    assert client.call_count == 2
    assert attempts == 2


@pytest.mark.asyncio
async def test_call_structured_timeout_raises_gemini_call_error():
    async def _hang(*args, **kwargs):
        await asyncio.sleep(10.0)

    client = MagicMock()
    client.aio.models.generate_content = _hang
    config = types.GenerateContentConfig(response_schema=DummyTarget)

    deadline = asyncio.get_event_loop().time() + 10.0
    with pytest.raises(GeminiCallError) as exc_info:
        await call_structured(
            client=client,
            contents=["test-prompt"],
            config=config,
            schema=DummyTarget,
            deadline=deadline,
            per_attempt_timeout=0.05,
            hedge_after_s=0.05,
            label="ProfileCall",
        )

    assert "ProfileCall call failed after retries" in str(exc_info.value)
