"""JSON serialization helpers for evidence/audit payloads.

Decimal values are serialized as strings (never floats) so money survives
round trips exactly; dates as ISO strings.
"""

import datetime
from decimal import Decimal
from typing import Any


def jsonable(value: Any) -> Any:
    """Recursively convert a payload into JSON-storable types without losing precision."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    return value
