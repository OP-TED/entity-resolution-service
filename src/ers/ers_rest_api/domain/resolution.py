"""Domain DTOs for entity mention resolution — /resolve and /resolveBulk."""

from __future__ import annotations

from erspec.models.core import EntityMention, EntityMentionIdentifier
from pydantic import Field, model_validator

from ers.commons.domain.data_transfer_objects import ERSRequest, ERSResponse, ResolutionOutcome
from ers.ers_rest_api.domain.errors import ErrorResponse

# ---------------------------------------------------------------------------
# Single resolve
# ---------------------------------------------------------------------------


class EntityMentionResolutionRequest(ERSRequest):
    """Request body for POST /resolve (and each item in a bulk batch)."""

    mention: EntityMention = Field(description="The entity mention to resolve.")


class EntityMentionResolutionResult(ERSResponse):
    """Result of resolving a single entity mention.

    Used as the API response for POST /resolve, as the internal coordinator
    return value, and as the per-item result in bulk resolve responses.

    For single /resolve, this is always a success (errors become ErrorResponse
    via exception handlers).  In bulk context, individual items may carry
    error_code + detail instead of success fields.

    If the coordinator later needs to carry extra metadata, extract a
    dedicated internal model at that point.
    """

    identified_by: EntityMentionIdentifier = Field(
        ...,
        description="Triad identifying the entity mention this result refers to.",
    )

    # Success fields (present when resolution succeeded)
    canonical_entity_id: str | None = Field(
        default=None,
        description="Cluster identifier assigned to the mention.",
    )
    status: ResolutionOutcome | None = Field(
        default=None,
        description="Whether the resolution is canonical or provisional.",
    )

    # Error fields (present when the mention failed — bulk context only)
    error: ErrorResponse | None = Field(
        default=None,
        description="Error response with a code a description.",
    )

    @model_validator(mode="after")
    def _check_success_xor_error(self) -> EntityMentionResolutionResult:
        is_success = self.canonical_entity_id is not None and self.status is not None
        is_error = self.error is not None
        if not (is_success ^ is_error):
            raise ValueError(
                "EntityMentionResolutionResult must have either success fields "
                "(canonical_entity_id + status) or error fields (error), "
                "not both or neither."
            )
        return self


# ---------------------------------------------------------------------------
# Bulk resolve
# ---------------------------------------------------------------------------


class BulkResolveRequest(ERSRequest):
    """Request body for POST /resolveBulk."""

    mentions: list[EntityMentionResolutionRequest] = Field(
        ...,
        min_length=1,
        description="One or more entity mentions to resolve in a single batch.",
    )


class BulkResolveResponse(ERSResponse):
    """Response body for POST /resolveBulk."""

    results: list[EntityMentionResolutionResult] = Field(
        ...,
        min_length=1,
        description="Per-mention results, one for each item in the request.",
    )
