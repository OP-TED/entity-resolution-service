---
name: Task 3 — Project Setup (continued)
description: Infrastructure fixes, quality tooling improvements, and project scaffolding completed on feature/ERS1-142-task3
type: project
date: 2026-03-17
branch: feature/ERS1-142-task3
---

# Task 3 — Project Setup (continued)

## What was done

### Infrastructure fixes

- **Moved `.dockerignore`** from the project root to `infra/docker/Dockerfile.dockerignore`.
  Docker auto-discovers `<dockerfile-path>.dockerignore`, so the file now lives co-located with the Dockerfile. The `data/` directory (postgres volume, root-owned) was added to exclusions to fix a `permission denied` build error.

- **Fixed Docker Compose env-file path**: `infra/compose.yaml` was referencing `../.env` (relative to the compose file). Changed to `.env` (relative to the `infra/` working dir). All `docker compose` make targets (`up`, `down`, `rebuild`, `logs`) now pass `--env-file $(ENV_FILE)` explicitly, where `ENV_FILE = infra/.env`.

- **Added `data/` and `.venv` to `.gitignore`**; added `.import_linter_cache` and `.coverage` to ignored files; un-ignored `poetry.toml` so it is committed.

### BDD step definition fixes

Several step definitions in `tests/steps/` had broken datatable iteration and incompatible parser patterns:

- **Datatable iteration**: replaced direct `for row in datatable` with the correct `headers = datatable[0]; for row_values in datatable[1:]: row = dict(zip(headers, row_values))` pattern across all affected step files.
- **Parser pattern**: replaced `parsers.parse(...)` with `parsers.re(...)` for steps containing optional segments or empty-capture groups (e.g. steps with optional context strings, optional plural suffixes, and empty cluster IDs).
- **Missing decorator**: added `@when` alongside `@given` for the ERE timeout step in `test_ucb11_resolve_entity_mention.py`.

Files fixed: `test_decision_persistence.py`, `test_deduplication_and_staleness.py`, `test_resolve_entity_mention.py`, `test_e2e_resolution_cycle.py`, `test_ucb11_resolve_entity_mention.py`, `test_ucb12_integrate_ere_outcomes.py`, `test_ucb22_bulk_curator_reevaluation.py`.

### Project scaffold

Added standard open-source project files:

| File | Content |
|------|---------|
| `LICENSE` | Apache 2.0 |
| `VERSION` | `0.4.0` |
| `README.md` | Full rewrite — description, system model, installation, running, development, contributing |
| `docs/CONTRIBUTING.md` | Setup, workflow, architecture constraints, testing expectations, PR and commit guidelines |
| `docs/CODE_OF_CONDUCT.md` | Based on Apache Foundation / SEMIC CoC |
| `poetry.toml` | `virtualenvs.in-project = true` + `prefer-active-python = true` |

### Quality tool config improvements

Adapted from rdflib's `pyproject.toml` and project best practices:

| File | Change |
|------|--------|
| `pyproject.toml` | Version `0.4.0`, non-empty description, `license = "Apache-2.0"`, `classifiers`, `maintainers` |
| `ruff.toml` | Added `RUF100` (unused noqa directives) |
| `mypy.ini` | Added `warn_unused_configs`, `warn_unreachable`, `implicit_reexport = False` |
| `pytest.ini` | Added `--strict-markers`, structured log format |
| `.coveragerc` | Added `branch = True`, `exclude_lines` for TYPE_CHECKING, `...`, `__repr__`, `NotImplementedError` |

### Memory updates

Updated `.claude/memory/MEMORY.md` and `.claude/memory/project-automation.md` to reflect:
- `.dockerignore` location change (`infra/docker/Dockerfile.dockerignore`)
- `.env` location (`infra/.env`)
- `--env-file` usage in make targets
- Docker port `TIME_WAIT` gotcha (wait a few seconds between `make down` and `make up`)

## Outcome

All changes committed and pushed to `feature/ERS1-142`. PR #15 opened against `develop`.
