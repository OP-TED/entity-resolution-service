Feature: Decision Review-State Lifecycle
  As an authorised Curator managing entity resolution outcomes
  I want to see which decisions need to be reviewed after ERE updates their placement
  So that I can identify and revisit decisions that have changed since I last curated them

  # Tests the materialised reviewed_since_placement flag (TEDSWS-524-2).
  # ERE responses are injected directly into ere_responses to make the test
  # deterministic and independent of live ERE processing latency.
  #
  # Three scenarios cover the full lifecycle:
  #   1. Fresh ERE placement → decision appears as unreviewed (flag starts False)
  #   2. Curator action     → decision removed from unreviewed list (flag flips True)
  #   3. ERE re-placement   → decision re-surfaces as unreviewed (flag resets False)

  Background: System is clean and all services are healthy
    Given the Curation API is reachable
    And the ERS API is reachable
    And the ERE response channel is operational
    And the decision store is empty
    And the ERE request queue is empty

  # ---------------------------------------------------------------------------
  # Scenario 1: Initial placement sets reviewed_since_placement to False
  # ---------------------------------------------------------------------------

  Scenario: A freshly placed decision appears in the unreviewed list
    Given an entity mention has been submitted and placed by ERE with a known cluster assignment
    When an authorised Curator queries the list of decisions not yet reviewed since placement
    Then that decision appears in the results

  # ---------------------------------------------------------------------------
  # Scenario 2: Curator action flips reviewed_since_placement to True
  # ---------------------------------------------------------------------------

  Scenario: Curating a decision removes it from the unreviewed list
    Given an entity mention has been submitted and placed by ERE with a known cluster assignment
    When an authorised Curator curates that decision
    Then the decision does not appear in the unreviewed-since-placement list

  # ---------------------------------------------------------------------------
  # Scenario 3: ERE re-placement resets reviewed_since_placement to False
  # ---------------------------------------------------------------------------

  Scenario: A curated decision re-surfaces as unreviewed after ERE issues a new placement
    Given an entity mention has been submitted and placed by ERE with a known cluster assignment
    And an authorised Curator has already curated that decision
    When ERE issues a new placement for that mention with a different cluster
    Then the decision re-appears in the unreviewed-since-placement list
    And the previous review count for that decision is greater than zero
