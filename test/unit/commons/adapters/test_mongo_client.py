from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ers.commons.adapters.mongo_client import MongoClientManager


class TestConnect:
    async def test_creates_async_client(self):
        manager = MongoClientManager("mongodb://localhost:27017", "test_db")
        with patch("ers.commons.adapters.mongo_client.AsyncMongoClient") as mock_cls:
            await manager.connect()
            mock_cls.assert_called_once_with("mongodb://localhost:27017")
            assert manager._client is not None


class TestClose:
    async def test_closes_existing_client(self):
        manager = MongoClientManager("mongodb://localhost:27017", "test_db")
        mock_client = AsyncMock()
        manager._client = mock_client

        await manager.close()

        mock_client.close.assert_awaited_once()
        assert manager._client is None

    async def test_noop_when_not_connected(self):
        manager = MongoClientManager("mongodb://localhost:27017", "test_db")
        await manager.close()


class TestGetDatabase:
    def test_returns_database_by_name(self):
        manager = MongoClientManager("mongodb://localhost:27017", "test_db")
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        manager._client = mock_client

        result = manager.get_database()

        mock_client.__getitem__.assert_called_once_with("test_db")
        assert result is mock_db

    def test_raises_when_not_connected(self):
        manager = MongoClientManager("mongodb://localhost:27017", "test_db")
        with pytest.raises(RuntimeError, match="not connected"):
            manager.get_database()


class TestEnsureIndexes:
    async def test_creates_all_indexes(self):
        manager = MongoClientManager("mongodb://localhost:27017", "test_db")
        mock_collection = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        mock_client = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        manager._client = mock_client

        await manager.ensure_indexes()

        assert mock_collection.create_index.await_count == 4

        index_calls = mock_collection.create_index.call_args_list
        index_names = {call.kwargs["name"] for call in index_calls}
        assert "resolution_requests_text" in index_names
        assert "decisions_about_entity_mention" in index_names
        assert "users_email_unique" in index_names
        assert "resolution_requests_source_received_at" in index_names
