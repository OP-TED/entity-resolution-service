from ers.commons.domain.exceptions import DomainError


class InvalidClusterError(DomainError):
    """Raised when a cluster reference is invalid for the operation."""

    def __init__(self, cluster_id: str, decision_id: str) -> None:
        self.cluster_id = cluster_id
        self.decision_id = decision_id
        message = f"Cluster '{cluster_id}' is not a valid candidate for decision '{decision_id}'"
        super().__init__(message)


class AlreadyCuratedError(DomainError):
    """Raised when a decision has already been curated on its current version."""

    def __init__(self, decision_id: str) -> None:
        self.decision_id = decision_id
        message = f"Decision '{decision_id}' has already been curated on its current version"
        super().__init__(message)
