"""Domain exceptions for the Resolution Coordinator service layer."""

from ers.commons.services.exceptions import ApplicationError


class CoordinatorException(ApplicationError):
    """Base exception for all Resolution Coordinator errors."""


class ResolutionTimeoutException(CoordinatorException):
    """Raised when a fatal timeout occurs in the resolution pipeline.

    Covers two scenarios:
    - MongoDB is unavailable during a provisional decision write (single-mention).
    - The bulk request time budget is exceeded before all mentions are resolved.

    NOT raised on ERE timeout — that path issues a provisional identifier instead.
    """


class ParsingFailedException(CoordinatorException):
    """Raised when RequestRegistryService fails to parse the incoming entity mention.

    The request is NOT registered in the Request Registry when this is raised.

    Args:
        message: Human-readable description of the failure.
        cause: The original exception raised by the parser, preserved for inspection.
    """

    def __init__(self, message: str, cause: Exception) -> None:
        self.cause = cause
        super().__init__(message)


class EnginePublishFailedException(CoordinatorException):
    """Raised when the ERE Contract Client cannot publish the request to Redis.

    Signals a RedisConnectionError at the publish boundary. The coordinator
    uses this as a trigger for graceful degradation — issuing a provisional
    identifier rather than failing the request.

    Args:
        message: Human-readable description of the failure.
        cause: The original RedisConnectionError, preserved for inspection.
    """

    def __init__(self, message: str, cause: Exception) -> None:
        self.cause = cause
        super().__init__(message)
