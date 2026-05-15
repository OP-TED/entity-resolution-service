"""Use-case exceptions for the Request Registry service layer.

Repository-level errors (DuplicateTriadError, RegistryConnectionError,
RepositoryOperationError) live in domain/errors.py so adapters can raise
them without importing from this module.
"""

from datetime import datetime

from erspec.models.core import EntityMentionIdentifier

from ers.commons.services.exceptions import ApplicationError


class IdempotencyConflictError(ApplicationError):
    """Raised when the same triad is resubmitted with a different content hash.

    Indicates that the caller is treating a previously registered request as a
    fresh submission by changing its content — a violation of idempotency.
    """

    def __init__(self, identifier: EntityMentionIdentifier) -> None:
        self.identifier = identifier
        message = (
            f"Idempotency conflict for triad "
            f"source_id='{identifier.source_id}', "
            f"request_id='{identifier.request_id}', "
            f"entity_type='{identifier.entity_type}': "
            "content hash differs from the stored record."
        )
        super().__init__(message)


class SnapshotRegressionError(ApplicationError):
    """Raised when advance_snapshot is called with a time at or before the current snapshot marker.

    The snapshot marker must advance monotonically.
    """

    def __init__(self, source_id: str, current: datetime, attempted: datetime) -> None:
        self.source_id = source_id
        self.current = current
        self.attempted = attempted
        message = (
            f"Snapshot regression for source_id='{source_id}': "
            f"attempted={attempted.isoformat()} is not after "
            f"current={current.isoformat()}."
        )
        super().__init__(message)
