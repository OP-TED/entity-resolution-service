"""Unit tests for RedisOutcomeListener — yield vs skip behaviour."""
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from erspec.models.core import ClusterReference, EntityMentionIdentifier
from erspec.models.ere import (
    EREErrorResponse,
    EntityMentionResolutionResponse,
)

from ers.commons.adapters.redis_client import AbstractClient
from ers.ere_result_integrator.adapters.redis_outcome_listener import RedisOutcomeListener


def make_resolution_response() -> EntityMentionResolutionResponse:
    return EntityMentionResolutionResponse(
        ere_request_id="req:001",
        entity_mention_id=EntityMentionIdentifier(
            source_id="S", request_id="R", entity_type="T"
        ),
        candidates=[
            ClusterReference(cluster_id="c-001", confidence_score=0.9, similarity_score=0.85)
        ],
        timestamp=datetime.now(UTC),
    )


def make_error_response() -> EREErrorResponse:
    return EREErrorResponse(
        ere_request_id="req:002",
        error_type="InternalError",
        error_title="ERE internal error",
    )


async def collect_n(generator, n: int) -> list:
    """Collect n items from an async generator."""
    items = []
    async for item in generator:
        items.append(item)
        if len(items) >= n:
            break
    return items


class TestRedisOutcomeListenerYield:
    async def test_yields_resolution_response(self):
        """EntityMentionResolutionResponse is yielded to the caller."""
        response = make_resolution_response()
        client = MagicMock(spec=AbstractClient)
        client.pull_response = AsyncMock(return_value=response)

        listener = RedisOutcomeListener(client=client)
        items = await collect_n(listener.consume(), 1)

        assert len(items) == 1
        assert items[0] is response

    async def test_skips_error_response(self):
        """EREErrorResponse is logged and skipped; next valid response is yielded."""
        error_resp = make_error_response()
        valid_resp = make_resolution_response()
        client = MagicMock(spec=AbstractClient)
        client.pull_response = AsyncMock(side_effect=[error_resp, valid_resp])

        listener = RedisOutcomeListener(client=client)
        items = await collect_n(listener.consume(), 1)

        assert len(items) == 1
        assert isinstance(items[0], EntityMentionResolutionResponse)

    async def test_error_response_logged_as_warning(self, caplog):
        """EREErrorResponse triggers a WARNING log with ere_request_id and error_type."""
        error_resp = make_error_response()
        valid_resp = make_resolution_response()
        client = MagicMock(spec=AbstractClient)
        client.pull_response = AsyncMock(side_effect=[error_resp, valid_resp])

        listener = RedisOutcomeListener(client=client)
        with caplog.at_level(logging.WARNING, logger="ers.ere_result_integrator"):
            await collect_n(listener.consume(), 1)

        assert any("error" in r.message.lower() for r in caplog.records)

    async def test_yields_multiple_responses_in_order(self):
        """Multiple resolution responses are yielded in arrival order."""
        responses = [make_resolution_response() for _ in range(3)]
        client = MagicMock(spec=AbstractClient)
        client.pull_response = AsyncMock(side_effect=responses)

        listener = RedisOutcomeListener(client=client)
        items = await collect_n(listener.consume(), 3)

        assert items == responses

    def test_is_async_outcome_listener(self):
        """RedisOutcomeListener implements AsyncOutcomeListener."""
        from ers.ere_result_integrator.adapters.outcome_listener import AsyncOutcomeListener
        assert issubclass(RedisOutcomeListener, AsyncOutcomeListener)
