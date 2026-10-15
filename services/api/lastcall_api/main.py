"""Last Call api service: the judge demo page and the Inspector, Ladder, Scout and call handoff.

Routes live in `lastcall_api.routes` (one module per area); shared request helpers in
`lastcall_api.deps`. This module only assembles the app.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from lastcall_api import item_photos, phone_demo
from lastcall_api.deps import check_ip_limit, photo_store_for, store_for, verify_access_code
from lastcall_api.routes import calls, decide, inspect, pages, scout
from lastcall_api.routes.pages import SERVICE_NAME, STATIC_DIR, VERSION
from lastcall_shared.config import get_settings
from lastcall_shared.logging_utils import setup_structured_logging

logger = setup_structured_logging(service_name=SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()  # fails fast on missing or invalid settings (e.g. a short APP_SIGNING_KEY)
    logger.info(
        "API service starting up",
        extra={
            "extra_fields": {
                "version": VERSION,
                "demo_access_code_present": bool((settings.DEMO_ACCESS_CODE or "").strip()),
                "voice_ws_url_present": bool(settings.VOICE_WS_URL),
            }
        },
    )
    yield
    # Cloud Run allows 10 s after SIGTERM: let shelf photos still uploading finish (D72), within 8 s
    await item_photos.wait_for_shelf_photos(timeout=8)
    logger.info("API service shutting down")


app = FastAPI(title="Last Call API", version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def no_cache_for_the_page(request: Request, call_next):
    """The page and its scripts are revalidated on every load, so a deploy reaches judges at once."""
    response = await call_next(request)
    if request.url.path == "/demo" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

for module in (pages, inspect, decide, scout, calls):
    app.include_router(module.router)

# Item photos (D62): signed crops the agent sends buyers.
app.include_router(
    item_photos.build_router(get_store=lambda: store_for(app), get_photo_store=lambda: photo_store_for(app))
)

# Phone demo (Module 9): every endpoint answers 404 unless PHONE_DEMO_ENABLED=true.
app.include_router(
    phone_demo.build_router(
        verify_access_code=verify_access_code,
        get_store=lambda: store_for(app),
        check_ip_limit=check_ip_limit,
        get_dialer=lambda: getattr(app.state, "phone_dialer", phone_demo.dial_twilio),
    )
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=get_settings().PORT)
