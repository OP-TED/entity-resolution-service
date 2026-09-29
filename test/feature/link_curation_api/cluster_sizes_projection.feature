Feature: cluster_sizes projection invariants

  Scenario: New decision integration increments the destination cluster
    Given cluster "X" has size 4 in cluster_sizes
    When ERE integrates a new decision with current_placement cluster_id "X"
    Then cluster_sizes["X"] size is 5

  Scenario: Placement change shifts the count atomically
    Given cluster "X" has size 5 in cluster_sizes
    And cluster "Y" has size 2 in cluster_sizes
    And a decision is currently placed in cluster "X"
    When ERE re-integrates that decision with cluster_id "Y"
    Then cluster_sizes["X"] size is 4
    And cluster_sizes["Y"] size is 3

  Scenario: Unchanged placement is a no-op
    Given cluster "X" has size 7 in cluster_sizes
    And a decision is currently placed in cluster "X"
    When ERE re-integrates that decision with cluster_id "X"
    Then cluster_sizes["X"] size is 7
