from datetime import datetime
from enum import StrEnum

from erspec.models.core import ClusterReference
from pydantic import Field

from ers.commons.domain.data_transfer_objects import FrozenDTO
from ers.resolution_coordinator.domain.data_transfer_objects import ResolutionOutcome

DEFAULT_REFRESH_BULK_LIMIT = 1000
MAX_REFRESH_BULK_LIMIT = 1000


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    MENTION_NOT_FOUND = "MENTION_NOT_FOUND"
    SERVICE_ERROR = "SERVICE_ERROR"


class EntityMentionRequest(FrozenDTO):
    """Request body for POST /resolve."""

    source_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    entity_type: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    content_type: str = Field(default="application/ld+json")
    context: str | None = None


class ResolveResponse(FrozenDTO):
    """Response body for POST /resolve."""

    canonical_entity_id: str
    status: ResolutionOutcome
    request_id: str


class LookupResponse(FrozenDTO):
    """Response body for GET /lookup."""

    cluster_reference: ClusterReference
    last_updated: datetime


class RefreshBulkRequest(FrozenDTO):
    """Request body for POST /refresh-bulk."""

    source_id: str = Field(..., min_length=1)
    limit: int = Field(default=DEFAULT_REFRESH_BULK_LIMIT, gt=0, le=MAX_REFRESH_BULK_LIMIT)
    continuation_cursor: str | None = None


class DeltaAssignment(FrozenDTO):
    """A single changed assignment in a refresh-bulk response."""

    source_id: str
    request_id: str
    entity_type: str
    canonical_entity_id: str
    updated_at: datetime


class RefreshBulkResponse(FrozenDTO):
    """Response body for POST /refresh-bulk."""

    deltas: list[DeltaAssignment]
    has_more: bool
    continuation_cursor: str | None = None


class ErrorResponse(FrozenDTO):
    """Standard error response body."""

    error_code: ErrorCode
    detail: str
