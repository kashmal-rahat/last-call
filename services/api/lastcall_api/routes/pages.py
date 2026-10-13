"""Health, the judge page, and the page's static lookups (sample photos, branches)."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from lastcall_api.deps import demo_rules
from lastcall_shared.config import get_settings

logger = logging.getLogger("lastcall_api.pages")

SERVICE_NAME = "api"
VERSION = "0.1.0"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

router = APIRouter()


@router.get("/health")
@router.get("/healthz")
async def healthz() -> dict:
    return {"service": SERVICE_NAME, "version": VERSION, "commit": get_settings().GIT_COMMIT, "status": "healthy"}


@router.get("/demo")
async def get_demo_page() -> FileResponse:
    """The judge demo page."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Demo page not found")
    return FileResponse(html_path)


@router.get("/demo/samples")
async def get_demo_samples() -> list:
    """Sample shelf photos the page offers."""
    samples_file = STATIC_DIR / "samples" / "samples.json"
    if not samples_file.exists():
        return []
    try:
        return json.loads(samples_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("failed_loading_samples", extra={"error": str(exc)})
        return []


@router.get("/demo/branches")
async def get_demo_branches() -> dict:
    """The demo mart's branches, without coordinates."""
    rules = demo_rules()
    return {
        "branches": [{"branch_id": b.branch_id, "name": b.name, "location": b.location} for b in rules.branches],
        "default_branch_id": rules.default_branch_id,
    }
