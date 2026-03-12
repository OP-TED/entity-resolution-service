import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ers.adapters.argon2_hasher import Argon2PasswordHasher
from ers.adapters.mongodb import (
    MongoClientManager,
    MongoCollections,
    MongoUserRepository,
)
from ers.config import Settings, get_settings
from ers.entrypoints.api.exception_handlers import register_exception_handlers
from ers.entrypoints.api.health import router as health_router
from ers.entrypoints.api.v1.router import v1_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage MongoDB client lifecycle and seed admin user."""
    settings: Settings = app.state.settings
    manager = MongoClientManager(settings.mongo_uri, settings.mongo_database_name)
    await manager.connect()
    await manager.ensure_indexes()
    app.state.mongo_db = manager.get_database()

    await _seed_admin_user(app.state.mongo_db, settings)

    try:
        yield
    finally:
        await manager.close()


async def _seed_admin_user(
    db: object,
    settings: Settings,
) -> None:
    """Create the default admin user if it does not exist."""
    import uuid
    from datetime import datetime, timezone

    from ers.domain.user import User

    collections = MongoCollections(db)  # type: ignore[arg-type]
    repo = MongoUserRepository(collections.users)
    existing = await repo.find_by_email(settings.admin_email)
    if existing is not None:
        return

    hasher = Argon2PasswordHasher()
    admin = User(
        id=str(uuid.uuid4()),
        email=settings.admin_email,
        hashed_password=hasher.hash(settings.admin_password),
        is_active=True,
        is_superuser=True,
        is_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(admin)
    logger.info("Seeded default admin user: %s", settings.admin_email)


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
