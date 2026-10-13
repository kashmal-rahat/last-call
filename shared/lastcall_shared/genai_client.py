"""One cached Gemini (Vertex AI) client per process, configured from Settings (D12, D13)."""

from functools import lru_cache

from google import genai

from lastcall_shared.config import get_settings


@lru_cache
def get_genai_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(
        vertexai=settings.GOOGLE_GENAI_USE_VERTEXAI,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.GOOGLE_CLOUD_LOCATION,
    )
