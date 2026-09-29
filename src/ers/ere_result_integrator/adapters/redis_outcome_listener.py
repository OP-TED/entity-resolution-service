"""Redis list-queue implementation of AsyncOutcomeListener (EPIC-05).

Wraps AbstractClient.pull_response() (LPUSH/BRPOP pattern from EPIC-03 commons)
in a polling loop with the following message-handling rules:

- ``EntityMentionResolutionResponse`` - yielded to the caller.
- ``EREErrorResponse`` - logged at WARNING and skipped.
- Unknown response types - logged at WARNING and skipped.
- ``TimeoutError`` (BRPOP window expired) - swallowed; polling resumes.
- ``ValueError`` (malformed / unknown-type payload) - logged at ERROR and skipped.
- ``ConnectionError`` (Redis drop) - logged at ERROR and re-raised so the
  caller (``OutcomeIntegrationWorker``) can restart with back-off.
"""
import logging
from collections.abc import AsyncGenerator

from erspec.models.ere import EntityMentionResolutionResponse, EREErrorResponse

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

        Raises:
            ConnectionError: Re-raised after logging when Redis drops the connection.
                The caller (worker) is expected to catch this and restart.

        Note:
            - ``EREErrorResponse`` messages are logged at WARNING and skipped.
            - ``TimeoutError`` (BRPOP window expired) is swallowed; polling resumes.
            - ``ValueError`` (malformed / unknown-type message) is logged at ERROR
              and skipped; the offending message is discarded.
            - Unknown response types are logged at WARNING and skipped.
            - The loop runs until the enclosing asyncio Task is cancelled or a
              ``ConnectionError`` propagates.
        """
        while True:
            try:
                response = await self._client.pull_response()
            except TimeoutError:
                continue
            except ConnectionError as exc:
                _log.error("Redis connection lost - outcome listener stopping", exc_info=exc)
                raise
            except ValueError as exc:
                _log.error("Undeserializable ERE message - discarding", exc_info=exc)
                continue

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
            else:
                _log.warning(
                    "Unrecognised ERE response type - skipping",
                    extra={"response_type": type(response).__name__},
                )
