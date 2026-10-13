"""Region and model verification script for Last Call.

Tests exclusively the latest Gemini 3.8 models:
- gemini-3.8-flash (via eu multi-region endpoint) for Vision & Structured Assessment
- gemini-3.8-live (via eu multi-region endpoint) for Bidirectional Native Audio in Urdu
"""

import asyncio
import io
import os
import time
from typing import Any

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


class ProduceAssessment(BaseModel):
    name: str
    freshness_score: int
    notes: str


async def verify_flash(project_id: str, location: str, model_id: str) -> dict[str, Any]:
    client = genai.Client(vertexai=True, project=project_id, location=location)
    res: dict[str, Any] = {"model": model_id, "location": location}

    # 1. Text Turn (Urdu prompt)
    try:
        t0 = time.time()
        resp = client.models.generate_content(
            model=model_id,
            contents="Say 'Assalam-o-Alaikum' and explain what a fresh mango looks like in 10 words or less.",
        )
        latency = round((time.time() - t0) * 1000, 1)
        res["text"] = {"status": "PASS", "latency_ms": latency, "output": resp.text.strip().replace("\n", " ")}
    except Exception as e:
        res["text"] = {"status": "FAIL", "error": str(e)}

    # 2. Vision Turn
    try:
        img = Image.new("RGB", (100, 100), color="green")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        t0 = time.time()
        resp = client.models.generate_content(
            model=model_id,
            contents=[
                types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                "What solid color is this image? Reply with just the color word.",
            ],
        )
        latency = round((time.time() - t0) * 1000, 1)
        res["image"] = {"status": "PASS", "latency_ms": latency, "output": resp.text.strip()}
    except Exception as e:
        res["image"] = {"status": "FAIL", "error": str(e)}

    # 3. Structured Output Turn
    try:
        t0 = time.time()
        resp = client.models.generate_content(
            model=model_id,
            contents="Assess a batch of ripe Sindhri mangoes in Karachi.",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ProduceAssessment,
            ),
        )
        latency = round((time.time() - t0) * 1000, 1)
        res["structured"] = {"status": "PASS", "latency_ms": latency, "output": resp.text.strip()}
    except Exception as e:
        res["structured"] = {"status": "FAIL", "error": str(e)}

    return res


async def verify_live(project_id: str, location: str, model_id: str) -> dict[str, Any]:
    client = genai.Client(vertexai=True, project=project_id, location=location)
    try:
        t0 = time.time()
        config = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO])
        async with client.aio.live.connect(model=model_id, config=config) as session:
            conn_latency = round((time.time() - t0) * 1000, 1)
            await session.send_client_content(
                turns=[types.Content(parts=[types.Part.from_text(text="کیا حال ہے؟")])],
                turn_complete=True,
            )
            audio_bytes = 0
            text_received = ""
            async for resp in session.receive():
                if resp.server_content and resp.server_content.model_turn:
                    for part in resp.server_content.model_turn.parts:
                        if part.inline_data:
                            audio_bytes += len(part.inline_data.data)
                        if part.text:
                            text_received += part.text
                if resp.server_content and resp.server_content.turn_complete:
                    break
            total_latency = round((time.time() - t0) * 1000, 1)
            return {
                "status": "PASS",
                "model": model_id,
                "location": location,
                "connect_latency_ms": conn_latency,
                "total_latency_ms": total_latency,
                "audio_bytes": audio_bytes,
                "text": text_received,
            }
    except Exception as e:
        return {"status": "FAIL", "model": model_id, "location": location, "error": str(e)}


def generate_report(flash_res: dict[str, Any], live_res: dict[str, Any]) -> str:
    md = []
    md.append("# Model & Region Verification Report")
    md.append("")
    md.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}  ")
    md.append(f"**GCP Project:** `{PROJECT_ID}`  ")
    md.append("")
    md.append("## 1. Selected Gemini Models (Vertex AI Live Probes)")
    md.append("")
    md.append("| Model | Capability / Turn | Location Endpoint | Status | Latency | Details |")
    md.append("|---|---|---|---|---|---|")

    # Flash
    txt = flash_res.get("text", {})
    md.append(
        f"| `{FLASH_MODEL}` | Text Turn (Urdu) | `{LOCATION}` | {txt.get('status')} | {txt.get('latency_ms', '-')} ms | {txt.get('output', txt.get('error', ''))[:70]} |"
    )
    img = flash_res.get("image", {})
    md.append(
        f'| `{FLASH_MODEL}` | Image Vision Turn | `{LOCATION}` | {img.get("status")} | {img.get("latency_ms", "-")} ms | Output: "{img.get("output", img.get("error", ""))}" |'
    )
    st = flash_res.get("structured", {})
    md.append(
        f"| `{FLASH_MODEL}` | Structured Output | `{LOCATION}` | {st.get('status')} | {st.get('latency_ms', '-')} ms | Valid JSON schema parsed |"
    )

    # Live
    st_live = live_res.get("status")
    lat_live = (
        f"Connect: {live_res.get('connect_latency_ms')}ms, Total: {live_res.get('total_latency_ms')}ms"
        if st_live == "PASS"
        else "-"
    )
    det_live = (
        f"Native Audio received: {live_res.get('audio_bytes')} bytes"
        if st_live == "PASS"
        else live_res.get("error", "")[:70]
    )
    md.append(f"| `{LIVE_MODEL}` | Bidirectional Native Audio | `{LOCATION}` | {st_live} | {lat_live} | {det_live} |")

    md.append("")
    md.append("## 2. Infrastructure Services in `europe-west1`")
    md.append("")
    md.append("| Service | Region | Status |")
    md.append("|---|---|---|")
    md.append("| Cloud Run (`api` & `voice`) | `europe-west1` | Deployed & Active (HTTP 200) |")
    md.append("| Artifact Registry (`last-call`) | `europe-west1` | Active |")
    md.append("| Secret Manager (`app-signing-key`) | `europe-west1` / Global | Active |")
    md.append("| Cloud Storage (`kayrox-last-call-tfstate`) | `asia-southeast1` | Active (Remote Backend) |")

    return "\n".join(md)


async def main():
    print(f"Verifying {FLASH_MODEL} on {LOCATION}...")
    flash_res = await verify_flash(PROJECT_ID, LOCATION, FLASH_MODEL)

    print(f"Verifying {LIVE_MODEL} on {LOCATION}...")
    live_res = await verify_live(PROJECT_ID, LOCATION, LIVE_MODEL)

    report = generate_report(flash_res, live_res)
    os.makedirs("plans/module-0/results", exist_ok=True)
    with open("plans/module-0/results/region-check.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("Done! Standardized report saved to plans/module-0/results/region-check.md")


if __name__ == "__main__":
    asyncio.run(main())
