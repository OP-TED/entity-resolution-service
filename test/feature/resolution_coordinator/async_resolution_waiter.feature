Feature: Async Resolution Waiter Coordination
  As an ERS system operator,
  I want the async resolution waiter to coordinate between the Resolution Coordinator
  and the ERE Result Integrator via shared in-process events,
  So that waiting resolutions are unblocked promptly and resources are cleaned up.

  Background:
    Given the async resolution waiter is available

  Scenario Outline: Waiters are unblocked when the Result Integrator signals
    Given <waiter_count> waiters are registered for correlation triad ("<source_id>", "<request_id>", "Organization")
    When the ERE Result Integrator signals an outcome for that triad
    Then all <waiter_count> waiters are unblocked

    Examples:
      | source_id | request_id | waiter_count |
      | SYSTEM_A  | req-001    | 1            |
      | SYSTEM_A  | req-002    | 3            |

  Scenario: A waiter is unblocked by timeout when no signal arrives
    Given 1 waiters are registered for correlation triad ("SYSTEM_B", "req-010", "Organization")
    When no signal arrives within the execution window
    Then the waiter is unblocked by timeout
    And the event for that triad remains available for a late signal

  Scenario: Signalling a triad with no registered waiters is a no-op
    When the ERE Result Integrator signals an outcome for triad ("SYSTEM_C", "req-020", "Organization") with no registered waiters
    Then no error is raised

  Scenario Outline: Event lifecycle on waiter release
    Given <initial_count> waiters are registered for correlation triad ("<source_id>", "<request_id>", "Organization")
    When <release_count> waiters release
    Then <event_state>

    Examples:
      | source_id | request_id | initial_count | release_count | event_state                                    |
      | SYSTEM_D  | req-030    | 2             | 1             | the event for that triad is still retained     |
      | SYSTEM_D  | req-031    | 2             | 2             | the event for that triad is removed            |
      | SYSTEM_D  | req-032    | 1             | 1             | the event for that triad is removed            |
