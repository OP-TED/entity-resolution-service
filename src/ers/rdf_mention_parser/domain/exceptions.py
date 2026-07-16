from ers.commons.domain.exceptions import DomainError


class UnsupportedEntityTypeError(DomainError):
    """Raised when an entity type URI has no matching entry in the parser configuration."""

    def __init__(self, entity_type_uri: str) -> None:
        self.entity_type_uri = entity_type_uri
        super().__init__(f"Entity type '{entity_type_uri}' not supported.")


class ContentTooLargeError(DomainError):
    """Raised when the RDF content exceeds the maximum allowed byte length."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"Content exceeds max size of {max_bytes} bytes.")


class UnsupportedContentTypeError(DomainError):
    """Raised when the MIME type of the RDF content is not supported."""

    def __init__(self, content_type: str) -> None:
        self.content_type = content_type
        super().__init__(f"Content type '{content_type}' not supported.")


class MalformedRDFError(DomainError):
    """Raised when the RDF content cannot be parsed."""

    def __init__(self, content_type: str) -> None:
        self.content_type = content_type
        super().__init__(f"Content is not valid {content_type}.")


class EntityTypeMismatchError(DomainError):
    """Raised when the graph contains no entity of the declared RDF type."""

    def __init__(self, entity_type_uri: str) -> None:
        self.entity_type_uri = entity_type_uri
        super().__init__(f"No entity of type '{entity_type_uri}' in content.")


class EmptyExtractionError(DomainError):
    """Raised when the SPARQL query returns no non-empty values for the configured fields."""

    def __init__(self, entity_type_uri: str) -> None:
        self.entity_type_uri = entity_type_uri
        super().__init__(f"No data extracted for type '{entity_type_uri}'.")


class MultipleEntitiesFoundError(DomainError):
    """Raised when the RDF payload contains more than one entity of the declared type."""

    def __init__(self, entity_type_uri: str, count: int) -> None:
        self.entity_type_uri = entity_type_uri
        self.count = count
        super().__init__(f"Expected exactly 1 entity of type '{entity_type_uri}', found {count}.")
