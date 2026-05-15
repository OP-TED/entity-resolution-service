"""Unit tests for MongoEntityMentionCurationRepository (mocked collection)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from ers.curation.adapters.entity_mention_repository import (
    MIN_SEARCH_LENGTH,
    MongoEntityMentionCurationRepository,
)


def _make_repo():
    mock_db = MagicMock()
    mock_collection = AsyncMock()
    mock_collection.find = MagicMock(return_value=_empty_cursor())
    mock_db.__getitem__.return_value = mock_collection
    return MongoEntityMentionCurationRepository(mock_db), mock_collection


def _empty_cursor():
    async def _gen():
        return
        yield  # make it an async generator

    cursor = MagicMock()
    cursor.__aiter__ = lambda self: _gen()
    return cursor


class TestSearchIdentifiers:
    """Unit tests for MongoEntityMentionCurationRepository.search_identifiers."""

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty_without_db_call(self):
        """N1: empty string short-circuits before any DB call."""
        repo, col = _make_repo()
        result = await repo.search_identifiers("")
        assert result == []
        col.find.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_below_min_length_returns_empty(self):
        """N1: query shorter than MIN_SEARCH_LENGTH returns empty list without DB call."""
        repo, col = _make_repo()
        short_query = "a" * (MIN_SEARCH_LENGTH - 1)
        result = await repo.search_identifiers(short_query)
        assert result == []
        col.find.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_at_min_length_runs_query(self):
        """N1: query exactly MIN_SEARCH_LENGTH chars triggers a DB find call."""
        repo, col = _make_repo()
        query = "a" * MIN_SEARCH_LENGTH
        col.find = MagicMock(return_value=_empty_cursor())
        await repo.search_identifiers(query)
        col.find.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_above_min_length_runs_query(self):
        """N1: query longer than MIN_SEARCH_LENGTH triggers a DB find call."""
        repo, col = _make_repo()
        query = "a" * (MIN_SEARCH_LENGTH + 5)
        col.find = MagicMock(return_value=_empty_cursor())
        await repo.search_identifiers(query)
        col.find.assert_called_once()

    def test_min_search_length_constant_is_three(self):
        """N1: MIN_SEARCH_LENGTH must be 3 (single-character regex causes full-scan)."""
        assert MIN_SEARCH_LENGTH == 3
