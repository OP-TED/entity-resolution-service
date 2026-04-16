Feature: Validate Resolution Requests and Handle Transport Failures
  As an ERS service layer consumer of the ERE Contract Client,
  I want invalid requests rejected before reaching the messaging channel
  and transport failures surfaced as explicit errors,
  So that the system never silently loses requests and callers can act on failures.

  Background:
    Given the ERE Contract Client is available

  Scenario Outline: Reject a request with an incomplete correlation triad
    Given a resolution request with "<missing_field>" absent
    When the resolution request is published
    Then an invalid request error is raised
    And no request is enqueued on the messaging channel

    Examples:
      | missing_field  |
      | source_id      |
      | request_id     |
      | entity_type    |
      | entity_mention |

  Scenario Outline: Surface transport and serialization failures as explicit errors
    Given the messaging channel is reachable
    And the transport will fail with "<failure_mode>"
    When a resolution request is published for triad ("TEDSWS", "req-020", "Organization")
    Then a "<error_type>" error is raised

    Examples:
      | failure_mode              | error_type          |
      | connection refused        | connection          |
      | response timeout          | channel_unavailable |
      | serialization failure     | serialization       |
      | channel accepted zero     | channel_unavailable |

  Scenario Outline: Report messaging channel health
    Given the messaging channel is "<channel_state>"
    When the health check is performed
    Then the result is "<health_result>"

    Examples:
      | channel_state | health_result |
      | reachable     | healthy       |
      | unreachable   | unhealthy     |
