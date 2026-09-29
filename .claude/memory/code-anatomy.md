---
name: ERS Architecture Dependency Specification
description: Tier-based dependency guardrails for all ERS components — inter-component hierarchy, intra-component layer rules, translatable to Import Linter contracts.
type: project
---

# ERS Architecture Dependency Specification

**Created:** 2026-03-17
**Purpose:** Import Linter guardrails for the Entity Resolution Service.
**Quality bar:** An agent can translate this into `.importlinter` contracts without guessing.

---

## 1. Architecture Overview

**Root module:** `ers` (from `src/ers/`). Two levels of structure:
1. **Component packages** — top-level sub-packages of `ers`
2. **Architectural layers** inside each component (Cosmic Python style, innermost layer is `domain`)

---

## 2. Assumptions

1. All components will eventually exist as sub-packages of `ers`, even if most do not exist today.
2. Current package mappings: `curation/` → `link_curation_rest_api`, `users/` → `user_store`.
3. Layers per component are from the planning roadmap and EPIC specs. Only declared layers listed.
4. Cross-cutting packages (`observability_adapter`, `configuration_manager`) are excluded from enforcement.
5. `commons` is a shared package, not a business component. Must not contain `entrypoints`.
6. `tests/features/decision_store` maps to future `resolution_decision_store` package.

---

## 3. Component Inventory

| # | Package | Tier | Layers | Exists |
|---|---|---|---|---|
| 1 | `request_registry` | 1 | domain, adapters, services | No |
| 2 | `rdf_mention_parser` | 1 | domain, adapters, services | No |
| 3 | `ere_contract_client` | 1 | adapters, services | No |
| 4 | `resolution_decision_store` | 1 | domain, adapters, services | No |
| 5 | `user_action_store` | 1 | domain, adapters, services | No |
| 6 | `user_store` | 1 | domain, adapters, services | Yes (`users/`) |
| 7 | `ere_result_integrator` | 2 | adapters, entrypoints, services | No |
| 8 | `resolution_coordinator` | 2 | services | No |
| 9 | `ers_rest_api` | 3 | domain, entrypoints, services | No |
| 10 | `link_curation_rest_api` | 3 | domain, adapters, entrypoints, services | Yes (`curation/`) |
| — | `commons` | 0 | domain, adapters, services | Yes |

**Component notes:**
- `user_store`: not in original 9-component roadmap; exists in source, dependency of `link_curation_rest_api`.
- `ere_result_integrator`: has `entrypoints` for Redis listener (EPIC-05).
- `resolution_coordinator`: services-only; orchestrates other components.

---

## 4. Intra-Component Layer Rules

Dependency direction inside each component (acyclic graph):

```
entrypoints → services → domain
entrypoints → adapters → domain
entrypoints → domain
```

**Allowed:** higher layers may import lower layers (entrypoints > services > adapters > domain, plus entrypoints > adapters and services > adapters).

**Prohibited:** domain must not import any other layer. adapters must not import services or entrypoints. services must not import entrypoints.

Apply only rules involving layers that exist in each component. There are 4 distinct layer combinations:

| Layer set | Components | Allowed | Prohibited |
|---|---|---|---|
| domain, adapters, services | #1, #2, #4, #5, #6, commons | svc→dom, svc→adp, adp→dom | dom→adp, dom→svc, adp→svc |
| adapters, services | #3 | svc→adp | adp→svc |
| adapters, entrypoints, services | #7 | ent→svc, ent→adp, svc→adp | adp→svc, adp→ent, svc→ent |
| domain, entrypoints, services | #9 | ent→svc, ent→dom, svc→dom | dom→svc, dom→ent, svc→ent |
| domain, adapters, entrypoints, services | #10 | ent→svc, ent→dom, ent→adp, svc→dom, svc→adp, adp→dom | dom→adp, dom→svc, dom→ent, adp→svc, adp→ent, svc→ent |

Component #8 (`resolution_coordinator`) has only `services` — no intra-component rules.

---

## 5. Inter-Component Rules (Tier Hierarchy)

**Core rule: a component may import any component in a lower tier, and must not import any component in the same or higher tier.**

| Tier | Name | Components | May import |
|---|---|---|---|
| 0 | shared | `commons` | No business components |
| 1 | foundation | `request_registry`, `rdf_mention_parser`, `ere_contract_client`, `resolution_decision_store`, `user_action_store`, `user_store` | Tier 0 only |
| 2 | orchestration | `ere_result_integrator`, `resolution_coordinator` | Tier 0 + Tier 1 |
| 3 | entrypoints | `ers_rest_api`, `link_curation_rest_api` | Tier 0 + Tier 1 + Tier 2 |

**Consequences:**
- Tier 1 peers cannot import each other.
- Tier 2 peers cannot import each other.
- Tier 3 peers cannot import each other.
- No component imports Tier 3.
- `commons` is imported by all; imports none.

### Cross-cutting (excluded from enforcement)

`observability_adapter` and `configuration_manager` are not enforced via Import Linter (Assumption 4).

---

## 6. Global Prohibitions

1. No same-tier or upward imports between components.
2. No upward imports between layers within a component.
3. No cycles — neither between components nor within a component's layers.
4. `commons` must not import any business component.

