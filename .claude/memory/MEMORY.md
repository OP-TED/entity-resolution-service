# Project Memory — Entity Resolution Service

## Project Overview

- Main repository for the Entity Resolution Service (ERS).
- Uses Antora (AsciiDoc) for technical documentation.
- Branch model: `develop` is the main branch.
- Infrastructure: `infra/` (Docker, compose, scripts). Env template: `infra/.env.example`.

## AI Coding Setup

- Five agents: epic-planner (opus), gherkin-writer (sonnet), implementer (sonnet), code-reviewer (opus), documenter (haiku).
- All agents have MCP tools in their frontmatter `tools:` array: gitnexus (query, context, impact, detect_changes, cypher, rename, list_repos), ide diagnostics, context7 docs. Implementer has the full set; others have a role-appropriate subset.
- Skills: stream-coding, clarity-gate, gitnexus (6 sub-skills).
- Methodology: stream-coding (documentation-first), Cosmic Python (layered architecture).
- Memory: auto-memory (this file) + epic/task memory under `epics/`.

## Planning Roadmap

- [planning-roadmap.md](planning-roadmap.md) — Master roadmap for 10 ERS epic specifications
- 3 phases: Foundation (EPIC-01 to 04), Core Flows (EPIC-05 to 07), Curation (EPIC-08 to 09) + cross-cutting (EPIC-X)
- Status: Epics 1-7 written, all Gherkin features complete (component + UC-level + E2E)

## Epic Status

| Epic | Component | Score | Status |
|------|-----------|-------|--------|
| [ERS-EPIC-01](epics/ers-epic-01-request-registry/EPIC.md) | Request Registry | 9.7 | Implementation in progress (Tasks 1.1–1.3 done) |
| [ERS-EPIC-02](epics/ers-epic-02-rdf-mention-parser/EPIC.md) | RDF Mention Parser | 9.8 | Gherkin Complete |
| [ERS-EPIC-03](epics/ers-epic-03-ere-contract-client/EPIC.md) | ERE Contract Client | 9.8 | Gherkin Complete |
| [ERS-EPIC-04](epics/ers-epic-04-resolution-decision-store/EPIC.md) | Decision Store | 9.8 | Gherkin Complete |
| [ERS-EPIC-05](epics/ers-epic-05-ere-result-integrator/EPIC.md) | ERE Result Integrator | 9.2 | Gherkin Complete |
| [ERS-EPIC-06](epics/ers-epic-06-resolution-coordinator/EPIC.md) | Resolution Coordinator | 9.8 | Gherkin Complete |
| [ERS-EPIC-07](epics/ers-epic-07-ere-rest-api/EPIC.md) | ERS REST API | 9.8 | Gherkin Complete |
| ERS-EPIC-08 | User Action Store | — | Pending |
| ERS-EPIC-09 | Link Curation REST API | — | Pending |
| ERS-EPIC-X | Observability & Config | — | Pending |

## Current Phase

- Branch: `feature/ERS1-143-task11` (stacked on `feature/ERS1-137-5`) — EPIC-01 Request Registry implementation
- **[2026-03-19] Task 1.1 complete** — domain models (`ResolutionRequestRecord`, `LookupState`, `LookupRequestRecord`, `LookupRequestType`, `JSONRepresentation`) + `SHA256ContentHasher`; 276 tests passing
- **[2026-03-20] Task 1.2 complete** — repository ABCs + Mongo implementations + `RequestRegistryService` + exceptions; 298 tests passing
- **[2026-03-20] Task 1.3 complete** — BDD feature files wired with real service calls; all scenarios passing
- **[2026-03-20] Agent MCP tools** — all agents updated with gitnexus, ide, context7 MCP tools in frontmatter
- Next: integration tests (Task 5) or PR

## Project Automation

- [project-automation.md](project-automation.md) — Toolchain, config files, Makefile targets, quality-control layers

## Architecture

