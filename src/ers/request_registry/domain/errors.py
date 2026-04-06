"""Domain errors for the Request Registry module.

Repository-level errors belong here so that adapters can raise them without
importing from the services layer (which would violate the layering rules).
"""

from erspec.models.core import EntityMentionIdentifier

from ers.commons.services.exceptions import ApplicationError


class DuplicateTriadError(ApplicationError):
    """Raised by the adapter when MongoDB rejects a duplicate composite _id.

    Wraps pymongo DuplicateKeyError so that upper layers are shielded from
    the persistence technology.
    """

    def __init__(self, identifier: EntityMentionIdentifier) -> None:
        self.identifier = identifier
        message = (
            f"Duplicate triad: source_id='{identifier.source_id}', "
            f"request_id='{identifier.request_id}', "
            f"entity_type='{identifier.entity_type}'."
        )
        super().__init__(message)


class RepositoryConnectionError(ApplicationError):
    """Raised when the adapter cannot connect to MongoDB."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Repository connection error: {detail}")


class RepositoryOperationError(ApplicationError):
    """Raised when a MongoDB operation fails for any reason other than connectivity."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Repository operation error: {detail}")
