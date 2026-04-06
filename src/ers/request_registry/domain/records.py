"""Domain records for the Request Registry (EPIC-01).

Immutable Pydantic models representing the artefacts persisted and queried
by the Request Registry service. No I/O, no service logic, no framework deps.
"""

from __future__ import annotations

from datetime import datetime

from erspec.models.core import EntityMention, EntityMentionIdentifier, LookupState
from pydantic import Field, field_validator, model_validator

from ers.commons.domain.data_transfer_objects import FrozenDTO


class LookupRequestRecord(FrozenDTO, LookupState):
    """Per-source delta exposure marker for bulk synchronisation.

    Tracks the last point in time for which bulk results were successfully
    produced for a source. Maps to lastNotificationDate in the architecture.

    Advanced only after a bulk refresh response is successfully produced
    (not on request receipt). Regression is rejected by the service layer.
    """
    updated_at: datetime = Field(
        ...,
        description="Wall-clock UTC time of the last state record update. Must be timezone-aware.",
    )

    @field_validator("last_snapshot", "updated_at", mode="after")
    @classmethod
    def _must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("datetime fields must be timezone-aware")
        return v

    @model_validator(mode="after")
    def _updated_at_not_before_last_snapshot(self) -> LookupRequestRecord:
        if self.updated_at < self.last_snapshot:
            raise ValueError("updated_at must not be before last_snapshot")
        return self


class ResolutionRequestRecord(FrozenDTO, EntityMention):
    """Immutable intake record for a single entity mention resolution request.

    Created once on first submission. Never mutated after storage.
    content_hash enables idempotency conflict detection.
    """
    content_hash: str = Field(
        ...,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex digest of entity_mention.content (64 lowercase hex chars).",
    )
    received_at: datetime = Field(
        ...,
        description="UTC timestamp of first acceptance. Must be timezone-aware.",
    )

    @field_validator("received_at", mode="after")
    @classmethod
    def _received_at_must_be_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        return v

    @model_validator(mode="after")
    def _identified_by_fields_must_be_non_empty(self) -> ResolutionRequestRecord:
        ident: EntityMentionIdentifier = self.identifiedBy
        if not ident.source_id:
            raise ValueError("source_id must not be empty")
        if not ident.request_id:
            raise ValueError("request_id must not be empty")
        if not ident.entity_type:
            raise ValueError("entity_type must not be empty")
        return self
