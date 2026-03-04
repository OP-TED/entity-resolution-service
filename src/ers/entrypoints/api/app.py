from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ers.adapters.mongodb import MongoClientManager
from ers.config import Settings, get_settings
from ers.entrypoints.api.exception_handlers import register_exception_handlers
from ers.entrypoints.api.health import router as health_router
from ers.entrypoints.api.v1.router import v1_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage MongoDB client lifecycle."""
    settings: Settings = app.state.settings
    manager = MongoClientManager(settings.mongo_uri, settings.mongo_database_name)
    await manager.connect()
    await manager.ensure_indexes()
    app.state.mongo_db = manager.get_database()
    try:
        yield
    finally:
        await manager.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory for the FastAPI instance."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router, prefix=settings.api_v1_prefix)

    return app
