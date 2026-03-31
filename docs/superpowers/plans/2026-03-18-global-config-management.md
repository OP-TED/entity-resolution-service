# Global Config Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `pydantic_settings.BaseSettings` with a unified `env_property` resolver pattern, exposing a single `config` singleton from `ers/__init__.py`.

**Architecture:** Resolver infrastructure lives in `ers/commons/adapters/config_resolver.py` (ABC + concrete resolvers + `env_property` decorator). Domain config classes and the aggregated `AppConfigResolver` singleton live in `src/ers/__init__.py`. `load_dotenv()` fires at import time so `.env` files are honoured; env vars already set in the process take precedence (standard python-dotenv semantics). All existing call sites are migrated from `Settings`/`get_settings()` to `from ers import config`.

**Tech Stack:** python-dotenv, pytest/monkeypatch, existing ruff/pylint toolchain.

**Spec:** `.claude/memory/epics/ers-epic-02-rdf-mention-parser/task5-global-config.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/ers/commons/adapters/config_resolver.py` | `ConfigResolverABC`, `EnvConfigResolver`, `DefaultConfigResolver`, `env_property` |
| Modify | `src/ers/__init__.py` | `load_dotenv()` + all domain config classes + `AppConfigResolver` + `config` singleton |
| Delete | `src/ers/config.py` | Removed once all callers migrated |
| Modify | `src/ers/curation/entrypoints/api/app.py` | Use `config` singleton |
| Modify | `src/ers/curation/entrypoints/api/dependencies.py` | Use `config` singleton |
| Modify | `src/ers/curation/entrypoints/api/v1/schemas.py` | Use `config.CURATION_CONFIDENCE_THRESHOLD` |
| Modify | `src/ers/rdf_mention_parser/services/mention_parser_service.py` | Use `config.ERS_PARSER_MAX_CONTENT_LENGTH` |
| Create | `tests/unit/commons/__init__.py` | Package marker |
| Create | `tests/unit/commons/adapters/__init__.py` | Package marker |
| Create | `tests/unit/commons/adapters/test_config_resolver.py` | Unit tests for resolver infrastructure |
| Create | `tests/unit/commons/adapters/test_app_config.py` | Unit tests for domain config classes |
| Modify | `tests/unit/curation/api/conftest.py` | Replace `Settings` fixture with env var monkeypatching |
| Modify | `tests/integration/conftest.py` | Replace `get_settings()` with `config` singleton |
| Modify | `pyproject.toml` | Add `python-dotenv`; remove `pydantic-settings` |

---

## Task 1: Add `python-dotenv` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency**

```bash
cd /path/to/repo && poetry add python-dotenv
```

- [ ] **Step 2: Verify lock file updated and venv synced**

```bash
poetry install
python -c "from dotenv import load_dotenv; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore: add python-dotenv dependency"
```

---

## Task 2: Create resolver infrastructure

**Files:**
- Create: `src/ers/commons/adapters/config_resolver.py`
- Create: `tests/unit/commons/__init__.py`
- Create: `tests/unit/commons/adapters/__init__.py`
- Create: `tests/unit/commons/adapters/test_config_resolver.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/commons/__init__.py` and `tests/unit/commons/adapters/__init__.py` as empty files.

Create `tests/unit/commons/adapters/test_config_resolver.py`:

