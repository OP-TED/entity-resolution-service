Feature: Resolve Entity Mention via ERS API
  As an Originator submitting entity mentions for resolution
  I want the ERS API to register my request, obtain a canonical cluster identifier, and record the outcome
  So that downstream consumers can use a stable canonical reference for each resolved mention

  Background: System is clean and all services are healthy
    Given the ERS API is reachable
    And the request registry is empty
    And the decision store is empty

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Main Success Scenario: Direct Engine Response
  # Reference: docs/AnnexeB-UseCases/ucb11.adoc
  # ---------------------------------------------------------------------------

  Scenario: Canonical resolution when ERE responds within the execution window
    Given a valid entity mention request for an organisation using the first test file
    When the Originator submits the entity mention for resolution
    Then the resolution is accepted
    And the response contains a canonical cluster identifier assigned by ERE
    And the entity mention is registered in the request registry
    And the cluster assignment is recorded in the decision store
    And no draft identifier is present in the response

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Alternate Scenario: Draft Identifier Issuance (ERE timeout)
  # ---------------------------------------------------------------------------

  Scenario: Provisional draft identifier issued when ERE does not respond within the execution window
    Given a valid entity mention request for an organisation using the first test file
    And the ERE engine will not respond within the execution window
    When the Originator submits the entity mention for resolution
    Then the resolution is accepted
    And the response contains a deterministic draft identifier
    And the entity mention is registered in the request registry
    And no cluster assignment is recorded in the decision store yet
    And a resolve-considering-recommendation request is forwarded to ERE

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Extension 2a: Draft determinism
  # ---------------------------------------------------------------------------

  Scenario: Same entity mention triad always produces the same draft identifier
    Given a valid entity mention request for an organisation using the first test file
    And the ERE engine will not respond within the execution window
    When the Originator submits the entity mention for resolution
    And the Originator submits the same entity mention for resolution a second time
    Then both responses contain the same draft identifier
    And the request registry contains exactly one entry for that triad

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Postcondition 2: Idempotent replay (same triad, same content)
  # ---------------------------------------------------------------------------

  Scenario: Identical submission replayed returns the same result without creating a duplicate entry
    Given a valid entity mention request for an organisation using the first test file
    When the Originator submits the entity mention for resolution
    And the Originator submits the same entity mention for resolution a second time
    Then both responses contain the same canonical identifier
    And the request registry contains exactly one entry for that triad

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Extension 2a: Idempotency conflict (same triad, different content)
  # ---------------------------------------------------------------------------

  Scenario: Submission with same triad but different content is rejected as an idempotency conflict
    Given a valid entity mention request for an organisation using the first test file
    And an alternative payload for the same entity mention triad using a different content file
    When the Originator submits the entity mention for resolution
    And the Originator submits the alternative payload for the same triad
    Then the second submission is rejected as a conflict
    And the request registry still contains exactly one entry for that triad
    And the decision store is not modified by the conflicting submission

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Extension 1a: Validation — missing required fields
  # ---------------------------------------------------------------------------

  Scenario Outline: Submission missing a required field is rejected without registering a request
    Given an entity mention request with the "<missing_field>" field omitted
    When the Originator submits the entity mention for resolution
    Then the submission is rejected as invalid
    And the request registry remains empty
    And no message is published to the ERE request channel

    Examples:
      | missing_field |
      | source_id     |
      | request_id    |
      | entity_type   |
      | content       |
      | content_type  |

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Extension 1b: Validation — unsupported entity type
  # ---------------------------------------------------------------------------

  Scenario: Submission with an unsupported entity type is explicitly rejected
    Given an entity mention request where the entity type is set to an unsupported value
    When the Originator submits the entity mention for resolution
    Then the submission is rejected with an explicit unsupported-type error
    And the request registry remains empty
    And no message is published to the ERE request channel

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Minimal Guarantee: Client timeout budget exceeded
  # ---------------------------------------------------------------------------

  Scenario: ERS returns an appropriate error before the client timeout budget is exceeded
    Given a valid entity mention request for an organisation using the first test file
    And both ERE and the ERS internal execution window are configured to exceed the client timeout budget
    When the Originator submits the entity mention for resolution
    Then an error is returned within the client timeout budget
    And no partial state is left in the request registry or decision store

  # ---------------------------------------------------------------------------
  # UC-B1.1 — Minimal Guarantee: Critical dependency failure
  # ---------------------------------------------------------------------------

  Scenario: ERS returns an error and leaves no partial state when a critical dependency is unavailable
    Given a valid entity mention request for an organisation using the first test file
    And the request registry dependency is unavailable
    When the Originator submits the entity mention for resolution
    Then an explicit service error is returned
    And no partial entry exists in the request registry
    And no partial entry exists in the decision store
