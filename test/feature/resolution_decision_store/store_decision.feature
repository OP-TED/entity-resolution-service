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
    Given an existing decision with updated_at "<stored_ts>"
    When I attempt to store the same triad with updated_at "<attempt_ts>"
    Then a StaleOutcomeError is raised

    Examples:
      | stored_ts            | attempt_ts           |
      | 2025-06-01T12:00:00Z | 2025-06-01T11:59:59Z |
      | 2025-06-01T12:00:00Z | 2025-06-01T12:00:00Z |

  Scenario: Candidates are truncated to max_candidates
    Given a valid entity mention identifier and 10 candidates
    When I store the decision
    Then the stored record has at most 5 candidates
