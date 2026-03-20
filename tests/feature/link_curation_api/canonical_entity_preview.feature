Feature: Canonical entity preview
  As a curator
  I need to view the proposed and alternative canonical entities for a decision
  So that I can understand the clustering context before curating

  Background:
    Given the curator is authenticated and verified

  # --- Proposed canonical entity ---

  Scenario: View the proposed canonical entity for a decision
    Given a decision exists with a current placement in cluster "cluster-A"
    And cluster "cluster-A" contains 3 entity mentions
    When the curator requests the proposed canonical entity
    Then a preview is returned for cluster "cluster-A"
    And the preview includes up to 5 top entity mentions from the cluster

  Scenario: Proposed canonical entity for a non-existent decision
    When the curator requests the proposed canonical entity for a non-existent decision
    Then the system responds with a not found error

  # --- Alternative canonical entities ---

  Scenario: View alternative canonical entities for a decision
    Given a decision exists with 3 candidate clusters
    And the current placement is in the first candidate
    When the curator requests alternative canonical entities
    Then 2 alternative entity previews are returned
    And each preview includes the cluster identifier and top entity mentions

  Scenario: Alternative canonical entities with pagination
    Given a decision exists with 6 candidate clusters including the current
    When the curator requests alternative canonical entities for page 1 with 2 items per page
    Then 2 alternative previews are returned
    And a next page indicator is present

  Scenario: Decision with no alternative candidates
    Given a decision exists with only 1 candidate cluster (the current placement)
    When the curator requests alternative canonical entities
    Then an empty result set is returned

  Scenario: Alternative canonical entities for a non-existent decision
    When the curator requests alternative canonical entities for a non-existent decision
    Then the system responds with a not found error

  # --- Incomplete data ---

  Scenario: Canonical entity preview with mentions lacking parsed representations
    Given a decision exists with a current placement in cluster "cluster-B"
    And cluster "cluster-B" contains entity mentions with no parsed representations
    When the curator requests the proposed canonical entity
    Then a preview is returned for cluster "cluster-B"
    And the preview includes only the entity mention identifiers where parsed representations are absent