```python
import pytest

from ers.commons.adapters.config_resolver import (
    DefaultConfigResolver,
    EnvConfigResolver,
    env_property,
)


class TestEnvConfigResolver:
    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "hello")
        resolver = EnvConfigResolver()
        assert resolver.concrete_config_resolve("MY_KEY") == "hello"

    def test_returns_default_when_missing(self):
        resolver = EnvConfigResolver()
        assert resolver.concrete_config_resolve("__NONEXISTENT__", "fallback") == "fallback"

    def test_returns_none_when_missing_no_default(self):
        resolver = EnvConfigResolver()
        assert resolver.concrete_config_resolve("__NONEXISTENT__") is None


class TestDefaultConfigResolver:
    def test_returns_default_ignoring_env(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "from_env")
        resolver = DefaultConfigResolver()
        assert resolver.concrete_config_resolve("MY_KEY", "my_default") == "my_default"

    def test_returns_none_when_no_default(self):
        resolver = DefaultConfigResolver()
        assert resolver.concrete_config_resolve("ANY_KEY") is None


class TestEnvProperty:
    def test_method_name_is_the_env_key(self, monkeypatch):
        monkeypatch.setenv("MY_SETTING", "42")

        class SampleConfig:
            @env_property()
            def MY_SETTING(self, config_value: str) -> int:
                return int(config_value)

        assert SampleConfig().MY_SETTING == 42

    def test_default_value_used_when_env_absent(self):
        class SampleConfig:
            @env_property(default_value="99")
            def ABSENT_KEY(self, config_value: str) -> int:
                return int(config_value)

        assert SampleConfig().ABSENT_KEY == 99

    def test_custom_resolver_class_is_used(self, monkeypatch):
        monkeypatch.setenv("OVERRIDE_ME", "from_env")

        class SampleConfig:
            @env_property(config_resolver_class=DefaultConfigResolver, default_value="from_default")
            def OVERRIDE_ME(self, config_value: str) -> str:
                return config_value

        # DefaultConfigResolver ignores env; returns default
        assert SampleConfig().OVERRIDE_ME == "from_default"

    def test_env_property_is_a_property(self):
        class SampleConfig:
            @env_property(default_value="x")
            def SOME_KEY(self, config_value: str) -> str:
                return config_value

        assert isinstance(SampleConfig.__dict__["SOME_KEY"], property)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
make test-unit -- tests/unit/commons/adapters/test_config_resolver.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `config_resolver` does not exist yet.

- [ ] **Step 3: Implement `config_resolver.py`**

Create `src/ers/commons/adapters/config_resolver.py`:

```python
import inspect
import logging
import os
from abc import ABC, abstractmethod
from typing import Type

logger = logging.getLogger(__name__)


class ConfigResolverABC(ABC):
    """Abstract base for configuration resolution strategies."""

    def config_resolve(self, default_value: str = None) -> str:
        """Resolve config using the caller method name as the key."""
        config_name = inspect.stack()[1][3]
        return self.concrete_config_resolve(config_name, default_value)

    @abstractmethod
    def concrete_config_resolve(self, config_name: str, default_value: str = None) -> str | None:
        """Resolve a named config value, returning default_value if not found."""
        raise NotImplementedError


class EnvConfigResolver(ConfigResolverABC):
    """Resolves config from environment variables."""

    def concrete_config_resolve(self, config_name: str, default_value: str = None) -> str | None:
        value = os.environ.get(config_name, default_value)
        logger.debug("[ENV] %s = %s (default: %s)", config_name, value, default_value)
        return value


class DefaultConfigResolver(ConfigResolverABC):
    """Returns only the supplied default — ignores environment variables.

    Useful in tests and as a terminal fallback in composite resolvers.
    """

    def concrete_config_resolve(self, config_name: str, default_value: str = None) -> str | None:
        return default_value


def env_property(
    config_resolver_class: Type[ConfigResolverABC] = EnvConfigResolver,
    default_value: str = None,
):
    """Decorator factory that turns a method into a config-backed property.

    The decorated method name becomes the environment variable key.
    The resolved string is passed as ``config_value``; the method body
    handles type coercion.

    Usage::

        class MyConfig:
            @env_property(default_value="5432")
            def DB_PORT(self, config_value: str) -> int:
                return int(config_value)
    """

    def decorator(func):
        @property
        def wrapper(self):
            resolver = config_resolver_class()
            config_value = resolver.concrete_config_resolve(func.__name__, default_value)
            return func(self, config_value)

        return wrapper

    return decorator
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
make test-unit -- tests/unit/commons/adapters/test_config_resolver.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/ers/commons/adapters/config_resolver.py \
        tests/unit/commons/__init__.py \
        tests/unit/commons/adapters/__init__.py \
        tests/unit/commons/adapters/test_config_resolver.py
