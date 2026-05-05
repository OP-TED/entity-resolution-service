"""Error envelope and error codes for the Curation API."""

from enum import StrEnum

from pydantic import Field

from ers.commons.domain.data_transfer_objects import FrozenDTO


class CurationErrorCode(StrEnum):
    """Machine-readable error codes returned in Curation API error responses."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    CONFLICT = "CONFLICT"
    APPLICATION_ERROR = "APPLICATION_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    SERVICE_ERROR = "SERVICE_ERROR"


class CurationErrorResponse(FrozenDTO):
    """Standard error response body returned by all Curation API endpoints."""

    error_code: CurationErrorCode
    message: str = Field(description="Human-readable explanation of the error.")
