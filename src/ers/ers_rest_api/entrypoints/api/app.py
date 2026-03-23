from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

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


def create_app() -> FastAPI:
    """Application factory for the ERS REST API."""
    app = FastAPI(
        title=config.ERS_API_NAME,
        debug=config.DEBUG,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router, prefix=config.ERS_API_PREFIX)

    return app
