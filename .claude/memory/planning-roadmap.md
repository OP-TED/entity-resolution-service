---
name: Epic Planning Roadmap
description: Master roadmap for writing ERS epic specifications (10 epics organized by component and spine)
type: project
---

# Epic Planning Roadmap — Entity Resolution System (ERS)

**Created:** 2026-03-12
**Status:** Planning Phase Active
**Next Phase:** Epic Writing (by epic-planner agent)

---

## System Snapshot

ERSys is a bounded, engine-authoritative entity resolution system. It translates a PRD into an implementable baseline with these boundaries:

**Inside scope:**
- Entity Resolution Service (ERS) — orchestrates, exposes, persists decisions
- Entity Resolution Engine (ERE) — authoritative clustering (engine-driven)
- Link Curation Web Application — human-in-the-loop curator backend
- Persistence: Request Registry, Decision Store, User Action Log, delta tracking

**Outside scope:**
- ERE internals (algorithms, models, training)
- Upstream ingestion/enrichment pipelines
- Master Data Management, data cleaning, ML lifecycle, compliance audit platform
- Authentication/identity management tech choices

### Authority Model (non-negotiable in all epics)
- **ERE:** Canonical identity / clustering — ERS never overrides
- **ERS:** Intake records (immutable), latest outcome projection, user action trace, delta exposure
- **Both:** Idempotency via correlation triad `(sourceId, requestId, entityType)`

### Tech Stack
- Python, Pydantic, FastAPI, MongoDB, Redis (async contract), RDFLib, LinkML
- OpenTelemetry (logs/traces at service level only)
- **Shared:** er-spec library (domain models reused across all components)

---

## Behavioural Spines (4 Spines — Architectural Commitments)

| Spine | Title | Key Behavior | Components Involved |
|---|---|---|---|
| Spine 0 | End-to-End Resolution Cycle | Conceptual anchor; two time budgets; provisional identifier lifecycle | All components |
| Spine A | Resolution Intake & Canonical Identifier Issuance | Idempotent intake → provisional/canonical clusterId within client budget | 1, 2, 3, 6, 7 |
| Spine B | Async Engine Interaction & Outcome Integration | Publish to ERE; absorb at-least-once outcomes; Decision Store update | 3, 4, 5 |
| Spine C | Canonical Assignment Lookup / Bulk-Delta | refreshBulk read-only; delta rule `lastNotificationDate < lastUpdateDate`; cursor pagination | 7 (lookup endpoints) |
| Spine D | Manual Curation & Engine Re-Evaluation | Curator recommendation → ERE re-resolve → Decision Store update | 8, 9 |

---

## Implementation Components (9 Core + 1 Cross-Cutting)

Listed in **dependency order** (implementation sequence):

| # | Component | Layers | Dependencies | Spines |
|---|---|---|---|---|
| 1 | Request Registry | model, adapter (MongoDB), service | None — foundational | A, B, C, D |
| 2 | RDF Mention Parser | model (config), adapter (RDFLib), service | er-spec config | A |
| 3 | ERE Contract Client | adapter (Redis), service | ERS-ERE contract spec | B, D |
| 4 | Resolution Decision Store | adapter (MongoDB), service | er-spec models | B, C, D |
| 5 | ERE Result Integrator | adapter (Redis listener), entrypoint, service | ERE Contract + Decision Store | B |
| 6 | Resolution Coordinator | service | Registry + RDF Parser + ERE Client | A, B |
| 7 | ERS REST API | model (er-spec), service, entrypoint (FastAPI) | Coordinator + Decision Store | A, C, D |
| 8 | User Action Store | model (er-spec), adapter (MongoDB), service | er-spec models | D |
| 9 | Link Curation REST API | model (er-spec), service, entrypoint (FastAPI) | Decision Store + User Action Store | D |
| X | Observability & Config Manager | cross-cutting (OpenTelemetry, config) | All components | — |

---

## Epic Structure (10 Epics)

### Approach: Component-First Hybrid

**Primary unit:** Component epics (9 + 1 cross-cutting), following dependency order.
**Deployment granularity:** Each epic covers a full vertical slice (model → adapter → service → entrypoint).
**Spine milestones:** Track when each full behavioral spine becomes testable end-to-end.
**Gherkin strategy:** Per-component feature files + integration-level features per completed spine.

### Epic List and Writing Order

#### Phase 1 — Foundation (Spines A/B prerequisite)
| Epic ID | Component | Spines | Status             |
|---|---|---|--------------------|
| **ERS-EPIC-01** | Request Registry | A, B, C, D | ✅ Gherkin Complete (9.7/10) |
| **ERS-EPIC-02** | RDF Mention Parser | A | ✅ Gherkin Complete (9.8/10) |
| **ERS-EPIC-03** | ERE Contract Client | B, D | ✅ Gherkin Complete (9.8/10) |
| **ERS-EPIC-04** | Resolution Decision Store | B, C, D | ✅ Gherkin Complete (9.8/10) |

