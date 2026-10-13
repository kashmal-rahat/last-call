"""Test model and configuration policy enforcement (Milestone 2B Step 7.5).

Rules:
1. Only gemini-3.8-live and gemini-3.8-flash are allowed in code and config.
2. Only Vertex multi-region location 'eu' is allowed.
3. Settings raises ValidationError on any invalid model or location.
4. All tracked code and config files are scanned for model ID compliance.
"""

import re
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from lastcall_shared.config import Settings, get_settings

ALLOWED_MODELS = {"gemini-3.8-live", "gemini-3.8-flash"}
MODEL_REGEX = re.compile(r"gemini-[0-9a-z.\-]+")
VALID_EXTENSIONS = {".py", ".tf", ".toml", ".j2", ".json"}


def test_settings_valid_defaults():
    """Default Settings must have only allowed models and location 'eu'."""
    settings = Settings()
    assert settings.GEMINI_FLASH_MODEL in ALLOWED_MODELS
    assert settings.GEMINI_LIVE_MODEL in ALLOWED_MODELS
    assert settings.GOOGLE_CLOUD_LOCATION == "eu"
    assert settings.GOOGLE_GENAI_USE_VERTEXAI is True


def test_settings_rejects_unapproved_flash_model():
    """Settings must raise ValidationError when given unapproved flash model."""
    bad_model = "gemini-" + "2.5-flash"
    with pytest.raises(ValidationError):
        Settings(GEMINI_FLASH_MODEL=bad_model)


def test_settings_rejects_unapproved_live_model():
    """Settings must raise ValidationError when given unapproved live model."""
    bad_model = "gemini-" + "2.0-flash-exp"
    with pytest.raises(ValidationError):
        Settings(GEMINI_LIVE_MODEL=bad_model)


def test_settings_rejects_unapproved_location():
    """Settings must raise ValidationError when given unapproved location."""
    with pytest.raises(ValidationError):
        Settings(GOOGLE_CLOUD_LOCATION="us-central1")


def test_get_settings_cached():
    """get_settings() returns a cached instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_settings_requires_valid_signing_key(monkeypatch):
    """Settings must raise ValidationError when APP_SIGNING_KEY is missing or too short (< 32 chars)."""
    # 1. Missing key
    monkeypatch.delenv("APP_SIGNING_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    # 2. Too short (< 32 chars)
    monkeypatch.setenv("APP_SIGNING_KEY", "too-short-secret-key-12345")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    # 3. Valid key (>= 32 chars)
    monkeypatch.setenv("APP_SIGNING_KEY", "a" * 32)
    s = Settings(_env_file=None)
    assert s.APP_SIGNING_KEY.get_secret_value() == "a" * 32


def test_scan_tracked_files_for_unapproved_models():
    """Scan all tracked files (excluding docs/ and plans/) for unapproved Gemini models."""
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = result.stdout.strip().splitlines()

    violations = []
    for rel_path in tracked_files:
        p = repo_root / rel_path
        # Exclude docs/ and plans/
        if rel_path.startswith("docs/") or rel_path.startswith("plans/"):
            continue
        # Check extensions or .env.example
        if p.suffix not in VALID_EXTENSIONS and p.name != ".env.example":
            continue
        if not p.is_file():
            continue

        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            matches = MODEL_REGEX.findall(line)
            for m in matches:
                if m not in ALLOWED_MODELS:
                    violations.append(f"{rel_path}:{line_no}: Found forbidden model '{m}' in line: {line.strip()}")

    assert not violations, "Forbidden Gemini models detected in codebase:\n" + "\n".join(violations)
