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
    """Filtering criteria for user action queries.

    ``decision_id`` is a public API field accepted from entrypoints.  The
    service resolves it to ``about_entity_mention`` (the stored field on
    ``UserAction`` documents) before passing the filter to the repository.
    The repository uses ``about_entity_mention`` directly; it never reads
    ``decision_id``.
    """

    action_type: UserActionType | None = None
    actor: str | None = None
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    ordering: BaseOrdering | None = None
    decision_id: str | None = None
    about_entity_mention: EntityMentionIdentifier | None = Field(
        default=None,
        description=(
            "Internal filter set by the service after resolving decision_id. "
            "Matches user_action documents whose about_entity_mention equals "
            "the entity mention of the requested decision."
        ),
    )


class EntityTypeDescriptor(FrozenDTO):
    """Discoverability descriptor for a configured entity type."""

    name: str = Field(description="The entity type identifier (e.g. 'ORGANISATION').")
    display_name_field: str = Field(
        description=(
            "Key in parsed_representation that the UI should render as the entity's display title."
        )
    )


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
    previous_review_count: int = Field(
        default=0,
        description=(
            "Lifetime count of curator actions ever recorded against this decision. "
            "Persists across ERE re-integrations. Drives the UI 'previously reviewed' indicator."
        ),
    )
    reviewed_since_placement: bool = Field(
        default=False,
        description=(
            "True iff a curator action exists whose created_at is after the current "
            "placement boundary (updated_at, else created_at). Materialised on the "
            "decision row by two writers: the integrator resets it to False on every "
            "placement advance; record_review conditionally sets it to True when a "
            "curator action lands. With previous_review_count the UI composes the "
            "review state: count==0 -> not reviewed; count>0 and not this flag -> "
            "needs revisit; this flag -> reviewed and up to date."
        ),
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
    cluster_size: int = Field(
        description=(
            "Total number of decisions (entity mentions) assigned to this cluster,"
            " sourced from the cluster_sizes projection."
        ),
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
    cluster_size_average: float = Field(description="Average decisions per cluster.")
    cluster_size_median: float = Field(description="Median (p50) cluster size.")
    cluster_size_p95: int = Field(
        description="95th-percentile cluster size — surfaces long-tail outliers."
    )
    cluster_size_max: int = Field(description="Largest cluster size.")
    cluster_singletons_count: int = Field(description="Number of clusters of size 1.")
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
