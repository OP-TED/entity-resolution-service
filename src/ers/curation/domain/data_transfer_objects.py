from datetime import datetime
from enum import StrEnum
from typing import Any

from erspec.models.core import (
    ClusterReference,
    EntityMentionIdentifier,
    UserActionType,
)
from pydantic import Field, Json

from ers.commons.domain.data_transfer_objects import DecisionFilters, DecisionOrdering, FrozenDTO

BULK_ACTION_MAX_SIZE = 200

__all__ = [
    "DecisionFilters",
    "DecisionOrdering",
    "BaseOrdering",
]


class BaseOrdering(StrEnum):
    """Base ordering options available to all entity listings."""

    CREATED_AT_ASC = "created_at"
    CREATED_AT_DESC = "-created_at"


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
    ordering: BaseOrdering | None = None


class EntityMentionPreview(FrozenDTO):
    """Lightweight entity mention projection for display."""

    identified_by: EntityMentionIdentifier
    parsed_representation: Json[dict[str, Any]] | None = Field(
        default=None, description="Parsed key-value representation of the entity mention."
    )


class DecisionSummary(FrozenDTO):
    """Decision summary for list display."""

    id: str = Field(description="Unique identifier of the curation decision.")
    about_entity_mention: EntityMentionPreview
    current_placement: ClusterReference
    created_at: datetime = Field(description="Timestamp when the decision was created.")
    updated_at: datetime | None = Field(
        default=None, description="Timestamp of the last update to this decision."
    )


class ActorSummary(FrozenDTO):
    """Embedded actor info for user action display."""

    id: str = Field(description="Unique identifier of the actor.")
    email: str = Field(description="Email address of the actor.")


class UserActionSummary(FrozenDTO):
    """User action summary for list display."""

    id: str = Field(description="Unique identifier of the user action.")
    about_entity_mention: EntityMentionPreview
    candidates: list[ClusterReference] = Field(
        description="Candidate clusters presented to the curator."
    )
    selected_cluster: ClusterReference | None = None
    action_type: UserActionType
    actor: ActorSummary
    created_at: datetime = Field(description="Timestamp when the user action was recorded.")
    metadata: Any | None = Field(
        default=None, description="Optional additional metadata attached to the action."
    )


class CanonicalEntityPreview(FrozenDTO):
    """Cluster preview with top entity mentions for display."""

    cluster_id: str = Field(description="Unique identifier of the canonical entity cluster.")
    confidence_score: float = Field(
        description="Model confidence that this cluster is the correct match."
    )
    similarity_score: float = Field(
        description="Similarity score between the entity mention and the cluster."
    )
    top_entities: list[EntityMentionPreview] = Field(
        description="Representative entity mentions from this cluster."
    )


class CurationStatistics(FrozenDTO):
    """Statistics about the curation process based on UserAction counts."""

    total_decisions: int = Field(description="Total number of curation decisions recorded.")
    selected_top: int = Field(
        description="Number of decisions where the top-ranked candidate was accepted."
    )
    selected_alternative: int = Field(
        description="Number of decisions where an alternative candidate was selected."
    )
    rejected_all: int = Field(description="Number of decisions where all candidates were rejected.")


class RegistryStatistics(FrozenDTO):
    """Statistics about the entity registry."""

    total_entity_mentions: int = Field(
        description="Total number of entity mentions stored in the registry."
    )
    total_canonical_entities: int = Field(
        description="Total number of distinct canonical entity clusters."
    )
    average_cluster_size: float = Field(
        description="Average number of entity mentions per canonical entity cluster."
    )
    resolution_requests: int = Field(
        description="Total number of entity resolution requests processed."
    )


class Statistics(FrozenDTO):
    """Aggregated statistics for the curation dashboard."""

    registry: RegistryStatistics
    curation: CurationStatistics


class AssignRequest(FrozenDTO):
    """Request body for assigning an entity to an alternative cluster."""

    cluster_id: str = Field(
        description="Identifier of the target canonical entity cluster to assign the mention to."
    )


class BulkItemStatus(StrEnum):
    """Outcome of an individual bulk action item."""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    ALREADY_CURATED = "already_curated"
    ERROR = "error"


class BulkItemResult(FrozenDTO):
    """Result of a single decision within a bulk action."""

    decision_id: str = Field(description="Identifier of the decision this result refers to.")
    status: BulkItemStatus
    detail: str | None = Field(
        default=None, description="Human-readable explanation when the status is not success."
    )


class BulkActionRequest(FrozenDTO):
    """Request body for bulk accept/reject operations."""

    decision_ids: set[str] = Field(
        ...,
        min_length=1,
        max_length=BULK_ACTION_MAX_SIZE,
        description="Set of decision identifiers to process in a single bulk operation.",
    )


class BulkActionResponse(FrozenDTO):
    """Response body for bulk accept/reject operations."""

    results: list[BulkItemResult] = Field(
        description="Per-decision outcomes for the bulk operation."
    )
