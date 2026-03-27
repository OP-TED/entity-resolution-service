from typing import Annotated

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from ers.commons.adapters.decision_repository import DecisionRepository, MongoDecisionRepository
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.ers_rest_api.services.resolve_service import ResolveService
from ers.request_registry.adapters.records_repository import (
    MongoResolutionRequestRepository,
    ResolutionRequestRepository,
)
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorServiceABC,
)
from ers.resolution_decision_store.services.resolution_decision_store_service import (
    ResolutionDecisionStoreServiceABC,
)

# Infrastructure


def _get_database(request: Request) -> AsyncDatabase:
    return request.app.state.mongo_db


# Repository providers


async def get_decision_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> DecisionRepository:
    return MongoDecisionRepository(db)


async def get_resolution_request_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> ResolutionRequestRepository:
    return MongoResolutionRequestRepository(db)


# Module service providers (implementations pending their respective EPICs)


async def get_resolution_coordinator(
    resolution_request_repository: Annotated[
        ResolutionRequestRepository, Depends(get_resolution_request_repository)
    ],
    decision_repository: Annotated[DecisionRepository, Depends(get_decision_repository)],
) -> ResolutionCoordinatorServiceABC:
    raise NotImplementedError("Resolution Coordinator implementation pending (EPIC-06)")


async def get_decision_store(
    decision_repository: Annotated[DecisionRepository, Depends(get_decision_repository)],
) -> ResolutionDecisionStoreServiceABC:
    raise NotImplementedError("Resolution Decision Store implementation pending (EPIC-04)")


# Endpoint orchestrators


async def get_resolve_service(
    coordinator: Annotated[ResolutionCoordinatorServiceABC, Depends(get_resolution_coordinator)],
) -> ResolveService:
    return ResolveService(resolution_coordinator=coordinator)


async def get_lookup_service(
    decision_store: Annotated[ResolutionDecisionStoreServiceABC, Depends(get_decision_store)],
) -> LookupService:
    return LookupService(decision_store=decision_store)


async def get_refresh_bulk_service(
    decision_store: Annotated[ResolutionDecisionStoreServiceABC, Depends(get_decision_store)],
) -> RefreshBulkService:
    return RefreshBulkService(decision_store=decision_store)
