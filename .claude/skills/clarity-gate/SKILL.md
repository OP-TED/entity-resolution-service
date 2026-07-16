---
name: clarity-gate
description: >
  Pre-implementation quality gate for EPIC specifications and documentation.
  Enforces epistemic quality by checking that claims are properly qualified,
  assumptions are visible, and documentation is AI-ready. Use before proceeding
  from planning to implementation, or when reviewing specification quality.
  Triggers on "clarity gate", "check spec quality", "is this spec ready",
  "review documentation quality", or "run clarity check".
---

# Clarity Gate v2.1

A pre-implementation verification system that asks: **"If another LLM reads this
document, will it mistake assumptions for facts?"**

**Core Principle:** Find missing uncertainty markers before they become confident
hallucinations. Verify FORM, not TRUTH — this skill checks whether claims are
properly marked as uncertain, not whether claims are actually true.

---

## The 13-Item Clarity Gate Checklist

### Foundation Checks (7 items)

- [ ] **Actionable** — Can AI act on every section? No aspirational content.
- [ ] **Current** — Is everything up-to-date? No outdated decisions.
- [ ] **Single Source** — No duplicate information across docs.
- [ ] **Decision, Not Wish** — Every statement is a decision, not a hope.
- [ ] **Prompt-Ready** — Would you put every section in an AI prompt?
- [ ] **No Future State** — All "will eventually," "might," "ideally" removed.
- [ ] **No Fluff** — All motivational/aspirational content removed.

### Document Architecture Checks (6 items)

- [ ] **Type Identified** — Document type clearly marked (Strategic vs Implementation vs Reference).
- [ ] **Anti-patterns Placed** — Anti-patterns in implementation docs only (strategic docs use pointers).
- [ ] **Test Cases Placed** — Test cases in implementation docs only.
- [ ] **Error Handling Placed** — Error handling matrix in implementation docs only.
- [ ] **Deep Links Present** — Deep links in ALL documents. No vague "see elsewhere."
- [ ] **No Duplicates** — Strategic docs use pointers, not duplicate content.

---

## Scoring Rubric (6 Criteria)

| Criterion | Weight | 10/10 means |
|-----------|--------|-------------|
| **Actionability** | 25% | Every section has an implementation implication |
| **Specificity** | 20% | All numbers concrete, all thresholds explicit |
| **Consistency** | 15% | Single source of truth, no duplicates |
| **Structure** | 15% | Tables over prose, clear hierarchy |
| **Disambiguation** | 15% | Anti-patterns present (5+), edge cases explicit |
| **Reference Clarity** | 10% | Deep links only, no vague references |

### Score Interpretation

| Score | Meaning | Action |
|-------|---------|--------|
| **10/10** | AI can implement with zero questions | Proceed to implementation |
| **9/10** | 1 minor clarification needed | Fix, then proceed |
| **7-8/10** | 3-5 ambiguities exist | Major revision required |
| **< 7/10** | Not AI-ready, fundamental issues | Return to planning |

**Minimum threshold for proceeding:** >= 9/10

---

## 9 Verification Points (Semantic Review)

### Epistemic Checks (Points 1-4) — Core Focus

1. **Hypothesis vs. Fact Labelling** — Every claim must indicate validation status.
   Add "PROJECTED:", "HYPOTHESIS:", "UNTESTED:", or supporting evidence.

2. **Uncertainty Marker Enforcement** — Forward-looking statements need qualifiers:
   "projected", "estimated", "expected", "designed to", "intended to".

3. **Assumption Visibility** — Implicit assumptions must be explicit. Add bracketed
   conditions: `[assuming <condition>]` or `[under <constraint>]`.

4. **Authoritative-Looking Unvalidated Data** — Tables with specific percentages
   without sources. Add "(est.)", "(guess)", or explicit warning.

### Data Quality Checks (Points 5-7) — Complementary

5. **Data Consistency** — Scan for conflicting numbers or facts across sections.

6. **Implicit Causation** — Challenge claims implying causation without evidence.
   Reframe as hypothesis: "MAY improve (unvalidated)".

7. **Future State as Present** — Planned outcomes described as achieved.
   Replace with "DESIGNED TO", "TARGET:", or "PLANNED:".

### Verification Routing (Points 8-9)

8. **Temporal Coherence** — Internal dates must be chronologically consistent.

9. **Externally Verifiable Claims** — Specific numbers (pricing, statistics) should
   be flagged for verification. Add dated sources or uncertainty markers.

---

## Quick Scan Patterns

| Pattern | Required Action |
|---------|-----------------|
| Specific percentages without source | Add source or "(est.)" marker |
| Comparison tables | Add "PROJECTED" header if unvalidated |
| Achievement verbs ("achieves", "delivers") | Use "designed to" / "intended to" if unvalidated |
| "100%" claims | Almost always needs qualification |
| Outdated timestamps | Verify against current date |

---

## Lightweight Clarity Check (5 items)

For documents that do NOT require the full 13-item gate (e.g., documentation,
summaries, explanations), use this abbreviated checklist:

- [ ] **Actionable** — Can the reader act on this? No aspirational filler.
- [ ] **Current** — Reflects actual state, not a future wish.
- [ ] **Specific** — References are precise (file paths, section anchors).
- [ ] **No Future State as Present** — Planned features marked as planned.
- [ ] **Single Source** — Links instead of duplicating content.

---

## When to Use

| Context | Which gate |
|---------|-----------|
| EPIC specifications (before implementation) | Full 13-item gate + scoring rubric |
| Task specifications | Full 13-item gate + scoring rubric |
| Documentation, summaries, explanations | Lightweight 5-item check |
| README updates | Lightweight 5-item check |

---

*Based on [Clarity Gate v2.1](https://github.com/frmoretto/clarity-gate) by
Francesco Marinoni Moretto. Adapted for a custom AI-assisted coding workflow.
License: CC-BY-4.0.*
