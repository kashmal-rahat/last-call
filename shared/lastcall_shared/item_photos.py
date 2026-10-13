"""Signed links to an item's photo (D62).

The api keeps each inspected shelf photo for a day and serves a crop of one item at
`/demo/item-photos/{inspection_id}/{item_key}.jpg`. The link carries an expiry and an
HMAC signature (APP_SIGNING_KEY), so it can be handed to the buyer's browser view or to
Twilio for WhatsApp without exposing the bucket or an access code.
"""

import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode

LINK_TTL_S = 3600


def item_photo_path(inspection_id: str, item_key: str) -> str:
    return f"/demo/item-photos/{inspection_id}/{item_key}.jpg"


def _signature(inspection_id: str, item_key: str, expires: int, key: str) -> str:
    message = f"item-photo:{inspection_id}:{item_key}:{expires}".encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def sign_item_photo_url(
    base_url: str,
    inspection_id: str,
    item_key: str,
    *,
    key: str,
    now: float | None = None,
    ttl_s: int = LINK_TTL_S,
) -> str:
    """An absolute, time-limited link to the item's photo."""
    if not key.strip():
        raise ValueError("Signing key cannot be empty")
    expires = int((now if now is not None else time.time()) + ttl_s)
    query = urlencode({"exp": expires, "sig": _signature(inspection_id, item_key, expires, key)})
    return f"{base_url.rstrip('/')}{item_photo_path(inspection_id, item_key)}?{query}"


def verify_item_photo_signature(
    inspection_id: str,
    item_key: str,
    expires: int,
    signature: str,
    *,
    key: str,
    now: float | None = None,
) -> bool:
    if not key.strip() or expires < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(signature, _signature(inspection_id, item_key, expires, key))
