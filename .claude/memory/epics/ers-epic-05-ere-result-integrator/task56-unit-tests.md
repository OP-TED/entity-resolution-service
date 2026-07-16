# Task 6: Unit Tests

## Context

Unit tests for the domain errors and the Redis adapter. Service tests were written in
Task 4 (TDD); worker tests were written in Task 5. This task adds the remaining coverage:
domain error attribute checks and the `RedisOutcomeListener` behaviour (yield vs skip).

---

## Files to Create

| Path | Purpose |
|------|---------|
| `tests/unit/ere_result_integrator/__init__.py` | Empty package marker |
| `tests/unit/ere_result_integrator/domain/__init__.py` | Empty package marker |
| `tests/unit/ere_result_integrator/domain/test_errors.py` | Error class attribute tests |
| `tests/unit/ere_result_integrator/adapters/__init__.py` | Empty package marker |
| `tests/unit/ere_result_integrator/adapters/test_redis_outcome_listener.py` | Listener yield/skip behaviour |

---

## Step 1 — Domain Error Tests

`tests/unit/ere_result_integrator/domain/test_errors.py`:

```python
"""Unit tests for OutcomeValidationError and TriadNotFoundError."""
import pytest
from erspec.models.core import EntityMentionIdentifier

from ers.commons.services.exceptions import ApplicationError
from ers.ere_result_integrator.domain.errors import (
    OutcomeValidationError,
    TriadNotFoundError,
)


def make_identifier() -> EntityMentionIdentifier:
    return EntityMentionIdentifier(source_id="S", request_id="R", entity_type="T")


class TestOutcomeValidationError:
    def test_is_application_error(self):
        assert issubclass(OutcomeValidationError, ApplicationError)

    def test_detail_attribute_set(self):
        err = OutcomeValidationError("null timestamp")
        assert err.detail == "null timestamp"

    def test_message_equals_detail(self):
        err = OutcomeValidationError("empty candidates")
        assert str(err) == "empty candidates"

    def test_can_be_raised_and_caught(self):
        with pytest.raises(OutcomeValidationError) as exc_info:
            raise OutcomeValidationError("test detail")
        assert exc_info.value.detail == "test detail"


class TestTriadNotFoundError:
    def test_is_application_error(self):
        assert issubclass(TriadNotFoundError, ApplicationError)

    def test_identifier_attribute_set(self):
        identifier = make_identifier()
        err = TriadNotFoundError(identifier)
        assert err.identifier is identifier

    def test_message_includes_triad_fields(self):
        identifier = make_identifier()
        err = TriadNotFoundError(identifier)
        msg = str(err)
        assert "S" in msg
        assert "R" in msg
        assert "T" in msg

    def test_can_be_raised_and_caught(self):
        identifier = make_identifier()
        with pytest.raises(TriadNotFoundError) as exc_info:
            raise TriadNotFoundError(identifier)
        assert exc_info.value.identifier == identifier
```

---

## Step 2 — Redis Outcome Listener Tests

`tests/unit/ere_result_integrator/adapters/test_redis_outcome_listener.py`:

```python
"""Unit tests for RedisOutcomeListener — yield vs skip behaviour."""
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
        import logging
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
```

---

## Step 3 — Verify Full Unit Suite

```bash
make test
```

All `tests/unit/ere_result_integrator/` tests must pass. Check that existing tests
outside `ere_result_integrator/` continue to pass (no regressions).

---

## Key References

| What | Where |
|------|-------|
| Service tests (written in Task 4) | `tests/unit/ere_result_integrator/services/test_outcome_integration_service.py` |
| Worker tests (written in Task 5) | `tests/unit/ere_result_integrator/entrypoints/test_outcome_integration_worker.py` |
| `EREErrorResponse`, `EntityMentionResolutionResponse` | `erspec/models/ere.py` |
