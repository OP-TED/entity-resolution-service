from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel

from ers.commons.domain.data_transfer_objects import (
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    CursorParams,
    PaginationParams,
)
from ers.curation.domain.data_transfer_objects import (
    DecisionFilters,
    DecisionOrdering,
    StatisticsFilters,
)


class ErrorResponse(BaseModel):
    """Standard error response body for OpenAPI documentation."""

    detail: str


# Query parameter dependencies
def get_pagination(
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    per_page: Annotated[
        int, Query(ge=1, le=MAX_PER_PAGE, description="Items per page")
    ] = DEFAULT_PER_PAGE,
) -> PaginationParams:
    return PaginationParams(page=page, per_page=per_page)


def get_decision_filters(
    entity_type: Annotated[str | None, Query(description="Filter by entity type")] = None,
    confidence_min: Annotated[
        float | None, Query(ge=0, le=1, description="Minimum confidence")
    ] = None,
    confidence_max: Annotated[
        float | None, Query(ge=0, le=1, description="Maximum confidence")
    ] = None,
    similarity_min: Annotated[
        float | None, Query(ge=0, le=1, description="Minimum similarity")
    ] = None,
    similarity_max: Annotated[
        float | None, Query(ge=0, le=1, description="Maximum similarity")
    ] = None,
    search: Annotated[str | None, Query(description="Search text")] = None,
    ordering: Annotated[DecisionOrdering | None, Query(description="Ordering field")] = None,
) -> DecisionFilters:
    return DecisionFilters(
        entity_type=entity_type,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        similarity_min=similarity_min,
        similarity_max=similarity_max,
        search=search,
        ordering=ordering,
    )


def get_statistics_filters(
    entity_type: Annotated[str | None, Query(description="Filter by entity type")] = None,
    timeframe_start: Annotated[datetime | None, Query(description="Start of timeframe")] = None,
    timeframe_end: Annotated[datetime | None, Query(description="End of timeframe")] = None,
) -> StatisticsFilters:
    return StatisticsFilters(
        entity_type=entity_type,
        timeframe_start=timeframe_start,
        timeframe_end=timeframe_end,
    )


Pagination = Annotated[PaginationParams, Depends(get_pagination)]
DecisionFiltersDep = Annotated[DecisionFilters, Depends(get_decision_filters)]
StatisticsFiltersDep = Annotated[StatisticsFilters, Depends(get_statistics_filters)]


def get_cursor_params(
    cursor: Annotated[
        str | None, Query(description="Pagination cursor from previous response")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=MAX_PER_PAGE, description="Items per page")
    ] = DEFAULT_PER_PAGE,
) -> CursorParams:
    return CursorParams(cursor=cursor, limit=limit)


CursorPagination = Annotated[CursorParams, Depends(get_cursor_params)]
