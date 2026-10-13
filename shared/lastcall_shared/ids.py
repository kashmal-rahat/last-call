"""Identifier formats, one definition each. Every API boundary validates against these."""

import re
import secrets
import uuid
from datetime import datetime

INSPECTION_ID = re.compile(r"^insp_[a-z0-9_]{1,80}$")  # insp_20261013_142501_a1b2c3
ITEM_KEY = re.compile(r"^[a-z0-9_]{1,60}$")  # banana_top_left, banana_top_left_2
BRANCH_ID = re.compile(r"^[a-z0-9_]{1,30}$")  # johar_town
SHELF_ID = re.compile(r"^[a-z0-9_-]{1,40}$")
CALL_ID = re.compile(r"^call_[a-f0-9]{32}$")
PLACES_BUYER_ID = re.compile(r"^places:[A-Za-z0-9_-]{1,300}$")
BATCH_ID = re.compile(r"^insp_[a-z0-9_]{1,80}__[a-z0-9_]{1,60}__[a-z0-9_]{1,30}$")
E164_PATTERN = r"^\+[1-9]\d{7,14}$"  # E.164: up to 15 digits
E164 = re.compile(E164_PATTERN)


def make_batch_id(inspection_id: str, item_key: str, branch_id: str) -> str:
    """A batch is one item of one inspection, sold from one branch (D54); its scout list shares the key."""
    return f"{inspection_id}__{item_key}__{branch_id}"


def new_inspection_id(now: datetime) -> str:
    return f"insp_{now:%Y%m%d_%H%M%S}_{secrets.token_hex(3)}"


def new_call_id() -> str:
    return f"call_{uuid.uuid4().hex}"
