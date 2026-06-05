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
        """Create required indexes on the database collections.

        Note: no MongoDB ``text`` index is created here. Curation's substring
        search uses ``$regex`` (see ``MongoEntityMentionCurationRepository``)
        for cross-engine portability — text indexes are not supported on
        Amazon DocumentDB.
        """
        db = self.get_database()

        await db["decisions"].create_index(
            "about_entity_mention",
            name="decisions_about_entity_mention",
        )

        await db["decisions"].create_index(
            [("reviewed_since_placement", 1), ("_id", 1)],
            name="decisions_reviewed_since_placement_id",
            background=True,
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

        await db["user_actions"].create_index(
            "about_entity_mention",
            name="user_actions_about_entity_mention",
        )

        await db["cluster_sizes"].create_index(
            "size",
            name="idx_cluster_sizes_size",
        )
