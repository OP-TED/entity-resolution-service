"""Resolution Coordinator Service — orchestrator for Spines A + B."""

import asyncio
import contextlib
from datetime import UTC, datetime

from erspec.models.core import (
    ClusterReference,
    Decision,
    EntityMention,
    EntityMentionIdentifier,
)
from erspec.models.ere import EntityMentionResolutionRequest
from opentelemetry import trace

from ers import config
from ers.commons.adapters.provisional_id import derive_provisional_cluster_id
from ers.commons.adapters.tracing import trace_function
from ers.ere_contract_client.domain.errors import (
    ChannelUnavailableError,
    RedisConnectionError,
)
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.rdf_mention_parser.domain.exceptions import (
    ContentTooLargeError,
    EmptyExtractionError,
    EntityTypeMismatchError,
    MalformedRDFError,
    MultipleEntitiesFoundError,
    UnsupportedEntityTypeError,
)
from ers.request_registry.domain.errors import DuplicateTriadError
from ers.request_registry.services.request_registry_service import (
    RequestRegistryService,
)
from ers.resolution_coordinator.domain.exceptions import (
    ParsingFailedError,
    ResolutionTimeoutError,
)
from ers.resolution_coordinator.services.async_resolution_waiter import (
    AsyncResolutionWaiter,
)
from ers.resolution_decision_store.domain.errors import (
    RepositoryConnectionError,
    StaleOutcomeError,
)
from ers.resolution_decision_store.services.decision_store_service import (
    DecisionStoreService,
)

_PARSING_ERRORS = (
    ValueError,
    MalformedRDFError,
    ContentTooLargeError,
    UnsupportedEntityTypeError,
    EntityTypeMismatchError,
    MultipleEntitiesFoundError,
    EmptyExtractionError,
)


