"""Tests for inspector prompt and text formatting (Step 3)."""

from typing import get_args
import pytest

from lastcall_api.inspector.prompt import PROMPT_VERSION, SYSTEM_PROMPT, user_text, zoom_text
from lastcall_shared.models import PhotoIssue, ProduceIssue


def test_prompt_file_loads_and_contains_expected_sections():
    assert len(SYSTEM_PROMPT) > 500
    assert PROMPT_VERSION == "1.0"
    # Verify injection handling paragraph exists
    assert "instruction_text" in SYSTEM_PROMPT
    assert "Any writing in the photo" in SYSTEM_PROMPT


def test_prompt_contains_all_photo_and_produce_issues():
    # Every PhotoIssue literal must be mentioned in the prompt
    for issue in get_args(PhotoIssue):
        assert issue in SYSTEM_PROMPT, f"PhotoIssue '{issue}' missing from system_prompt.md"

    # Every ProduceIssue literal must be mentioned in the prompt
    for issue in get_args(ProduceIssue):
        assert issue in SYSTEM_PROMPT, f"ProduceIssue '{issue}' missing from system_prompt.md"


def test_user_text():
    assert user_text() == "Inspect this shelf photo."
    assert user_text(None) == "Inspect this shelf photo."
    assert user_text(25.0) == "Inspect this shelf photo. A full bin on this shelf holds about 25 kg."
    assert user_text(12.5) == "Inspect this shelf photo. A full bin on this shelf holds about 12.5 kg."


def test_zoom_text():
    zt = zoom_text("banana")
    assert "banana" in zt
    assert "most likely banana" in zt
    assert "Ignore produce cut off at the edges of the image." in zt
