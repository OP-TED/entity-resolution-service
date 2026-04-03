from fastapi import APIRouter

from ers.ers_rest_api.entrypoints.api.v1.lookup import router as lookup_router
from ers.ers_rest_api.entrypoints.api.v1.resolution import router as resolution_router

v1_router = APIRouter()
v1_router.include_router(resolution_router)
v1_router.include_router(lookup_router)
