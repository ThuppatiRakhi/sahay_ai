"""Shared JSON contracts and schema utilities for SahayAI."""

import json
from pathlib import Path
from typing import Any, Dict

SCHEMA_PATH = Path(__file__).parent / "schemas.json"


def get_shared_schemas() -> Dict[str, Any]:
    """Load and return the central JSON schemas contract."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


__all__ = ["SCHEMA_PATH", "get_shared_schemas"]
