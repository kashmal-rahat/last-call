"""Last Call Voice service."""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from lastcall_shared.logging_utils import setup_structured_logging

SERVICE_NAME = "voice"
VERSION = "0.1.0"
COMMIT = os.getenv("GIT_COMMIT", "dev")

logger = setup_structured_logging(service_name=SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Voice service starting up", extra={"extra_fields": {"version": VERSION}})
    yield
    logger.info("Voice service shutting down")


app = FastAPI(title="Last Call Voice Agent", version=VERSION, lifespan=lifespan)


@app.get("/health")
@app.get("/healthz")
async def healthz():
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "commit": COMMIT,
        "status": "healthy",
    }


from starlette.websockets import WebSocket
from lastcall_voice.live_session import handle_live_call_websocket


@app.websocket("/ws/call")
async def ws_call_endpoint(websocket: WebSocket):
    await handle_live_call_websocket(websocket)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
