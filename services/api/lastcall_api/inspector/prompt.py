"""Prompt definitions and request text builders for Freshness Inspector."""

from pathlib import Path

PROMPT_VERSION = "1.0"

_PROMPT_PATH = Path(__file__).parent / "system_prompt.md"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


def user_text(bin_capacity_kg: float | None = None) -> str:
    """Builds the pass-1 user prompt for inspecting a shelf photo."""
    text = "Inspect this shelf photo."
    if bin_capacity_kg is not None:
        # Avoid trailing zeros if integer
        cap_str = f"{int(bin_capacity_kg)}" if bin_capacity_kg.is_integer() else f"{bin_capacity_kg}"
        text += f" A full bin on this shelf holds about {cap_str} kg."
    return text


def zoom_text(name: str) -> str:
    """Builds the pass-2 user prompt for inspecting a cropped close-up."""
    return (
        f"This is a close-up of one group from a larger shelf photo, most likely {name}. "
        "Report only that group as a single item, judged from this close-up. "
        "Ignore produce cut off at the edges of the image."
    )
