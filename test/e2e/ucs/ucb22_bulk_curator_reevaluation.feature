Feature: UC-B2.2 — Submit Bulk Curator Re-evaluation Requests
  As a curator reviewing multiple entity mentions,
  I want to apply a uniform re-evaluation recommendation to several mentions at once,
  So that ERE re-evaluates each mention independently and the Decision Store
  reflects the latest authoritative outcomes without my actions directly modifying
  canonical identity.

  # Bulk curation integration test. ERE is mocked at the messaging boundary.
  # Each mention is processed independently — no shared clustering semantics.
  # Partial success is supported: invalid mentions are rejected individually.
  # ERE outcome integration is tested in UC-B1.2; this UC tests bulk decomposition
  # and per-mention forwarding only.
  # Traceability: UC-W2, UC-B2.2.

  Background:
    Given the ERS system is operational
    And the Decision Store is available
    And the ERE messaging boundary is available
    And the user is authenticated and authorised

  # ---------------------------------------------------------------------------
  # Main Success — bulk placement recommendation
  # ---------------------------------------------------------------------------

  Scenario: Forward bulk placement recommendations to ERE independently
    Given the following mentions exist in the Decision Store:
      | source_id | request_id | entity_type  | current_cluster |
      | SYSTEM_A  | req-001    | ORGANISATION | cluster-010     |
      | SYSTEM_A  | req-002    | ORGANISATION | cluster-011     |
      | SYSTEM_A  | req-003    | ORGANISATION | cluster-012     |
    And the curator recommends placement into cluster "cluster-050" for all selected mentions
    When the curator submits the bulk re-evaluation request
    Then the request is accepted
    And 3 individual resolveConsideringRecommendation messages are forwarded to ERE
    And each forwarded message recommends cluster "cluster-050"
    And the Decision Store is not modified for any of the selected mentions

  # ---------------------------------------------------------------------------
  # Main Success — bulk exclusion recommendation
  # ---------------------------------------------------------------------------

  Scenario: Forward bulk exclusion recommendations to ERE independently
    Given the following mentions exist in the Decision Store:
      | source_id | request_id | entity_type  | current_cluster |
      | SYSTEM_B  | req-010    | ORGANISATION | cluster-020     |
      | SYSTEM_B  | req-011    | ORGANISATION | cluster-021     |
    And the curator recommends excluding clusters "cluster-020,cluster-021" for all selected mentions
    When the curator submits the bulk re-evaluation request
    Then the request is accepted
    And 2 individual resolveWithExclusions messages are forwarded to ERE
    And the Decision Store is not modified for any of the selected mentions

  # ---------------------------------------------------------------------------
  # Partial validation failure (Extension 1a)
  # ---------------------------------------------------------------------------

  Scenario: Invalid mentions rejected individually while valid mentions proceed
    Given the following mentions exist in the Decision Store:
      | source_id | request_id | entity_type  | current_cluster |
      | SYSTEM_D  | req-030    | ORGANISATION | cluster-040     |
      | SYSTEM_D  | req-031    | ORGANISATION | cluster-041     |
    And mention with triad "SYSTEM_D", "req-032", "ORGANISATION" does not exist in the Decision Store
    And the curator selects all three mentions for bulk re-evaluation
    And the curator recommends placement into cluster "cluster-080" for all selected mentions
    When the curator submits the bulk re-evaluation request
    Then the response indicates partial success
    And 2 individual resolveConsideringRecommendation messages are forwarded to ERE
    And the response includes a per-mention rejection for "SYSTEM_D", "req-032", "ORGANISATION" with error "MENTION_NOT_FOUND"

  # ---------------------------------------------------------------------------
  # Empty selection
  # ---------------------------------------------------------------------------

  Scenario: Reject bulk re-evaluation with no mentions selected
    Given an empty selection of mentions
    And the curator recommends placement into cluster "cluster-100"
    When the curator submits the bulk re-evaluation request
    Then the request is rejected with error "VALIDATION_ERROR"
