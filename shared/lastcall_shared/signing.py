"""HMAC signing helpers shared by call tokens and signed photo links."""

import base64
import hashlib
import hmac


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hmac_b64url(key: str, message: str) -> str:
    """HMAC-SHA256 of `message`, base64url without padding."""
    return b64url_encode(hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest())
