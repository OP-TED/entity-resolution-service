# Minimal Python Project Setup Specification

## Goal

Define and implement a minimal, clean Python project setup based on **Option A**:

* use **Poetry** for dependency management
* use **Makefile** as the main developer command interface
* use **dedicated config files** for tools
* **do not use tox**
* keep `pyproject.toml` focused mainly on:

  * `[build-system]`
  * `[project]`
  * minimal Poetry-specific package configuration if required
* avoid a large `[tool.*]` area in `pyproject.toml`

This specification is intended for implementation by an LLM coding agent.

---

## Desired Principles

The implementation should optimise for:

1. **Clarity**: each file should have a clear purpose.
2. **Minimalism**: avoid unnecessary layers and duplication.
3. **Local developer ergonomics**: common tasks should be run through `make` targets.
4. **Separation of concerns**:

   * `pyproject.toml` defines the project and build metadata
   * tool-specific files define tool behaviour
   * `Makefile` defines human-friendly workflows
5. **No orchestration duplication**: avoid overlapping control logic across multiple systems.

---

## Architecture Decision

Implement **Option A**:

* developers run commands through `make`
* CI should be able to run the same `make` targets
* no `tox.ini`
* no tox-based orchestration

This project should not introduce tox unless there is a future, explicit need for:

* multi-Python-version matrix execution
* isolated environment orchestration beyond Poetry
* a CI abstraction layer that cannot be handled cleanly by `make`

For the current scope, tox is considered unnecessary complexity.

---

## Target File Structure

The repository should follow this structure:

```text
pyproject.toml
Makefile
pytest.ini
ruff.toml
mypy.ini
.coveragerc
.importlinter
.pre-commit-config.yaml
```

If some of these files do not exist yet, create them.

---

## Responsibilities of Each File

### `pyproject.toml`

This file should remain intentionally small.

It should contain:

* `[build-system]`
* `[project]`
* minimal Poetry-specific configuration only if needed for package discovery or packaging
* dependency groups if they are already part of the chosen Poetry workflow

It should **not** become the main place for tool configuration.

The `[tool.*]` area should be removed entirely if possible.
If something must remain there for compatibility reasons, keep it to an absolute minimum and document why.

**Exception:** `[tool.poetry]` must stay — Poetry requires it for source layout discovery (`packages = [{include = "ers", from = "src"}]`). This is not tool configuration; it is build/packaging metadata.

### `Makefile`

This is the primary command interface for contributors.

It should expose simple, predictable targets for setup, formatting, linting, type checking, testing, architecture checks, build, and cleaning.

### Tool config files

Each tool should have its own dedicated config file:

* `pytest.ini` for pytest
* `ruff.toml` for Ruff
* `mypy.ini` for mypy
* `.coveragerc` for coverage
* `.importlinter` for import-linter

These files should contain the configuration that was previously under `[tool.*]` sections in `pyproject.toml`.

---

## Dependency Management Expectations

Use Poetry as the dependency manager.

The dependency grouping should remain explicit and meaningful.
A good structure is:

* runtime dependencies in `[project.dependencies]`
* development helpers in a `dev` group
* testing dependencies in a `test` group
* linting and static-analysis tools in a separate `lint` group

Avoid putting all non-runtime tools into a generic `test` bucket if they are not actually test tools.

Example intention:

* `dev`: pre-commit, linkml, and lightweight local dev helpers
* `test`: pytest, pytest-bdd, pytest-cov, pytest-asyncio, httpx, testcontainers, polyfactory
* `lint`: ruff, pylint, mypy, import-linter, radon, xenon

Remove `tox` from dependencies entirely — it is not used in this setup.

The final grouping may be adjusted slightly if needed, but the implementation should preserve semantic clarity.

---

## Makefile Requirements

The `Makefile` should provide a minimal but complete workflow.

At minimum, implement these targets:

* `help`
* `install`
* `lock`
* `format`
* `lint`
* `lint-fix`
* `typecheck`
* `test`
* `test-unit`
* `test-integration`
* `check-architecture`
* `check-quality`
* `check-all`
* `build`
* `clean`
* `seed-db` (preserve existing target)

### Expected behaviour of targets

#### `install`

Install project dependencies via Poetry, including the required non-runtime groups.

Important:

* `install` should **not** run `poetry lock`
* locking should not happen implicitly during normal environment setup
* add a separate `lock` target for explicit locking when needed

#### `format`

Run code formatting only.

#### `lint`

Run non-mutating lint checks only.

#### `lint-fix`

Run lint auto-fixes where supported.

#### `typecheck`

Run mypy against the source package.

#### `test`

Run the full test suite.

#### `test-unit`

Run only non-integration tests.

#### `test-integration`

Run only integration tests.

#### `check-architecture`

Run import-linter checks.

#### `check-quality`

Aggregate static quality checks without running tests.
Recommended composition:

* `lint`
* `typecheck`
* `check-architecture`

#### `check-all`

Run the full non-mutating verification suite.
Recommended composition:

* `check-quality`
* `test`

#### `build`

Build the distributable package.

#### `clean`

Remove caches, temporary files, test artefacts, and build artefacts.

---

## Naming and Behaviour Rules

The implementation should follow these conventions:

* targets that modify files should be clearly named, such as `format` or `lint-fix`
* targets that only validate should not modify files
* `check-all` should be the main all-in-one verification target
* commands should rely on tool config files rather than repeating long inline configuration in the `Makefile`

Keep the `Makefile` readable. Avoid excessive shell noise and avoid embedding large chunks of policy in target commands.

---

## Tool Migration Requirements

Migrate configuration out of `pyproject.toml` as follows:

* pytest → `pytest.ini`
* Ruff → `ruff.toml`
* mypy → `mypy.ini`
* coverage → `.coveragerc`
* import-linter → `.importlinter`

After migration:

* remove the corresponding `[tool.pytest.*]`, `[tool.ruff.*]`, `[tool.mypy]`, `[tool.coverage.*]`, and import-linter sections from `pyproject.toml`
* verify that commands still work using the new dedicated files

---

## Implementation Constraints

The coding agent should:

1. preserve existing project behaviour as much as possible
2. reduce configuration sprawl inside `pyproject.toml`
3. avoid introducing tox
4. avoid unnecessary refactoring outside the setup/configuration scope
5. keep the final result understandable to a human maintainer without needing extra explanation

---

## Definition of Done

The task is complete when:

1. `pyproject.toml` is reduced to a minimal project/build-focused role
2. tool configs are moved to dedicated files
3. `Makefile` becomes the main local workflow entrypoint
4. no tox configuration is added
5. the repository has a coherent, minimal, and maintainable setup
6. core commands work through `make`, especially:

   * `make install`
   * `make format`
   * `make lint`
   * `make typecheck`
   * `make test`
   * `make check-architecture`
   * `make check-all`
   * `make build`
   * `make clean`

---

## Preferred Outcome

The final setup should feel intentionally small and boring.

It should be easy for a new contributor to understand:

* where project metadata lives
* where each tool is configured
* which command to run for common tasks

The desired result is not maximum consolidation.
The desired result is **minimum confusion**.
