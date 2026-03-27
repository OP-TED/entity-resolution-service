from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

MAX_PER_PAGE = 50
DEFAULT_PER_PAGE = 20


class FrozenDTO(BaseModel):
    """Base model for all application-layer DTOs."""

    model_config = ConfigDict(frozen=True)


class ERSRequest(FrozenDTO):
    """Base class for all ERS REST API request DTOs.

    Mirrors the ERERequest / EREResponse pattern from erspec,
    providing an extraction point if these models are later
    promoted to the erspec contract.
    """


class ERSResponse(FrozenDTO):
    """Base class for all ERS REST API response DTOs.

    Mirrors the ERERequest / EREResponse pattern from erspec,
    providing an extraction point if these models are later
    promoted to the erspec contract.
    """


class PaginationParams(FrozenDTO):
    """Pagination query parameters."""

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE)


class PaginatedResult[T](FrozenDTO):
    """Paginated query result."""

    count: int
    previous: int | None = None
    next: int | None = None
    results: list[T]


class CursorParams(FrozenDTO):
    """Cursor-based pagination parameters."""

    cursor: str | None = None
    limit: int = Field(default=DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE)


class CursorPage[T](FrozenDTO):
    """Cursor-paginated query result."""

    results: list[T]
    next_cursor: str | None = None


class ResolutionOutcome(StrEnum):
    """Possible outcomes of a single entity mention resolution.

    CANONICAL — the cluster ID was produced by the Entity Resolution Engine.
    PROVISIONAL — the cluster ID was derived deterministically (singleton).
    """

    CANONICAL = "CANONICAL"
    PROVISIONAL = "PROVISIONAL"
