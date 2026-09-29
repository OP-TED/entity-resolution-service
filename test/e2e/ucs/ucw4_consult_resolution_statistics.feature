Feature: UC-W4 — Consult Resolution Statistics
  As a curator reviewing entity resolution activity,
  I want to consult aggregated statistics about mentions, clusters, and recent activity,
  So that I can assess workload and prioritise review efforts
  without inspecting individual records or modifying system state.

  # Read-only statistics derived from the Decision Store.
  # Strictly aggregated counts — no individual mention or cluster details exposed.
  # Traceability: UC-W4.

  Background:
    Given the ERS system is operational
    And the Decision Store is available
    And the user is authenticated and authorised

  # ---------------------------------------------------------------------------
  # Main Success — retrieve statistics per entity type
  # ---------------------------------------------------------------------------

  Scenario Outline: Retrieve aggregated statistics for a given entity type
    Given the Decision Store contains <mention_count> mentions of entity type "<entity_type>"
    And those mentions are assigned to <cluster_count> distinct clusters
    And <recent_count> resolution requests were submitted in the last day
    When the curator requests statistics for entity type "<entity_type>"
    Then the response returns total mentions <mention_count>
    And the response returns total clusters <cluster_count>
    And the response returns recent requests <recent_count>

    Examples:
      | entity_type  | mention_count | cluster_count | recent_count |
      | ORGANISATION | 1500          | 320           | 45           |
      | PROCEDURE    | 800           | 210           | 12           |

  # ---------------------------------------------------------------------------
  # Empty state — no data for entity type
  # ---------------------------------------------------------------------------

  Scenario Outline: Return zero counts when no data exists for the requested entity type
    Given the Decision Store contains no mentions of entity type "<entity_type>"
    When the curator requests statistics for entity type "<entity_type>"
    Then the response returns total mentions <mention_count>
    And the response returns total clusters <cluster_count>
    And the response returns recent requests <recent_count>

    Examples:
      | entity_type | mention_count | cluster_count | recent_count |
      | LOCATION    | 0             | 0             | 0            |

  # ---------------------------------------------------------------------------
  # All entity types — overview
  # ---------------------------------------------------------------------------

  Scenario: Retrieve aggregated statistics across all entity types
    Given the Decision Store contains mentions across multiple entity types
    When the curator requests statistics without specifying an entity type
    Then the response includes aggregated totals across all entity types
    And each entity type section includes total mentions, total clusters, and recent requests

  # ---------------------------------------------------------------------------
  # Read-only contract
  # ---------------------------------------------------------------------------

  Scenario Outline: Statistics retrieval does not modify any system state
    Given the Decision Store contains <mention_count> mentions of entity type "<entity_type>"
    When the curator requests statistics for entity type "<entity_type>"
    Then no resolution request is published to the ERE
    And no cluster assignment is written or modified in the Decision Store
    And no new resolution request is registered

    Examples:
      | entity_type  | mention_count |
      | ORGANISATION | 100           |

  # ---------------------------------------------------------------------------
  # Service failure
  # ---------------------------------------------------------------------------

  Scenario Outline: Return service error when the Decision Store is unavailable
    Given the Decision Store is unavailable
    When the curator requests statistics for entity type "<entity_type>"
    Then the response returns error "<error_code>"

    Examples:
      | entity_type  | error_code    |
      | ORGANISATION | SERVICE_ERROR |
