"""Smoke test for Gemini Flash and Gemini Live on Vertex AI."""

import asyncio
import io
import sys
import time

from google import genai
from google.genai import types
from PIL import Image
from pydantic import BaseModel

from lastcall_shared.config import get_settings

settings = get_settings()
PROJECT_ID = settings.GOOGLE_CLOUD_PROJECT
FLASH_MODEL = settings.GEMINI_FLASH_MODEL
LIVE_MODEL = settings.GEMINI_LIVE_MODEL
LOCATION = settings.GOOGLE_CLOUD_LOCATION


class SmokeAssessment(BaseModel):
    item: str
    condition_rating: int


async def smoke_flash() -> bool:
    print(f"\n[1/2] Testing Gemini Flash ({FLASH_MODEL}) in {LOCATION}...")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    # 1. Text
    t0 = time.time()
    resp_text = client.models.generate_content(
        model=FLASH_MODEL,
        contents="Say 'Assalam-o-Alaikum' and confirm you are operational.",
    )
    print(f"  ✓ Text call passed ({round((time.time() - t0)*1000)}ms): {resp_text.text.strip()[:60]}...")

    # 2. Vision
    img = Image.new("RGB", (64, 64), color="yellow")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    t0 = time.time()
    resp_img = client.models.generate_content(
        model=FLASH_MODEL,
        contents=[types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"), "What color is this?"],
    )
    print(f"  ✓ Vision call passed ({round((time.time() - t0)*1000)}ms): {resp_img.text.strip()[:40]}...")

    # 3. Structured Output
    t0 = time.time()
    resp_struct = client.models.generate_content(
        model=FLASH_MODEL,
        contents="Assess a crate of apples.",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SmokeAssessment,
        ),
    )
    print(f"  ✓ Structured call passed ({round((time.time() - t0)*1000)}ms): {resp_struct.text.strip()}")
    return True


async def smoke_live() -> bool:
    print(f"\n[2/2] Testing Gemini Live ({LIVE_MODEL}) in {LOCATION}...")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    config = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO])
    t0 = time.time()
    async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
        t_conn = round((time.time() - t0) * 1000)
        await session.send_client_content(
            turns=[types.Content(parts=[types.Part.from_text(text="سلام، کیا آپ تیار ہیں؟")])],
            turn_complete=True,
        )
        audio_bytes = 0
        async for resp in session.receive():
            if resp.server_content and resp.server_content.model_turn:
                for p in resp.server_content.model_turn.parts:
                    if p.inline_data:
                        audio_bytes += len(p.inline_data.data)
            if resp.server_content and resp.server_content.turn_complete:
                break
        t_total = round((time.time() - t0) * 1000)
        print(f"  ✓ Live native audio session passed (connect={t_conn}ms, total={t_total}ms, audio={audio_bytes} bytes)")
    return True


async def main():
    print("=== Last Call Gemini Smoke Verification ===")
    print(f"Project: {PROJECT_ID}")
    try:
        await smoke_flash()
        await smoke_live()
        print("\n>>> All Gemini smoke tests PASSED! <<<")
    except Exception as e:
        print(f"\n❌ Gemini smoke test failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
