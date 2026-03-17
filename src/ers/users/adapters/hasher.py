from abc import ABC, abstractmethod

from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import VerifyMismatchError


class PasswordHasher(ABC):
    """Port for password hashing operations."""

    @abstractmethod
    def hash(self, password: str) -> str:
        """Hash a plaintext password."""

    @abstractmethod
    def verify(self, password: str, hashed: str) -> bool:
        """Verify a plaintext password against a hash."""


class Argon2PasswordHasher(PasswordHasher):
    """Argon2-based password hasher."""

    def __init__(self) -> None:
        self._hasher = Argon2Hasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, hashed: str) -> bool:
        try:
            return self._hasher.verify(hashed, password)
        except VerifyMismatchError:
            return False
