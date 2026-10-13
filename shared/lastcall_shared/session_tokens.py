"""Short-lived HMAC session token minting and verification (Milestone 2B Step 9).

Used to authenticate the browser's WebSocket connection to the Voice service:
1. API service mints a 120-second token on session creation:
   base64url(json{call_id, nonce, exp}).base64url(hmac_sha256)
2. Voice service verifies signature with APP_SIGNING_KEY and checks expiration.
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime

from pydantic import AwareDatetime


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(s: str) -> bytes:
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def mint(
    call_id: str,
    nonce: str,
    key: str,
    ttl: int = 120,
    now: AwareDatetime | datetime | None = None,
) -> str:
    """Mints a short-lived HMAC-signed session token.

    Args:
        call_id: The ID of the call session.
        nonce: The single-use nonce for the session.
        key: The secret HMAC signing key.
        ttl: Time to live in seconds (default 120s).
        now: Optional reference timestamp.
    """
    if not key or not key.strip():
        raise ValueError("Signing key cannot be empty")

    now_ts = now.timestamp() if now else time.time()
    payload = {
        "call_id": call_id,
        "nonce": nonce,
        "exp": int(now_ts + ttl),
    }
    p_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    p_b64 = _b64url_encode(p_bytes)
    sig = hmac.new(key.encode("utf-8"), p_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return f"{p_b64}.{sig_b64}"


def verify(
    token: str,
    key: str,
    now: AwareDatetime | datetime | None = None,
) -> tuple[bool, dict | None, str | None]:
    """Verifies a session token against key and expiration.

    Returns:
        (valid, payload, error_message)
    """
    if not key or not key.strip():
        raise ValueError("Signing key cannot be empty")

    now_ts = now.timestamp() if now else time.time()
    parts = token.split(".")
    if len(parts) != 2:
        return False, None, "Invalid token format"

    p_b64, sig_b64 = parts
    expected_sig = hmac.new(key.encode("utf-8"), p_b64.encode("utf-8"), hashlib.sha256).digest()

    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception:
        return False, None, "Invalid signature encoding"

    if not hmac.compare_digest(actual_sig, expected_sig):
        return False, None, "Invalid signature"

    try:
        payload = json.loads(_b64url_decode(p_b64).decode("utf-8"))
    except Exception:
        return False, None, "Invalid payload JSON"

    if not isinstance(payload, dict):
        return False, None, "Payload must be a JSON object"

    exp = payload.get("exp", 0)
    if exp < now_ts:
        return False, payload, "Token expired"

    if "call_id" not in payload or "nonce" not in payload:
        return False, payload, "Missing required token fields"

    return True, payload, None