class ResolutionCoordinatorService:
    """Orchestrator for single-mention and bulk entity mention resolution.

    Coordinates registration (EPIC-01), engine submission (EPIC-03), and
    decision persistence (EPIC-04) to return a canonical or provisional
    cluster identifier within the request time budget.
    """

    def __init__(
        self,
        registry_service: RequestRegistryService,
        ere_publish_service: EREPublishService,
        decision_store_service: DecisionStoreService,
        waiter: AsyncResolutionWaiter,
    ) -> None:
        single_budget: float = config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET
        bulk_budget: float = config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET
        if single_budget <= 0:  # pylint: disable=comparison-with-callable
            raise ValueError(
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET must be > 0"
            )
        if bulk_budget <= 0:  # pylint: disable=comparison-with-callable
            raise ValueError(
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET must be > 0"
            )
        self._registry_service = registry_service
        self._ere_publish_service = ere_publish_service
        self._decision_store_service = decision_store_service
        self._waiter = waiter

    async def lookup_by_triad(
        self, identifier: EntityMentionIdentifier
    ) -> Decision | None:
        """Look up the current decision for a triad.

        Thin gateway so the REST API accesses the Decision Store only
        through the Coordinator.

        Args:
            identifier: The entity mention triad.

        Returns:
            The matching Decision, or None.
        """
        return await self._decision_store_service.get_decision_by_triad(
            identifier
        )

    async def resolve_single(
        self, entity_mention: EntityMention
    ) -> Decision:
        """Resolve a single entity mention and return a Decision.

        Registers the mention, checks for an existing decision, publishes to
        ERE, and waits for a response within the time budget. If ERE does not
        respond or Redis is unavailable, issues a provisional identifier.

        Args:
            entity_mention: The entity mention to resolve.

        Returns:
            A Decision with a canonical or provisional cluster assignment.

        Raises:
            ParsingFailedError: If registration fails due to invalid content.
            IdempotencyConflictError: If the triad exists with different content.
            ResolutionTimeoutError: If the Decision Store is unreachable
                during provisional write.
        """
        # 1. Register (embeds RDF parsing)
        try:
            await self._registry_service.register_resolution_request(
                entity_mention
            )
        except _PARSING_ERRORS as exc:
            raise ParsingFailedError(str(exc), cause=exc) from exc
        except DuplicateTriadError:
            pass  # Concurrent registration — another coroutine inserted first; proceed.

        # 2. Check existing decision — instant return for replays
        identifier = entity_mention.identifiedBy
        existing = await self._decision_store_service.get_decision_by_triad(
            identifier
        )
        if existing is not None:
            return existing

        # 3+4+5. Publish → wait → provisional fallback
        triad_key = (
            f"{identifier.source_id}"
            f"{identifier.request_id}"
            f"{identifier.entity_type}"
        )
        event = await self._waiter.get_or_create(triad_key)
        try:
            try:
                request = EntityMentionResolutionRequest(
                    entity_mention=entity_mention,
                    ere_request_id="",
                )
                await self._ere_publish_service.publish_request(request)
                await asyncio.wait_for(
                    asyncio.shield(event.wait()),
                    timeout=config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET,
                )
                decision = await self._decision_store_service.get_decision_by_triad(
                    identifier
                )
                if decision is not None:
                    return decision
            except (TimeoutError, RedisConnectionError, ChannelUnavailableError):
                pass

            return await self._issue_provisional(identifier)
        finally:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(self._waiter.release(triad_key))

    async def resolve_bulk(
        self, entity_mentions: list[EntityMention]
    ) -> list[Decision | Exception]:
        """Resolve multiple entity mentions concurrently.

        Each mention is resolved independently via ``resolve_single``.
        Failures are captured as exception objects in the results list,
        preserving input order. One failing mention does not abort the batch.

        Note:
            The result list may contain any exception type raised by
            ``resolve_single``, including ``IdempotencyConflictError``
            (which is not a ``CoordinatorError``).

        Args:
            entity_mentions: The list of entity mentions to resolve.

        Returns:
            A list of Decision or Exception in input order.

        Raises:
            ResolutionTimeoutError: If the bulk time budget is exceeded.
        """
        if not entity_mentions:
            return []
        tasks = [self.resolve_single(m) for m in entity_mentions]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET,
            )
            return list(results)
        except TimeoutError as exc:
            raise ResolutionTimeoutError(
                "Bulk resolution exceeded client time budget"
            ) from exc

    async def _issue_provisional(
        self, identifier: EntityMentionIdentifier
    ) -> Decision:
        """Derive and persist a provisional singleton decision.

        Args:
            identifier: The entity mention triad.

        Returns:
            The persisted provisional Decision.

        Raises:
            ResolutionTimeoutError: If the Decision Store is unreachable.
        """
        provisional_id = derive_provisional_cluster_id(identifier)
        cluster_ref = ClusterReference(
            cluster_id=provisional_id,
            confidence_score=1.0,
            similarity_score=1.0,
        )
        try:
            return await self._decision_store_service.store_decision(
                identifier=identifier,
                current=cluster_ref,
                candidates=[cluster_ref],
                updated_at=datetime.now(UTC),
            )
        except StaleOutcomeError as exc:
            decision = await self._decision_store_service.get_decision_by_triad(
                identifier
            )
            if decision is None:  # pragma: no cover — ERE wrote it moments ago
                raise ResolutionTimeoutError(
                    "Decision vanished after StaleOutcomeError"
                ) from exc
            return decision
        except RepositoryConnectionError as exc:
            raise ResolutionTimeoutError(
                f"Cannot persist provisional decision: {exc}"
            ) from None


@trace_function(span_name="resolution_coordinator.lookup_by_triad")
async def lookup_by_triad(
    identifier: EntityMentionIdentifier,
    service: ResolutionCoordinatorService,
) -> Decision | None:
    """Traced entry point for single-mention lookup."""
    return await service.lookup_by_triad(identifier)


@trace_function(span_name="resolution_coordinator.resolve_single")
async def resolve_single(
    entity_mention: EntityMention,
    service: ResolutionCoordinatorService,
) -> Decision:
    """Traced entry point for single-mention resolution."""
    return await service.resolve_single(entity_mention)


@trace_function(span_name="resolution_coordinator.resolve_bulk")
async def resolve_bulk(
    entity_mentions: list[EntityMention],
    service: ResolutionCoordinatorService,
) -> list[Decision | Exception]:
    """Traced entry point for bulk resolution."""
    trace.get_current_span().set_attribute(
        "entity_mention.bulk_count", len(entity_mentions)
    )
    return await service.resolve_bulk(entity_mentions)
