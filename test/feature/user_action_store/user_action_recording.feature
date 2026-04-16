Feature: User action recording
  As a curation system
  I need to record curator recommendations against resolution decisions
  So that there is a traceable audit trail of all curation activity

  Background:
    Given a resolution decision exists for an entity mention
    And the decision has candidate clusters with confidence scores

  # --- Recommend top candidate ---

  Scenario: Record a recommendation for the top candidate placement
    Given the decision has not been curated on its current version
    When the curator recommends the top candidate placement
    Then a user action is recorded with action type "accept top"
    And the selected cluster matches the decision's current placement
    And the action captures all candidates as a snapshot

  # --- Full decision context capture ---

  Scenario Outline: Recorded action captures the full decision context
    Given the decision has not been curated on its current version
    And the decision has candidates with known confidence and similarity scores
    And the current placement is known
    When the curator "<actor>" recommends <recommendation>
    Then the recorded action has actor "<actor>"
    And the recorded action has a timestamp
    And the recorded action has action type "<action_type>"
    And the recorded action snapshot includes all candidates with their confidence and similarity scores
    And the recorded action snapshot includes the current placement

    Examples:
      | actor                  | recommendation                          | action_type        |
      | curator@example.com    | the top candidate placement             | accept top         |
      | reviewer@example.com   | rejection of all candidates             | reject all         |
      | admin@example.com      | placement in alternative cluster        | accept alternative |

  # --- Recommend rejection of all candidates ---

  Scenario: Record a recommendation to reject all candidates
    Given the decision has not been curated on its current version
    When the curator recommends rejection of all candidates
    Then a user action is recorded with action type "reject all"
    And the selected cluster is empty
    And the action captures all candidates as a snapshot

  # --- Recommend alternative cluster placement ---

  Scenario: Record a recommendation for an alternative cluster placement
    Given the decision has not been curated on its current version
    And the decision has an alternative candidate "cluster-B"
    When the curator recommends placement in alternative cluster "cluster-B"
    Then a user action is recorded with action type "accept alternative"
    And the selected cluster is "cluster-B"

  Scenario: Recommend a cluster not among the candidates is rejected
    Given the decision has not been curated on its current version
    When the curator recommends placement in cluster "nonexistent-cluster"
    Then the action is rejected because the cluster is not a valid candidate