- [code-anatomy.md](code-anatomy.md) — Tier-based dependency specification for all ERS components

## PR Strategy

- **Stacked PRs**: each feature branch is based on the previous feature branch, not `develop`. PR diff is scoped to its own changes only.
- Use `/commit-push-pr --base <previous-branch>` to target the correct base directly.
- Always use **merge commits** — squash/rebase breaks auto-retargeting when the upstream PR merges.

## Key Decisions

- 2026-03-11: AI-assisted coding setup with 5 agents, stream-coding methodology.
- 2026-03-12: All 7 core epics written; Clarity Gate scores 9.2-9.8/10.
- 2026-03-17: Innermost layer is `domain/` not `models/`. Hierarchy: `entrypoints -> services -> domain`, `adapters -> domain`.
- 2026-03-17: Toolchain: Ruff (replaces pylint/black/isort), mypy, pytest, import-linter, radon/xenon. No tox.
- 2026-03-17: `pyproject.toml` kept minimal — tool configs in dedicated files. Dep groups: dev/test/lint.
- 2026-03-17: Infrastructure moved to `infra/` (compose, Dockerfile, scripts, .env.example).
- 2026-03-17: `.dockerignore` moved to `infra/docker/Dockerfile.dockerignore`; `data/` excluded to avoid permission errors on postgres volume.
- 2026-03-17: `.env` lives at `infra/.env`; all `docker compose` make targets use `--env-file infra/.env` explicitly.
- 2026-03-18: Tests split into high-level folders by type: `tests/unit/`, `tests/feature/`, `tests/e2e/`. Markers (`unit`, `feature`, `e2e`, `integration`) applied via `pytest_collection_modifyitems` hook in `tests/conftest.py`. Makefile targets use `-m <marker>`. `pytestmark` in `conftest.py` is silently ignored by pytest — do not use it there.
- 2026-03-18: rdflib returns 0 rows (not 1 all-None row) when an entity exists but has no configured SPARQL fields. `has_entity_of_type` must be retained alongside SPARQL to distinguish `EntityTypeMismatchError` from `EmptyExtractionError`.
- 2026-03-18: Services layer exposes two public functions for entrypoints — `load_config()` and `parse_entity_mention(...)`. Entrypoints never instantiate `MentionParserService` directly. The class stays for unit-testability; the functions own dependency wiring.
- 2026-03-18: Config pattern — `env_property(default_value=...)` decorator + `ConfigResolverABC` in `ers/commons/adapters/config_resolver.py`. Domain config classes in `ers/__init__.py` use UPPER_SNAKE_CASE method names (= env var keys). N802 ruff rule suppressed for that file via `ruff.toml` `[lint.per-file-ignores]`. `load_dotenv()` called at module import. Singleton: `config = AppConfigResolver()`.
- 2026-03-18: `ers/config.py` (pydantic_settings) was deleted. If `ers/config.py` exists, Python resolves `from ers import config` as the submodule, shadowing the `__init__.py` attribute. Delete the file first, then rename.

## Codebase Patterns

- Agent files in `.claude/agents/` with YAML frontmatter + markdown system prompt.
- Skills in `.claude/skills/<name>/SKILL.md`.
- Tool configs: `pytest.ini`, `ruff.toml`, `mypy.ini`, `.coveragerc`, `.importlinter`.
- Makefile is primary dev/CI workflow interface. See `make help`.

## Gotchas

- epic-planner agent hits CLAUDE_CODE_MAX_OUTPUT_TOKENS (8192) when writing large EPICs. Workaround: write the EPIC directly in the main conversation instead.
- GitNexus PostToolUse hook has MODULE_NOT_FOUND error — doesn't block work.
- Docker port 8000 may stay in `TIME_WAIT` briefly after `make down`; if `make up` fails immediately, wait a few seconds and retry.
- `.dockerignore` is at `infra/docker/Dockerfile.dockerignore`, not repo root.
