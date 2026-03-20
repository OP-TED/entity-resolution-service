Feature: Curation statistics
  As a curator
  I need to view aggregated statistics about resolution and curation activity
  So that I can prioritise my review efforts and understand operational workload

  Background:
    Given the curator is authenticated and verified

  Scenario: Retrieve overall statistics
    Given decisions and user actions exist in the system
    When the curator requests statistics
    Then the response includes registry statistics and curation statistics
    And registry statistics contain total entity mentions and canonical entities
    And registry statistics contain average cluster size and resolution request count
    And curation statistics contain counts for accepted top, accepted alternative, and rejected all

  Scenario: Filter statistics by entity type
    Given decisions exist for entity types "Organization" and "Person"
    And user actions exist for both entity types
    When the curator requests statistics filtered by entity type "Organization"
    Then the statistics reflect only "Organization" data

  Scenario: Filter statistics by time window
    Given user actions exist across different dates
    When the curator requests statistics for a specific time range
    Then the curation statistics reflect only actions within that time range

  Scenario: Statistics with no data
    Given no decisions or user actions exist
    When the curator requests statistics
    Then all counts are zero
    And the average cluster size is zero

  Scenario: Statistics are read-only
    When the curator requests statistics
    Then no system state is modified