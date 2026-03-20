# Project: Entity Resolution Service

This is the main repository for the Entity Resolution
project. It uses Antora (AsciiDoc) for technical documentation and serves as the planning hub for AI-assisted development.

- **Main branch:** `develop` (PR target)
- **Global instructions:** The user-level `~/.claude/CLAUDE.md` contains Meaningfy-wide
  coding practices (Clean Code, SOLID, Cosmic Python, testing strategy). It
  complements this project-level file and is loaded into every conversation.

## Methodology

This project follows the **Meaningfy AI-Assisted Coding** methodology:
- **Runbook:** `docs/ai-coding/ai-coding-runbook.md`
- **Setup guide:** `docs/ai-coding/ai-coding-setup-guide.md`

Agents, skills, and memory are configured under `.claude/`.

---

## Agent Behaviour Rules

These rules apply to ALL agents in this project.

### Commits and PRs

- **Never commit without explicit developer consent.** Always present changes and
  wait for approval before committing.
- No `Co-Authored-By` statements in git commits unless the developer requests them.
- Commit messages: strict, succinct, describe the **final outcome** — not the
  process, not internal memory references. Only what changed in the repository.
- Commits are triggered by medium-sized, conceptually atomic chunks of work.
  Avoid mixing unrelated changes. Avoid large-scale commits.
- Signal to the developer when unrelated changes may be introduced (detect changes
  in subject/intention).
- PRs are triggered upon completing an EPIC. Exceptionally, large Epics may have
  intermediate PRs grouping stories that deliver business value.
- **Stacked PRs (non-cumulative diffs):** Each feature branch is based on the
  previous feature branch, not on `develop`. This keeps each PR's diff scoped to
  its own changes only.
  - When creating a PR for a branch built on a previous feature branch, pass
    `--base <previous-branch>` to `/commit-push-pr` (e.g.
    `/commit-push-pr --base feature/ERS1-142-task3`).
  - When the earlier PR merges, GitHub automatically re-targets the dependent PR
    to `develop`.
  - Always use **merge commits** — squash/rebase destroys the shared history that
    makes auto-retargeting work correctly.

### Working Methodology

- Use project-specific tooling defined in `README.md` (like `make` targets).
- As a final step of every significant code change, run relevant tests via
  available tooling and auto-fix issues (new, regression).
- Use planning mode (`/plan`) before writing to files for reasoning-heavy work —
  it's cheaper and faster.
- When code fails: **fix the spec, not the code** (Rule of Divergence from
  stream-coding methodology).
- Follow the Cosmic Python layered architecture: `entrypoints -> services -> domain`,
  `adapters -> domain`. Domain must not import from higher layers.
  **Note:** The innermost layer is called `domain` (not `models`) in this project.
- Always use Context7 when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.

### Code Documentation & Docstrings
- All docstrings must follow **Google Python style** (see `.claude/references/google_python_docstring_style.md`).
- Key rules: one-line summary first, then optional description, then `Args`, `Returns`, `Raises` sections.
- Write for behaviour, not implementation; focus on inputs, outputs, and exceptions.
- Keep docstrings concise; avoid redundancy with self-documenting code.

### Interaction

- Never make assumptions — ask clarifying questions when information is missing.
- Keep proposals within the shaped scope of the current Epic. If a request seems
  to go beyond scope, flag it and ask for confirmation.

---

## File References

### Agents (`.claude/agents/`)

| Agent | Model | Purpose |
|-------|-------|---------|
| `epic-planner` | Opus | Write EPIC specs from business requirements (Phases 1-2) |
| `gherkin-writer` | Sonnet | Write BDD Gherkin features and test data |
| `implementer` | Sonnet | Implement code following stream-coding (Phases 3-4) |
| `code-reviewer` | Opus | Pre-PR review, read-only |
| `documenter` | Haiku | Documentation, explanations, summaries |

### Skills (`.claude/skills/`)

| Skill | Purpose |
|-------|---------|
| `stream-coding` | Documentation-first development methodology |
| `clarity-gate` | Quality verification for specs and documentation |

### Memory (`.claude/memory/`)

| Path | Purpose |
|------|---------|
| `MEMORY.md` | Auto-memory index (stable patterns, <= 200 lines) |
| `epics/<name>/EPIC.md` | Epic specification with plan and roadmap |
| `epics/<name>/yyyy-mm-dd-<task>.md` | Task outcome files |

