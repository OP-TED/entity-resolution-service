---
name: Project automation setup
description: Toolchain, config file locations, dependency groups, Makefile targets, and quality-control layers for the ERS project
type: project
---

# ERS Project Automation Setup

## Toolchain

| Tool | Role | Config file |
|---|---|---|
| Poetry | Dependency management, packaging | `pyproject.toml` |
| Ruff | Formatting + linting (replaces black, isort, pylint) | `ruff.toml` |
| mypy | Type checking | `mypy.ini` |
| pytest | Test runner | `pytest.ini` |
| coverage.py | Coverage measurement (opt-in via Makefile) | `.coveragerc` |
| import-linter | Architecture constraint enforcement | `.importlinter` |
| radon / xenon | Complexity + maintainability analysis | CLI only |
| pre-commit | Git hook automation (ruff-check + ruff-format) | `.pre-commit-config.yaml` |

**Not used:** tox, pylint, black, isort. Ruff replaces all formatting and most linting. mypy covers type safety.

## pyproject.toml — intentionally small

Contains only: `[project]`, `[tool.poetry]`, `[build-system]`, `[dependency-groups]`. All tool config lives in dedicated files.

## Dependency Groups

| Group | Contents | Installed by |
|---|---|---|
| runtime | pydantic, fastapi, pymongo, redis, etc. | `poetry install` |
| `dev` | linkml, pre-commit | `--with dev` |
| `test` | pytest, pytest-bdd, pytest-cov, pytest-asyncio, testcontainers, polyfactory, httpx | `--with test` |
| `lint` | ruff, mypy, import-linter, radon, xenon | `--with lint` |

`make install` installs all groups.

## Makefile Command Model

### Mutating (modify files)

| Target | Action |
|---|---|
| `format` | Ruff format |
| `lint-fix` | Ruff auto-fix |
| `pre-commit` | Run all pre-commit hooks |

### Validation (read-only)

| Target | Action |
|---|---|
| `lint` | Ruff check |
| `typecheck` | mypy |
| `check-architecture` | import-linter |
| `test` | All tests with coverage |
| `test-unit` | Unit tests only (excludes features/steps + integration) |
| `test-feature` | BDD feature tests only (features + steps) |
| `test-integration` | Integration-marked tests only |

### Aggregates

| Target | Composition |
|---|---|
| `check-quality` | lint + typecheck + check-architecture |
| `check-all` | check-quality + test |
| `ci-quick` | check-quality + test-unit |
| `ci-full` | check-all + clean-code |

### Reports (opt-in)

| Target | Output |
|---|---|
| `coverage-report` | `reports/htmlcov/` |
| `quality-report` | `reports/complexity.json`, `reports/maintainability.json` |

### Clean Code (separate)

| Target | Tool |
|---|---|
| `complexity` | radon cc |
| `maintainability` | radon mi |
| `clean-code` | xenon threshold checks |

## Quality-Control Layers

| Layer | When | Targets |
|---|---|---|
| Quick dev feedback | During coding | `lint`, `typecheck` |
| Before commit | Pre-commit | `format`, `lint`, `typecheck`, `test-unit` |
| Before PR | Local validation | `check-quality`, `test`, `clean-code` |
| CI quick | Push / PR update | `ci-quick` |
| CI full | Merge to develop | `ci-full` |

## Test Splitting

- `test-unit`: `pytest tests/ --ignore=tests/features --ignore=tests/steps -m "not integration"`
- `test-feature`: `pytest tests/features tests/steps`
- `test-integration`: `pytest tests/ -m "integration"`
- Coverage flags (`--cov`) are not in `pytest.ini` — they are added only by `test` and `coverage-report` targets.

## Architecture Guardrails

Import-linter enforces a tier-based component hierarchy. Spec: `.claude/memory/code-anatomy.md`. Contracts in `.importlinter`. Checked by `make check-architecture`.

## Infrastructure

All deployment files live in `infra/`: `compose.yaml`, `docker/Dockerfile`, `scripts/entrypoint.sh`, `.env.example`.

| Target | Action |
|---|---|
| `up` | `docker compose -f infra/compose.yaml up -d` |
| `down` | Stop services |
| `rebuild` | Rebuild images and start |
| `logs` | Follow service logs |

`.dockerignore` lives at `infra/docker/Dockerfile.dockerignore` (co-located with Dockerfile; Docker auto-discovers it). `.env` lives at `infra/.env`, template at `infra/.env.example`. All `docker compose` make targets pass `--env-file $(ENV_FILE)` explicitly.