#### Phase 2 — Core Flows (Spines A + B complete)
| Epic ID | Component | Spines | Status |
|---|---|---|---|
| **ERS-EPIC-05** | ERE Result Integrator | B | ✅ Gherkin Complete (9.2/10) |
| **ERS-EPIC-06** | Resolution Coordinator | A, B | ✅ Gherkin Complete (9.8/10) |
| **ERS-EPIC-07** | ERS REST API (resolve + lookup + refreshBulk) | A, C | ✅ Gherkin Complete (9.8/10) |

**Milestone:** Spine A + B testable end-to-end after EPIC-07.

#### Phase 3 — Curation (Spine D)
| Epic ID | Component | Spines | Status |
|---|---|---|---|
| **ERS-EPIC-08** | User Action Store | D | ⬜ Pending |
| **ERS-EPIC-09** | Link Curation REST API | D | ⬜ Pending |

**Milestone:** Spine D testable end-to-end after EPIC-09.

#### Cross-Cutting
| Epic ID | Component | Scope | Status |
|---|---|---|---|
| **ERS-EPIC-X** | Observability & Config Manager | OpenTelemetry + config | ⬜ Pending |

---

## Epic Writing Workflow

### Step 1: Epic Writing (In Progress)
For each epic in order:
1. **Read** relevant spine and use-case documents (see mapping below)
2. **Invoke epic-planner agent** to write detailed EPIC.md at `.claude/memory/epics/<name>/EPIC.md`
   - Must include Clarity Gate quality checklist
   - Must specify models, adapters, services, entrypoints
   - Must define Gherkin feature set (scenarios per spine)
3. **Run Clarity Gate** (epic-planner includes this in skill)
4. **Update status** in this roadmap when complete

### Step 2: Gherkin Features ✅ Complete (EPICs 01–07)
For each epic:
1. **Invoke gherkin-writer agent** to produce feature files at `tests/features/<component>/`
2. **Integration Gherkin:** After each spine's components are complete, write end-to-end spine features

**Component-level features:** 22 feature files under `tests/features/<component>/` (EPICs 01–07)
**UC-level integration features:** 6 feature files under `tests/features/ucs/`:
- `ucb11_resolve_entity_mention.feature` (10 scenarios) — full resolve integration
- `ucb12_integrate_ere_outcomes.feature` (10 scenarios) — async ERE outcome integration
- `ucb21_submit_user_reevaluation.feature` (5 scenarios) — curation recommendations
- `ucb22_bulk_curator_reevaluation.feature` (4 scenarios) — bulk curation decomposition
- `ucw4_consult_resolution_statistics.feature` (5 scenarios) — read-only statistics
- `e2e_resolution_cycle.feature` (4 scenarios) — black-box 3-phase cycle

**Coverage decisions:** UCW3 (reclustering) covered by UCB12. UCB21/UCB22 trimmed to avoid duplicating UCB12 outcome integration. E2E trimmed to 4 non-redundant cross-phase scenarios.

### Step 3: Planning Phase Complete
When all 10 epics are written + Clarity Gate passes → implementation phase begins.

---

## Primary Source Documents Per Epic

| Epic | Files to Read |
|---|---|
| **ERS-EPIC-01** (Request Registry) | `spine-a.adoc`, `ucw1.adoc`, `ucb11.adoc`, `conceptual-model.adoc` |
| **ERS-EPIC-02** (RDF Mention Parser) | `interface.adoc`, `ucb11.adoc`, `adrc1.adoc` |
| **ERS-EPIC-03** (ERE Contract Client) | `interface.adoc`, `spine-b.adoc`, `adrc1.adoc`, `adrc2.adoc` |
| **ERS-EPIC-04** (Decision Store) | `conceptual-model.adoc`, `spine-b.adoc`, `ucw1.adoc`, `adra1.adoc`, `adra2.adoc` |
| **ERS-EPIC-05** (ERE Result Integrator) | `spine-b.adoc`, `ucb12.adoc`, `interface.adoc`, `adra3.adoc` |
| **ERS-EPIC-06** (Resolution Coordinator) | `spine-a.adoc`, `spine-b.adoc`, `ucw1.adoc`, `ucb11.adoc`, `ucb12.adoc` |
| **ERS-EPIC-07** (ERS REST API) | `spine-a.adoc`, `spine-c.adoc`, `ucw1.adoc`, `ucw3.adoc`, `ucb11.adoc`, `ucb12.adoc`, `ucb13.adoc`, `adra1.adoc` |
| **ERS-EPIC-08** (User Action Store) | `spine-d.adoc`, `ucw2.adoc`, `ucb21.adoc`, `ucb22.adoc` |
| **ERS-EPIC-09** (Link Curation REST API) | `spine-d.adoc`, `ucw2.adoc`, `ucw4.adoc`, `ucw5.adoc`, `ucb21.adoc`, `ucb22.adoc`, `adrc1.adoc` |
| **ERS-EPIC-X** (Observability) | `adrf1.adoc`, `adrd1.adoc`, `adrd2.adoc`, `adrg1.adoc`, `adrg2.adoc` |

