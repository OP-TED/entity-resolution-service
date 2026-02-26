from erspec.models.core import CanonicalEntityIdentifier

from ers.application.ports.repositories import AsyncReadRepository


class CanonicalEntityRepository(
    AsyncReadRepository[CanonicalEntityIdentifier, str],
):
    """Read-only repository for canonical entity (cluster) retrieval."""
