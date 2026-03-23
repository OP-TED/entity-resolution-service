"""Domain error types for the ERE Contract Client."""

from erspec.models.core import EntityMentionIdentifier

from ers.commons.domain.exceptions import DomainError


class EREContractError(DomainError):
    """Base class for all ERE Contract Client domain errors."""


class InvalidRequestError(EREContractError):
    """Raised when a resolution request has an incomplete correlation triad.

    The triad (source_id, request_id, entity_type) must all be non-empty.
    An absent or None entity_mention also triggers this error.

    Use the specific subclasses below to raise with structured context.
    """


class MissingEntityMentionError(InvalidRequestError):
    """Raised when entity_mention is absent on a resolution request."""

    def __init__(self) -> None:
        super().__init__("entity_mention is required")


class MissingSourceIdError(InvalidRequestError):
    """Raised when source_id is empty in the correlation triad.

    Attributes:
        identifier: The partial triad that triggered the error.
    """

    def __init__(self, identifier: EntityMentionIdentifier) -> None:
        self.identifier = identifier
        super().__init__(
            f"source_id is required; triad has "
            f"request_id='{identifier.request_id}', entity_type='{identifier.entity_type}'"
        )


class MissingRequestIdError(InvalidRequestError):
    """Raised when request_id is empty in the correlation triad.

    Attributes:
        identifier: The partial triad that triggered the error.
    """

    def __init__(self, identifier: EntityMentionIdentifier) -> None:
        self.identifier = identifier
        super().__init__(
            f"request_id is required; triad has "
            f"source_id='{identifier.source_id}', entity_type='{identifier.entity_type}'"
        )


class MissingEntityTypeError(InvalidRequestError):
    """Raised when entity_type is empty in the correlation triad.

    Attributes:
        identifier: The partial triad that triggered the error.
    """

    def __init__(self, identifier: EntityMentionIdentifier) -> None:
        self.identifier = identifier
        super().__init__(
            f"entity_type is required; triad has "
            f"source_id='{identifier.source_id}', request_id='{identifier.request_id}'"
        )


class SerializationError(EREContractError):
    """Raised when serialization of the request fails."""


class ChannelUnavailableError(EREContractError):
    """Raised when the message queue channel cannot accept the request (e.g. push returned 0)."""


class DeserializationError(EREContractError):
    """Raised when deserialization of a response message fails."""


class RedisConnectionError(EREContractError):
    """Raised when a message queue connection is refused or times out."""
