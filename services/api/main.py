"""Last Call API service skeleton."""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from lastcall_shared.logging_utils import setup_structured_logging

SERVICE_NAME = "api"
VERSION = "0.1.0"
COMMIT = os.getenv("GIT_COMMIT", "dev")

logger = setup_structured_logging(service_name=SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Security requirement: check APP_SIGNING_KEY presence and log ONLY its presence/absence, NEVER the value
    signing_key_present = bool(os.getenv("APP_SIGNING_KEY", "").strip())
    logger.info(
        "API service starting up",
        extra={"extra_fields": {"app_signing_key_present": signing_key_present, "version": VERSION}},
    )
    yield
    logger.info("API service shutting down")


app = FastAPI(title="Last Call API", version=VERSION, lifespan=lifespan)


@app.get("/health")
@app.get("/healthz")
async def healthz():
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "commit": COMMIT,
        "status": "healthy",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
