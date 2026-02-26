from fastapi import APIRouter

from ers.entrypoints.api.v1.decisions import router as decisions_router
from ers.entrypoints.api.v1.statistics import router as statistics_router

v1_router = APIRouter()
v1_router.include_router(decisions_router)
v1_router.include_router(statistics_router)
