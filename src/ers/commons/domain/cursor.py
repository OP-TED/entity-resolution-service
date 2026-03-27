"""Opaque cursor encoding and decoding for cursor-based pagination."""

import base64
import json
from datetime import datetime
from typing import Any

from ers.commons.domain.exceptions import InvalidCursorError


def encode_cursor(sort_value: float | datetime | None, last_id: str) -> str:
    """Encode sort value and document ID into an opaque cursor string."""
    serialized = sort_value.isoformat() if isinstance(sort_value, datetime) else sort_value
    payload = {"s": serialized, "i": last_id}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def decode_cursor(cursor: str) -> tuple[Any, str]:
    """Decode an opaque cursor into (sort_value, last_id).

    The sort_value may be a float, ISO datetime string, or None.
    Callers should convert based on the expected sort field type.

    Raises:
        InvalidCursorError: If the cursor is malformed.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(raw)
        return payload["s"], payload["i"]
    except Exception as exc:
        raise InvalidCursorError() from exc
