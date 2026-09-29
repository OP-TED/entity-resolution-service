Feature: Resolve a Single Entity Mention (Spine A Intake)
  As a service layer consumer of the Resolution Coordinator,
  I want a single entity mention parsed, registered, and submitted for resolution,
  So that a canonical or provisional cluster identifier is returned within the client timeout budget.

  Background:
    Given the Resolution Coordinator is available with all dependency services

  Scenario Outline: Resolve a valid entity mention under different ERE response conditions
    Given a valid entity mention with correlation triad ("<source_id>", "<request_id>", "Organization")
    And <ere_condition>
    When the resolution request is submitted
    Then <outcome>
    And the cluster assignment is persisted in the Decision Store

    Examples:
      | source_id | request_id | ere_condition                                       | outcome                                        |
      | SYSTEM_A  | req-001    | the ERE responds within the execution window        | the canonical cluster identifier is returned   |
      | SYSTEM_A  | req-002    | the ERE does not respond within the execution window | a provisional singleton identifier is returned |
      | SYSTEM_A  | req-003    | the messaging channel is unavailable                | a service unavailable error is raised          |

  Scenario: Return the existing ERE decision when a provisional write races with an ERE outcome
    Given a valid entity mention with correlation triad ("SYSTEM_B", "req-004", "Organization")
    And the ERE does not respond within the execution window
    But the ERE has already written a decision to the Decision Store for that triad
    When the resolution request is submitted
    Then the stale provisional is discarded and the existing ERE decision is returned

  Scenario Outline: Handle idempotent replay
    Given a resolution request was previously submitted for triad ("<source_id>", "<request_id>", "Organization") with identical content
    And <prior_decision_state>
    When the same resolution request is submitted again
    Then <replay_outcome>
    And no new request is published to the ERE

    Examples:
      | source_id | request_id | prior_decision_state                                          | replay_outcome                                        |
      | SYSTEM_C  | req-010    | a decision exists in the Decision Store with cluster "cl-42"  | the existing decision "cl-42" is returned             |
      | SYSTEM_C  | req-011    | no decision exists yet (ERE still pending)                    | the request shares the pending async wait             |

  Scenario: Reject an idempotency conflict when the same triad is resubmitted with different content
    Given a resolution request was previously submitted for triad ("SYSTEM_D", "req-020", "Organization")
    When a new request is submitted for the same triad but with different RDF content
    Then an idempotency conflict error is raised
    And the Decision Store is not modified

  Scenario: Reject a request when the RDF content cannot be parsed
    Given an entity mention with malformed RDF content for triad ("SYSTEM_E", "req-030", "Organization")
    When the resolution request is submitted
    Then a parsing failure error is raised
    And the request is not registered in the Request Registry
    And no request is published to the ERE

  Scenario: Raise a fatal error when the Decision Store is unavailable
    Given a valid entity mention with correlation triad ("SYSTEM_F", "req-040", "Organization")
    And the Decision Store is unavailable
    When the resolution request is submitted
    Then a service unavailable error is raised

  Scenario: Issue provisional immediately when time budget is zero
    Given a valid entity mention with correlation triad ("SYSTEM_Z", "req-100", "Organization")
    And the time budget is configured to zero
    When the resolution request is submitted
    Then a provisional singleton identifier is returned
    And no request is published to the ERE
