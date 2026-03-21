import uuid

import pytest
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from ers import config
from ers.commons.adapters.mongo_collections_manager import MongoCollections


@pytest.fixture
async def mongo_db() -> AsyncDatabase:
    """Provide an isolated test database that is dropped after each test."""
    client = AsyncMongoClient(config.MONGO_URI)
    db_name = f"ers_test_{uuid.uuid4().hex[:8]}"
    db = client[db_name]
    collections = MongoCollections(db)

    await collections.entity_mentions.create_index(
        [("content", "text"), ("parsed_representation", "text")],
        name="entity_mentions_text",
    )

    yield db
    await client.drop_database(db_name)
    await client.close()
