from erspec.models.core import EntityMentionIdentifier

from ers.ers_rest_api.domain.errors import ErrorCode, ErrorResponse
from ers.ers_rest_api.domain.lookup import (
    BulkLookupRequest,
    BulkLookupResponse,
    BulkLookupResult,
    LookupResponse,
)
from ers.ers_rest_api.services.exceptions import MentionNotFoundError
from ers.resolution_decision_store.services.resolution_decision_store_service import (
    ResolutionDecisionStoreServiceABC,
)


class LookupService:
    """Orchestrator for the GET /lookup and POST /lookup-bulk endpoints."""

    def __init__(self, decision_store: ResolutionDecisionStoreServiceABC) -> None:
        self._decision_store = decision_store

    async def handle_lookup(
        self,
        source_id: str,
        request_id: str,
        entity_type: str,
    ) -> LookupResponse:
        """Look up the current cluster assignment for a mention triad."""
        decision = await self._decision_store.get_decision_for_mention(
            source_id=source_id,
            request_id=request_id,
            entity_type=entity_type,
        )

        if decision is None:
            raise MentionNotFoundError(source_id, request_id, entity_type)

        return LookupResponse(
            identified_by=EntityMentionIdentifier(
                source_id=decision.about_entity_mention.source_id,
                request_id=decision.about_entity_mention.request_id,
                entity_type=decision.about_entity_mention.entity_type,
            ),
            cluster_reference=decision.current_placement,
            last_updated=decision.updated_at or decision.created_at,
        )

    async def handle_bulk_lookup(
        self,
        request: BulkLookupRequest,
    ) -> BulkLookupResponse:
        """Look up cluster assignments for multiple mentions, collecting per-item results."""
        results: list[BulkLookupResult] = []
        for item in request.mentions:
            ident = item.identified_by
            try:
                # TODO: replace with batch lookup method to decision store service once available
                lookup = await self.handle_lookup(
                    source_id=ident.source_id,
                    request_id=ident.request_id,
                    entity_type=ident.entity_type,
                )
                results.append(
                    BulkLookupResult(
                        identified_by=lookup.identified_by,
                        cluster_reference=lookup.cluster_reference,
                        last_updated=lookup.last_updated,
                    )
                )
            except MentionNotFoundError:
                results.append(
                    BulkLookupResult(
                        identified_by=ident,
                        error=ErrorResponse(
                            error_code=ErrorCode.MENTION_NOT_FOUND,
                            detail=f"Mention ({ident.source_id}, {ident.request_id}, "
                            f"{ident.entity_type}) not found",
                        ),
                    )
                )
            except Exception:
                results.append(
                    BulkLookupResult(
                        identified_by=ident,
                        error=ErrorResponse(
                            error_code=ErrorCode.SERVICE_ERROR,
                            detail=f"Failed to look up mention ({ident.source_id}, "
                            f"{ident.request_id}, {ident.entity_type})",
                        ),
                    )
                )
        return BulkLookupResponse(results=results)
