# Task 4: Decision Store Service Layer

## Context

Adds the service layer and OTel span extractors on top of the already-implemented MongoDB adapter (`MongoDecisionRepository`). The service orchestrates candidate truncation, staleness propagation, and cursor-based pagination. Module-level public API functions carry the tracing boundary, mirroring the `request_registry_service.py` pattern exactly.

---

## Files to Create

| Path | Purpose |
|------|---------|
| `src/ers/resolution_decision_store/services/decision_store_service.py` | `DecisionStoreService` class + traced module-level public API |
| `src/ers/resolution_decision_store/adapters/span_extractors.py` | OTel extractor for `Decision` domain type |
| `tests/unit/resolution_decision_store/services/__init__.py` | Empty package marker |
| `tests/unit/resolution_decision_store/services/test_decision_store_service.py` | Unit tests for service and public API functions |

**Do NOT touch** `resolution_decision_store_service.py` — it is a temporary ABC placeholder for future delta-sync work (EPIC-06).

---

## Step 1 — Write Failing Tests First (TDD)

`tests/unit/resolution_decision_store/services/test_decision_store_service.py`:

```python
"""Unit tests for DecisionStoreService."""
from datetime import datetime, timezone
from unittest.mock import create_autospec

import pytest
from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers import config
from ers.commons.domain.cursor import encode_cursor
from ers.commons.domain.data_transfer_objects import CursorPage, CursorParams
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import (
    DecisionStoreService,
    get_decision_by_triad,
    query_decisions_paginated,
    store_decision,
)


def make_identifier():
    return EntityMentionIdentifier(source_id="s1", request_id="r1", entity_type="Person")

def make_cluster(cluster_id="c1"):
    return ClusterReference(cluster_id=cluster_id, confidence_score=0.9, similarity_score=0.85)

def make_decision(now=None):
    now = now or datetime.now(timezone.utc)
    return Decision(
        id="hash123",
        about_entity_mention=make_identifier(),
        current_placement=make_cluster(),
        candidates=[],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def mock_repo():
    return create_autospec(MongoDecisionRepository, instance=True)

@pytest.fixture()
def service(mock_repo):
    return DecisionStoreService(repository=mock_repo)


class TestStoreDecision:
    async def test_delegates_to_repository(self, service, mock_repo):
        now = datetime.now(timezone.utc)
        mock_repo.upsert_decision.return_value = make_decision(now)
        result = await service.store_decision(make_identifier(), make_cluster(), [], now)
        assert isinstance(result, Decision)
        mock_repo.upsert_decision.assert_called_once()

    async def test_truncates_candidates_to_max(self, service, mock_repo):
        now = datetime.now(timezone.utc)
        mock_repo.upsert_decision.return_value = make_decision(now)
        many = [make_cluster(f"c{i}") for i in range(10)]
        await service.store_decision(make_identifier(), make_cluster(), many, now)
        _, kwargs = mock_repo.upsert_decision.call_args
        assert len(kwargs["candidates"]) == config.DECISION_STORE_MAX_CANDIDATES

    async def test_does_not_truncate_when_within_limit(self, service, mock_repo):
        now = datetime.now(timezone.utc)
        mock_repo.upsert_decision.return_value = make_decision(now)
        few = [make_cluster(f"c{i}") for i in range(2)]
        await service.store_decision(make_identifier(), make_cluster(), few, now)
        _, kwargs = mock_repo.upsert_decision.call_args
        assert len(kwargs["candidates"]) == 2

    async def test_propagates_stale_outcome_error(self, service, mock_repo):
        mock_repo.upsert_decision.side_effect = StaleOutcomeError(
            "s1", "r1", "Person", stored_at="T1", attempted_at="T0"
        )
        with pytest.raises(StaleOutcomeError):
            await service.store_decision(make_identifier(), make_cluster(), [], datetime.now(timezone.utc))


class TestGetDecisionByTriad:
    async def test_returns_decision_when_found(self, service, mock_repo):
        mock_repo.find_by_triad.return_value = make_decision()
        result = await service.get_decision_by_triad(make_identifier())
        assert isinstance(result, Decision)

    async def test_returns_none_when_not_found(self, service, mock_repo):
        mock_repo.find_by_triad.return_value = None
        result = await service.get_decision_by_triad(make_identifier())
        assert result is None


class TestQueryDecisionsPaginated:
    async def test_returns_cursor_page(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        result = await service.query_decisions_paginated()
        assert isinstance(result, CursorPage)

    async def test_uses_default_page_size_when_none(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        await service.query_decisions_paginated(page_size=None)
        _, kwargs = mock_repo.find_with_filters.call_args
        assert kwargs["cursor_params"].limit == config.DECISION_STORE_DEFAULT_PAGE_SIZE

    async def test_caps_page_size_at_maximum(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        await service.query_decisions_paginated(page_size=99999)
        _, kwargs = mock_repo.find_with_filters.call_args
        assert kwargs["cursor_params"].limit == config.DECISION_STORE_MAX_PAGE_SIZE

    async def test_passes_cursor_to_repository(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        cursor = encode_cursor(datetime.now(timezone.utc), "hash123")
        await service.query_decisions_paginated(cursor=cursor)
        _, kwargs = mock_repo.find_with_filters.call_args
        assert kwargs["cursor_params"].cursor == cursor


class TestPublicAPIFunctions:
    async def test_store_decision_delegates_to_service(self, service, mock_repo):
        now = datetime.now(timezone.utc)
        mock_repo.upsert_decision.return_value = make_decision(now)
        result = await store_decision(make_identifier(), make_cluster(), [], now, service=service)
        assert isinstance(result, Decision)

    async def test_get_decision_by_triad_delegates_to_service(self, service, mock_repo):
        mock_repo.find_by_triad.return_value = make_decision()
        result = await get_decision_by_triad(make_identifier(), service=service)
        assert isinstance(result, Decision)

    async def test_query_decisions_paginated_delegates_to_service(self, service, mock_repo):
        mock_repo.find_with_filters.return_value = CursorPage(results=[], next_cursor=None)
        result = await query_decisions_paginated(service=service)
        assert isinstance(result, CursorPage)
```

