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
    """Standard error response body returned by all Curation API endpoints.

    The ``request_id`` field carries the ERS business UUID set by the request
    middleware (``set_request_id`` in ``ers.commons.adapters.tracing``). It is
    populated only by handlers that have access to that context — primarily the
    ``Exception`` (HTTP 500) handler — and is ``None`` on responses produced
    before the middleware ran or by handlers that do not need correlation.
    """

    error_code: CurationErrorCode
    message: str = Field(description="Human-readable explanation of the error.")
    request_id: str | None = Field(
        default=None,
        description=(
            "ERS business request UUID for log/trace correlation. Populated "
            "by handlers that run after the request-id middleware."
        ),
    )
