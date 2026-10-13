"""Buyer keys, hashing, and phone masking helpers (D50, D51).

Note: Rotating APP_SIGNING_KEY orphans phone-based do-not-call entries.
"""

import hashlib
import hmac

from pydantic import SecretStr


def phone_key(e164: str, secret: str | bytes | SecretStr) -> str:
    """Computes a keyed HMAC-SHA256 hash for an E.164 phone number.
    
    Returns 'phone:' followed by the first 32 hex chars of the digest.
    """
    if isinstance(secret, SecretStr):
        secret_bytes = secret.get_secret_value().encode("utf-8")
    elif isinstance(secret, str):
        secret_bytes = secret.encode("utf-8")
    else:
        secret_bytes = secret

    msg = f"phone:{e164}".encode("utf-8")
    digest = hmac.new(secret_bytes, msg, hashlib.sha256).hexdigest()[:32]
    return f"phone:{digest}"


def mask_phone(e164: str) -> str:
    """Masks phone preserving country code prefix and last 3 digits.
    
    e.g. '+92 300 1234567' / '+923001234567' -> '+92 ••••••• 567'
    """
    clean = "".join(c for c in e164 if c.isdigit() or c == "+")
    if not clean:
        return ""
    if clean.startswith("+92") and len(clean) >= 6:
        country = "+92"
        rest = clean[3:]
        bullets = "•" * (len(rest) - 3)
        return f"{country} {bullets} {rest[-3:]}"
    if clean.startswith("+") and len(clean) >= 6:
        country = clean[:3] if len(clean) > 8 else clean[:2]
        rest = clean[len(country):]
        bullets = "•" * max(1, len(rest) - 3)
        return f"{country} {bullets} {rest[-3:]}"
    if len(clean) >= 4:
        return "•" * (len(clean) - 3) + clean[-3:]
    return "•••"
