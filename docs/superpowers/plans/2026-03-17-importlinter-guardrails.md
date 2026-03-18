# Import Linter Architecture Guardrails — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate the tier-based dependency specification (`.claude/memory/code-anatomy.md`) into enforceable Import Linter contracts in `pyproject.toml`, with a `make check-architecture` target.

**Architecture:** Import Linter contracts enforce two axes: (1) intra-component layer ordering via `layers` contracts with `containers`, and (2) inter-component tier hierarchy via a single `layers` contract with pipe-separated siblings (enforces both ordering AND same-tier independence). Non-existent packages use `(optional)` parentheses so contracts pass until packages are created.

**Tech Stack:** import-linter (already in test deps), pyproject.toml (TOML config), Make

**Spec:** `.claude/memory/code-anatomy.md`

**Package name convention:** Contracts use current on-disk names where packages exist today (`ers.curation` for `link_curation_rest_api`, `ers.users` for `user_store`). Future packages use `(optional)` syntax. When a package is renamed or created, update the contracts accordingly.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `pyproject.toml` | Add `[tool.importlinter]` section with all contracts |
| Modify | `Makefile` | Add `check-architecture` target |

---

## Task 1: Add Import Linter root config and tier hierarchy contract

**Files:**
- Modify: `pyproject.toml` (append after `[tool.coverage.report]` section)

- [ ] **Step 1: Add root config and tier hierarchy contract**

The `layers` contract with pipe `|` separators enforces both tier ordering (higher may import lower, not reverse) AND same-tier independence (pipes mean siblings cannot import each other). Parenthesised entries `(pkg)` are skipped if the package doesn't exist on disk.

Add to `pyproject.toml`:

```toml
# =============================================================================
# Import Linter — Architecture Guardrails
# =============================================================================
# Spec: .claude/memory/code-anatomy.md
# Tier model: 0=commons, 1=foundation, 2=orchestration, 3=entrypoints
# Rule: lower tiers must not import higher tiers. Same-tier must not import peers.
#
# Package name mapping (current -> target):
#   ers.curation -> link_curation_rest_api
#   ers.users    -> user_store
# Cross-cutting packages (observability_adapter, configuration_manager) are
# excluded from enforcement — add contracts when they are created.

[tool.importlinter]
root_packages = ["ers"]

# --- Tier hierarchy: entrypoints > orchestration > foundation > commons ---
# Pipe (|) = independent siblings at same tier level.
# Parentheses = optional (skipped if package doesn't exist yet).
[[tool.importlinter.contracts]]
name = "Tier hierarchy: entrypoints > orchestration > foundation > commons"
type = "layers"
layers = [
    "(ers.ers_rest_api) | ers.curation",
    "(ers.ere_result_integrator) | (ers.resolution_coordinator)",
    "(ers.request_registry) | (ers.rdf_mention_parser) | (ers.ere_contract_client) | (ers.resolution_decision_store) | (ers.user_action_store) | ers.users",
    "ers.commons",
]
```

- [ ] **Step 2: Run lint-imports to verify**

Run: `poetry run lint-imports`
Expected: PASS. The existing packages (`ers.curation`, `ers.users`, `ers.commons`) are checked. Optional packages are skipped.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add import-linter root config and tier hierarchy contract"
```

---

## Task 2: Add intra-component layer contracts

**Files:**
- Modify: `pyproject.toml` (append contracts)

Each distinct layer combination gets one `layers` contract with `containers`. Layers are marked optional with `()` so contracts pass even if a component hasn't created all its layer sub-packages yet.

Note: `resolution_coordinator` (component #8) has only `services` — no intra-component rules needed, intentionally omitted.

- [ ] **Step 1: Add layer contract for {domain, adapters, services} components**

This covers: `request_registry`, `rdf_mention_parser`, `resolution_decision_store`, `user_action_store`, `user_store`(=`ers.users`), and `commons`.

```toml
# --- Intra-component layers: domain, adapters, services ---
[[tool.importlinter.contracts]]
name = "Layers [domain,adapters,services]: svc > adp > dom"
type = "layers"
layers = [
    "(services)",
    "(adapters)",
    "(domain)",
]
containers = [
    "ers.request_registry",
    "ers.rdf_mention_parser",
    "ers.resolution_decision_store",
    "ers.user_action_store",
    "ers.users",
    "ers.commons",
]
```

- [ ] **Step 2: Add layer contract for {adapters, services} component**

```toml
# --- Intra-component layers: adapters, services ---
[[tool.importlinter.contracts]]
name = "Layers [adapters,services]: svc > adp"
type = "layers"
layers = [
    "(services)",
    "(adapters)",
]
containers = [
    "ers.ere_contract_client",
]
```

- [ ] **Step 3: Add layer contract for {adapters, entrypoints, services} component**

```toml
# --- Intra-component layers: adapters, entrypoints, services ---
[[tool.importlinter.contracts]]
name = "Layers [adapters,entrypoints,services]: ent > svc > adp"
type = "layers"
layers = [
    "(entrypoints)",
    "(services)",
    "(adapters)",
]
containers = [
    "ers.ere_result_integrator",
]
```

- [ ] **Step 4: Add layer contract for {domain, entrypoints, services} component**

```toml
# --- Intra-component layers: domain, entrypoints, services ---
[[tool.importlinter.contracts]]
name = "Layers [domain,entrypoints,services]: ent > svc > dom"
type = "layers"
layers = [
    "(entrypoints)",
    "(services)",
    "(domain)",
]
containers = [
    "ers.ers_rest_api",
]
```

- [ ] **Step 5: Add layer contract for {domain, adapters, entrypoints, services} component**

```toml
# --- Intra-component layers: all four ---
[[tool.importlinter.contracts]]
name = "Layers [all]: ent > svc > adp > dom"
type = "layers"
layers = [
    "(entrypoints)",
    "(services)",
    "(adapters)",
    "(domain)",
]
containers = [
    "ers.curation",
]
```

- [ ] **Step 6: Run lint-imports to verify**

Run: `poetry run lint-imports`
Expected: PASS. Existing packages (`ers.users`, `ers.commons`, `ers.curation`) are checked with their actual layers. Non-existent containers are skipped.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add intra-component layer contracts for all 5 layer combinations"
```

