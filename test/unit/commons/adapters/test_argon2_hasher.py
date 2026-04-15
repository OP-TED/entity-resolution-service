"""Unit tests for Argon2PasswordHasher."""

from ers.commons.adapters.hasher import Argon2PasswordHasher


class TestArgon2PasswordHasher:
    def test_hash_returns_argon2_formatted_string(self) -> None:
        hasher = Argon2PasswordHasher()
        result = hasher.hash("secret-password")
        assert result.startswith("$argon2")

    def test_hash_is_nondeterministic(self) -> None:
        hasher = Argon2PasswordHasher()
        assert hasher.hash("same-password") != hasher.hash("same-password")

    def test_verify_returns_true_for_correct_password(self) -> None:
        hasher = Argon2PasswordHasher()
        digest = hasher.hash("correct-password")
        assert hasher.verify("correct-password", digest) is True

    def test_verify_returns_false_for_wrong_password(self) -> None:
        hasher = Argon2PasswordHasher()
        digest = hasher.hash("correct-password")
        assert hasher.verify("wrong-password", digest) is False
