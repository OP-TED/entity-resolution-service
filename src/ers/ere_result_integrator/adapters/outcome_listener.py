"""Abstract interface for ERE outcome consumption (EPIC-05).

Concrete implementations wrap a specific messaging backend (Redis, Kafka, etc.)
and yield EntityMentionResolutionResponse objects one at a time. The service layer
depends only on this interface - never on a concrete implementation.
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from erspec.models.ere import EntityMentionResolutionResponse


class AsyncOutcomeListener(ABC):
    """Framework-agnostic interface for async ERE outcome consumption.

    Implementations must yield only ``EntityMentionResolutionResponse`` objects.
    Error responses (``EREErrorResponse``) are handled inside the implementation
    and must not be yielded.
    """

    @abstractmethod
    def consume(self) -> AsyncGenerator[EntityMentionResolutionResponse, None]:
        """Yield ERE resolution responses as they arrive.

        Runs indefinitely - callers are responsible for cancelling the task
        (via ``OutcomeIntegrationWorker.stop()``) when shutting down.

        Yields:
            EntityMentionResolutionResponse: Each valid response from the ERE.
        """
