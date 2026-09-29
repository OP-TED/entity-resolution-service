Feature: Publish Resolution Requests to ERE via the Unified Resolution Envelope
  As an ERS service layer consumer of the ERE Contract Client,
  I want all resolution request variants to be published through the unified envelope
  to the messaging channel in a fire-and-forget manner,
  So that the ERE can consume and process each request independently.

  Background:
    Given the ERE Contract Client is available
    And the messaging channel is reachable

  Scenario Outline: Publish a resolution request with optional constraint fields
    Given a valid entity mention with correlation triad ("<source_id>", "<request_id>", "Organization")
    And the request includes proposed placements "<proposed>" and excluded clusters "<excluded>"
    When the resolution request is published
    Then the request is enqueued on the messaging channel
    And the published request contains the complete correlation triad
    And the ere_request_id is present in the published request

    Examples:
      | source_id | request_id | proposed                  | excluded                          |
      | TEDSWS    | req-001    | none                      | none                              |
      | TEDSWS    | req-002    | cluster-aa                | none                              |
      | TEDSWS    | req-003    | none                      | cluster-cc,cluster-dd             |
      | TEDSWS    | req-004    | cluster-aa                | cluster-cc,cluster-dd             |

  Scenario: Publish a singleton proposal for a provisional cluster
    Given a valid entity mention with correlation triad ("TEDSWS", "req-005", "Organization")
    And the request includes a single proposed placement using the SHA256-derived provisional cluster
    When the resolution request is published
    Then the request is enqueued on the messaging channel
    And the proposed placements contain exactly the provisional cluster identifier

  Scenario Outline: Auto-generate missing request metadata before publishing
    Given a valid entity mention with correlation triad ("TEDSWS", "req-010", "Organization")
    And the resolution request has "<field>" not set
    When the resolution request is published
    Then the published request has "<field>" auto-populated
    And the request is enqueued on the messaging channel

    Examples:
      | field          |
      | ere_request_id |
      | timestamp      |

  Scenario: Publishing the same request twice succeeds under at-least-once semantics
    Given a valid entity mention with correlation triad ("TEDSWS", "req-020", "Organization")
    When the resolution request is published
    And the same resolution request is published again
    Then both requests are enqueued on the messaging channel
