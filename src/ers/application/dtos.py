from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, Json

from erspec.models.core import (
    ClusterReference,
    EntityMentionIdentifier,
    EntityType,
)

T = TypeVar("T")

MAX_PER_PAGE = 50
DEFAULT_PER_PAGE = 20
BULK_ACTION_MAX_SIZE = 200


class FrozenDTO(BaseModel):
    """Base model for all application-layer DTOs."""

    model_config = ConfigDict(frozen=True)


class PaginationParams(FrozenDTO):
    """Pagination query parameters."""

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE)


class PaginatedResult(FrozenDTO, Generic[T]):
    """Paginated query result."""

    count: int
    previous: int | None = None
    next: int | None = None
    results: list[T]


class DecisionOrdering(str, Enum):
    """Allowed ordering options for decision listing."""

    CONFIDENCE_ASC = "confidence_score"
    CONFIDENCE_DESC = "-confidence_score"
    CREATED_AT_ASC = "created_at"
    CREATED_AT_DESC = "-created_at"
    UPDATED_AT_ASC = "updated_at"
    UPDATED_AT_DESC = "-updated_at"


class DecisionFilters(FrozenDTO):
    """Filtering criteria for decision queries."""

    entity_type: str | None = None
    confidence_min: float | None = None
    confidence_max: float | None = None
    similarity_min: float | None = None
    similarity_max: float | None = None
    search: str | None = None
    ordering: DecisionOrdering | None = None


class StatisticsFilters(FrozenDTO):
    """Filtering criteria for statistics queries."""

    entity_type: EntityType | None = None
    timeframe_start: datetime | None = None
    timeframe_end: datetime | None = None


class EntityMentionPreview(FrozenDTO):
    """Lightweight entity mention projection for display."""

    identified_by: EntityMentionIdentifier
    parsed_representation: Json[dict[str, Any]] | None = None


class DecisionSummary(FrozenDTO):
    """Decision summary for list display."""

    id: str
    about_entity_mention: EntityMentionPreview
    current_placement: ClusterReference
    created_at: datetime
    updated_at: datetime | None = None


class CanonicalEntityPreview(FrozenDTO):
    """Cluster preview with top entity mentions for display."""

    cluster_id: str
    confidence_score: float
    similarity_score: float
    top_entities: list[EntityMentionPreview]


class CurationStatistics(FrozenDTO):
    """Statistics about the curation process based on UserAction counts."""

    total_decisions: int
    selected_top: int
    selected_alternative: int
    rejected_all: int


class RegistryStatistics(FrozenDTO):
    """Statistics about the entity registry."""

    total_entity_mentions: int
    total_canonical_entities: int
    average_cluster_size: float
    resolution_requests: int


class Statistics(FrozenDTO):
    """Aggregated statistics for the curation dashboard."""

    registry: RegistryStatistics
    curation: CurationStatistics


class AssignRequest(FrozenDTO):
    """Request body for assigning an entity to an alternative cluster."""

    cluster_id: str


class BulkItemStatus(str, Enum):
    """Outcome of an individual bulk action item."""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    ALREADY_CURATED = "already_curated"
    ERROR = "error"


class BulkItemResult(FrozenDTO):
    """Result of a single decision within a bulk action."""

    decision_id: str
    status: BulkItemStatus
    detail: str | None = None


class BulkActionRequest(FrozenDTO):
    """Request body for bulk accept/reject operations."""

    decision_ids: set[str] = Field(..., min_length=1, max_length=BULK_ACTION_MAX_SIZE)


class BulkActionResponse(FrozenDTO):
    """Response body for bulk accept/reject operations."""

    results: list[BulkItemResult]
