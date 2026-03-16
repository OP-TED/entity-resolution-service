from abc import ABC, abstractmethod
from typing import Any


class TokenService(ABC):
    """Port for JWT token operations."""

    @abstractmethod
    def create_access_token(self, subject: str, extra_claims: dict[str, Any]) -> str:
        """Create a short-lived access token."""

    @abstractmethod
    def create_refresh_token(self, subject: str) -> str:
        """Create a longer-lived refresh token."""

    @abstractmethod
    def decode_token(self, token: str) -> dict[str, Any]:
        """Decode and validate a token. Raises AuthenticationError on failure."""
