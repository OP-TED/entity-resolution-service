"""Error envelope and error codes for the ERS REST API."""

from enum import StrEnum

from pydantic import Field

from ers.commons.domain.data_transfer_objects import FrozenDTO


class ErrorCode(StrEnum):
    """Machine-readable error codes returned in error responses."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    PARSING_FAILED = "PARSING_FAILED"
    MENTION_NOT_FOUND = "MENTION_NOT_FOUND"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SERVICE_ERROR = "SERVICE_ERROR"
    SERVICE_TIMEOUT = "SERVICE_TIMEOUT"


class ErrorResponse(FrozenDTO):
    """Standard error response body returned by all ERS REST API endpoints."""

    error_code: ErrorCode
    detail: str = Field(description="Human-readable explanation of the error.")
