"""Transcript price guard (v2: digits only, with no word dictionary).

Per Module 2 Step 4 v2:
The hard guarantee is confirm_deal, which cannot save a price below the floor.
The guard catches a wrong price being spoken/written, so it is cheap,
deterministic, and free of false positives.
"""

import asyncio
import json
import re
from typing import Any, Literal

from lastcall_shared.config import get_settings

URDU_DIGITS = {
    "۰": "0",
    "۱": "1",
    "۲": "2",
    "۳": "3",
    "۴": "4",
    "۵": "5",
    "۶": "6",
    "۷": "7",
    "۸": "8",
    "۹": "9",
}

PREFIX_REGEX = re.compile(r"(?i)^(?:rs|₨|₹|pkr)$")
SUFFIX_WORDS = {"rupay", "rupaye", "rupees", "روپے", "روپیہ"}
SPOKEN_PRICE_CUES = {"rupay", "rupaye", "rupees", "روپے", "روپیہ", "sau", "سو", "hazaar", "ہزار"}


def normalise_urdu_digits(text: str) -> str:
    """Normalises Eastern Arabic / Urdu digits to ASCII Western digits."""
    return "".join(URDU_DIGITS.get(ch, ch) for ch in text)


def find_prices(text: str) -> list[int]:
    """Finds all digit-based prices attached to currency markers.

    Rules:
    1. Prefix markers ('Rs', 'Rs.', '₨', '₹', 'PKR') bind ONLY to the number immediately after them.
    2. Suffix markers are rupee WORDS only ('rupay', 'rupaye', 'rupees', 'روپے', 'روپیہ'),
       and must come IMMEDIATELY after the number (0 tokens between).
    3. Each currency marker binds to at most one number. Prefix binding wins over suffix binding.
    """
    norm = normalise_urdu_digits(text)
    # Normalise 'Rs.' to 'Rs' so period is not treated as a separator token
    norm = re.sub(r"(?i)\brs\.\s*", "Rs ", norm)
    # Separate attached prefix currency symbols from digits (e.g. ₹110 -> ₹ 110)
    norm = re.sub(r"(?i)(rs|₨|₹|pkr)(\d)", r"\1 \2", norm)

    raw_tokens = re.findall(r"[\w۰-۹]+(?:,[\w۰-۹]+)*|[^\s\w]+", norm)
    tokens = [t.strip() for t in raw_tokens if t.strip()]

    prices: list[int] = []
    bound_numbers: set[int] = set()

    # Rule 1 & 3: Prefix markers bind ONLY to the number immediately after them (wins over suffix)
    for i in range(len(tokens) - 1):
        if PREFIX_REGEX.fullmatch(tokens[i]):
            clean_num = tokens[i + 1].replace(",", "")
            if clean_num.isdigit():
                prices.append(int(clean_num))
                bound_numbers.add(i + 1)

    # Rule 2 & 3: Suffix markers (rupee words only) IMMEDIATELY after number (0 tokens between)
    for i in range(len(tokens) - 1):
        clean_num = tokens[i].replace(",", "")
        if clean_num.isdigit() and i not in bound_numbers:
            next_t = tokens[i + 1].lower()
            if next_t in SUFFIX_WORDS:
                prices.append(int(clean_num))
                bound_numbers.add(i)

    return prices


# Alias for backward compatibility
find_spoken_prices = find_prices


def classify(
    prices: list[int],
    floor: int,
    approved_prices: list[int],
    current_price: int,
) -> Literal["below_floor", "unapproved", "ok"]:
    """Classifies prices against the floor and negotiation state.

    - below_floor if any price < floor
    - unapproved if any price < current_price and not in approved_prices and >= floor
    - otherwise ok
    """
    has_unapproved = False
    for p in prices:
        if p < floor:
            return "below_floor"
        if p < current_price and p not in approved_prices:
            has_unapproved = True

    if has_unapproved:
        return "unapproved"
    return "ok"


def has_spoken_price_cue(text: str) -> bool:
    """Checks whether text contains a spoken price cue."""
    lower = text.lower()
    return any(cue in lower for cue in SPOKEN_PRICE_CUES)


async def fallback_extract_prices(
    text: str,
    client: Any,
    model: str | None = None,
    timeout: float = 3.0,
) -> tuple[list[int], bool]:
    """Voice mode fallback: calls Flash when no digit price is found but cues exist.

    Returns (prices, unchecked). If timeout or error occurs, unchecked=True.
    """
    model_name = model or get_settings().GEMINI_FLASH_MODEL
    prompt = (
        "You are auditing an Urdu sales call utterance.\n"
        "List the per-unit prices the speaker offers or agrees to, not prices the other person mentioned.\n"
        f"Utterance: {text}\n"
        'Respond in strictly valid JSON: {"agent_offered_prices": [int]}'
    )
    try:
        from google.genai import types

        coro = client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        resp = await asyncio.wait_for(coro, timeout=timeout)
        data = json.loads(resp.text)
        raw_prices = data.get("agent_offered_prices", [])
        return [int(p) for p in raw_prices if isinstance(p, (int, float))], False
    except Exception:
        return [], True