git commit -m "feat(commons): add config resolver infrastructure and env_property decorator"
```

---

## Task 3: Implement domain config classes and singleton

**Files:**
- Modify: `src/ers/__init__.py`
- Create: `tests/unit/commons/adapters/test_app_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/commons/adapters/test_app_config.py`:

```python
import json

import pytest

from ers.commons.adapters.config_resolver import DefaultConfigResolver, env_property


# ---------------------------------------------------------------------------
# Helpers — build isolated config objects using DefaultConfigResolver so
# tests never depend on the real environment.
# ---------------------------------------------------------------------------

def _make(cls, **env_overrides):
    """Return an instance of cls with env vars set via monkeypatch."""
    return cls()


class TestAppConfig:
    def test_app_name_default(self, monkeypatch):
        monkeypatch.delenv("APP_NAME", raising=False)
        from ers import CurationAppConfig
        assert CurationAppConfig().APP_NAME == "Entity Resolution Service"

    def test_debug_default_is_false(self, monkeypatch):
        monkeypatch.delenv("DEBUG", raising=False)
        from ers import CurationAppConfig
        assert CurationAppConfig().DEBUG is False

    def test_debug_true_from_env(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")
        from ers import CurationAppConfig
        assert CurationAppConfig().DEBUG is True

    def test_cors_origins_default_is_list(self, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        from ers import CurationAppConfig
        assert CurationAppConfig().CORS_ORIGINS == ["*"]

    def test_cors_origins_from_env(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", '["https://a.com","https://b.com"]')
        from ers import CurationAppConfig
        assert CurationAppConfig().CORS_ORIGINS == ["https://a.com", "https://b.com"]


class TestJWTConfig:
    def test_algorithm_default(self, monkeypatch):
        monkeypatch.delenv("JWT_ALGORITHM", raising=False)
        from ers import JWTConfig
        assert JWTConfig().JWT_ALGORITHM == "HS256"

    def test_access_expire_minutes_is_int(self, monkeypatch):
        monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        from ers import JWTConfig
        assert isinstance(JWTConfig().ACCESS_TOKEN_EXPIRE_MINUTES, int)
        assert JWTConfig().ACCESS_TOKEN_EXPIRE_MINUTES == 15


class TestMongoDBConfig:
    def test_mongo_uri_default(self, monkeypatch):
        monkeypatch.delenv("MONGO_URI", raising=False)
        from ers import MongoDBConfig
        assert MongoDBConfig().MONGO_URI == "mongodb://localhost:27017"

    def test_mongo_database_name_from_env(self, monkeypatch):
        monkeypatch.setenv("MONGO_DATABASE_NAME", "mydb")
        from ers import MongoDBConfig
        assert MongoDBConfig().MONGO_DATABASE_NAME == "mydb"


class TestCurationConfig:
    def test_threshold_default_is_float(self, monkeypatch):
        monkeypatch.delenv("CURATION_CONFIDENCE_THRESHOLD", raising=False)
        from ers import CurationConfig
        assert CurationConfig().CURATION_CONFIDENCE_THRESHOLD == pytest.approx(0.85)

    def test_threshold_from_env(self, monkeypatch):
        monkeypatch.setenv("CURATION_CONFIDENCE_THRESHOLD", "0.75")
        from ers import CurationConfig
        assert CurationConfig().CURATION_CONFIDENCE_THRESHOLD == pytest.approx(0.75)


class TestRDFMentionParserConfig:
    def test_max_content_length_default(self, monkeypatch):
        monkeypatch.delenv("ERS_PARSER_MAX_CONTENT_LENGTH", raising=False)
        from ers import RDFMentionParserConfig
        assert RDFMentionParserConfig().ERS_PARSER_MAX_CONTENT_LENGTH == 1_048_576

    def test_max_content_length_from_env(self, monkeypatch):
        monkeypatch.setenv("ERS_PARSER_MAX_CONTENT_LENGTH", "2097152")
        from ers import RDFMentionParserConfig
        assert RDFMentionParserConfig().ERS_PARSER_MAX_CONTENT_LENGTH == 2_097_152


class TestAppConfigResolverSingleton:
    def test_config_singleton_has_all_keys(self):
        from ers import config
        assert hasattr(config, "APP_NAME")
        assert hasattr(config, "JWT_SECRET_KEY")
        assert hasattr(config, "MONGO_URI")
        assert hasattr(config, "CURATION_CONFIDENCE_THRESHOLD")
        assert hasattr(config, "ERS_PARSER_MAX_CONTENT_LENGTH")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
make test-unit -- tests/unit/commons/adapters/test_app_config.py -v
```

Expected: `ImportError` — `AppConfig` not yet defined in `ers`.

- [ ] **Step 3: Implement domain config classes in `src/ers/__init__.py`**

`src/ers/__init__.py` currently contains a single empty line — replace it entirely with the following:

```python
import json

from dotenv import load_dotenv

from ers.commons.adapters.config_resolver import EnvConfigResolver, env_property

load_dotenv()


class AppConfig:
    @env_property(default_value="Entity Resolution Service")
    def APP_NAME(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="false")
    def DEBUG(self, config_value: str) -> bool:
        return config_value.lower() == "true"

    @env_property(default_value="/api/v1")
    def API_V1_PREFIX(self, config_value: str) -> str:
        return config_value

    @env_property(default_value='["*"]')
    def CORS_ORIGINS(self, config_value: str) -> list[str]:
        return json.loads(config_value)


class JWTConfig:
    @env_property(default_value="change-me-in-production")
    def JWT_SECRET_KEY(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="HS256")
    def JWT_ALGORITHM(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="15")
    def ACCESS_TOKEN_EXPIRE_MINUTES(self, config_value: str) -> int:
        return int(config_value)

    @env_property(default_value="10080")
    def REFRESH_TOKEN_EXPIRE_MINUTES(self, config_value: str) -> int:
        return int(config_value)


class AdminConfig:
    @env_property(default_value="admin@ers.local")
    def ADMIN_EMAIL(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="changeme")
    def ADMIN_PASSWORD(self, config_value: str) -> str:
        return config_value


class CurationConfig:
    @env_property(default_value="0.85")
    def CURATION_CONFIDENCE_THRESHOLD(self, config_value: str) -> float:
        return float(config_value)


class MongoDBConfig:
    @env_property(default_value="mongodb://localhost:27017")
    def MONGO_URI(self, config_value: str) -> str:
        return config_value

    @env_property(default_value="ers")
    def MONGO_DATABASE_NAME(self, config_value: str) -> str:
        return config_value


class RDFMentionParserConfig:
    @env_property(default_value="1048576")
    def ERS_PARSER_MAX_CONTENT_LENGTH(self, config_value: str) -> int:
        return int(config_value)


class AppConfigResolver(
    AppConfig,
    JWTConfig,
    AdminConfig,
    CurationConfig,
    MongoDBConfig,
    RDFMentionParserConfig,
):
    """Aggregates all ERS configuration.

    Values are resolved lazily from environment variables at property access time.
    The .env file (if present) is loaded once at module import via load_dotenv().
    Environment variables already set in the process take precedence over .env values.
    """


config = AppConfigResolver()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
make test-unit -- tests/unit/commons/adapters/test_app_config.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/ers/__init__.py tests/unit/commons/adapters/test_app_config.py
git commit -m "feat(ers): add domain config classes and AppConfigResolver singleton"
```

---

## Task 4: Migrate curation entrypoints

**Files:**
- Modify: `src/ers/curation/entrypoints/api/app.py`
- Modify: `src/ers/curation/entrypoints/api/dependencies.py`
- Modify: `src/ers/curation/entrypoints/api/v1/schemas.py`

- [ ] **Step 1: Update `app.py`**

Replace the `Settings`-based logic. The new `create_app` no longer accepts a settings parameter — it always uses the `config` singleton.

```python
# src/ers/curation/entrypoints/api/app.py
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ers import config
from ers.commons.adapters.mongo_client import MongoClientManager
from ers.commons.adapters.mongo_collections_manager import MongoCollections
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
    from datetime import datetime, timezone

    from ers.users.domain.users import User

    collections = MongoCollections(db)  # type: ignore[arg-type]
    repo = MongoUserRepository(collections.users)
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
        created_at=datetime.now(timezone.utc),
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
```

- [ ] **Step 2: Update `dependencies.py`**

Replace `Settings`/`get_settings` import and `get_token_service` signature:

```python
# Remove:
from ers.config import Settings, get_settings

# Add:
from ers import config

# Replace get_token_service:
def get_token_service() -> TokenService:
    return JWTTokenService(
        secret_key=config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
        access_expire_minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES,
        refresh_expire_minutes=config.REFRESH_TOKEN_EXPIRE_MINUTES,
    )
```

- [ ] **Step 3: Update `schemas.py`**

```python
# Remove:
from ers.config import get_settings

# Add:
from ers import config

# Replace the default value:
confidence_max: float | None = Query(
    config.CURATION_CONFIDENCE_THRESHOLD,
    ge=0,
    le=1,
    description="Maximum confidence",
),
```

> **Note:** `config.CURATION_CONFIDENCE_THRESHOLD` is accessed here as a default argument in a `Query(...)` call, which means it is evaluated once at module import time (when `schemas.py` is first loaded), not at each request. This is identical to the old `get_settings().curation_confidence_threshold` behaviour. Any test that monkeypatches `CURATION_CONFIDENCE_THRESHOLD` after the module is already imported will not affect this default value. Tests that need to control it must set the env var **before** `schemas.py` is first imported, or mock the `Query` default directly.

- [ ] **Step 4: Run existing unit tests — all must pass**

```bash
make test-unit -- tests/unit/curation/ -v
```

Expected: ❌ failures in `tests/unit/curation/api/conftest.py` because `Settings` fixture still imports from `ers.config`. That's fixed in Task 5.

- [ ] **Step 5: Commit (entrypoints only)**

```bash
git add src/ers/curation/entrypoints/api/app.py \
        src/ers/curation/entrypoints/api/dependencies.py \
        src/ers/curation/entrypoints/api/v1/schemas.py
git commit -m "feat(curation): migrate entrypoints from Settings to config singleton"
```

---

## Task 5: Migrate `rdf_mention_parser` service

**Files:**
- Modify: `src/ers/rdf_mention_parser/services/mention_parser_service.py`

- [ ] **Step 1: Replace module-level `os.environ.get`**

In `mention_parser_service.py`, line 16:

```python
# Remove:
import os
MAX_CONTENT_LENGTH: int = int(os.environ.get("ERS_PARSER_MAX_CONTENT_LENGTH", 1_048_576))

# Add at top of file (with other imports):
from ers import config
```

Then in `MentionParserService.parse`, replace all uses of `MAX_CONTENT_LENGTH` with `config.ERS_PARSER_MAX_CONTENT_LENGTH`:

```python
content_bytes = content.encode("utf-8")
if len(content_bytes) > config.ERS_PARSER_MAX_CONTENT_LENGTH:
    logger.warning(
        "Content too large: entity_type=%s content_type=%s size=%d",
        entity_type,
        content_type,
        len(content_bytes),
    )
    raise ContentTooLargeError(config.ERS_PARSER_MAX_CONTENT_LENGTH)
```

- [ ] **Step 2: Run rdf_mention_parser unit tests**

```bash
make test-unit -- tests/unit/rdf_mention_parser/ -v
```

Expected: all green (env_property reads lazily, so existing test env patches still apply).

- [ ] **Step 3: Commit**

```bash
git add src/ers/rdf_mention_parser/services/mention_parser_service.py
git commit -m "feat(rdf-mention-parser): use config singleton for ERS_PARSER_MAX_CONTENT_LENGTH"
```

---

## Task 6: Migrate tests

**Files:**
- Modify: `tests/unit/curation/api/conftest.py`
- Modify: `tests/integration/conftest.py`

- [ ] **Step 1: Update `tests/unit/curation/api/conftest.py`**

The `settings` fixture is replaced with env var monkeypatching on the `app` fixture. Remove the `Settings` import entirely.

> **Ordering constraint:** `monkeypatch.setenv(...)` calls **must come before** `create_app()`. `create_app()` accesses `config.APP_NAME`, `config.DEBUG`, and `config.CORS_ORIGINS` synchronously during `FastAPI(...)` instantiation — the env vars must already be set at that point.

```python
# Remove:
from ers.config import Settings
# ...
@pytest.fixture
def settings() -> Settings:
    return Settings(app_name="Test ERS", debug=True)

# Replace the app fixture — no longer receives settings:
@pytest.fixture
def app(
    monkeypatch,
    decision_curation_service: AsyncMock,
    canonical_entity_service: AsyncMock,
    entity_service: AsyncMock,
    statistics_service: AsyncMock,
    auth_service: AsyncMock,
    user_action_service: AsyncMock,
    user_management_service: AsyncMock,
) -> FastAPI:
    monkeypatch.setenv("APP_NAME", "Test ERS")
    monkeypatch.setenv("DEBUG", "true")
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_decision_curation_service] = lambda: decision_curation_service
    app.dependency_overrides[get_canonical_entity_service] = lambda: canonical_entity_service
    app.dependency_overrides[get_entity_service] = lambda: entity_service
    app.dependency_overrides[get_statistics_service] = lambda: statistics_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_user_action_service] = lambda: user_action_service
    app.dependency_overrides[get_user_management_service] = lambda: user_management_service
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_CONTEXT
    return app
```

- [ ] **Step 2: Update `tests/integration/conftest.py`**

```python
# Remove:
from ers.config import get_settings

# Replace:
from ers import config

# In mongo_db fixture:
@pytest.fixture
async def mongo_db() -> AsyncDatabase:
    client = AsyncMongoClient(config.MONGO_URI)
    # ... rest unchanged
```

- [ ] **Step 3: Run all unit tests**

```bash
make test-unit -v
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/curation/api/conftest.py tests/integration/conftest.py
git commit -m "test: migrate test fixtures from Settings to config singleton"
```

---

## Task 7: Delete `ers/config.py` and remove `pydantic-settings`

**Files:**
- Delete: `src/ers/config.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Verify no remaining imports of `ers.config`**

```bash
grep -rn "from ers.config\|import ers.config" src/ tests/
```

Expected: no output. If any remain, fix them before proceeding.

- [ ] **Step 2: Delete `ers/config.py`**

```bash
git rm src/ers/config.py
```

- [ ] **Step 3: Remove `pydantic-settings` from `pyproject.toml`**

```bash
poetry remove pydantic-settings
```

- [ ] **Step 4: Run the full test suite**

```bash
make test-unit
```

Expected: all green, no import errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore: remove pydantic-settings and delete ers/config.py"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run full test suite including feature tests**

```bash
make test
```

Expected: all green.

- [ ] **Step 2: Check for linting issues**

```bash
make lint
```

Expected: no new errors.

- [ ] **Step 3: Verify import architecture (if importlinter configured)**

```bash
make check-architecture
```

- [ ] **Step 4: Smoke-test the app starts cleanly**

```bash
python -c "from ers.curation.entrypoints.api.app import create_app; app = create_app(); print('ok')"
```

Expected: `ok`
