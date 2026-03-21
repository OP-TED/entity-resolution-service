Feature: Snapshot State Management
  As a process that coordinates delta exposure for source systems,
  I want to advance the snapshot watermark per source,
  So that each source's last successful bulk refresh point is tracked reliably
  and backward time movement is detected and rejected.

  Background:
    Given the Request Registry service is available
    And the repository is empty

  Scenario Outline: Advance the snapshot for a source system
    Given a source system identified by "<source_id>"
    And the existing last_snapshot for "<source_id>" is "<existing_last_snapshot>"
    When the snapshot is advanced to "<snapshot_time>"
    Then the lookup state for "<source_id>" has last_snapshot "<snapshot_time>"

    Examples:
      | source_id       | existing_last_snapshot        | snapshot_time                 |
      | source_system_a | (none)                        | 2024-06-01T12:00:00+00:00     |
      | source_system_b | 2024-06-01T12:00:00+00:00     | 2024-06-15T08:30:00+00:00     |

  Scenario Outline: Reject snapshot regression
    Given a source system identified by "<source_id>"
    And the existing last_snapshot for "<source_id>" is "<existing_last_snapshot>"
    When the snapshot is advanced to "<snapshot_time>"
    Then a SnapshotRegressionError is raised
    And the last_snapshot for "<source_id>" remains "<existing_last_snapshot>"

    Examples:
      | source_id       | existing_last_snapshot        | snapshot_time                 |
      | source_system_a | 2024-06-15T08:30:00+00:00     | 2024-06-01T00:00:00+00:00     |
      | source_system_b | 2024-06-15T08:30:00+00:00     | 2024-06-15T08:30:00+00:00     |

  Scenario: Retrieve the current lookup state for a known source
    Given a source system identified by "source_system_a"
    And the snapshot watermark for "source_system_a" has been advanced to "2024-06-01T12:00:00+00:00"
    When the current lookup state is retrieved for "source_system_a"
    Then the lookup state is returned with last_snapshot "2024-06-01T12:00:00+00:00"

  Scenario: Retrieve lookup state for an unknown source returns nothing
    Given a source system identified by "source_system_unknown"
    And no lookup state exists for "source_system_unknown"
    When the current lookup state is retrieved for "source_system_unknown"
    Then no lookup state is returned
