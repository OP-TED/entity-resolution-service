"""Unit tests for redis_messages error branches in get_message_object."""
import json

import pytest

from ers.commons.adapters.redis_messages import (
    SUPPORTED_REQUEST_CLASSES,
    SUPPORTED_RESPONSE_CLASSES,
    get_message_object,
)


def _to_bytes(data: dict) -> bytes:
    return json.dumps(data).encode("utf-8")


class TestGetMessageObjectErrors:
    def test_raises_when_type_field_is_missing(self):
        raw = _to_bytes({"ere_request_id": "x", "content": "y"})

        with pytest.raises(ValueError, match="'type' field"):
            get_message_object(raw, SUPPORTED_REQUEST_CLASSES)

    def test_raises_when_type_field_is_empty_string(self):
        raw = _to_bytes({"type": ""})

        with pytest.raises(ValueError, match="'type' field"):
            get_message_object(raw, SUPPORTED_REQUEST_CLASSES)

    def test_raises_when_type_is_unsupported(self):
        raw = _to_bytes({"type": "FullRebuildRequest"})

        with pytest.raises(ValueError, match='Unsupported message type: "FullRebuildRequest"'):
            get_message_object(raw, SUPPORTED_REQUEST_CLASSES)

    def test_raises_for_unsupported_type_in_response_classes(self):
        raw = _to_bytes({"type": "UnknownResponseType"})

        with pytest.raises(ValueError, match='Unsupported message type: "UnknownResponseType"'):
            get_message_object(raw, SUPPORTED_RESPONSE_CLASSES)
