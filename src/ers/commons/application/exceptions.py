class ApplicationError(Exception):
    """Base exception for application-level errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
