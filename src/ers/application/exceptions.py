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
