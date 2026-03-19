from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase


class MongoCollections:
    """Single source of truth for MongoDB collection names and access."""

    DECISIONS = "decisions"
    ENTITY_MENTIONS = "entity_mentions"
    LOOKUP_STATES = "lookup_states"
    RESOLUTION_REQUESTS = "resolution_requests"
    USER_ACTIONS = "user_actions"
    USERS = "users"

    def __init__(self, database: AsyncDatabase) -> None:
        self._db = database

    @property
    def decisions(self) -> AsyncCollection:
        return self._db[self.DECISIONS]

    @property
    def entity_mentions(self) -> AsyncCollection:
        return self._db[self.ENTITY_MENTIONS]

    @property
    def lookup_states(self) -> AsyncCollection:
        return self._db[self.LOOKUP_STATES]

    @property
    def resolution_requests(self) -> AsyncCollection:
        return self._db[self.RESOLUTION_REQUESTS]

    @property
    def user_actions(self) -> AsyncCollection:
        return self._db[self.USER_ACTIONS]

    @property
    def users(self) -> AsyncCollection:
        return self._db[self.USERS]
