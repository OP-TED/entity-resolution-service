import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from ers import config
from ers.commons.adapters.mongo_client import MongoClientManager
from ers.commons.adapters.redis_client import RedisConnectionConfig, RedisEREClient
from ers.curation.entrypoints.api.exception_handlers import register_exception_handlers
from ers.curation.entrypoints.api.health import router as health_router
from ers.curation.entrypoints.api.v1.router import v1_router
from ers.users.adapters import Argon2PasswordHasher, MongoUserRepository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage MongoDB and Redis client lifecycles and seed admin user."""
    manager = MongoClientManager(config.MONGO_URI, config.MONGO_DATABASE_NAME)
    await manager.connect()
    await manager.ensure_indexes()
    app.state.mongo_db = manager.get_database()

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

    await _seed_admin_user(app.state.mongo_db)

    try:
        yield
    finally:
        await redis_client.close()
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
        description=(
            "The Curation REST API enables human-in-the-loop review of entity resolution"
            " decisions. Curators can browse low-confidence matches, accept or reject"
            " proposed canonical entities, assign mentions to alternative clusters, and"
            " perform bulk curation actions. The API also provides authentication,"
            " user management, audit trails, and registry/curation statistics."
        ),
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

    app.openapi = lambda: _custom_openapi(app)  # type: ignore[method-assign]

    return app


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
