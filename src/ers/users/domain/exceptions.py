from ers.commons.domain.exceptions import DomainError


class AuthenticationError(DomainError):
    """Raised when authentication fails (invalid credentials, expired token)."""


class AuthorizationError(DomainError):
    """Raised when the user lacks required permissions."""
