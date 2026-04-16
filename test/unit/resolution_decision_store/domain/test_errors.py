from ers.commons.services.exceptions import ApplicationError
from ers.resolution_decision_store.domain.errors import (
    DecisionNotFoundError,
    DecisionStoreError,
    RepositoryConnectionError,
    RepositoryOperationError,
    StaleOutcomeError,
)


def test_all_errors_inherit_from_base():
    for cls in (
        StaleOutcomeError,
        DecisionNotFoundError,
        RepositoryConnectionError,
        RepositoryOperationError,
    ):
        assert issubclass(cls, DecisionStoreError)


def test_base_inherits_application_error():
    assert issubclass(DecisionStoreError, ApplicationError)


def test_stale_outcome_error_carries_detail():
    err = StaleOutcomeError(
        "s1", "r1", "Person", stored_at="2025-01-01", attempted_at="2024-12-31"
    )
    assert "s1" in str(err)


def test_stale_outcome_error_includes_both_timestamps():
    err = StaleOutcomeError(
        "src", "req", "Org", stored_at="2025-06-01", attempted_at="2025-05-31"
    )
    assert "2025-06-01" in str(err)
    assert "2025-05-31" in str(err)
