import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from ers import config
from ers.commons.adapters.mongo_client import MongoClientManager
from ers.commons.adapters.redis_client import RedisConnectionConfig, RedisEREClient
from ers.commons.adapters.tracing import (
    configure_auto_instrumentation,
    configure_fastapi_telemetry,
    configure_tracing,
    shutdown_tracing,
)
from ers.ers_rest_api.entrypoints.api.exception_handlers import register_exception_handlers
from ers.ers_rest_api.entrypoints.api.health import router as health_router
from ers.ers_rest_api.entrypoints.api.v1.router import v1_router
from ers.resolution_coordinator.services.async_resolution_waiter import (
    AsyncResolutionWaiter,
)

_log = logging.getLogger(__name__)


class _ReadinessSignal(Protocol):
    """Minimal structural type satisfied by NotificationSubscriberWorker."""

    @property
    def subscribed(self) -> asyncio.Event: ...


async def _await_subscriber_ready(worker: _ReadinessSignal, timeout: float) -> None:
    """Block until the notification subscriber has subscribed, or timeout.

    Closes the startup statelessness gap: peer ERS instances may publish
    cross-instance outcomes the moment this pod becomes routable, so we
    must wait for SUBSCRIBE before yielding to the HTTP server.

    Args:
        worker: Anything exposing a ``subscribed`` ``asyncio.Event``.
        timeout: Seconds to wait. ``0`` (or any non-positive value) skips
            the wait entirely — operator opt-out for single-instance
            deployments where the gate has no effect.
    """
    if timeout <= 0:
        return
    try:
        await asyncio.wait_for(worker.subscribed.wait(), timeout=timeout)
    except TimeoutError:
        _log.warning(
            "Notification subscriber not ready after %.1fs; cross-instance "
            "notifications may be lost during this window. The pod will "
            "continue starting in degraded mode.",
            timeout,
        )


def make_outcome_stored_callback(
    waiter: AsyncResolutionWaiter,
    ere_client: RedisEREClient,
    channel: str,
) -> Callable[[str], Awaitable[None]]:
    """Return an async callback that notifies locally first, then via Pub/Sub.

    Only publishes to ``channel`` when the local waiter has no event for the
    triad key — i.e. the ERE response was pulled by a different ERS instance.
    Single-instance deployments never touch Redis Pub/Sub on this path.

    Args:
        waiter: The process-local resolution waiter.
        ere_client: A Redis client able to publish on Pub/Sub channels.
        channel: The Pub/Sub channel name on which peers listen for outcomes.

    Returns:
        An async callable taking the triad key, suitable as
        ``OutcomeIntegrationService(on_outcome_stored=...)``.
    """
    async def _on_outcome_stored(key: str) -> None:
        if await waiter.notify(key):
            _log.debug(
                "ERE outcome for triad '%s': resolved on this instance, "
                "no cross-instance notification needed", key,
            )
            return
        _log.debug(
            "ERE outcome for triad '%s': no local waiter, publishing to '%s'", key, channel,
        )
        try:
            await ere_client.publish_notification(channel, key)
        except ConnectionError:
            _log.warning(
                "Cross-instance notification publish failed for triad '%s' on "
                "channel '%s'; remote waiter may time out to provisional",
                key, channel,
            )
            raise
    return _on_outcome_stored


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

    from ers.resolution_coordinator.entrypoints.notification_subscriber_worker import (
        NotificationSubscriberWorker,
    )

    notifications_channel = config.ERS_NOTIFICATIONS_CHANNEL
    ere_client = app.state.redis_client
    outcome_service = OutcomeIntegrationService(
        registry_service=registry_service,
        decision_service=decision_service,
        on_outcome_stored=make_outcome_stored_callback(waiter, ere_client, notifications_channel),
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

    # Dedicated subscriber connection (SUBSCRIBE mode cannot share LPUSH/BRPOP connections)
    subscriber_worker = NotificationSubscriberWorker(
        redis_config=redis_config,
        channel=notifications_channel,
        waiter=waiter,
    )
    subscriber_worker.start()
    _log.info("NotificationSubscriberWorker started in lifespan")

    # Gate the HTTP-traffic-yielding moment on a successful SUBSCRIBE handshake
    # so peer instances cannot publish into a not-yet-subscribed pod.
    await _await_subscriber_ready(
        subscriber_worker, timeout=config.ERS_SUBSCRIBER_READY_TIMEOUT
    )

    if config.ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET == 0:
        _log.info(
            "ERS_COORDINATOR_SINGLE_REQUEST_TIME_BUDGET=0: ERE processing disabled for"
            " single requests - ERS will generate provisional identifiers immediately"
            " without submitting to ERE."
        )
    if config.ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET == 0:
        _log.info(
            "ERS_COORDINATOR_BULK_REQUEST_TIME_BUDGET=0: outer bulk timeout disabled -"
            " no asyncio.wait_for wrapper applied to bulk resolution gather."
        )

    try:
        yield
    finally:
        await worker.stop()
        _log.info("OutcomeIntegrationWorker stopped")
        await subscriber_worker.stop()
        _log.info("NotificationSubscriberWorker stopped")
        await redis_client.close()
        await listener_client.close()
        await manager.close()
        shutdown_tracing()


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
    # Wire the ers logger into uvicorn's handler so application logs are visible.
    # Uvicorn only configures its own logger hierarchy; without this, ers.* records
    # have no handler and are silently dropped.
    _ers_log = logging.getLogger("ers")
    _ers_log.setLevel(logging.DEBUG if config.DEBUG else logging.INFO)
    for _h in logging.getLogger("uvicorn").handlers:
        _ers_log.addHandler(_h)

    # Bootstrap OTel tracing (no-op when TRACING_ENABLED=False).
    configure_tracing(config)
    configure_auto_instrumentation(config)

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

    configure_fastapi_telemetry(app, config)

    return app
