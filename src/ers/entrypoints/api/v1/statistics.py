from typing import Annotated

from fastapi import APIRouter, Depends

from ers.application.dtos import Statistics
from ers.application.services import StatisticsService
from ers.entrypoints.api.auth import VerifiedUser
from ers.entrypoints.api.dependencies import get_statistics_service
from ers.entrypoints.api.v1.schemas import StatisticsFiltersDep

router = APIRouter(prefix="/curation/stats", tags=["Statistics"])


@router.get("", response_model=Statistics)
async def get_statistics(
    filters: StatisticsFiltersDep,
    user: VerifiedUser,
    service: Annotated[StatisticsService, Depends(get_statistics_service)],
) -> Statistics:
    """Retrieve registry statistics and curation statistics with optional filtering."""
    return await service.get_statistics(filters=filters)
