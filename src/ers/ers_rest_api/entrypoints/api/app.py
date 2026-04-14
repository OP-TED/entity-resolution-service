import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from ers import config
from ers.commons.adapters.mongo_client import MongoClientManager
from ers.commons.adapters.redis_client import RedisConnectionConfig, RedisEREClient
from ers.ers_rest_api.entrypoints.api.exception_handlers import register_exception_handlers
from ers.ers_rest_api.entrypoints.api.health import router as health_router
from ers.ers_rest_api.entrypoints.api.v1.router import v1_router

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage MongoDB, Redis, AsyncResolutionWaiter and EPIC-05 worker lifecycle."""
    # --- MongoDB ---
    manager = MongoClientManager(config.MONGO_URI, config.MONGO_DATABASE_NAME)
    await manager.connect()
    await manager.ensure_indexes()
    app.state.mongo_db = manager.get_database()

    # --- Redis client (shared by ERE publish + outcome listener) ---
    redis_config = RedisConnectionConfig.from_settings(config)
    redis_client = RedisEREClient(
        config_or_client=redis_config,
        request_channel=config.ERE_REQUEST_CHANNEL,
        response_channel=config.ERE_RESPONSE_CHANNEL,
    )
    app.state.redis_client = redis_client

    # --- RDF config (loaded once, shared via app.state) ---
    from ers.rdf_mention_parser.adapter.rdf_mapping_config_reader import RDFConfigReader

    app.state.rdf_config = RDFConfigReader.from_file(config.RDF_MENTION_CONFIG_FILE)

    # --- AsyncResolutionWaiter (process-scoped singleton) ---
    from ers.resolution_coordinator.services.async_resolution_waiter import (
        AsyncResolutionWaiter,
    )

    waiter = AsyncResolutionWaiter()
    app.state.waiter = waiter

    # --- EPIC-05: Outcome Integration Worker ---
    from ers.commons.adapters.hasher import SHA256ContentHasher
    from ers.ere_result_integrator.adapters.redis_outcome_listener import (
        RedisOutcomeListener,
    )
    from ers.ere_result_integrator.entrypoints.outcome_integration_worker import (
        OutcomeIntegrationWorker,
    )
    from ers.ere_result_integrator.services.outcome_integration_service import (
        OutcomeIntegrationService,
    )
    from ers.rdf_mention_parser.services.mention_parser_service import (
        parse_entity_mention,
    )
    from ers.request_registry.adapters.records_repository import (
        MongoLookupStateRepository,
        MongoResolutionRequestRepository,
    )
    from ers.request_registry.services.request_registry_service import (
        RequestRegistryService,
    )
    from ers.resolution_decision_store.adapters.decision_repository import (
        MongoDecisionRepository,
    )
    from ers.resolution_decision_store.services.decision_store_service import (
        DecisionStoreService,
    )

    db = app.state.mongo_db
    rdf_config = app.state.rdf_config

    registry_service = RequestRegistryService(
        resolution_repo=MongoResolutionRequestRepository(db),
        lookup_repo=MongoLookupStateRepository(db),
        hasher=SHA256ContentHasher(),
        mention_parser=lambda em: parse_entity_mention(em, rdf_config),
    )
    decision_service = DecisionStoreService(
        repository=MongoDecisionRepository(db),
    )

    outcome_service = OutcomeIntegrationService(
        registry_service=registry_service,
        decision_service=decision_service,
        on_outcome_stored=waiter.notify,
    )

    # Separate Redis client for the listener (needs its own BRPOP connection)
    listener_client = RedisEREClient(
        config_or_client=redis_config,
        request_channel=config.ERE_REQUEST_CHANNEL,
        response_channel=config.ERE_RESPONSE_CHANNEL,
    )
    listener = RedisOutcomeListener(client=listener_client)
    worker = OutcomeIntegrationWorker(listener=listener, service=outcome_service)
    worker.start()
    _log.info("OutcomeIntegrationWorker started in lifespan")

    try:
        yield
    finally:
        await worker.stop()
        _log.info("OutcomeIntegrationWorker stopped")
        await redis_client.close()
        await listener_client.close()
        await manager.close()


def _custom_openapi(app: FastAPI) -> dict[str, Any]:
    """Generate OpenAPI schema without the default 422 validation error response."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation.get("responses", {}).pop("422", None)

    app.openapi_schema = schema
    return schema


def create_app() -> FastAPI:
    """Application factory for the ERS REST API."""
    # Register OTel span attribute extractors. Must be imported here (not at module
    # level) so they are registered after the module graph is fully loaded.
    import ers.commons.adapters.span_extractors
    import ers.ere_contract_client.adapters.span_extractors
    import ers.ere_result_integrator.adapters.span_extractors
    import ers.request_registry.adapters.span_extractors
    import ers.resolution_decision_store.adapters.span_extractors  # noqa: F401

    app = FastAPI(
        title=config.ERS_API_NAME,
        description=(
            "The Entity Resolution Service (ERS) REST API provides endpoints for resolving"
            " entity mentions to canonical cluster identifiers, looking up existing cluster"
            " assignments, and synchronising assignment deltas. It serves as the primary"
            " integration point for external systems that need to resolve, deduplicate, or"
            " track entity mentions across multiple sources."
        ),
        debug=config.DEBUG,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router, prefix=config.ERS_API_PREFIX)

    app.openapi = lambda: _custom_openapi(app)  # type: ignore[method-assign]

    return app
