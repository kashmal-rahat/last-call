"""Configuration and model policy settings for Last Call.

Only two Gemini models are permitted:
- gemini-3.8-live (the voice negotiator)
- gemini-3.8-flash (text mode, simulator buyer/judge, price-guard fallback, call summary)

Both models run on Vertex AI multi-region location 'eu' (D12, D13).
Any other model ID or location fails at startup.
"""

from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with strict model and location validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Model and Cloud Policy (Strictly validated)
    GEMINI_LIVE_MODEL: Literal["gemini-3.8-live"] = "gemini-3.8-live"
    GEMINI_FLASH_MODEL: Literal["gemini-3.8-flash"] = "gemini-3.8-flash"
    GOOGLE_CLOUD_PROJECT: str = "kayrox-last-call"
    GOOGLE_CLOUD_LOCATION: Literal["eu"] = "eu"
    GOOGLE_GENAI_USE_VERTEXAI: bool = True

    # Voice Agent Settings
    AGENT_VOICE: str = "Puck"
    AGENT_GENDER: Literal["male", "female"] = "male"
    MAX_CALL_SECONDS: int = 300
    MAX_SESSIONS_PER_INSTANCE: int = 4
    ALLOWED_ORIGINS: str = "*"

    # Service & Security
    APP_SIGNING_KEY: str | None = None
    DEMO_ACCESS_CODE: str | None = None
    DEMO_DAILY_SESSION_CAP: int = 10
    VOICE_WS_URL: str | None = None

    # Service Defaults
    PORT: int = 8080
    ENVIRONMENT: str = "development"


@lru_cache
def get_settings() -> Settings:
    """Returns the cached application settings instance."""
    return Settings()
