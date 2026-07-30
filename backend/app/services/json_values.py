from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def json_safe_value(value: Any) -> Any:
    """Recursively convert database/domain values to JSON-native values."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe_value(item) for item in value]
    return value


def json_safe_dict(value: Any) -> dict[str, Any]:
    return json_safe_value(dict(value))
