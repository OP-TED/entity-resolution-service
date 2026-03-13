from abc import ABC, abstractmethod


class PasswordHasher(ABC):
    """Port for password hashing operations."""

    @abstractmethod
    def hash(self, password: str) -> str:
        """Hash a plaintext password."""

    @abstractmethod
    def verify(self, password: str, hashed: str) -> bool:
        """Verify a plaintext password against a hash."""
