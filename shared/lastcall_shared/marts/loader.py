"""Loader for mart rules and pricing data."""

import json
from functools import lru_cache
from pathlib import Path

from lastcall_shared.models import MartRules

MARTS_DIR = Path(__file__).parent


@lru_cache
def load_mart_rules(mart_id: str) -> MartRules:
    """Loads and validates MartRules from JSON by mart_id.

    Raises KeyError if the mart configuration does not exist.
    """
    file_path = MARTS_DIR / f"{mart_id}.json"
    if not file_path.is_file():
        raise KeyError(f"Unknown mart: {mart_id}")

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return MartRules.model_validate(data)
    except Exception as e:
        if isinstance(e, KeyError):
            raise
        raise ValueError(f"Failed to load mart rules for '{mart_id}': {e}") from e
