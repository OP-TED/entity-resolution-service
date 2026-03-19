"""Domain records for the Request Registry (EPIC-01).

Immutable Pydantic models representing the artefacts persisted and queried
by the Request Registry service. No I/O, no service logic, no framework deps.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from erspec.models.core import EntityMention, EntityMentionIdentifier
from pydantic import Field, field_validator, model_validator

from ers.commons.domain.data_transfer_objects import FrozenDTO


class LookupRequestType(StrEnum):
    """Distinguishes between a single-entity lookup and a bulk source refresh."""

    SINGLE = "SINGLE"
    BULK = "BULK"


class LookupRequestRecord(FrozenDTO):
    """Append-only audit record capturing that a lookup was requested from a source.

    Never mutated after storage. Multiple records per source_id are allowed
    (one per lookup request). The collection acts as an append-only log.
    """

    source_id: str = Field(
        ...,
        min_length=1,
        description="Source system identifier — which source requested the lookup.",
    )
    requested_at: datetime = Field(
        ...,
        description="UTC timestamp of the lookup request. Must be timezone-aware.",
    )
    request_type: LookupRequestType = Field(
        ...,
        description="Whether this is a SINGLE-entity lookup or a BULK source refresh.",
    )

    @field_validator("requested_at", mode="after")
    @classmethod
    def _requested_at_must_be_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("requested_at must be timezone-aware")
        return v


class JSONRepresentation(FrozenDTO):
    """Thin wrapper for a parsed JSON form of entity mention content.

    The data dict contains arbitrary key-value pairs produced by a parser (EPIC-02).
    No internal structure is validated in this EPIC.
    """

    data: dict[str, Any] = Field(..., description="Parsed JSON payload from the entity mention content.")


class ResolutionRequestRecord(FrozenDTO):
    """Immutable intake record for a single entity mention resolution request.

    Created once on first submission. Never mutated after storage.
    content_hash enables idempotency conflict detection.
    """

    identifier: EntityMentionIdentifier = Field(
        ...,
        description="Triad (source_id, request_id, entity_type) — unique key.",
    )
    entity_mention: EntityMention = Field(
        ...,
        description="Full entity mention payload as submitted.",
    )
    content_hash: str = Field(
        ...,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex digest of entity_mention.content (64 lowercase hex chars).",
    )
    received_at: datetime = Field(
        ...,
        description="UTC timestamp of first acceptance. Must be timezone-aware.",
    )
    json_representation: JSONRepresentation | None = Field(
        default=None,
        description="Parsed JSON form; populated by EPIC-02.",
    )

    @field_validator("received_at", mode="after")
    @classmethod
    def _received_at_must_be_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        return v


class LookupState(FrozenDTO):
    """Per-source delta exposure watermark for bulk synchronisation.

    Tracks the last point in time for which bulk results were successfully
    produced for a source. Maps to lastNotificationDate in the architecture.

    Advanced only after a bulk refresh response is successfully produced
    (not on request receipt). Regression is rejected by the service layer.
    """

    source_id: str = Field(
        ...,
        min_length=1,
        description="Source system identifier — unique key.",
    )
    last_snapshot: datetime = Field(
        ...,
        description="Last bulk refresh point; advances monotonically. Must be timezone-aware.",
    )
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
    def _updated_at_not_before_last_snapshot(self) -> LookupState:
        if self.updated_at < self.last_snapshot:
            raise ValueError("updated_at must not be before last_snapshot")
        return self
