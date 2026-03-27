"""Redis list-queue implementation of AsyncOutcomeListener (EPIC-05).

Wraps AbstractClient.pull_response() (LPUSH/BRPOP pattern from EPIC-03 commons)
in a polling loop. EREErrorResponse messages are logged at WARNING and skipped.
"""
import logging
from collections.abc import AsyncGenerator

from erspec.models.ere import EREErrorResponse, EntityMentionResolutionResponse

from ers.commons.adapters.redis_client import AbstractClient
from ers.ere_result_integrator.adapters.outcome_listener import AsyncOutcomeListener

_log = logging.getLogger(__name__)


class RedisOutcomeListener(AsyncOutcomeListener):
    """Polls the ERE response Redis channel and yields valid resolution responses.

    Uses ``AbstractClient.pull_response()`` which performs a blocking BRPOP on
    the configured ``ere_responses`` channel. The loop yields control to the
    asyncio event loop at every ``await``, so it does not starve other tasks.

    Args:
        client: Connected ``AbstractClient`` instance (``RedisEREClient``).
    """

    def __init__(self, client: AbstractClient) -> None:
        self._client = client

    async def consume(self) -> AsyncGenerator[EntityMentionResolutionResponse, None]:
        """Yield ERE resolution responses indefinitely.

        Yields:
            EntityMentionResolutionResponse: Each valid solicited or unsolicited
                response received from the ERE.

        Note:
            ``EREErrorResponse`` messages are logged at WARNING and skipped.
            The loop runs until the enclosing asyncio Task is cancelled.
        """
        while True:
            response = await self._client.pull_response()
            if isinstance(response, EntityMentionResolutionResponse):
                yield response
            elif isinstance(response, EREErrorResponse):
                _log.warning(
                    "ERE error response received - skipping",
                    extra={
                        "ere_request_id": response.ere_request_id,
                        "error_type": response.error_type,
                    },
                )
