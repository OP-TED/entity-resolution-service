# Task 7: Gherkin Features

## Context

BDD feature files and step definitions for the three core use cases of the Resolution Decision Store. Step definitions call the module-level public API functions (`store_decision`, `get_decision_by_triad`, `query_decisions_paginated`) with a mocked repository — consistent with the `tests/feature/request_registry/` pattern.

---

## Files to Create

| Path | Purpose |
|------|---------|
| `tests/feature/resolution_decision_store/__init__.py` | Empty package marker |
| `tests/feature/resolution_decision_store/conftest.py` | Shared fixtures: `ctx`, `service`, `mock_repo` |
| `tests/feature/resolution_decision_store/store_decision.feature` | BDD: store + staleness scenarios |
| `tests/feature/resolution_decision_store/retrieve_decision.feature` | BDD: retrieve by triad |
| `tests/feature/resolution_decision_store/paginated_query.feature` | BDD: cursor pagination |
| `tests/feature/resolution_decision_store/test_store_decision.py` | pytest-bdd step defs |
| `tests/feature/resolution_decision_store/test_retrieve_decision.py` | pytest-bdd step defs |
| `tests/feature/resolution_decision_store/test_paginated_query.py` | pytest-bdd step defs |

**Before writing:** Read `tests/feature/request_registry/` to understand exact step definition pattern (fixture injection, `ctx` object, `@scenario` bindings).

---

## Feature Files (Gherkin)

### `store_decision.feature`

```gherkin
Feature: Store Resolution Decision

  Scenario: Storing a new decision succeeds
    Given a valid entity mention identifier and cluster outcome
    When I store the decision
    Then the stored record matches the input

  Scenario: Replacing a decision with a newer timestamp succeeds
    Given an existing decision for a triad
    When I store the same triad with a newer updated_at
    Then the record reflects the updated cluster

  Scenario Outline: Stale outcome is rejected
    Given an existing decision stored at "<stored_ts>"
    When I attempt to store the same triad with timestamp "<attempt_ts>"
    Then a StaleOutcomeError is raised

    Examples:
      | stored_ts              | attempt_ts             |
      | 2025-06-01T12:00:00Z   | 2025-06-01T11:59:59Z   |
      | 2025-06-01T12:00:00Z   | 2025-06-01T12:00:00Z   |

  Scenario: Candidates are truncated to max_candidates
    Given a valid entity mention identifier and 10 candidates
    When I store the decision
    Then the stored record has at most 5 candidates
```

### `retrieve_decision.feature`

```gherkin
Feature: Retrieve Resolution Decision

  Scenario: Finding an existing decision by triad
    Given a stored decision for a known triad
    When I look up the decision by that triad
    Then the returned record matches the stored decision

  Scenario: Looking up a non-existent triad returns None
    Given an empty decision store
    When I look up a decision by an unknown triad
    Then the result is None
```

### `paginated_query.feature`

```gherkin
Feature: Paginated Query of Decisions

  Scenario: First page with no cursor returns results and a next cursor
    Given 5 stored decisions
    When I query decisions with page_size 3 and no cursor
    Then I receive 3 records
    And the response includes a next_cursor

  Scenario: Following the cursor returns remaining decisions
    Given 5 stored decisions
    When I query page 1 then follow the next_cursor
    Then page 2 contains 2 records with no next_cursor

  Scenario: Empty store returns empty page
    Given an empty decision store
    When I query decisions paginated
    Then I receive 0 records and no next_cursor

  Scenario: page_size is capped at system limit
    Given a valid decision store
    When I query with page_size 9999
    Then the effective page_size does not exceed 50
```

---

## Step Definitions Pattern

Mirror `tests/feature/request_registry/test_resolution_request_registration.py`:

```python
# tests/feature/resolution_decision_store/conftest.py
import pytest
from unittest.mock import create_autospec
from ers.resolution_decision_store.adapters.decision_repository import MongoDecisionRepository
from ers.resolution_decision_store.services.decision_store_service import DecisionStoreService

class Ctx:
    """Shared scenario context object."""
    result = None
    error = None
    next_cursor = None

@pytest.fixture()
def ctx():
    return Ctx()

@pytest.fixture()
def mock_repo():
    return create_autospec(MongoDecisionRepository, instance=True)

@pytest.fixture()
def service(mock_repo):
    return DecisionStoreService(repository=mock_repo)
```

Step definitions use `@given`, `@when`, `@then` from `pytest_bdd` and inject `ctx`, `service`, `mock_repo` via function arguments.

---

## Verify

```bash
poetry run pytest tests/feature/resolution_decision_store/ -v
```