---

## Step 2 — Implement the Service

`src/ers/resolution_decision_store/services/decision_store_service.py`:

```python
"""Decision Store service — orchestrates decision persistence and cursor-paginated queries."""
import logging
from datetime import datetime

from erspec.models.core import ClusterReference, Decision, EntityMentionIdentifier

from ers import config
from ers.commons.adapters.tracing import trace_function
from ers.commons.domain.data_transfer_objects import CursorPage, CursorParams
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository

_log = logging.getLogger(__name__)


class DecisionStoreService:
    """Application service for the Resolution Decision Store use cases."""

    def __init__(self, repository: MongoDecisionRepository) -> None:
        self._repository = repository

    async def store_decision(
        self,
        identifier: EntityMentionIdentifier,
        current: ClusterReference,
        candidates: list[ClusterReference],
        updated_at: datetime,
    ) -> Decision:
        """Store or atomically replace a decision, truncating excess candidates.

        Args:
            identifier: Entity mention triad for this decision.
            current: New cluster assignment.
            candidates: Pre-ordered candidate list from ERE.
            updated_at: Must be strictly greater than stored updated_at.

        Returns:
            The persisted Decision.

        Raises:
            StaleOutcomeError: If stored updated_at >= incoming updated_at.
            RepositoryConnectionError: On MongoDB connection failure.
            RepositoryOperationError: On unexpected MongoDB error.
        """
        max_candidates = config.DECISION_STORE_MAX_CANDIDATES
        if len(candidates) > max_candidates:
            _log.warning("Candidate list truncated",
                         extra={"original": len(candidates), "max": max_candidates})
        return await self._repository.upsert_decision(
            identifier=identifier,
            current=current,
            candidates=candidates[:max_candidates],
            updated_at=updated_at,
        )

    async def get_decision_by_triad(
        self, identifier: EntityMentionIdentifier
    ) -> Decision | None:
        """Return the current decision for a triad, or None if not stored.

        Args:
            identifier: The entity mention triad.

        Returns:
            The matching Decision, or None.
        """
        return await self._repository.find_by_triad(identifier)

    async def query_decisions_paginated(
        self,
        cursor: str | None = None,
        page_size: int | None = None,
    ) -> CursorPage[Decision]:
        """Cursor-paginated traversal of all stored decisions (bulk sync mode).

        Args:
            cursor: Opaque pagination token from a previous response, or None for first page.
            page_size: Max results per page. Capped at DECISION_STORE_MAX_PAGE_SIZE.
                Defaults to DECISION_STORE_DEFAULT_PAGE_SIZE if None.

        Returns:
            A CursorPage with results and an optional next_cursor.

        Raises:
            InvalidCursorError: If the cursor string cannot be decoded.
        """
        effective_size = min(
            page_size if page_size is not None else config.DECISION_STORE_DEFAULT_PAGE_SIZE,
            config.DECISION_STORE_MAX_PAGE_SIZE,
        )
        return await self._repository.find_with_filters(
            filters=None,
            cursor_params=CursorParams(cursor=cursor, limit=effective_size),
        )


# ── Public API (traced at the service boundary) ───────────────────────────────


@trace_function(span_name="decision_store.store_decision")
async def store_decision(
    identifier: EntityMentionIdentifier,
    current: ClusterReference,
    candidates: list[ClusterReference],
    updated_at: datetime,
    service: DecisionStoreService,
) -> Decision:
    """Store or atomically replace a resolution decision.

    Args:
        identifier: Entity mention triad for this decision.
        current: New cluster assignment.
        candidates: Pre-ordered candidate list from ERE.
        updated_at: Timestamp — must be strictly greater than stored updated_at.
        service: The DecisionStoreService instance.

    Returns:
        The persisted Decision.

    Raises:
        StaleOutcomeError: If stored updated_at >= incoming updated_at.
        RepositoryConnectionError: On MongoDB connection failure.
        RepositoryOperationError: On unexpected MongoDB error.
    """
    return await service.store_decision(identifier, current, candidates, updated_at)


@trace_function(span_name="decision_store.get_decision_by_triad")
async def get_decision_by_triad(
    identifier: EntityMentionIdentifier,
    service: DecisionStoreService,
) -> Decision | None:
    """Retrieve the current decision for an entity mention triad.

    Args:
        identifier: The entity mention triad.
        service: The DecisionStoreService instance.

    Returns:
        The matching Decision, or None.
    """
    return await service.get_decision_by_triad(identifier)


@trace_function(span_name="decision_store.query_paginated")
async def query_decisions_paginated(
    service: DecisionStoreService,
    cursor: str | None = None,
    page_size: int | None = None,
) -> CursorPage[Decision]:
    """Cursor-paginated traversal of all stored decisions for bulk sync.

    Args:
        service: The DecisionStoreService instance.
        cursor: Opaque pagination token, or None for first page.
        page_size: Max results per page. Capped at DECISION_STORE_MAX_PAGE_SIZE.

    Returns:
        A CursorPage with results and an optional next_cursor.

    Raises:
        InvalidCursorError: If the cursor string cannot be decoded.
    """
    return await service.query_decisions_paginated(cursor=cursor, page_size=page_size)
```

