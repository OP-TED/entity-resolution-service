"""Resolution Coordinator Service — orchestrator for Spines A + B."""

import asyncio
import contextlib
import logging
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
from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.commons.services.exceptions import ServiceUnavailableError
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
from ers.request_registry.domain.errors import (
    DuplicateTriadError,
    RegistryConnectionError,
)
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

_log = logging.getLogger(__name__)

_PARSING_ERRORS = (
    ValueError,
    MalformedRDFError,
    ContentTooLargeError,
    UnsupportedEntityTypeError,
    EntityTypeMismatchError,
    MultipleEntitiesFoundError,
    EmptyExtractionError,
)

_MONGO_CONNECTION_ERRORS = (
    RegistryConnectionError,    # ers.request_registry.domain.errors
    RepositoryConnectionError,  # ers.resolution_decision_store.domain.errors
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
        if single_budget < 0:  # pylint: disable=comparison-with-callable
            raise ValueError(
                "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET must be >= 0"
            )
        if bulk_budget < 0:  # pylint: disable=comparison-with-callable
            raise ValueError(
                "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET must be >= 0"
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
    ) -> tuple[Decision, ResolutionOutcome]:
        """Resolve a single entity mention and return a Decision with its outcome.

        Registers the mention, checks for an existing decision, publishes to
        ERE, and waits for a response within the time budget. If ERE does not
        respond or Redis is unavailable, issues a provisional identifier.

        Replays always return CANONICAL: once a decision exists in the store,
        regardless of how it was originally created, it is the authoritative answer.

        Args:
            entity_mention: The entity mention to resolve.

        Returns:
            A tuple of (Decision, ResolutionOutcome). Outcome is CANONICAL when
            the decision came from ERE or is a replay; PROVISIONAL when ERS
            issued the draft identifier due to a timeout.

        Raises:
            ParsingFailedError: If registration fails due to invalid content.
            IdempotencyConflictError: If the triad exists with different content.
            ServiceUnavailableError: If a MongoDB or Redis/channel connection
                failure is detected during registration, publish, or provisional write.
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
        except _MONGO_CONNECTION_ERRORS as exc:
            raise ServiceUnavailableError("mongodb", str(exc)) from exc

        # 2. Check existing decision — instant return for replays (always CANONICAL)
        identifier = entity_mention.identifiedBy
        try:
            existing = await self._decision_store_service.get_decision_by_triad(
                identifier
            )
        except RepositoryConnectionError as exc:
            raise ServiceUnavailableError("mongodb", str(exc)) from exc
        if existing is not None:
            return existing, ResolutionOutcome.CANONICAL

        # 3. Immediate provisional mode — budget == 0 means ERE is not consulted.
        if config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET == 0:
            _log.debug(
                "ERE processing disabled (ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET=0): issuing"
                " provisional identifier immediately for %s/%s/%s.",
                identifier.source_id, identifier.request_id, identifier.entity_type,
            )
            return await self._issue_provisional(identifier)

        # 4+5+6. Publish → wait → provisional fallback
        triad_key = (
            f"{identifier.source_id}"
            f"{identifier.request_id}"
            f"{identifier.entity_type}"
        )
        event = await self._waiter.get_or_create(triad_key)
        try:
            decision = await self._publish_and_wait(entity_mention, event)
            if decision is not None:
                return decision, ResolutionOutcome.CANONICAL
            return await self._issue_provisional(identifier)
        finally:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(self._waiter.release(triad_key))

    async def _publish_and_wait(
        self,
        entity_mention: EntityMention,
        event: asyncio.Event,
    ) -> Decision | None:
        """Publish to ERE, await the waiter, and read the authoritative decision.

        Returns the persisted Decision if ERE responded inside the budget, or
        ``None`` if the budget elapsed (caller falls back to a provisional).

        Raises:
            ServiceUnavailableError: If Redis, the messaging channel, or the
                Decision Store is unreachable. The ``service_name`` field
                identifies which backend failed.
        """
        identifier = entity_mention.identifiedBy
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
            return await self._decision_store_service.get_decision_by_triad(
                identifier
            )
        except RedisConnectionError as exc:
            raise ServiceUnavailableError("redis", str(exc)) from exc
        except ChannelUnavailableError as exc:
            raise ServiceUnavailableError("channel", str(exc)) from exc
        except RepositoryConnectionError as exc:
            raise ServiceUnavailableError("mongodb", str(exc)) from exc
        except TimeoutError:
            return None

    async def resolve_bulk(
        self, entity_mentions: list[EntityMention]
    ) -> list[tuple[Decision, ResolutionOutcome] | BaseException]:
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
            A list of (Decision, ResolutionOutcome) tuples or BaseException in
            input order.

        Raises:
            ResolutionTimeoutError: If the bulk time budget is exceeded.
        """
        if not entity_mentions:
            return []
        tasks = [self.resolve_single(m) for m in entity_mentions]
        try:
            bulk_budget = config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET
            if bulk_budget == 0:
                results = await asyncio.gather(*tasks, return_exceptions=True)
            else:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=bulk_budget,
                )
            return list(results)
        except TimeoutError as exc:
            raise ResolutionTimeoutError(
                "Bulk resolution exceeded client time budget"
            ) from exc

    async def _issue_provisional(
        self, identifier: EntityMentionIdentifier
    ) -> tuple[Decision, ResolutionOutcome]:
        """Derive and persist a provisional singleton decision.

        Args:
            identifier: The entity mention triad.

        Returns:
            A tuple of (Decision, ResolutionOutcome.PROVISIONAL) when ERS writes
            the draft identifier, or (Decision, ResolutionOutcome.CANONICAL) when
            ERE has already written a decision (StaleOutcomeError race).

        Raises:
            ServiceUnavailableError: If the Decision Store is unreachable.
        """
        provisional_id = derive_provisional_cluster_id(identifier)
        cluster_ref = ClusterReference(
            cluster_id=provisional_id,
            confidence_score=0.0,
            similarity_score=0.0,
        )
        try:
            decision = await self._decision_store_service.store_decision(
                identifier=identifier,
                current=cluster_ref,
                candidates=[cluster_ref],
                updated_at=datetime.now(UTC),
            )
            return decision, ResolutionOutcome.PROVISIONAL
        except StaleOutcomeError as exc:
            try:
                decision = await self._decision_store_service.get_decision_by_triad(
                    identifier
                )
            except RepositoryConnectionError as conn_exc:
                raise ServiceUnavailableError("mongodb", str(conn_exc)) from conn_exc
            if decision is None:  # pragma: no cover — ERE wrote it moments ago
                raise ResolutionTimeoutError(
                    "Decision vanished after StaleOutcomeError"
                ) from exc
            return decision, ResolutionOutcome.CANONICAL
        except RepositoryConnectionError as exc:
            raise ServiceUnavailableError(
                "mongodb", f"Cannot persist provisional decision: {exc}"
            ) from exc


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
) -> tuple[Decision, ResolutionOutcome]:
    """Traced entry point for single-mention resolution."""
    return await service.resolve_single(entity_mention)


@trace_function(span_name="resolution_coordinator.resolve_bulk")
async def resolve_bulk(
    entity_mentions: list[EntityMention],
    service: ResolutionCoordinatorService,
) -> list[tuple[Decision, ResolutionOutcome] | BaseException]:
    """Traced entry point for bulk resolution."""
    trace.get_current_span().set_attribute(
        "entity_mention.bulk_count", len(entity_mentions)
    )
    return await service.resolve_bulk(entity_mentions)
