"""Outcome Integration Service - orchestrates ERE result absorption (EPIC-05).

Algorithm (6 steps from EPIC-05 §2.3):
  1. Validate message contract (timestamp, candidates).
  2. Extract identifier from response.
  3. Query Request Registry - reject unknown triads.
  4. Map response fields to store_decision() arguments.
  5. Persist to Decision Store - catch StaleOutcomeError.
  6. Notify coordinator via injected callback.
"""
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from erspec.models.core import Decision, EntityMentionIdentifier
from erspec.models.ere import EntityMentionResolutionResponse

from ers.commons.adapters.tracing import trace_function
from ers.ere_result_integrator.domain.errors import (
    OutcomeValidationError,
    TriadNotFoundError,
)
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_decision_store.domain.errors import StaleOutcomeError
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

_log = logging.getLogger(__name__)


class OutcomeIntegrationService:
    """Orchestrates ERE outcome validation, persistence, and coordinator notification.

    Args:
        registry_service: Used to verify the triad exists in the Request Registry.
        decision_service: Used to atomically persist the cluster assignment.
        on_outcome_stored: Optional async callback called after every persist attempt
            (including stale rejections). At runtime this is ``AsyncResolutionWaiter.notify``
            injected by the EPIC-07 lifespan. ``None`` is valid (testing / isolation mode).
    """

    def __init__(
        self,
        registry_service: RequestRegistryService,
        decision_service: DecisionStoreService,
        on_outcome_stored: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._registry = registry_service
        self._decisions = decision_service
        self._on_outcome_stored = on_outcome_stored

    async def integrate_outcome(
        self, response: EntityMentionResolutionResponse
    ) -> Decision | None:
        """Process one ERE resolution response end-to-end.

        Args:
            response: Deserialized ERE response from ``AsyncOutcomeListener.consume()``.

        Returns:
            The persisted ``Decision``, or ``None`` on stale rejection.

        Raises:
            OutcomeValidationError: If ``timestamp`` is ``None`` or ``candidates`` is empty.
            TriadNotFoundError: If the triad is not registered in the Request Registry.
        """
        # Step 1 - validate message contract
        if response.timestamp is None:
            raise OutcomeValidationError(
                "timestamp is None; ERE response must carry a timestamp"
            )
        if response.timestamp.tzinfo is None:
            raise OutcomeValidationError(
                "timestamp is timezone-naive; ERE response timestamp must be timezone-aware"
            )
        if not response.candidates:
            raise OutcomeValidationError(
                "candidates is empty; ERE response must have at least one candidate"
            )

        # Step 2 - extract identifier
        identifier: EntityMentionIdentifier = response.entity_mention_id

        # Step 3 - registry check
        record = await self._registry.get_resolution_request(identifier)
        if record is None:
            raise TriadNotFoundError(identifier)

        # Step 4 - map response to store_decision() arguments
        current = response.candidates[0]
        candidates = response.candidates[1:]
        updated_at: datetime = response.timestamp

        # Step 5 - persist (catch stale; always proceed to notify)
        decision: Decision | None = None
        try:
            decision = await self._decisions.store_decision(
                identifier=identifier,
                current=current,
                candidates=candidates,
                updated_at=updated_at,
            )
        except StaleOutcomeError:
            _log.debug(
                "Stale outcome rejected",
                extra={
                    "source_id": identifier.source_id,
                    "request_id": identifier.request_id,
                    "entity_type": identifier.entity_type,
                    "ere_request_id": response.ere_request_id,
                },
            )

        # Step 6 - notify coordinator (doorbell, not data pipe)
        if self._on_outcome_stored is not None:
            triad_key = (
                f"{identifier.source_id}"
                f"{identifier.request_id}"
                f"{identifier.entity_type}"
            )
            try:
                await self._on_outcome_stored(triad_key)
            except Exception as exc:
                _log.error(
                    "Coordinator notification failed - decision persisted but caller may hang",
                    exc_info=exc,
                    extra={"triad_key": triad_key},
                )

        return decision


# ── Public API (traced at the service boundary) ───────────────────────────────


@trace_function(span_name="outcome_integration.integrate_outcome")
async def integrate_outcome(
    response: EntityMentionResolutionResponse,
    service: OutcomeIntegrationService,
) -> Decision | None:
    """Process one ERE resolution response end-to-end.

    Args:
        response: Deserialized ERE response from ``AsyncOutcomeListener.consume()``.
        service: The OutcomeIntegrationService instance.

    Returns:
        The persisted ``Decision``, or ``None`` on stale rejection.

    Raises:
        OutcomeValidationError: If ``timestamp`` is ``None`` or ``candidates`` is empty.
        TriadNotFoundError: If the triad is not registered in the Request Registry.
    """
    return await service.integrate_outcome(response)
