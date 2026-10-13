"""Last Call voice service: the Negotiator agent on a live audio connection.

- `/ws/call`: the judge's browser call (the demo page opens it with a single-use call token).
- `/phone/stream`: the phone demo's Twilio Media Stream (Module 9, D61), off unless switched on.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.websockets import WebSocket

from lastcall_shared.config import get_settings
from lastcall_shared.logging_utils import setup_structured_logging
from lastcall_voice.live_session import handle_live_call_websocket
from lastcall_voice.phone.bridge import handle_twilio_stream

SERVICE_NAME = "voice"
VERSION = "0.1.0"

logger = setup_structured_logging(service_name=SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # fails fast on missing or invalid settings (e.g. a short APP_SIGNING_KEY)
    logger.info("Voice service starting up", extra={"extra_fields": {"version": VERSION}})
    yield
    logger.info("Voice service shutting down")


app = FastAPI(title="Last Call Voice Agent", version=VERSION, lifespan=lifespan)


@app.get("/health")
@app.get("/healthz")
async def healthz():
    return {"service": SERVICE_NAME, "version": VERSION, "commit": get_settings().GIT_COMMIT, "status": "healthy"}


@app.websocket("/ws/call")
async def ws_call_endpoint(websocket: WebSocket):
    await handle_live_call_websocket(websocket)


@app.websocket("/phone/stream")
async def phone_stream_endpoint(websocket: WebSocket):
    await handle_twilio_stream(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=get_settings().PORT)
