class ApplicationError(Exception):
    """Base exception for application-level errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(ApplicationError):
    """Raised when a requested entity is not found."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        message = f"{entity_type} with id '{entity_id}' not found"
        super().__init__(message)


class ServiceUnavailableError(ApplicationError):
    """Raised when a required backend service is unreachable.

    Carries a structured ``service_name`` so logs, dashboards, and SLO alerts
    can distinguish which backend is unhealthy. API exception handlers map
    this exception to HTTP 503 across both the curation and ERS REST APIs.

    Attributes:
        service_name: Canonical name of the unreachable backend
            ("mongodb", "redis", or "channel").
        detail: Optional cause-side detail (typically ``str(exc)`` of the
            wrapped pymongo/redis/channel connection error).
    """

    def __init__(self, service_name: str, detail: str = "") -> None:
        self.service_name = service_name
        self.detail = detail
        message = (
            f"{service_name} is unavailable: {detail}"
            if detail
            else f"{service_name} is unavailable"
        )
        super().__init__(message)