---

## Task 3: Add commons isolation contracts

**Files:**
- Modify: `pyproject.toml` (append contracts)

Two contracts: (1) commons must not import any business component, (2) commons layers are exhaustive (catches creation of undeclared layers like `entrypoints`).

- [ ] **Step 1: Add forbidden contract for commons importing business components**

```toml
# --- Commons must not import any business component ---
[[tool.importlinter.contracts]]
name = "Commons must not import business components"
type = "forbidden"
source_modules = [
    "ers.commons",
]
forbidden_modules = [
    "ers.request_registry",
    "ers.rdf_mention_parser",
    "ers.ere_contract_client",
    "ers.resolution_decision_store",
    "ers.user_action_store",
    "ers.users",
    "ers.ere_result_integrator",
    "ers.resolution_coordinator",
    "ers.ers_rest_api",
    "ers.curation",
]
```

- [ ] **Step 2: Add exhaustive layer contract for commons**

This catches creation of undeclared layers (e.g., `entrypoints`) inside commons. Separate from the shared Task 2 contract because `exhaustive` applies per-contract.

```toml
# --- Commons must only contain domain, adapters, services ---
[[tool.importlinter.contracts]]
name = "Commons layers are exhaustive (no entrypoints allowed)"
type = "layers"
layers = [
    "services",
    "adapters",
    "domain",
]
containers = [
    "ers.commons",
]
exhaustive = true
```

- [ ] **Step 3: Run lint-imports to verify**

Run: `poetry run lint-imports`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add commons isolation and exhaustive layer contracts"
```

---

## Task 4: Add Makefile target

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add check-architecture target**

Add after the code quality section (before `#--- Utility commands`):

```makefile
#-----------------------------------------------------------------------------
# Architecture commands
#-----------------------------------------------------------------------------
.PHONY: check-architecture
check-architecture: ## Check architecture constraints with import-linter
	@ echo -e "$(BUILD_PRINT)$(ICON_PROGRESS) Checking architecture constraints$(END_BUILD_PRINT)"
	@ poetry run lint-imports
	@ echo -e "$(BUILD_PRINT)$(ICON_DONE) Architecture checks passed$(END_BUILD_PRINT)"
```

- [ ] **Step 2: Update help target**

Add to the help output, after the Code Quality section:

```makefile
	@ echo ""
	@ echo -e "  $(BUILD_PRINT)Architecture:$(END_BUILD_PRINT)"
	@ echo "    check-architecture   - Check architecture constraints with import-linter"
```

- [ ] **Step 3: Run the new target**

Run: `make check-architecture`
Expected: PASS. All contracts pass.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat: add make check-architecture target for import-linter"
```

---

## Task 5: End-to-end validation

**Files:** None (verification only)

- [ ] **Step 1: Run full lint-imports with verbose output**

Run: `poetry run lint-imports --verbose`
Expected: All contracts listed, all PASS. Verify `ers.curation`, `ers.users`, and `ers.commons` are actively checked.

- [ ] **Step 2: Sanity-check violation detection**

Temporarily add a violating import to an actual source file to verify detection:

```bash
# Add a reverse-layer import in commons (domain importing from services)
echo "from ers.commons.services import exceptions" >> src/ers/commons/domain/__init__.py
poetry run lint-imports
# Expected: FAIL on "Layers [domain,adapters,services]" contract
# Revert:
git checkout src/ers/commons/domain/__init__.py
```

- [ ] **Step 3: Run make test-unit to ensure nothing is broken**

Run: `make test-unit`
Expected: All existing tests still pass. Import-linter config doesn't affect runtime.
