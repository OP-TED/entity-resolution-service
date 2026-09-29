"""Unit tests for SHA256ContentHasher."""


from ers.commons.adapters.hasher import SHA256ContentHasher


class TestSHA256ContentHasher:
    """Tests for SHA256ContentHasher — fast deterministic content hashing."""

    def test_hash_empty_string_returns_known_sha256_digest(self) -> None:
        """SHA-256 of the empty string is a well-known constant."""
        hasher = SHA256ContentHasher()
        result = hasher.hash("")
        assert result == "e3b0c44298fc1c149afbf4c8996fb924" "27ae41e4649b934ca495991b7852b855"

    def test_hash_returns_hex_string_of_64_chars(self) -> None:
        hasher = SHA256ContentHasher()
        result = hasher.hash("some content")
        assert isinstance(result, str)
        assert len(result) == 64

    def test_hash_is_deterministic(self) -> None:
        hasher = SHA256ContentHasher()
        content = "deterministic content"
        assert hasher.hash(content) == hasher.hash(content)

    def test_different_content_produces_different_hash(self) -> None:
        hasher = SHA256ContentHasher()
        assert hasher.hash("content A") != hasher.hash("content B")

    def test_verify_returns_true_for_matching_pair(self) -> None:
        hasher = SHA256ContentHasher()
        content = "entity mention payload"
        digest = hasher.hash(content)
        assert hasher.verify(content, digest) is True

    def test_verify_returns_false_for_mismatched_pair(self) -> None:
        hasher = SHA256ContentHasher()
        content_a = "entity mention payload"
        content_b = "different payload"
        digest_b = hasher.hash(content_b)
        assert hasher.verify(content_a, digest_b) is False

    def test_verify_returns_false_for_empty_hash(self) -> None:
        hasher = SHA256ContentHasher()
        assert hasher.verify("some content", "") is False

    def test_hash_unicode_content(self) -> None:
        hasher = SHA256ContentHasher()
        result = hasher.hash("Ünïcödé cöntënt 日本語")
        assert isinstance(result, str)
        assert len(result) == 64
