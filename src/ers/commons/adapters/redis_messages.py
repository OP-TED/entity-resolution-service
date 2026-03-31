"""Utilities for parsing raw message bytes into domain model instances."""

import json
from collections.abc import Mapping

from erspec.models.ere import (
    EntityMentionResolutionRequest,
    EntityMentionResolutionResponse,
    EREErrorResponse,
    EREMessage,
    # FullRebuildRequest,  # Not yet implemented in erspec.models.ere
    # FullRebuildResponse,  # Not yet implemented in erspec.models.ere
    ERERequest,
    EREResponse,
)

# Maps message 'type' field to request classes. We use explicit dicts rather than
# dynamic discovery: simpler, more transparent, and sufficient for current needs.
# If new message types become frequent, consider a plugin registry then.
SUPPORTED_REQUEST_CLASSES = {
    cls.__name__: cls
    for cls in [EntityMentionResolutionRequest]
    # FullRebuildRequest,  # Add when erspec implements it
}

# Maps message 'type' field to response classes. We use explicit dicts rather than
# dynamic discovery: simpler, more transparent, and sufficient for current needs.
# If new message types become frequent, consider a plugin registry then.
SUPPORTED_RESPONSE_CLASSES = {
    cls.__name__: cls
    for cls in [EntityMentionResolutionResponse, EREErrorResponse]
    # FullRebuildResponse,  # Add when erspec implements it
}


def get_message_object(
    raw_msg: bytes,
    supported_classes: Mapping[str, type[EREMessage]],
    encoding: str = "utf-8",
) -> EREMessage:
    """Parse raw message bytes into a request or response domain model instance.

    Args:
        raw_msg: Serialized JSON message (bytes).
        supported_classes: mapping 'type' field values to message classes.
        encoding: Character encoding (default: utf-8).

    Returns:
        Deserialized domain model instance (ERERequest or EREResponse).

    Raises:
        ValueError: If message lacks 'type' field or type is not in supported_classes.
    """
    msg_str = raw_msg.decode(encoding)
    try:
        msg_json = json.loads(msg_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Message is not valid JSON: {exc}") from exc

    message_type = msg_json.get("type")
    if not message_type:
        raise ValueError("Message without 'type' field")

    message_class = supported_classes.get(message_type)
    if not message_class:
        raise ValueError(f'Unsupported message type: "{message_type}"')

    return message_class.model_validate_json(msg_str)


def get_response_from_message(raw_msg: bytes, encoding: str = "utf-8") -> EREResponse:
    """Parse raw message bytes into a response domain model instance."""
    return get_message_object(raw_msg, SUPPORTED_RESPONSE_CLASSES, encoding)


def get_request_from_message(raw_msg: bytes, encoding: str = "utf-8") -> ERERequest:
    """Parse raw message bytes into a request domain model instance."""
    return get_message_object(raw_msg, SUPPORTED_REQUEST_CLASSES, encoding)
