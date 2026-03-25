from datetime import datetime
from enum import StrEnum
from typing import Any, TypeVar

from erspec.models.core import (
    ClusterReference,
    EntityMentionIdentifier,
    UserActionType,
)
from pydantic import Field, Json

from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering, FrozenDTO

T = TypeVar("T")
BULK_ACTION_MAX_SIZE = 200

# DecisionFilters and DecisionOrdering are defined in ers.commons.domain.data_transfer_objects
# and re-exported here for backward compatibility.
__all__ = [
    "DecisionFilters",
    "DecisionOrdering",
]


class StatisticsFilters(FrozenDTO):
    """Filtering criteria for statistics queries."""

    entity_type: str | None = None
    timeframe_start: datetime | None = None
    timeframe_end: datetime | None = None


class UserActionFilters(FrozenDTO):
    """Filtering criteria for user action queries."""

    action_type: UserActionType | None = None
    actor: str | None = None
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None


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


class UserActionSummary(FrozenDTO):
    """User action summary for list display."""

    id: str
    about_entity_mention: EntityMentionPreview
    candidates: list[ClusterReference]
    selected_cluster: ClusterReference | None = None
    action_type: UserActionType
    actor: str
    created_at: datetime
    metadata: Any | None = None


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


class BulkItemStatus(StrEnum):
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
