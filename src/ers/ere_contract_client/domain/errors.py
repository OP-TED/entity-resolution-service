"""Domain error types for the ERE Contract Client."""

from ers.commons.domain.exceptions import DomainError


class EREContractError(DomainError):
    """Base class for all ERE Contract Client domain errors."""


class InvalidRequestError(EREContractError):
    """Raised when a resolution request has an incomplete correlation triad.

    The triad (source_id, request_id, entity_type) must all be non-empty.
    An absent or None entity_mention also triggers this error.
    """


class SerializationError(EREContractError):
    """Raised when serialization of the request fails."""


class ChannelUnavailableError(EREContractError):
    """Raised when the message queue channel cannot accept the request (e.g. push returned 0)."""


class DeserializationError(EREContractError):
    """Raised when deserialization of a response message fails."""


class RedisConnectionError(EREContractError):
    """Raised when a message queue connection is refused or times out."""
