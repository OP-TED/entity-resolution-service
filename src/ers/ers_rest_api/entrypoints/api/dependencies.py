from typing import Annotated

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from ers.commons.adapters.decision_repository import BaseDecisionRepository, BaseMongoDecisionRepository
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.ers_rest_api.services.resolve_service import ResolveService
from ers.request_registry.adapters.records_repository import (
    MongoResolutionRequestRepository,
    ResolutionRequestRepository,
)
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorServiceABC,
)
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

# Infrastructure


def _get_database(request: Request) -> AsyncDatabase:
    return request.app.state.mongo_db


# Repository providers


# TODO (EPIC-06): this provider returns BaseMongoDecisionRepository from commons, which
# does not implement the curation-specific DecisionRepository methods.  When the
# Resolution Coordinator is wired, replace this with MongoDecisionRepository from
# ers.resolution_decision_store.adapters.decision_repository and consolidate with
# get_decision_store_service.
async def get_decision_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> BaseDecisionRepository:
    return BaseMongoDecisionRepository(db)


async def get_resolution_request_repository(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> ResolutionRequestRepository:
    return MongoResolutionRequestRepository(db)


# Module service providers (implementations pending their respective EPICs)


async def get_resolution_coordinator(
    resolution_request_repository: Annotated[
        ResolutionRequestRepository, Depends(get_resolution_request_repository)
    ],
    decision_repository: Annotated[BaseDecisionRepository, Depends(get_decision_repository)],
) -> ResolutionCoordinatorServiceABC:
    raise NotImplementedError("Resolution Coordinator implementation pending (EPIC-06)")


async def get_request_registry_service() -> RequestRegistryService:
    raise NotImplementedError("Request Registry Service wiring pending")


async def get_decision_store_service(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> DecisionStoreService:
    return DecisionStoreService(MongoDecisionRepository(db))


# Endpoint orchestrators


async def get_resolve_service(
    coordinator: Annotated[ResolutionCoordinatorServiceABC, Depends(get_resolution_coordinator)],
) -> ResolveService:
    return ResolveService(resolution_coordinator=coordinator)


async def get_lookup_service(
    decision_store: Annotated[DecisionStoreService, Depends(get_decision_store_service)],
) -> LookupService:
    return LookupService(decision_store=decision_store)


async def get_refresh_bulk_service(
    decision_store: Annotated[DecisionStoreService, Depends(get_decision_store_service)],
    registry: Annotated[RequestRegistryService, Depends(get_request_registry_service)],
) -> RefreshBulkService:
    return RefreshBulkService(decision_store=decision_store, registry=registry)
