from ers.commons.services.exceptions import ApplicationError


class MentionNotFoundError(ApplicationError):
    """Raised when a mention triad is not found in the Decision Store."""

    def __init__(self, source_id: str, request_id: str, entity_type: str) -> None:
        self.source_id = source_id
        self.request_id = request_id
        self.entity_type = entity_type
        message = f"Mention ({source_id}, {request_id}, {entity_type}) not found"
        super().__init__(message)
