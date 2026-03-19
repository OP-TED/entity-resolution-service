from enum import StrEnum

from ers.commons.domain.data_transfer_objects import FrozenDTO


class ResolutionOutcome(StrEnum):
    CANONICAL = "CANONICAL"
    PROVISIONAL = "PROVISIONAL"


class ResolutionResult(FrozenDTO):
    """Result returned by the Resolution Coordinator after handling an entity mention intake."""

    canonical_entity_id: str
    outcome: ResolutionOutcome
    request_id: str
