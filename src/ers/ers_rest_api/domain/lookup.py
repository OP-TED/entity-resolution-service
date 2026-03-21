"""Domain DTOs for cluster assignment lookup — /lookup and /refreshBulk."""

from __future__ import annotations

from datetime import datetime

from erspec.models.core import ClusterReference, EntityMentionIdentifier
from pydantic import Field, model_validator

from ers import config
from ers.commons.domain.data_transfer_objects import ERSRequest, ERSResponse

# ---------------------------------------------------------------------------
# Lookup — single and bulk
# ---------------------------------------------------------------------------


class LookupRequest(ERSRequest):
    """Query parameters for GET /lookup."""

    identified_by: EntityMentionIdentifier = Field(
        ..., description="Triad identifying the entity mention to look up.",
    )


class LookupResponse(ERSResponse):
    """Current cluster assignment for an entity mention.

    Used as the response body for GET /lookup (single mention) and as
    each item inside RefreshBulkResponse (delta synchronisation).
    """

    identified_by: EntityMentionIdentifier = Field(
        ..., description="Triad identifying the entity mention.",
    )
    cluster_reference: ClusterReference = Field(
        ..., description="Current canonical cluster assignment for the mention.",
    )
    last_updated: datetime = Field(
        ..., description="Timestamp of the most recent assignment update.",
    )


# ---------------------------------------------------------------------------
# Refresh bulk (delta synchronisation)
# ---------------------------------------------------------------------------


class RefreshBulkRequest(ERSRequest):
    """Request body for POST /refreshBulk."""

    source_id: str = Field(
        ..., min_length=1, description="Source system whose deltas to retrieve.",
    )
    limit: int = Field(
        default=config.REFRESH_BULK_MAX_LIMIT,
        gt=0,
        le=config.REFRESH_BULK_MAX_LIMIT,
        description="Maximum number of delta assignments to return per page.",
    )
    continuation_cursor: str | None = Field(
        default=None,
        description="Opaque cursor returned by a previous response for pagination.",
    )


class RefreshBulkResponse(ERSResponse):
    """Response body for POST /refreshBulk."""

    deltas: list[LookupResponse] = Field(
        default_factory=list,
        description="Changed assignments since the last synchronisation snapshot.",
    )
    has_more: bool = Field(
        ..., description="Whether additional pages of deltas are available.",
    )
    continuation_cursor: str | None = Field(
        default=None,
        description="Cursor to pass in the next request to retrieve the next page.",
    )

    @model_validator(mode="after")
    def _cursor_consistent_with_has_more(self) -> RefreshBulkResponse:
        if self.has_more and self.continuation_cursor is None:
            raise ValueError("continuation_cursor must be present when has_more is True")
        if not self.has_more and self.continuation_cursor is not None:
            raise ValueError("continuation_cursor must be absent when has_more is False")
        return self
