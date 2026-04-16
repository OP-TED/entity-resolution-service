import asyncio
import logging
from collections.abc import Callable, Collection, Coroutine
from typing import Any

from erspec.models.core import Decision, EntityMention
from erspec.models.ere import EntityMentionResolutionRequest

from ers.commons.domain.data_transfer_objects import CursorPage, CursorParams
from ers.commons.services.exceptions import NotFoundError
from ers.curation.adapters.entity_mention_repository import (
    EntityMentionCurationRepository,
)
from ers.curation.domain.data_transfer_objects import (
    BulkActionResponse,
    BulkItemResult,
    BulkItemStatus,
    DecisionFilters,
    DecisionSummary,
    EntityMentionPreview,
)
from ers.curation.domain.exceptions import AlreadyCuratedError
from ers.curation.services.user_action_service import UserActionService
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.resolution_decision_store.adapters.decision_repository import DecisionRepository

log = logging.getLogger(__name__)


class DecisionCurationService:
    """Orchestrates curation actions and decision queries."""

    _BULK_CONCURRENCY = 25

    def __init__(
        self,
        decision_repository: DecisionRepository,
        entity_mention_repository: EntityMentionCurationRepository,
        user_action_service: UserActionService,
        ere_publish_service: EREPublishService,
    ) -> None:
        self._decision_repository = decision_repository
        self._entity_mention_repository = entity_mention_repository
        self._user_action_service = user_action_service
        self._ere_publish_service = ere_publish_service

    async def _get_decision_or_raise(self, decision_id: str) -> Decision:
        decision = await self._decision_repository.find_by_id(decision_id)
        if decision is None:
            raise NotFoundError("Decision", decision_id)
        return decision

    async def _publish_reevaluation(
        self,
        decision: Decision,
        proposed_cluster_ids: list[str] | None = None,
        excluded_cluster_ids: list[str] | None = None,
    ) -> None:
        """Publish an ERE re-evaluation request after a curation action.

        Fetches the entity mention from the repository and publishes a
        re-evaluation request to ERE. Skips silently if the entity mention
        is not found. Swallows ERE publish errors so the curation action
        response is not affected.

        Args:
            decision: The curated decision (provides entity mention identifier).
            proposed_cluster_ids: Clusters to propose (resolveConsideringRecommendation).
            excluded_cluster_ids: Clusters to exclude (resolveWithExclusions).
        """
        mentions = await self._entity_mention_repository.find_by_identifiers(
            [decision.about_entity_mention]
        )
        if not mentions:
            log.warning(
                "Entity mention not found for ERE re-evaluation: decision=%s identifier=%s",
                decision.id,
                decision.about_entity_mention,
            )
            return

        request = EntityMentionResolutionRequest(
            entity_mention=mentions[0],
            ere_request_id="",
            proposed_cluster_ids=proposed_cluster_ids or [],
            excluded_cluster_ids=excluded_cluster_ids or [],
        )
        try:
            await self._ere_publish_service.publish_request(request)
        except Exception:
            log.exception("Failed to publish ERE re-evaluation for decision %s", decision.id)

    async def list_decisions(
        self,
        filters: DecisionFilters,
        cursor_params: CursorParams,
    ) -> CursorPage[DecisionSummary]:
        """List decisions with filtering, cursor pagination, and embedded entity data."""
        mention_identifiers = None
        if filters.search is not None:
            mention_identifiers = await self._entity_mention_repository.search_identifiers(
                filters.search,
            )
            if not mention_identifiers:
                return CursorPage(results=[])

        page = await self._decision_repository.find_with_filters(
            filters=filters,
            cursor_params=cursor_params,
            mention_identifiers=mention_identifiers,
        )

        identifiers = [d.about_entity_mention for d in page.results]
        entity_mentions = await self._entity_mention_repository.find_by_identifiers(
            identifiers,
        )
        mention_map = self._index_by_identifier(entity_mentions)

        decision_summaries = [
            self._to_decision_summary(decision, mention_map) for decision in page.results
        ]

        return CursorPage(
            results=decision_summaries,
            count=page.count,
            next_cursor=page.next_cursor,
        )

    async def get_decision(self, decision_id: str) -> Decision:
        """Retrieve a single decision by ID.

        Raises:
            NotFoundError: If the decision does not exist.
        """
        return await self._get_decision_or_raise(decision_id)

    async def accept_decision(self, decision_id: str, actor: str) -> None:
        """Accept the top candidate for a decision.

        After recording the user action, forwards a resolveConsideringRecommendation
        request to ERE for re-evaluation with the current placement as the proposed cluster.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_accept(actor=actor, decision=decision)
        await self._publish_reevaluation(
            decision,
            proposed_cluster_ids=[decision.current_placement.cluster_id],
        )

    async def reject_decision(self, decision_id: str, actor: str) -> None:
        """Reject all candidates for a decision.

        After recording the user action, forwards a resolveWithExclusions
        request to ERE for re-evaluation excluding all current candidates.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_reject(actor=actor, decision=decision)
        await self._publish_reevaluation(
            decision,
            excluded_cluster_ids=[c.cluster_id for c in decision.candidates],
        )

    async def assign_decision(self, decision_id: str, cluster_id: str, actor: str) -> None:
        """Assign a decision to an alternative cluster.

        After recording the user action, forwards a resolveConsideringRecommendation
        request to ERE for re-evaluation with the assigned cluster as the proposed cluster.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
            InvalidClusterError: If cluster_id is not in candidates.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_assign(
            actor=actor, decision=decision, cluster_id=cluster_id
        )
        await self._publish_reevaluation(
            decision,
            proposed_cluster_ids=[cluster_id],
        )

    async def bulk_accept_decisions(
        self, decision_ids: Collection[str], actor: str
    ) -> BulkActionResponse:
        """Accept multiple decisions concurrently."""
        return await self._execute_bulk_action(decision_ids, actor, self.accept_decision)

    async def bulk_reject_decisions(
        self, decision_ids: Collection[str], actor: str
    ) -> BulkActionResponse:
        """Reject multiple decisions concurrently."""
        return await self._execute_bulk_action(decision_ids, actor, self.reject_decision)

    async def _execute_bulk_action(
        self,
        decision_ids: Collection[str],
        actor: str,
        action: Callable[[str, str], Coroutine[Any, Any, None]],
    ) -> BulkActionResponse:
        semaphore = asyncio.Semaphore(self._BULK_CONCURRENCY)

        async def _execute_single(decision_id: str) -> BulkItemResult:
            async with semaphore:
                return await self._try_single_action(decision_id, actor, action)

        results = await asyncio.gather(*(_execute_single(did) for did in decision_ids))
        return BulkActionResponse(results=list(results))

    @staticmethod
    async def _try_single_action(
        decision_id: str,
        actor: str,
        action: Callable[[str, str], Coroutine[Any, Any, None]],
    ) -> BulkItemResult:
        try:
            await action(decision_id, actor)
            return BulkItemResult(decision_id=decision_id, status=BulkItemStatus.SUCCESS)
        except NotFoundError:
            return BulkItemResult(decision_id=decision_id, status=BulkItemStatus.NOT_FOUND)
        except AlreadyCuratedError:
            return BulkItemResult(decision_id=decision_id, status=BulkItemStatus.ALREADY_CURATED)
        except Exception as exc:
            return BulkItemResult(
                decision_id=decision_id,
                status=BulkItemStatus.ERROR,
                detail=str(exc),
            )

    @staticmethod
    def _index_by_identifier(
        entity_mentions: list[EntityMention],
    ) -> dict[tuple[str, str, str], EntityMention]:
        return {
            (
                em.identifiedBy.source_id,
                em.identifiedBy.request_id,
                em.identifiedBy.entity_type,
            ): em
            for em in entity_mentions
        }

    @staticmethod
    def _to_decision_summary(
        decision: Decision,
        mention_map: dict[tuple[str, str, str], EntityMention],
    ) -> DecisionSummary:
        emi = decision.about_entity_mention
        key = (emi.source_id, emi.request_id, emi.entity_type)
        mention = mention_map.get(key)

        return DecisionSummary(
            id=decision.id,
            about_entity_mention=EntityMentionPreview(
                identified_by=emi,
                parsed_representation=(mention.parsed_representation if mention else None),
            ),
            current_placement=decision.current_placement,
            created_at=decision.created_at,
            updated_at=decision.updated_at,
        )


# ---------------------------------------------------------------------------
# Traced entry points — module-level
# ---------------------------------------------------------------------------

from opentelemetry import trace  # noqa: E402

from ers.commons.adapters.tracing import trace_function  # noqa: E402


@trace_function(span_name="curation.bulk_accept")
async def bulk_accept_decisions(
    decision_ids: Collection[str],
    actor: str,
    service: DecisionCurationService,
) -> BulkActionResponse:
    """Traced entry point for bulk accept."""
    trace.get_current_span().set_attribute("curation.bulk_count", len(decision_ids))
    result = await service.bulk_accept_decisions(decision_ids, actor)
    trace.get_current_span().set_attribute(
        "curation.bulk_success_count",
        sum(1 for r in result.results if r.status == BulkItemStatus.SUCCESS),
    )
    return result


@trace_function(span_name="curation.bulk_reject")
async def bulk_reject_decisions(
    decision_ids: Collection[str],
    actor: str,
    service: DecisionCurationService,
) -> BulkActionResponse:
    """Traced entry point for bulk reject."""
    trace.get_current_span().set_attribute("curation.bulk_count", len(decision_ids))
    result = await service.bulk_reject_decisions(decision_ids, actor)
    trace.get_current_span().set_attribute(
        "curation.bulk_success_count",
        sum(1 for r in result.results if r.status == BulkItemStatus.SUCCESS),
    )
    return result
