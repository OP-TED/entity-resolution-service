from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")
ID = TypeVar("ID")


class AsyncReadRepository(ABC, Generic[T, ID]):
    """Abstract async read-only repository."""

    @abstractmethod
    async def find_by_id(self, entity_id: ID) -> T | None:
        """Find an entity by its identifier. Returns None if not found."""


class AsyncWriteRepository(ABC, Generic[T, ID]):
    """Abstract async write repository."""

    @abstractmethod
    async def save(self, entity: T) -> T:
        """Persist an entity. Handles both creation and updates."""
