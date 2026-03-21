import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ers import config
from ers.commons.adapters.mongo_client import MongoClientManager
from ers.curation.entrypoints.api.exception_handlers import register_exception_handlers
from ers.curation.entrypoints.api.health import router as health_router
from ers.curation.entrypoints.api.v1.router import v1_router
from ers.users.adapters import Argon2PasswordHasher, MongoUserRepository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage MongoDB client lifecycle and seed admin user."""
    manager = MongoClientManager(config.MONGO_URI, config.MONGO_DATABASE_NAME)
    await manager.connect()
    await manager.ensure_indexes()
    app.state.mongo_db = manager.get_database()

    await _seed_admin_user(app.state.mongo_db)

    try:
        yield
    finally:
        await manager.close()


async def _seed_admin_user(db: object) -> None:
    """Create the default admin user if it does not exist."""
    import uuid
    from datetime import datetime

    from ers.users.domain.users import User

    repo = MongoUserRepository(db)  # type: ignore[arg-type]
    existing = await repo.find_by_email(config.ADMIN_EMAIL)
    if existing is not None:
        return

    hasher = Argon2PasswordHasher()
    admin = User(
        id=str(uuid.uuid4()),
        email=config.ADMIN_EMAIL,
        hashed_password=hasher.hash(config.ADMIN_PASSWORD),
        is_active=True,
        is_superuser=True,
        is_verified=True,
        created_at=datetime.now(UTC),
    )
    await repo.save(admin)
    logger.info("Seeded default admin user: %s", config.ADMIN_EMAIL)


def create_app() -> FastAPI:
    """Application factory for the FastAPI instance."""
    app = FastAPI(
        title=config.APP_NAME,
        debug=config.DEBUG,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router, prefix=config.API_V1_PREFIX)

    return app
