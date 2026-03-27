from ers.commons.domain.exceptions import DomainError


class AuthenticationError(DomainError):
    """Raised when authentication fails (invalid credentials, expired token)."""


class AuthorizationError(DomainError):
    """Raised when the user lacks required permissions."""


class LastAdminError(DomainError):
    """Raised when attempting to deactivate the last active administrator."""

    def __init__(self) -> None:
        super().__init__("Cannot deactivate the last active administrator")
