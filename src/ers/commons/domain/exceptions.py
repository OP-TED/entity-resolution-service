class DomainError(Exception):
    """Base exception for all domain-level errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidCursorError(DomainError):
    """Raised when a pagination cursor is malformed or invalid."""

    def __init__(self) -> None:
        super().__init__("Invalid or expired pagination cursor")
