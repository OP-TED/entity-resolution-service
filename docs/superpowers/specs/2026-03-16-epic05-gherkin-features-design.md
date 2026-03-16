# ERS-EPIC-05: Gherkin Feature Design — ERE Result Integrator

**Date:** 2026-03-16
**Epic:** ERS-EPIC-05 (ERE Result Integrator)
**Spine:** Spine B (Asynchronous Engine Interaction & Outcome Integration)
**Scope:** BDD feature files for OutcomeIntegrationService behaviour

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| File split | 3 files by behavioural concern | Keeps each file focused; scales well with exhaustive examples |
| Scope | Service-level only | No worker resilience, no listener/Redis specifics — those are unit-tested |
| Delta tracking | Excluded | Not ERE's responsibility; belongs to separate refresh/bulk concern |
| Examples density | Exhaustive (4-6 rows for main flows, 2 rows for marginal edges) | Per user preference; thorough coverage without redundancy |
| "Accept newer" scenario | Dropped | Redundant with File 1 acceptance scenarios which already prove persistence |
| Error paths location | All in File 3 | Clean separation: File 1 = happy paths, File 2 = staleness, File 3 = errors |
| Glossary | Spine B / EPIC terms | "correlation triad", "solicited/unsolicited outcome", "cluster assignment", "monotonic outcome marker", "latest assignment wins", "at-least-once delivery" |

---

## File Structure

```
tests/features/ere_result_integrator/
├── outcome_acceptance.feature
├── deduplication_and_staleness.feature
└── contract_validation.feature
```

---

## File 1: `outcome_acceptance.feature`

**Business question:** When the ERE publishes a valid outcome, does ERS correctly persist the latest cluster assignment?

**Background:** Request Registry contains a mention with a known correlation triad.

### Scenarios

**Scenario Outline: Accept valid solicited resolution result**
- 4-5 Examples rows: Organisation / Person / Location / generic URI entity types, 0 / 1 / 3 candidates, different source systems

**Scenario Outline: Accept unsolicited resolution result (ERE-initiated reclustering)**
- 3-4 Examples rows: `ereNotification:` prefix, with/without prior assignment, different entity types

**Scenario Outline: Replace alternatives wholesale on new outcome**
- 3 Examples rows: 3→1, 0→3, 2→0 alternatives (proves the no-merge invariant from EPIC anti-patterns §3.3)

---

## File 2: `deduplication_and_staleness.feature`

**Business question:** Does ERS correctly enforce "latest assignment wins" using monotonic timestamp comparison?

**Background:** Request Registry contains a mention with an existing assignment at a known outcome timestamp.

### Scenarios

**Scenario Outline: Ignore stale outcome silently**
- 2 Examples rows: earlier timestamp, exact-equal timestamp (boundary)

**Scenario Outline: Tolerate at-least-once duplicate delivery**
- 2 Examples rows: identical message twice, identical triad with same timestamp

**Scenario Outline: Handle out-of-order arrival**
- 2 Examples rows: T3→T1→T2 arrival, T2→T1 arrival — proves only the latest survives

---

## File 3: `contract_validation.feature`

**Business question:** Does ERS correctly reject invalid outcomes without mutating decision state?

**Background:** Decision Store in a known state (for proving immutability on error).

### Scenarios

**Scenario Outline: Reject malformed outcome message**
- 4 Examples rows: missing `entity_mention_id`, missing `timestamp`, null triad fields, empty JSON object

**Scenario Outline: Reject outcome when triad not in Request Registry**
- 3 Examples rows: unknown source, unknown request, partially null triad

**Scenario Outline: Reject outcome with invalid timestamp format**
- 3 Examples rows: non-ISO string, Unix epoch number, missing timezone

**Scenario: Tolerate extra unknown fields in outcome message**
- Single scenario: extra fields present → outcome processed normally

**Scenario: Contract violation never mutates Decision Store**
- Cross-cutting invariant: any validation error → Decision Store state unchanged

---

## Total: ~14 scenarios across 3 files

## References

- **EPIC spec:** `.claude/memory/epics/ers-epic-05-ere-result-integrator/EPIC.md`
- **Spine B narrative:** `docs/modules/ROOT/pages/ERSArchitecture/spine-b.adoc` §8.3
- **Existing feature pattern:** `tests/features/request_registry/` (EPIC-01)
- **Error handling matrix:** EPIC-05 §3.2
- **Anti-patterns:** EPIC-05 §3.3