---

## Step 3 — Implement Span Extractors

`src/ers/resolution_decision_store/adapters/span_extractors.py`:

```python
"""OTel span attribute extractors for the Resolution Decision Store.

Import this module at application startup only — NOT at module level in other packages.
"""
from erspec.models.core import Decision

from ers.commons.adapters.tracing import register_span_extractor

register_span_extractor(
    Decision,
    lambda d: {
        "decision_store.source_id": d.about_entity_mention.source_id,
        "decision_store.cluster_id": d.current_placement.cluster_id,
        "decision_store.candidate_count": len(d.candidates),
    },
)
```

**Note:** `EntityMentionIdentifier` is already registered in `src/ers/commons/adapters/span_extractors.py`. Do not re-register it here.

---

## Step 4 — Verify

```bash
# New service tests
poetry run pytest tests/unit/resolution_decision_store/services/ -v
# Full RDS suite (no regressions)
poetry run pytest tests/unit/resolution_decision_store/ -v
```

---

## Key References

| What | Where |
|------|-------|
| Reference service pattern | `src/ers/request_registry/services/request_registry_service.py` |
| `trace_function` decorator | `src/ers/commons/adapters/tracing.py` |
| Global config (`DECISION_STORE_*`) | `src/ers/__init__.py` — `DecisionStoreConfig` mixin |
| `MongoDecisionRepository` (to inject) | `src/ers/resolution_decision_store/adapters/decision_repository.py` |
| Extractor pattern reference | `src/ers/request_registry/adapters/span_extractors.py` |
| Do NOT touch | `src/ers/resolution_decision_store/services/resolution_decision_store_service.py` |
