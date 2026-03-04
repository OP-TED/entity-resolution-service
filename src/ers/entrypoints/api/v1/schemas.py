from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel

from erspec.models.core import EntityType
from ers.config import get_settings
from ers.application.dtos import (
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    DecisionFilters,
    DecisionOrdering,
    PaginationParams,
    StatisticsFilters,
)


class ErrorResponse(BaseModel):
    """Standard error response body for OpenAPI documentation."""

    detail: str


# Query parameter dependencies
def get_pagination(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(
        DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE, description="Items per page"
    ),
) -> PaginationParams:
    return PaginationParams(page=page, per_page=per_page)


def get_decision_filters(
    entity_type: EntityType | None = Query(None, description="Filter by entity type"),
    confidence_min: float | None = Query(
        None, ge=0, le=1, description="Minimum confidence"
    ),
    confidence_max: float | None = Query(
        get_settings().curation_confidence_threshold,
        ge=0,
        le=1,
        description="Maximum confidence",
    ),
    similarity_min: float | None = Query(
        None, ge=0, le=1, description="Minimum similarity"
    ),
    similarity_max: float | None = Query(
        None, ge=0, le=1, description="Maximum similarity"
    ),
    search: str | None = Query(None, description="Search text"),
    ordering: DecisionOrdering | None = Query(None, description="Ordering field"),
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
    entity_type: EntityType | None = Query(None, description="Filter by entity type"),
    timeframe_start: datetime | None = Query(None, description="Start of timeframe"),
    timeframe_end: datetime | None = Query(None, description="End of timeframe"),
) -> StatisticsFilters:
    return StatisticsFilters(
        entity_type=entity_type,
        timeframe_start=timeframe_start,
        timeframe_end=timeframe_end,
    )


Pagination = Annotated[PaginationParams, Depends(get_pagination)]
DecisionFiltersDep = Annotated[DecisionFilters, Depends(get_decision_filters)]
StatisticsFiltersDep = Annotated[StatisticsFilters, Depends(get_statistics_filters)]
