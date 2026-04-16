from typing import Annotated

from fastapi import APIRouter, Depends

from ers.curation.domain.data_transfer_objects import Statistics
from ers.curation.entrypoints.api.auth import VerifiedUser
from ers.curation.entrypoints.api.dependencies import get_statistics_service
from ers.curation.entrypoints.api.v1.schemas import ErrorResponse, StatisticsFiltersDep
from ers.curation.services import StatisticsService

router = APIRouter(prefix="/curation/stats", tags=["Statistics"])


@router.get(
    "",
    responses={400: {"model": ErrorResponse}},
)
async def get_statistics(
    filters: StatisticsFiltersDep,
    user: VerifiedUser,
    service: Annotated[StatisticsService, Depends(get_statistics_service)],
) -> Statistics:
    """Retrieve registry statistics and curation statistics with optional filtering."""
    return await service.get_statistics(filters=filters)
