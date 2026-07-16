# Task 5 — Global Config Management

## Status: Complete (2026-03-18)

### Outcome
All 8 implementation steps delivered. 390 unit+feature tests passing. Key files:
- `src/ers/commons/adapters/config_resolver.py` — `ConfigResolverABC`, `EnvConfigResolver`, `DefaultConfigResolver`, `env_property`
- `src/ers/__init__.py` — all domain config classes + `config` singleton, `load_dotenv()` at import
- `src/ers/config.py` — deleted
- `ruff.toml` — `[lint.per-file-ignores]` for N802 on `ers/__init__.py`
- `tests/unit/commons/adapters/test_config_resolver.py` — 11 tests
- `tests/unit/commons/adapters/test_app_config.py` — 17 tests

---

---

## 1. Goal

Replace the existing `pydantic_settings`-based `Settings` class with a unified, strategy-based
configuration resolver system. All config values are declared as `@env_property`-decorated
methods on domain config classes. A module-level singleton `config` provides the single access
point across the entire application.

---

## 2. Design

### 2.1 Infrastructure — `src/ers/commons/adapters/config_resolver.py`

| Class / Function | Responsibility |
|-----------------|----------------|
| `ConfigResolverABC` | Abstract base. Contract: `concrete_config_resolve(name, default)`. Also provides `config_resolve(default)` which auto-derives the config name from the calling method via `inspect.stack`. |
| `EnvConfigResolver` | Reads from `os.environ.get(name, default)`. The default resolver. |
| `DefaultConfigResolver` | Returns `default_value` only — no env lookup. Useful in tests and as a terminal fallback. |
| `env_property(config_resolver_class, default_value)` | Decorator factory. Wraps a method as a `@property`. Calls `resolver.concrete_config_resolve(func.__name__, default_value)` and passes the result as `config_value` to the method body. **Method name = env var key.** |

Key design rules:
- `concrete_config_resolve` always returns `str | None`. Type coercion is the method body's job.
- The resolver class and default are set per-property at decoration time.
- Adding a new source (Vault, SSM, etc.) = one new class, no existing code touched (OCP).

### 2.2 Domain Config Classes + Singleton — `src/ers/__init__.py`

`load_dotenv()` is called at the top of `ers/__init__.py` before any config class is instantiated.
This populates `os.environ` from `.env` if present; already-set env vars take precedence
(standard python-dotenv behaviour).

One class per infrastructure concern:

| Class | Config keys |
|-------|-------------|
| `AppConfig` | `APP_NAME`, `DEBUG`, `API_V1_PREFIX`, `CORS_ORIGINS` (JSON-decoded list) |
| `JWTConfig` | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_MINUTES` |
| `AdminConfig` | `ADMIN_EMAIL`, `ADMIN_PASSWORD` |
| `MongoDBConfig` | `MONGO_URI`, `MONGO_DATABASE_NAME` |
| `RDFMentionParserConfig` | `ERS_PARSER_MAX_CONTENT_LENGTH` (int) |

Aggregated via multiple inheritance:

```python
class AppConfigResolver(AppConfig, JWTConfig, AdminConfig,
                        MongoDBConfig, RDFMentionParserConfig):
    """Aggregates all ERS configuration."""

config = AppConfigResolver()
```

Consumers import as: `from ers import config`

### 2.3 `.env` Loading

```python
# src/ers/__init__.py  (top of file)
from dotenv import load_dotenv
load_dotenv()  # no-op if .env absent; pre-set env vars win
```

`python-dotenv` must be added to `pyproject.toml` (not currently a dependency).
`pydantic-settings` is removed once migration is complete.

---

## 3. Migration from `pydantic_settings`

| Old | New |
|-----|-----|
| `from ers.config import Settings, get_settings` | `from ers import config` |
| `settings.mongo_uri` | `config.MONGO_URI` |
| `settings.jwt_secret_key` | `config.JWT_SECRET_KEY` |
| `settings.cors_origins` | `config.CORS_ORIGINS` |
| `Depends(get_settings)` | `Depends(lambda: config)` or direct use |
| `os.environ.get("ERS_PARSER_MAX_CONTENT_LENGTH", …)` in service | `config.ERS_PARSER_MAX_CONTENT_LENGTH` |
| `src/ers/config.py` | deleted |

Call sites to update (all in `src/ers/curation/entrypoints/`):
- `api/dependencies.py`
- `api/app.py`
- `api/v1/schemas.py`

And `src/ers/rdf_mention_parser/services/mention_parser_service.py` (remove module-level `os.environ.get`).

---

## 4. Test Strategy

**Unit tests** — `tests/unit/commons/adapters/test_config_resolver.py`
- `EnvConfigResolver` reads from env via `monkeypatch.setenv`
- `DefaultConfigResolver` returns default regardless of env
- `env_property` decorator wires method name to resolver

**Unit tests** — `tests/unit/commons/adapters/test_app_config.py`
- Each domain config class tested in isolation using `DefaultConfigResolver`
- Type coercions tested: int, bool, float, list (JSON)
- Edge cases: empty string, missing env var → default used

**No integration tests needed** for this task (env var behaviour is fully unit-testable).

---

## 5. Implementation Steps

1. Add `python-dotenv` to `pyproject.toml`; remove `pydantic-settings`
2. Create `src/ers/commons/adapters/config_resolver.py` (ABC + resolvers + decorator)
3. Update `src/ers/__init__.py` with `load_dotenv()` + all domain config classes + singleton
4. Delete `src/ers/config.py`
5. Update all call sites in `curation/entrypoints/`
6. Update `mention_parser_service.py` to use `config.ERS_PARSER_MAX_CONTENT_LENGTH`
7. Write unit tests for resolver infrastructure and domain config classes
8. Run `make test` — all existing tests must stay green
