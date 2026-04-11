"""FastAPI dependency providers for the ERS REST API.

All REST API services access domain functionality exclusively through the
Resolution Coordinator (EPIC-06). No repositories or lower-level services
are exposed directly to the REST API layer.
"""

from typing import Annotated, cast

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from ers.commons.adapters.hasher import SHA256ContentHasher
from ers.commons.adapters.redis_client import RedisEREClient
from ers.ere_contract_client.services.ere_publish_service import EREPublishService
from ers.ers_rest_api.services.lookup_service import LookupService
from ers.ers_rest_api.services.refresh_bulk_service import RefreshBulkService
from ers.ers_rest_api.services.resolve_service import ResolveService
from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig
from ers.rdf_mention_parser.services.mention_parser_service import parse_entity_mention
from ers.request_registry.adapters.records_repository import (
    MongoLookupStateRepository,
    MongoResolutionRequestRepository,
)
from ers.request_registry.services.request_registry_service import RequestRegistryService
from ers.resolution_coordinator.services.async_resolution_waiter import (
    AsyncResolutionWaiter,
)
from ers.resolution_coordinator.services.bulk_refresh_coordinator_service import (
    BulkRefreshCoordinatorService,
)
from ers.resolution_coordinator.services.resolution_coordinator_service import (
    ResolutionCoordinatorService,
)
from ers.resolution_decision_store.adapters.decision_repository import (
    MongoDecisionRepository,
)
from ers.resolution_decision_store.services.decision_store_service import (
    DecisionStoreService,
)

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


def _get_database(request: Request) -> AsyncDatabase:
    return cast(AsyncDatabase, request.app.state.mongo_db)


# ---------------------------------------------------------------------------
# Singleton accessors (from app.state, created in lifespan)
# ---------------------------------------------------------------------------


def _get_waiter(request: Request) -> AsyncResolutionWaiter:
    return cast(AsyncResolutionWaiter, request.app.state.waiter)


def _get_redis_client(request: Request) -> RedisEREClient:
    return cast(RedisEREClient, request.app.state.redis_client)


# ---------------------------------------------------------------------------
# RDF config (loaded once in lifespan, accessed via app.state)
# ---------------------------------------------------------------------------


def get_rdf_config(request: Request) -> RDFMappingConfig:
    """Return the RDF mapping config from app.state (loaded once in lifespan)."""
    return cast(RDFMappingConfig, request.app.state.rdf_config)


# ---------------------------------------------------------------------------
# Domain service providers (internal — not exposed to routers)
# ---------------------------------------------------------------------------


async def _get_decision_store_service(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
) -> DecisionStoreService:
    return DecisionStoreService(repository=MongoDecisionRepository(db))


async def _get_request_registry_service(
    db: Annotated[AsyncDatabase, Depends(_get_database)],
    rdf_config: Annotated[RDFMappingConfig, Depends(get_rdf_config)],
) -> RequestRegistryService:
    return RequestRegistryService(
        resolution_repo=MongoResolutionRequestRepository(db),
        lookup_repo=MongoLookupStateRepository(db),
        hasher=SHA256ContentHasher(),
        mention_parser=lambda em: parse_entity_mention(em, rdf_config),
    )


async def _get_ere_publish_service(
    client: Annotated[RedisEREClient, Depends(_get_redis_client)],
) -> EREPublishService:
    return EREPublishService(adapter=client)


# ---------------------------------------------------------------------------
# Coordinator providers
# ---------------------------------------------------------------------------


async def get_resolution_coordinator(
    registry: Annotated[RequestRegistryService, Depends(_get_request_registry_service)],
    publisher: Annotated[EREPublishService, Depends(_get_ere_publish_service)],
    decisions: Annotated[DecisionStoreService, Depends(_get_decision_store_service)],
    waiter: Annotated[AsyncResolutionWaiter, Depends(_get_waiter)],
) -> ResolutionCoordinatorService:
    return ResolutionCoordinatorService(
        registry_service=registry,
        ere_publish_service=publisher,
        decision_store_service=decisions,
        waiter=waiter,
    )


async def _get_bulk_refresh_coordinator(
    registry: Annotated[RequestRegistryService, Depends(_get_request_registry_service)],
    decisions: Annotated[DecisionStoreService, Depends(_get_decision_store_service)],
) -> BulkRefreshCoordinatorService:
    return BulkRefreshCoordinatorService(
        registry_service=registry,
        decision_store_service=decisions,
    )


# ---------------------------------------------------------------------------
# Endpoint orchestrators (injected into routers)
# ---------------------------------------------------------------------------


async def get_resolve_service(
    coordinator: Annotated[
        ResolutionCoordinatorService, Depends(get_resolution_coordinator)
    ],
) -> ResolveService:
    return ResolveService(resolution_coordinator=coordinator)


async def get_lookup_service(
    coordinator: Annotated[
        ResolutionCoordinatorService, Depends(get_resolution_coordinator)
    ],
    registry: Annotated[RequestRegistryService, Depends(_get_request_registry_service)],
) -> LookupService:
    return LookupService(resolution_coordinator=coordinator, registry_service=registry)


async def get_refresh_bulk_service(
    coordinator: Annotated[
        BulkRefreshCoordinatorService, Depends(_get_bulk_refresh_coordinator)
    ],
    registry: Annotated[RequestRegistryService, Depends(_get_request_registry_service)],
) -> RefreshBulkService:
    return RefreshBulkService(bulk_coordinator=coordinator, registry_service=registry)
