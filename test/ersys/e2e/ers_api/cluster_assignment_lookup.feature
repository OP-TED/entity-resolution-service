Feature: Cluster Assignment Lookup and Bulk Delta Retrieval
  As an Originator that has previously submitted entity mentions for resolution
  I want to look up the current cluster assignment for a single mention and retrieve bulk deltas
  So that I can reconcile my downstream references with the latest canonical identifiers

  Background: System is clean and all services are healthy
    Given the ERS API is reachable
    And the request registry is empty
    And the decision store is empty

  # ---------------------------------------------------------------------------
  # UC-B1.3 — Main Success Scenario: Single lookup — resolved mention
  # Reference: docs/AnnexeB-UseCases/ucb13.adoc
  # ---------------------------------------------------------------------------

  Scenario: Looking up a previously resolved mention returns its current cluster assignment
    Given an entity mention has been submitted and fully resolved by ERE
    When the Originator requests the cluster assignment for that entity mention
    Then the response confirms the mention is found
    And the response contains the canonical cluster identifier assigned by ERE
    And the response contains the entity type and request identifier
    And the decision store is not modified by the lookup

  # ---------------------------------------------------------------------------
  # UC-B1.3 — Minimal Guarantee: Unknown triad lookup
  # ---------------------------------------------------------------------------

  Scenario: Looking up an entity mention that has never been submitted returns a not-found outcome
    Given no entity mention with the queried source identifier, request identifier, and entity type has been submitted
    When the Originator requests the cluster assignment for that entity mention
    Then the response indicates the mention was not found
    And the decision store remains empty

  # ---------------------------------------------------------------------------
  # UC-B1.3 — Provisional status lookup
  # ---------------------------------------------------------------------------

  Scenario: Looking up an entity mention that has a provisional draft identifier returns provisional status
    Given an entity mention has been submitted but ERE did not respond within the execution window
    And the mention carries a provisional draft identifier
    When the Originator requests the cluster assignment for that entity mention
    Then the response confirms the mention is found
    And the response indicates the cluster assignment is provisional
    And the decision store is not modified by the lookup

  # ---------------------------------------------------------------------------
  # UC-B1.3 — refreshBulk: delta retrieval with updates present
  # ---------------------------------------------------------------------------

  Scenario: refreshBulk returns only mentions whose cluster assignment changed since the last notification date
    Given several entity mentions have been submitted and resolved for origin "test-source-001"
    And some of those mentions have had their cluster assignment updated since the last notification date
    When the Originator invokes refreshBulk for origin "test-source-001"
    Then the response contains only the mentions whose cluster assignment changed after the last notification date
    And each returned entry contains the request identifier, entity type, and canonical cluster identifier
    And after the response is emitted the last notification date for "test-source-001" is updated in the delta tracking store
    And the decision store records for unchanged mentions are not modified

  # ---------------------------------------------------------------------------
  # UC-B1.3 — Extension 1a: refreshBulk with no updates
  # ---------------------------------------------------------------------------

  Scenario: refreshBulk returns an empty collection when no cluster assignments have changed since the last notification date
    Given entity mentions have been submitted and resolved for origin "test-source-002"
    And no cluster assignments have changed since the last notification date for "test-source-002"
    When the Originator invokes refreshBulk for origin "test-source-002"
    Then the response contains an empty collection of updated mentions
    And after the response is emitted the last notification date for "test-source-002" is still updated in the delta tracking store
    And the decision store is not modified by the refreshBulk call