---

## Key Architectural Constraints to Enforce in All Epics

1. **ERE Authority:** ERS must never override or derive canonical identifiers independently
2. **Triad Correlation:** All idempotency keyed on `(sourceId, requestId, entityType)`
3. **Decision Store Atomicity:** Each mention's assignment updated atomically (no partial state exposed)
4. **At-Least-Once Tolerance:** Async channels (ERE) must tolerate duplicates and late arrivals
5. **Delta Rule:** `lastNotificationDate < lastUpdateDate` for refreshBulk paging
6. **Provisional Identifier Lifecycle:** Deterministically derived; stored as normal ClusterReference
7. **Curator Recommendations Only:** User actions are forwarded to ERE; ERE outcome is binding
8. **Monotonic Outcome Marker:** Use for ordering/staleness detection in Decision Store updates
9. **Observability at Service Level:** Logs/traces in services only; not in models or adapters
10. **Reuse er-spec Models:** All components use shared er-spec library; no duplication

---

## Success Criteria for Planning Phase

- [ ] All 10 epics written in detail
- [ ] Each epic passes Clarity Gate (13-item quality checklist)
- [ ] Each epic includes identified Gherkin feature set
- [ ] Dependency graph validated (no circular deps)
- [ ] Spine milestones clearly marked
- [ ] Source documents cited in each epic
- [ ] Architectural constraints explicitly called out per epic

---

## Related Memory Files

- **CLAUDE.md** — Project-level instructions for all work (commit policy, agent behavior, etc.)
- **MEMORY.md** — Main auto-memory index
- **ai-coding-runbook.md** (in docs) — Developer workflow for AI-assisted coding
- **Epic memory:** Each completed epic gets a folder at `.claude/memory/epics/<name>/` with:
  - `EPIC.md` — the specification itself
  - `yyyy-mm-dd-task-outcome.md` — task completion notes (written per task in epic)

---

## Next Action

All component-level Gherkin features (EPICs 01–07) and UC-level integration features complete. EPICs 08–09 (curation) and EPIC-X (observability) pending. Next: begin implementation phase starting with foundation EPICs (01–04), or write remaining curation EPICs (08–09) if needed before implementation.

---

## PR #14 Review Comments Analysis (2026-03-19)

PR #14: "feat: BDD Gherkin features for all 7 EPICs + UC-level integration and E2E" (merged into develop).
Reviewers: **gkostkowski** (human), **Copilot** (bot). Comments from **costezki** acknowledge deferred items.

### Gherkin Feature Adjustments (from gkostkowski's human review)

| # | File | Comment | Status |
|---|------|---------|--------|
| A1 | `ere_contract_client/request_validation_and_transport.feature` | Field names in ERE message structure examples are placeholders — must align with domain models once defined. | **Deferred → EPIC-03 implementation.** |
| A2 | `ere_contract_client/request_validation_and_transport.feature` | Error types (`connection`, `serialization`, etc.) are placeholders — must map to concrete domain exceptions. | **Deferred → EPIC-03 implementation.** |
| A3 | `decision_store/decision_persistence.feature` | Triad format normalized from `SYSTEM_E/r1` shorthand to explicit `("SYSTEM_E", "r1", "Organization")` tuples. | ✅ **Fixed 2026-03-19.** |
| A4 | `ere_result_integrator/contract_validation.feature` | Added `zero candidate alternatives are provided` malformation example. | ✅ **Fixed 2026-03-19.** |
| A5 | `ere_result_integrator/outcome_acceptance.feature` | Removed redundant Background; registry setup moved into per-scenario Given steps. | ✅ **Fixed 2026-03-19.** |
| A6 | `ere_result_integrator/outcome_acceptance.feature` | Count-based candidate test should use concrete candidate IDs instead. | **Deferred → EPIC-05 implementation.** |
| A7 | `decision_store/decision_persistence.feature` | Singleton confidence/similarity corrected from 1.0 to 0.0 (matches ERE convention). | ✅ **Fixed 2026-03-19.** |
