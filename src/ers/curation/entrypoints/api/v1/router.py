from fastapi import APIRouter

from ers.curation.entrypoints.api.v1.auth import router as auth_router
from ers.curation.entrypoints.api.v1.decisions import router as decisions_router
from ers.curation.entrypoints.api.v1.entity_types import router as entity_types_router
from ers.curation.entrypoints.api.v1.statistics import router as statistics_router
from ers.curation.entrypoints.api.v1.user_actions import router as user_actions_router
from ers.curation.entrypoints.api.v1.users import router as users_router

v1_router = APIRouter()
v1_router.include_router(auth_router)
v1_router.include_router(decisions_router)
v1_router.include_router(entity_types_router)
v1_router.include_router(statistics_router)
v1_router.include_router(user_actions_router)
v1_router.include_router(users_router)
