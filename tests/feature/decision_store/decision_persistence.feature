Feature: Decision Store Persistence Operations
  As a service layer consumer of the Decision Store,
  I want atomic upsert, retrieval, and configuration-driven truncation
  to work correctly at the persistence layer,
  So that upstream components (ERE Result Integrator, Resolution Coordinator)
  can rely on the store's CRUD guarantees.

  Background:
    Given the Decision Store is available

  Scenario Outline: Atomic upsert preserves created_at and stores the decision
    Given a correlation triad ("<source_id>", "<request_id>", "Organization")
    And the Decision Store "<prior_state>" a decision for that triad
    When a resolution decision is stored with cluster "<cluster_id>", <candidate_count> candidates, and timestamp "<timestamp>"
    Then the Decision Store contains a decision for that triad with current placement "<cluster_id>"
    And <candidate_count> candidate alternatives are stored
    And created_at "<created_at_rule>"

    Examples:
      | source_id | request_id | prior_state      | cluster_id    | candidate_count | timestamp                  | created_at_rule                    |
      | SYSTEM_A  | req-001    | does not contain | cluster-org-1 | 2               | 2026-03-12T14:30:45.123Z   | equals updated_at                  |
      | SYSTEM_A  | req-002    | contains         | cluster-org-7 | 3               | 2026-03-12T14:35:00.000Z   | is preserved from the original     |

  Scenario Outline: Truncate candidate alternatives to the configured maximum
    Given a correlation triad ("<source_id>", "<request_id>", "Organization")
    And the maximum candidate count is configured to <max_candidates>
    When a resolution decision is stored with <incoming_count> candidate alternatives
    Then the Decision Store retains exactly <stored_count> candidates in their original order

    Examples:
      | source_id | request_id | max_candidates | incoming_count | stored_count |
      | SYSTEM_B  | req-010    | 5              | 8              | 5            |
      | SYSTEM_B  | req-011    | 5              | 5              | 5            |
      | SYSTEM_B  | req-012    | 5              | 0              | 0            |

  Scenario: Store a provisional singleton decision
    Given a correlation triad ("SYSTEM_C", "req-020", "Organization")
    And the Decision Store does not contain a decision for that triad
    When a provisional singleton decision is stored with a SHA256-derived cluster identifier
    Then the current placement is the provisional singleton cluster with confidence 0.0 and similarity 0.0
    And the provisional singleton cluster is the only candidate alternative

  Scenario Outline: Retrieve a resolution decision by its correlation triad
    Given a correlation triad ("<source_id>", "<request_id>", "Organization")
    And the Decision Store "<store_state>" a decision for that triad
    When the decision is retrieved by that triad
    Then "<retrieval_result>"

    Examples:
      | source_id | request_id | store_state      | retrieval_result                                  |
      | SYSTEM_D  | req-030    | contains         | the full resolution decision is returned          |
      | SYSTEM_D  | req-999    | does not contain | no decision is returned                           |

  Scenario Outline: Query decisions by outcome timestamp interval
    Given the Decision Store contains decisions with outcome timestamps:
      | triad                                  | outcome_timestamp          |
      | ("SYSTEM_E", "r1", "Organization")     | 2026-03-10T10:00:00.000Z   |
      | ("SYSTEM_E", "r2", "Organization")     | 2026-03-12T14:00:00.000Z   |
      | ("SYSTEM_E", "r3", "Organization")     | 2026-03-15T09:00:00.000Z   |
    When decisions are queried with start "<start>" and end "<end>"
    Then <expected_count> decisions are returned

    Examples:
      | start                      | end                        | expected_count |
      | 2026-03-11T00:00:00.000Z   | 2026-03-13T00:00:00.000Z  | 1              |
      | 2026-03-10T10:00:00.000Z   | None                       | 3              |
      | None                       | 2026-03-12T14:00:00.000Z  | 2              |
      | None                       | None                       | 3              |

  Scenario Outline: Query decisions by confidence score interval
    Given the Decision Store contains decisions with confidence scores:
      | triad                                  | confidence |
      | ("SYSTEM_F", "r1", "Organization")     | 0.45       |
      | ("SYSTEM_F", "r2", "Organization")     | 0.78       |
      | ("SYSTEM_F", "r3", "Organization")     | 0.92       |
    When decisions are queried with min confidence "<min_conf>" and max confidence "<max_conf>"
    Then <expected_count> decisions are returned

    Examples:
      | min_conf | max_conf | expected_count |
      | 0.70     | 0.95     | 2              |
      | 0.80     | None     | 1              |
      | None     | 0.50     | 1              |
      | None     | None     | 3              |