---

## Memory Conventions

### Auto-memory (`MEMORY.md`)

- Updated after significant work sessions with stable, confirmed facts.
- Contains codebase patterns, architectural decisions, key file paths.
- Kept to <= 200 lines (auto-loaded into every conversation).
- No session-specific notes, no unverified conclusions.

### Epic/Task memory (`epics/`)

- **Do NOT auto-load** all memory files from the epics folder.
- When starting work on an epic, read only the relevant `EPIC.md`.
- When completing a task, write a task outcome file:
  `epics/<epic-name>/yyyy-mm-dd-<task-title>.md`.
- Task files focus on **outcomes and victories**, not logistics.
- Update the EPIC.md roadmap and status as tasks complete.

### Memory update triggers

| Event | Action |
|-------|--------|
| Starting work on an epic | Read the relevant `EPIC.md` |
| Completing a task | Write task outcome file, update EPIC.md roadmap |
| End of significant session | Update `MEMORY.md` with stable patterns |
| Completing an epic | Update EPIC.md status to complete |

---

## Gotchas & Common Pitfalls

- `AGENTS.md` at repo root is auto-generated by GitNexus — not a manual file.
  Do not edit it directly; it is regenerated by `npx gitnexus analyze`.
- `ai-agent-runbook.md` at repo root is raw brainstorming input, NOT the actual
  runbook. The real runbook is `docs/ai-coding/ai-coding-runbook.md`.
- Skills referenced in agent `skills:` frontmatter must exist at project level
  (`.claude/skills/<name>/SKILL.md`) OR user level (`~/.claude/skills/<name>/SKILL.md`).
  If neither exists, the skill silently fails to load.
- Agent changes require a session restart or `/agents` reload to take effect.
- `MEMORY.md` is truncated at 200 lines when loaded into context. Keep it concise
  and curate regularly.
- GitNexus PostToolUse auto-index hook has a known `MODULE_NOT_FOUND` error
  (`~/.claude/dist/cli/index.js`). Re-index manually: `npx gitnexus analyze`.
- Sub-agents cannot spawn other sub-agents. If a workflow needs chaining, the
  main conversation orchestrates: ask agent A, get results, ask agent B.
- `pytestmark` in `conftest.py` is silently ignored by pytest — conftest is loaded
  as a plugin, not a test module. Test-type markers (`unit`, `feature`, `e2e`,
  `integration`) are applied via `pytest_collection_modifyitems` in `tests/conftest.py`.
  Do not add `pytestmark` to conftest files.

---

## Project Tooling

- Documentation: Antora (AsciiDoc) — see `docs/antora-playbook.yml`
- GitNexus: See auto-generated section above (CLI: `analyze`, `status`, `wiki`)

### Commands

```bash
make install-antora   # Install Antora + dependencies (first time)
make build-docs       # Build documentation to docs/build/site/
make preview-docs     # Build + serve at http://localhost:8080
make clean-docs       # Remove build artifacts
```

---


<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **entity-resolution-service** (1930 symbols, 3587 relationships, 52 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/entity-resolution-service/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/entity-resolution-service/context` | Codebase overview, check index freshness |
| `gitnexus://repo/entity-resolution-service/clusters` | All functional areas |
| `gitnexus://repo/entity-resolution-service/processes` | All execution flows |
| `gitnexus://repo/entity-resolution-service/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:
1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## Keeping the Index Fresh

After committing code changes, the GitNexus index becomes stale. Re-run analyze to update it:

```bash
npx gitnexus analyze
```

If the index previously included embeddings, preserve them by adding `--embeddings`:

```bash
npx gitnexus analyze --embeddings
```

To check whether embeddings exist, inspect `.gitnexus/meta.json` — the `stats.embeddings` field shows the count (0 means no embeddings). **Running analyze without `--embeddings` will delete any previously generated embeddings.**

> Claude Code users: A PostToolUse hook handles this automatically after `git commit` and `git merge`.

## CLI

- Re-index: `npx gitnexus analyze`
- Check freshness: `npx gitnexus status`
- Generate docs: `npx gitnexus wiki`

<!-- gitnexus:end -->
