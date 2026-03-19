from datetime import datetime
from enum import StrEnum

from erspec.models.core import ClusterReference, Decision
from pydantic import Field

from ers.commons.domain.data_transfer_objects import FrozenDTO

DEFAULT_REFRESH_BULK_LIMIT = 1000
MAX_REFRESH_BULK_LIMIT = 1000


class EntityMentionRequest(FrozenDTO):
    """Request body for POST /resolve."""

    source_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    entity_type: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    content_type: str = Field(
        default="application/ld+json"
    )  # can use an enum to restrict to specific content types
    context: str | None = None


class ResolutionOutcome(StrEnum):
    CANONICAL = "CANONICAL"
    PROVISIONAL = "PROVISIONAL"


class ResolveResponse(FrozenDTO):
    """Response body for POST /resolve."""

    canonical_entity_id: str
    status: ResolutionOutcome
    request_id: str


class ResolutionResult(FrozenDTO):
    """Result returned by the Resolution Coordinator after handling an entity mention intake."""

    canonical_entity_id: str
    outcome: ResolutionOutcome
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


class DeltaPage(FrozenDTO):
    """A page of changed decision assignments with cursor-based pagination."""

    deltas: list[Decision]
    continuation_cursor: str | None
    has_more: bool


class RefreshBulkResponse(FrozenDTO):
    """Response body for POST /refresh-bulk."""

    deltas: list[DeltaAssignment]
    has_more: bool
    continuation_cursor: str | None = None


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    MENTION_NOT_FOUND = "MENTION_NOT_FOUND"
    SERVICE_ERROR = "SERVICE_ERROR"


class ErrorResponse(FrozenDTO):
    """Standard error response body."""

    error_code: ErrorCode
    detail: str
