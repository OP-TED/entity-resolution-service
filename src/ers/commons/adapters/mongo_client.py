from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase


class MongoClientManager:
    """Manages the lifecycle of an AsyncMongoClient."""

    def __init__(self, mongo_uri: str, database_name: str) -> None:
        self._mongo_uri = mongo_uri
        self._database_name = database_name
        self._client: AsyncMongoClient | None = None

    async def connect(self) -> None:
        """Create the async MongoDB client."""
        self._client = AsyncMongoClient(self._mongo_uri)

    async def close(self) -> None:
        """Close the client and release connections."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    def get_database(self) -> AsyncDatabase:
        """Return the database instance. Must be called after connect()."""
        if self._client is None:
            raise RuntimeError("MongoClientManager is not connected. Call connect() first.")
        return self._client[self._database_name]

    async def ensure_indexes(self) -> None:
        """Create required indexes on the database collections."""
        db = self.get_database()

        await db["resolution_requests"].create_index(
            [("content", "text"), ("parsed_representation", "text")],
            name="resolution_requests_text",
        )

        await db["decisions"].create_index(
            "about_entity_mention",
            name="decisions_about_entity_mention",
        )

        await db["users"].create_index(
            "email",
            unique=True,
            name="users_email_unique",
        )

        await db["resolution_requests"].create_index(
            [("identifiedBy.source_id", 1), ("received_at", 1)],
            name="resolution_requests_source_received_at",
        )
