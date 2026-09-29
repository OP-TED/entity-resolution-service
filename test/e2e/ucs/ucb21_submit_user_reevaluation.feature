Feature: UC-B2.1 — Submit User Re-evaluation Request
  As an authorised user reviewing entity resolution outcomes,
  I want to submit a placement recommendation or exclusion list for a single mention,
  So that ERE re-evaluates the clustering and the Decision Store reflects
  the latest authoritative outcome without my action directly modifying canonical identity.

  # User curation integration test. ERE is mocked at the messaging boundary.
  # User recommendations are forwarded to ERE; ERS never modifies the cluster
  # assignment directly — only ERE outcomes update the Decision Store (tested in UC-B1.2).
  # Traceability: UC-W2, UC-B2.1.

  Background:
    Given the ERS system is operational
    And the Decision Store is available
    And the ERE messaging boundary is available
    And the user is authenticated and authorised

  # ---------------------------------------------------------------------------
  # Main Success — placement recommendation
  # ---------------------------------------------------------------------------

  Scenario Outline: Forward a placement recommendation to ERE
    Given a mention with triad "<source_id>", "<request_id>", "<entity_type>" exists in the Decision Store
    And the current cluster assignment is "<current_cluster>"
    And the user recommends placement into cluster "<recommended_cluster>"
    When the user submits the re-evaluation request
    Then the request is accepted
    And a resolveConsideringRecommendation message is forwarded to ERE for triad "<source_id>", "<request_id>", "<entity_type>"
    And the recommended cluster in the forwarded message is "<recommended_cluster>"
    And the Decision Store still reflects "<current_cluster>" for that triad

    Examples:
      | source_id | request_id | entity_type  | current_cluster | recommended_cluster |
      | SYSTEM_A  | req-001    | ORGANISATION | cluster-010     | cluster-020         |
      | SYSTEM_A  | req-002    | ORGANISATION | cluster-011     | cluster-030         |

  # ---------------------------------------------------------------------------
  # Alternate — exclusion recommendation
  # ---------------------------------------------------------------------------

  Scenario Outline: Forward an exclusion recommendation to ERE
    Given a mention with triad "<source_id>", "<request_id>", "<entity_type>" exists in the Decision Store
    And the current cluster assignment is "<current_cluster>"
    And the user recommends excluding clusters "<excluded_clusters>"
    When the user submits the re-evaluation request
    Then the request is accepted
    And a resolveWithExclusions message is forwarded to ERE for triad "<source_id>", "<request_id>", "<entity_type>"
    And the excluded clusters in the forwarded message are "<excluded_clusters>"
    And the Decision Store still reflects "<current_cluster>" for that triad

    Examples:
      | source_id | request_id | entity_type  | current_cluster | excluded_clusters       |
      | SYSTEM_B  | req-010    | ORGANISATION | cluster-040     | cluster-040             |
      | SYSTEM_B  | req-011    | ORGANISATION | cluster-050     | cluster-050,cluster-051 |

  # ---------------------------------------------------------------------------
  # Validation errors
  # ---------------------------------------------------------------------------

  Scenario: Reject re-evaluation for an unknown mention
    Given no mention with triad "SYSTEM_UNKNOWN", "req-999", "ORGANISATION" exists in the Decision Store
    And the user recommends placement into cluster "cluster-phantom"
    When the user submits the re-evaluation request for triad "SYSTEM_UNKNOWN", "req-999", "ORGANISATION"
    Then the request is rejected with error "MENTION_NOT_FOUND"
    And no message is forwarded to ERE

  Scenario Outline: Reject re-evaluation with invalid request fields
    Given a mention with triad "SYSTEM_D", "req-030", "ORGANISATION" exists in the Decision Store
    And the current cluster assignment is "cluster-110"
    And a re-evaluation request with <invalid_condition>
    When the user submits the re-evaluation request
    Then the request is rejected with error "VALIDATION_ERROR"
    And no message is forwarded to ERE
    And the Decision Store still reflects "cluster-110" for that triad

    Examples:
      | invalid_condition                         |
      | recommended_cluster absent for placement  |
      | excluded_clusters empty for exclusion     |
      | action_type unrecognised                  |

  # ---------------------------------------------------------------------------
  # ERE unavailable
  # ---------------------------------------------------------------------------

  Scenario: Current cluster assignment unchanged when ERE is unavailable
    Given a mention with triad "SYSTEM_E", "req-040", "ORGANISATION" exists in the Decision Store
    And the current cluster assignment is "cluster-120"
    And the user recommends placement into cluster "cluster-130"
    And the ERE messaging boundary is unavailable
    When the user submits the re-evaluation request
    Then the request is rejected with error "SERVICE_ERROR"
    And the Decision Store still reflects "cluster-120" for that triad
