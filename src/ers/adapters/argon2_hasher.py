from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import VerifyMismatchError

from ers.application.ports.password_hasher import PasswordHasher


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
