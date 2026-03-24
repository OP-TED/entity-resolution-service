"""Domain error hierarchy for the Resolution Decision Store."""
from ers.commons.services.exceptions import ApplicationError


class DecisionStoreError(ApplicationError):
    """Base for all Resolution Decision Store errors."""


class StaleOutcomeError(DecisionStoreError):
    """Raised when the incoming updated_at is not strictly greater than the stored updated_at."""

    def __init__(
        self,
        source_id: str,
        request_id: str,
        entity_type: str,
        stored_at: str,
        attempted_at: str,
    ) -> None:
        super().__init__(
            f"Stale outcome rejected for triad ({source_id}/{request_id}/{entity_type}): "
            f"stored={stored_at}, attempted={attempted_at}"
        )


class DecisionNotFoundError(DecisionStoreError):
    """Raised when a decision triad cannot be found when one is required."""


class RepositoryConnectionError(DecisionStoreError):
    """Raised when the MongoDB connection fails."""


class RepositoryOperationError(DecisionStoreError):
    """Raised when a MongoDB operation fails unexpectedly."""
