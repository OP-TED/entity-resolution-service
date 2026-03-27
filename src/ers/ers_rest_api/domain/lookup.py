"""Domain DTOs for cluster assignment lookup — /lookup, /lookup-bulk, and /refresh-bulk."""

from __future__ import annotations

from datetime import datetime

from erspec.models.core import ClusterReference, EntityMentionIdentifier
from pydantic import Field, model_validator

from ers import config
from ers.commons.domain.data_transfer_objects import ERSRequest, ERSResponse
from ers.ers_rest_api.domain.errors import ErrorResponse

# ---------------------------------------------------------------------------
# Lookup — single
# ---------------------------------------------------------------------------


class LookupRequest(ERSRequest):
    """Query parameters for GET /lookup."""

    identified_by: EntityMentionIdentifier = Field(
        ...,
        description="Triad identifying the entity mention to look up.",
    )


class LookupResponse(ERSResponse):
    """Current cluster assignment for an entity mention.

    Used as the response body for GET /lookup (single mention) and as
    each item inside RefreshBulkResponse (delta synchronisation).
    """

    identified_by: EntityMentionIdentifier = Field(
        ...,
        description="Triad identifying the entity mention.",
    )
    cluster_reference: ClusterReference = Field(
        ...,
        description="Current canonical cluster assignment for the mention.",
    )
    last_updated: datetime = Field(
        ...,
        description="Timestamp of the most recent assignment update.",
    )


# ---------------------------------------------------------------------------
# Bulk lookup
# ---------------------------------------------------------------------------


class BulkLookupRequest(ERSRequest):
    """Request body for POST /lookup-bulk."""

    mentions: list[LookupRequest] = Field(
        ...,
        min_length=1,
        description="One or more mention triads to look up in a single batch.",
    )


class BulkLookupResult(ERSResponse):
    """Result of looking up a single entity mention in a bulk batch.

    Each item is either a success (cluster_reference + last_updated present)
    or an error (error present), never both.
    """

    identified_by: EntityMentionIdentifier = Field(
        ...,
        description="Triad identifying the entity mention this result refers to.",
    )

    # Success fields
    cluster_reference: ClusterReference | None = Field(
        default=None,
        description="Current canonical cluster assignment for the mention.",
    )
    last_updated: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent assignment update.",
    )

    # Error fields (present when the mention failed)
    error: ErrorResponse | None = Field(
        default=None,
        description="Error response with a code and description.",
    )

    @model_validator(mode="after")
    def _check_success_xor_error(self) -> BulkLookupResult:
        is_success = self.cluster_reference is not None and self.last_updated is not None
        is_error = self.error is not None
        if not (is_success ^ is_error):
            raise ValueError(
                "BulkLookupResult must have either success fields "
                "(cluster_reference + last_updated) or error fields (error), "
                "not both or neither."
            )
        return self


class BulkLookupResponse(ERSResponse):
    """Response body for POST /lookup-bulk."""

    results: list[BulkLookupResult] = Field(
        ...,
        min_length=1,
        description="Per-mention results, one for each item in the request.",
    )


# ---------------------------------------------------------------------------
# Refresh bulk (delta synchronisation)
# ---------------------------------------------------------------------------


class RefreshBulkRequest(ERSRequest):
    """Request body for POST /refreshBulk."""

    source_id: str = Field(
        ...,
        min_length=1,
        description="Source system whose deltas to retrieve.",
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
        ...,
        description="Whether additional pages of deltas are available.",
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
