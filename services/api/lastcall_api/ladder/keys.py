"""Utility functions for produce keys."""

import re


def produce_key(name: str) -> str:
    """Normalises produce name into a clean alphanumeric key."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
