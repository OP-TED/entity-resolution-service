import hashlib
from abc import ABC, abstractmethod

from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import VerifyMismatchError


class ContentHasher(ABC):
    """Abstract class to generate a digest/hash for arbitrary content"""

    @abstractmethod
    def hash(self, content: str) -> str:
        """Hash a plaintext content."""

    @abstractmethod
    def verify(self, content: str, hash: str) -> bool:
        """Verify a plaintext content against a hash."""


class Argon2PasswordHasher(ContentHasher):
    """Argon2-based password hasher."""

    def __init__(self) -> None:
        self._hasher = Argon2Hasher()

    def hash(self, content: str) -> str:
        return self._hasher.hash(content)

    def verify(self, content: str, hash: str) -> bool:
        try:
            return self._hasher.verify(hash, content)
        except VerifyMismatchError:
            return False


class SHA256ContentHasher(ContentHasher):
    """SHA-256 based content hasher — fast and deterministic.

    Suitable for content deduplication and idempotency checks.
    NOT suitable for password storage (use Argon2PasswordHasher for that).
    """

    def hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def verify(self, content: str, hash: str) -> bool:
        return self.hash(content) == hash
