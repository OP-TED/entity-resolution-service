"""Mock service implementations returning factory-generated responses.

Temporary stand-ins while real service implementations are pending.
Wire via FastAPI dependency_overrides in the app factory.
"""

from ers.commons.domain.data_transfer_objects import ResolutionOutcome
from ers.ers_rest_api.domain.lookup import (
    BulkLookupRequest,
    BulkLookupResponse,
    LookupResponse,
    RefreshBulkRequest,
    RefreshBulkResponse,
)
from ers.ers_rest_api.domain.resolution import (
    BulkResolveRequest,
    BulkResolveResponse,
    EntityMentionResolutionRequest,
    EntityMentionResolutionResult,
)
from tests.mock.ers_rest_api.factories import (
    BulkLookupResultFactory,
    LookupResponseFactory,
    RefreshBulkResponseFactory,
)
from tests.unit.factories import EntityMentionIdentifierFactory


class MockResolveService:
    """Returns factory-generated resolution results."""

    async def handle_resolve(
        self,
        request: EntityMentionResolutionRequest,
    ) -> EntityMentionResolutionResult:
        return EntityMentionResolutionResult(
            identified_by=request.mention.identifiedBy,
            canonical_entity_id=f"cluster-{EntityMentionIdentifierFactory.__faker__.uuid4()}",
            status=ResolutionOutcome.CANONICAL,
        )

    async def handle_bulk_resolve(
        self,
        request: BulkResolveRequest,
    ) -> BulkResolveResponse:
        results = [
            EntityMentionResolutionResult(
                identified_by=item.mention.identifiedBy,
                canonical_entity_id=f"cluster-{EntityMentionIdentifierFactory.__faker__.uuid4()}",
                status=ResolutionOutcome.CANONICAL,
            )
            for item in request.mentions
        ]
        return BulkResolveResponse(results=results)


class MockLookupService:
    """Returns factory-generated lookup results."""

    async def handle_lookup(
        self,
        source_id: str,
        request_id: str,
        entity_type: str,
    ) -> LookupResponse:
        return LookupResponseFactory.build(
            identified_by=EntityMentionIdentifierFactory.build(
                source_id=source_id,
                request_id=request_id,
                entity_type=entity_type,
            ),
        )

    async def handle_bulk_lookup(
        self,
        request: BulkLookupRequest,
    ) -> BulkLookupResponse:
        results = [
            BulkLookupResultFactory.build(identified_by=item.identified_by)
            for item in request.mentions
        ]
        return BulkLookupResponse(results=results)


class MockRefreshBulkService:
    """Returns factory-generated refresh bulk results."""

    async def handle_refresh_bulk(
        self,
        request: RefreshBulkRequest,
    ) -> RefreshBulkResponse:
        return RefreshBulkResponseFactory.build()
