"""Domain errors for the ERE Result Integrator (EPIC-05).

Both errors subclass ApplicationError to integrate with the existing
ERS exception hierarchy and FastAPI exception handlers.
"""
from erspec.models.core import EntityMentionIdentifier

from ers.commons.services.exceptions import ApplicationError


class OutcomeValidationError(ApplicationError):
    """Raised when an ERE response fails contract validation.

    Triggered by:
    - ``response.timestamp`` is ``None``
    - ``response.candidates`` is empty

    Args:
        detail: Human-readable description of the validation failure.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class TriadNotFoundError(ApplicationError):
    """Raised when the correlation triad is not found in the Request Registry.

    Outcome is logged at WARN level and ignored - the Decision Store is not modified.

    Args:
        identifier: The triad that could not be resolved.
    """

    def __init__(self, identifier: EntityMentionIdentifier) -> None:
        self.identifier = identifier
        super().__init__(
            f"Triad not found: ({identifier.source_id}, "
            f"{identifier.request_id}, {identifier.entity_type})"
        )
