Feature: Outbound ERS to ERE Request Publishing
  As an operator of ERSys
  I want ERS to publish well-formed resolution and re-evaluation requests to the ERE request queue
  So that ERE can process each entity mention or user recommendation asynchronously

  # Reference: docs/AnnexeB-UseCases/ucb11.adoc (UC-B1.1)
  # Reference: docs/AnnexeB-UseCases/ucb21.adoc (UC-B2.1)
  # Reference: docs/superpowers/specs/2026-04-02-e2e-test-architecture-design.md §5.4

  Background: System is clean and all services are healthy
    Given the ERS API is reachable
    And the Curation API is reachable
    And the ERE request queue is empty

  # ---------------------------------------------------------------------------
  # Scenario 1: Standard resolution request published after entity mention submission
  # ---------------------------------------------------------------------------

  Scenario: A resolution request is published to the ERE queue after a valid entity mention is submitted
    Given a valid entity mention request for an organisation using the first test file
    When the Originator submits the entity mention for resolution
    Then the resolution is accepted
    And a resolution request message appears on the ERE request queue
    And the message is correlated to the submitted entity mention triad
    And the message carries the entity mention content

  # ---------------------------------------------------------------------------
  # Scenario 2: Resolve-considering-recommendation published after draft timeout
  # ---------------------------------------------------------------------------

  Scenario: A resolve-considering-recommendation request is published when ERE does not respond within the execution window
    Given a valid entity mention request for an organisation using the second test file
    And the ERE engine will not respond within the execution window
    When the Originator submits the entity mention for resolution
    Then the resolution is accepted with a provisional draft identifier
    And a resolve-considering-recommendation request appears on the ERE request queue
    And the message includes the provisional draft identifier as the recommended cluster

  # ---------------------------------------------------------------------------
  # Scenario 3: Re-evaluation request published after a curator submits a recommendation
  # ---------------------------------------------------------------------------

  Scenario Outline: A re-evaluation request is published to the ERE queue after a curator submits a recommendation
    Given a previously resolved entity mention is present in the system
    And an authenticated curator is submitting a "<recommendation_type>" recommendation for that mention
    When the curator submits the re-evaluation request
    Then the re-evaluation is accepted
    And a re-evaluation request message appears on the ERE request queue
    And the message carries the "<recommendation_type>" interaction type
    And the decision store is not modified immediately

    Examples:
      | recommendation_type |
      | placement           |
      | exclusion           |

  # ---------------------------------------------------------------------------
  # Scenario 4: No message published when the resolve submission is invalid
  # ---------------------------------------------------------------------------

  Scenario Outline: No ERE request is published when an entity mention submission is rejected as invalid
    Given an entity mention request with the "<missing_field>" field omitted
    When the Originator submits the entity mention for resolution
    Then the submission is rejected as invalid
    And no message is published to the ERE request queue

    Examples:
      | missing_field |
      | source_id     |
      | request_id    |
      | entity_type   |
      | content       |
      | content_type  |
