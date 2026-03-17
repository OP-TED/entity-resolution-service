# Project Memory — Entity Resolution Docs

## Project Overview

- Documentation and specification repository for Entity Resolution project.
- Uses Antora (AsciiDoc) for technical documentation.
- Serves as planning hub for AI-assisted development.
- Branch model: `develop` is the main branch.

## AI Coding Setup

- Five agents: epic-planner (opus), gherkin-writer (sonnet), implementer (sonnet), code-reviewer (opus), documenter (haiku).
- Skills at project level: stream-coding, clarity-gate, gitnexus (6 sub-skills).
- Methodology: stream-coding (documentation-first), Cosmic Python (layered architecture).
- Memory: dual approach — auto-memory (this file) + epic/task memory under epics/.
- Docs: `docs/ai-coding/` contains runbook, setup guide, DoD quality gates, and review.

## Planning Roadmap

- [planning-roadmap.md](planning-roadmap.md) — Master roadmap for 10 ERS epic specifications
- 3 phases: Foundation (EPIC-01 to 04), Core Flows (EPIC-05 to 07), Curation (EPIC-08 to 09) + cross-cutting (EPIC-X)
- Status: Epics 1-7 written, Gherkin feature writing next

## Epic Status

| Epic | Component | Score | Status |
|------|-----------|-------|--------|
| [ERS-EPIC-01](epics/ers-epic-01-request-registry/EPIC.md) | Request Registry | 9.7 | Gherkin Complete |
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

- Branch: `feature/ERS1-137-4`, implementing EPIC-01 (Request Registry)
- **[2026-03-16] ERS-EPIC-01: Gherkin features complete** — `resolution_request_registration.feature` and `bulk_lookup_and_snapshot_management.feature` written and aligned with EPIC spec
- **[2026-03-16] ERS-EPIC-05: Gherkin features complete** — 3 feature files + step scaffolding for ERE Result Integrator (outcome acceptance, deduplication, contract validation)
- **[2026-03-16] ERS-EPIC-04: Gherkin features complete** — 2 feature files + step scaffolding for Decision Store (persistence, filtered queries, paginated query)
- Steps reorganised into component subfolders: `tests/steps/request_registry/`, `tests/steps/ere_result_integrator/`, `tests/steps/decision_store/`
- **[2026-03-16] ERS-EPIC-03: Gherkin features complete** — 2 feature files + step scaffolding for ERE Contract Client (request publishing, validation and transport)
- **[2026-03-16] ERS-EPIC-02: Gherkin features complete** — 2 feature files + step scaffolding for RDF Mention Parser (config loading/validation, RDF parsing with all 6 error types)
- **[2026-03-16] ERS-EPIC-06: Gherkin features complete** — 3 feature files + step scaffolding for Resolution Coordinator (single-mention resolution, bulk decomposition, async waiter coordination)
- **[2026-03-17] ERS-EPIC-07: Gherkin features complete** — 2 feature files + step definitions for ERS REST API:
  - `resolve_entity_mention.feature` (16 scenarios): single + bulk resolve, 200 canonical / 202 provisional / 207 mixed, idempotency, validation
  - `lookup_cluster_assignment.feature` (11 scenarios): merged single GET /lookup + bulk POST /refreshBulk, pagination, synchronisation snapshot, read-only contract
- Key EPIC-07 design decisions: 202 Accepted for provisional outcomes, 207 Multi-Status for mixed bulk, POST /resolveBulk as separate endpoint, content is RDF Turtle (mock fixtures), context field optional (NoticeID)
- Next: Implementation of EPIC-07 (requires EPIC-04 and EPIC-06 to be complete)
- Design spec: `docs/superpowers/specs/2026-03-16-epic05-gherkin-features-design.md`

## Codebase Patterns

- Agent files live in `.claude/agents/` with YAML frontmatter + markdown system prompt.
- Skills live in `.claude/skills/<name>/SKILL.md`.
- CLAUDE.md is the master entry point; kept under 200 lines.
- GitNexus rules are inline in CLAUDE.md (within `<!-- gitnexus:start/end -->` markers).

## Key Decisions

- 2026-03-11: Established AI-assisted coding setup with 5 agents, stream-coding methodology.
- 2026-03-11: Stream-coding Phases 1-2 owned by epic-planner, Phases 3-4 by implementer.
- 2026-03-11: Clarity Gate — full 13-item for specs, lightweight 5-item for documentation.
- 2026-03-12: All 7 core epics written; Clarity Gate scores 9.2-9.8/10.
- 2026-03-12: EPIC-06 key design: AsyncResolutionWaiter (asyncio.Event), graceful degradation on Redis down, bulk decomposition in Coordinator.

## Gotchas

- epic-planner agent hits CLAUDE_CODE_MAX_OUTPUT_TOKENS (8192) when writing large EPICs. Workaround: write the EPIC directly in the main conversation instead.
- GitNexus PostToolUse hook has MODULE_NOT_FOUND error — doesn't block work.
