import asyncio
import logging
from collections.abc import Callable, Collection, Coroutine
from typing import Any

from erspec.models.core import Decision, EntityMention, UserActionType
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
from ers.curation.services._pymongo_translation import translate_mongo_errors
from ers.curation.services.user_action_service import UserActionService
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.resolution_decision_store.adapters.decision_repository import (
    DecisionRepository,
    ReviewMetadata,
)

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
        action: UserActionType,
        proposed_cluster_ids: list[str] | None = None,
        excluded_cluster_ids: list[str] | None = None,
    ) -> None:
        """Publish an ERE re-evaluation request after a curation action.

        Fetches the entity mention from the repository and publishes a
        re-evaluation request to ERE. Skips silently if the entity mention
        is not found. Swallows ERE publish errors so the curation action
        response is not affected (best-effort delivery, TEDSWS-530).

        On a successful publish, logs the outgoing payload summary at INFO so the
        exclusions/proposals are auditable in the logs (TEDSWS-530).

        Args:
            decision: The curated decision (provides entity mention identifier).
            action: The curator action driving the re-evaluation.
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
            ere_request_id = await self._ere_publish_service.publish_request(request)
        except Exception:
            log.exception("Failed to publish ERE re-evaluation for decision %s", decision.id)
            return

        log.info(
            "Curator re-evaluation published: action=%s decision=%s "
            "proposed_cluster_ids=%s excluded_cluster_ids=%s ere_request_id=%s",
            action.value,
            decision.id,
            request.proposed_cluster_ids,
            request.excluded_cluster_ids,
            ere_request_id,
        )

    @translate_mongo_errors
    async def list_decisions(
        self,
        filters: DecisionFilters,
        cursor_params: CursorParams,
        *,
        ever_reviewed: bool | None = None,
        reviewed_since_placement: bool | None = None,
        reviewed: bool | None = None,
    ) -> CursorPage[DecisionSummary]:
        """List decisions with filtering, cursor pagination, and embedded entity data.

        Args:
            filters: Field-level filter criteria (entity type, confidence, etc.).
            cursor_params: Cursor-based pagination parameters.
            ever_reviewed: When True/False, filter on whether any curator action has
                ever been recorded against the decision. None disables it.
            reviewed_since_placement: When True/False, filter on whether a curator
                action exists since the current placement. None disables it.
            reviewed: Deprecated alias of ``reviewed_since_placement`` kept for
                backward compatibility; ignored when ``reviewed_since_placement``
                is set.

        Raises:
            ServiceUnavailableError: If MongoDB is unreachable for any of the
                repository reads. The curation API exception handler maps this to
                HTTP 503.
        """
        # Backward-compat: the legacy ``reviewed`` boolean maps to the
        # "since current placement" primitive.
        effective_reviewed_since_placement = (
            reviewed_since_placement if reviewed_since_placement is not None else reviewed
        )

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
            ever_reviewed=ever_reviewed,
            reviewed_since_placement=effective_reviewed_since_placement,
        )

        # Two independent reads sharing ``page.results`` as input — run them
        # concurrently. The previous third read against ``user_actions`` is gone
        # now that ``reviewed_since_placement`` is materialised on the decision
        # row and returned by ``find_review_metadata`` alongside the counter.
        identifiers = [d.about_entity_mention for d in page.results]
        decision_ids = [d.id for d in page.results]
        entity_mentions, review_metadata = await asyncio.gather(
            self._entity_mention_repository.find_by_identifiers(identifiers),
            self._decision_repository.find_review_metadata(decision_ids),
        )

        mention_map = self._index_by_identifier(entity_mentions)

        decision_summaries = [
            self._to_decision_summary(decision, mention_map, review_metadata)
            for decision in page.results
        ]

        return CursorPage(
            results=decision_summaries,
            count=page.count,
            next_cursor=page.next_cursor,
        )

    @translate_mongo_errors
    async def get_decision(self, decision_id: str) -> Decision:
        """Retrieve a single decision by ID.

        Raises:
            NotFoundError: If the decision does not exist.
            ServiceUnavailableError: If MongoDB is unreachable.
        """
        return await self._get_decision_or_raise(decision_id)

    async def accept_decision(self, decision_id: str, actor: str) -> None:
        """Accept the top candidate for a decision.

        After recording the user action, forwards an ERE re-evaluation request
        carrying ``proposed_cluster_ids=[current placement]`` (re-confirm).

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_accept(actor=actor, decision=decision)
        await self._publish_reevaluation(
            decision,
            action=UserActionType.ACCEPT_TOP,
            proposed_cluster_ids=[decision.current_placement.cluster_id],
        )

    async def reject_decision(self, decision_id: str, actor: str) -> None:
        """Reject all candidates for a decision.

        After recording the user action, forwards an ERE re-evaluation request
        carrying ``excluded_cluster_ids`` covering the current placement **and**
        all candidates (deduplicated) — see ``_reject_exclusion_ids``.

        Raises:
            NotFoundError: If the decision does not exist.
            AlreadyCuratedError: If already curated on current version.
        """
        decision = await self._get_decision_or_raise(decision_id)
        await self._user_action_service.record_reject(actor=actor, decision=decision)
        await self._publish_reevaluation(
            decision,
            action=UserActionType.REJECT_ALL,
            excluded_cluster_ids=self._reject_exclusion_ids(decision),
        )

    async def assign_decision(self, decision_id: str, cluster_id: str, actor: str) -> None:
        """Assign a decision to an alternative cluster.

        After recording the user action, forwards an ERE re-evaluation request
        carrying ``proposed_cluster_ids=[chosen cluster]``.

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
            action=UserActionType.ACCEPT_ALTERNATIVE,
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
    def _reject_exclusion_ids(decision: Decision) -> list[str]:
        """Build the exclusion set for a "reject all" action.

        Excludes the current placement **and** every candidate, deduplicated and
        order-preserving (placement first). The stored ``candidates`` never
        contains the current placement, so the placement must be added explicitly
        or it would leak to ERE as still valid (TEDSWS-530).

        Args:
            decision: The decision being rejected.

        Returns:
            The deduplicated cluster ids to exclude; always non-empty (the
            current placement is always present).
        """
        ordered = [decision.current_placement.cluster_id] + [
            c.cluster_id for c in decision.candidates
        ]
        return list(dict.fromkeys(ordered))

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
        review_metadata: dict[str, ReviewMetadata] | None = None,
    ) -> DecisionSummary:
        """Build a DecisionSummary from a Decision and its related data.

        Args:
            decision: The decision to summarise.
            mention_map: Index of EntityMention objects keyed by
                ``(source_id, request_id, entity_type)``.
            review_metadata: Optional mapping of ``decision_id`` → ``ReviewMetadata``
                (counter + flag, both materialised on the decision row). Missing
                keys default to ``ReviewMetadata(count=0, reviewed_since_placement=False)``.

        Returns:
            A DecisionSummary with all fields populated.
        """
        emi = decision.about_entity_mention
        key = (emi.source_id, emi.request_id, emi.entity_type)
        mention = mention_map.get(key)
        metadata = (review_metadata or {}).get(decision.id, ReviewMetadata())

        return DecisionSummary(
            id=decision.id,
            about_entity_mention=EntityMentionPreview(
                identified_by=emi,
                parsed_representation=(mention.parsed_representation if mention else None),
            ),
            current_placement=decision.current_placement,
            created_at=decision.created_at,
            updated_at=decision.updated_at,
            previous_review_count=metadata.previous_review_count,
            reviewed_since_placement=metadata.reviewed_since_placement,
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
