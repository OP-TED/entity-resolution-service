"""Internal DTOs for the Resolution Decision Store module."""

from erspec.models.core import Decision

from ers.commons.domain.data_transfer_objects import FrozenDTO


class DeltaPage(FrozenDTO):
    """A page of changed decision assignments with cursor-based pagination."""

    deltas: list[Decision]
    continuation_cursor: str | None
    has_more: bool
