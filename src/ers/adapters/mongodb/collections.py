from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase


class MongoCollections:
    """Single source of truth for MongoDB collection names and access."""

    DECISIONS = "decisions"
    ENTITY_MENTIONS = "entity_mentions"
    USER_ACTIONS = "user_actions"

    def __init__(self, database: AsyncDatabase) -> None:
        self._db = database

    @property
    def decisions(self) -> AsyncCollection:
        return self._db[self.DECISIONS]

    @property
    def entity_mentions(self) -> AsyncCollection:
        return self._db[self.ENTITY_MENTIONS]

    @property
    def user_actions(self) -> AsyncCollection:
        return self._db[self.USER_ACTIONS]
