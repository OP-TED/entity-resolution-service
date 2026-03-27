Feature: Decision curation recommendations
  As a curator
  I need to view resolution decisions and submit recommendations
  So that I can guide entity clustering corrections through the ERE

  Background:
    Given the curator is authenticated and verified

  # --- View decision ---

  Scenario: View full details of a resolution decision
    Given a resolution decision exists with entity mention preview, current placement, and ranked candidates
    When the curator requests the full details of that decision
    Then the decision details are returned including the entity mention preview
    And the current placement is shown
    And the ranked candidates with scores are listed
    And the curation timestamps are included

  Scenario: View details of a non-existent decision
    When the curator requests the details of a decision that does not exist
    Then the system responds with a not found error

  # --- Recommend top candidate ---

  Scenario: Recommend placement of the top candidate for a decision
    Given a decision exists that has not been curated on its current version
    When the curator recommends the top candidate placement for the decision
    Then the recommendation is recorded
    And a recommendation of type "accept top" is recorded

  Scenario: Recommend top candidate for a non-existent decision
    When the curator attempts to recommend the top candidate for a decision that does not exist
    Then the system responds with a not found error

  Scenario: Recommend top candidate for a decision already curated on its current version
    Given a decision exists that has already been curated on its current version
    When the curator attempts to recommend the top candidate placement for the decision
    Then the system responds with a conflict error indicating already curated

  # --- Recommend rejection of all candidates ---

  Scenario: Recommend rejection of all candidates for a decision
    Given a decision exists that has not been curated on its current version
    When the curator recommends rejection of all candidates for the decision
    Then the recommendation is recorded
    And a recommendation of type "reject all" is recorded

  Scenario: Recommend rejection for a non-existent decision
    When the curator attempts to recommend rejection of all candidates for a decision that does not exist
    Then the system responds with a not found error

  # --- Recommend alternative cluster placement ---

  Scenario Outline: Recommend placement in an alternative cluster
    Given a decision exists with alternative candidate "<cluster_id>"
    And the decision has not been curated on its current version
    When the curator recommends placement in cluster "<cluster_id>"
    Then the recommendation is recorded
    And a recommendation of type "accept alternative" is recorded for cluster "<cluster_id>"

    Examples:
      | cluster_id  |
      | cluster-B   |
      | cluster-C   |
      | cluster-D   |

  Scenario: Recommend a cluster that is not among the candidates
    Given a decision exists that has not been curated on its current version
    When the curator recommends placement in cluster "nonexistent-cluster"
    Then the system responds with a conflict error indicating an invalid cluster

  Scenario: Recommend alternative cluster placement for a non-existent decision
    When the curator attempts to recommend alternative cluster placement for a decision that does not exist
    Then the system responds with a not found error
