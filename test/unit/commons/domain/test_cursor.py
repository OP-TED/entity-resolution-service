from datetime import UTC, datetime

import pytest

from ers.commons.domain.cursor import decode_cursor, encode_cursor
from ers.commons.domain.exceptions import InvalidCursorError


class TestEncodeDecode:
    def test_roundtrip_float_value(self) -> None:
        cursor = encode_cursor(0.75, "decision-123")
        value, last_id = decode_cursor(cursor)

        assert value == 0.75
        assert last_id == "decision-123"

    def test_roundtrip_datetime_value(self) -> None:
        dt = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        cursor = encode_cursor(dt, "decision-456")
        value, last_id = decode_cursor(cursor)

        assert value == dt.isoformat()
        assert last_id == "decision-456"

    def test_roundtrip_none_value(self) -> None:
        cursor = encode_cursor(None, "decision-789")
        value, last_id = decode_cursor(cursor)

        assert value is None
        assert last_id == "decision-789"

    def test_cursor_is_url_safe(self) -> None:
        cursor = encode_cursor(0.5, "id-123")
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-=")

        assert all(c in allowed for c in cursor)


class TestDecodeInvalid:
    def test_garbage_string_raises_error(self) -> None:
        with pytest.raises(InvalidCursorError):
            decode_cursor("not-a-valid-cursor!!!")

    def test_empty_string_raises_error(self) -> None:
        with pytest.raises(InvalidCursorError):
            decode_cursor("")
