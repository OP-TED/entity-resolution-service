from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from ers import config
from ers.commons.adapters.mongo_client import MongoClientManager
from ers.ers_rest_api.entrypoints.api.exception_handlers import register_exception_handlers
from ers.ers_rest_api.entrypoints.api.health import router as health_router
from ers.ers_rest_api.entrypoints.api.v1.router import v1_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage MongoDB client lifecycle for the ERS REST API."""
    manager = MongoClientManager(config.MONGO_URI, config.MONGO_DATABASE_NAME)
    await manager.connect()
    app.state.mongo_db = manager.get_database()
    try:
        yield
    finally:
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
    import ers.request_registry.adapters.span_extractors  # noqa: F401

    app = FastAPI(
        title=config.ERS_API_NAME,
        debug=config.DEBUG,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router, prefix=config.ERS_API_PREFIX)

    app.openapi = lambda: _custom_openapi(app)  # type: ignore[assignment]

    return app
